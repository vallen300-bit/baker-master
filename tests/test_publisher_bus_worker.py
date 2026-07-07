"""Unit tests for the Publisher bus drain worker (PUBLISHER_AGENT_INSTALL_1 Part 2).

Fake HTTP + injected render_fn (the clerk injection pattern). Covers the drain
contract: per-wake cap, ack-after-receipt ordering, bounce path (AC3), receipt
with gate table + cost (AC5), gate-FAIL escalation, self-skip, and render-crash
fault tolerance.
"""
from __future__ import annotations

import pytest

from orchestrator.publisher_bus_worker import (
    PublisherBusWorker,
    PublisherBusWorkerConfig,
    publisher_bus_worker_config_from_env,
)


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHTTP:
    """Records an ordered call log so tests can assert ack-after-receipt ordering."""

    def __init__(self, *, inbox, full_bodies, fail_on_reply=False):
        self.inbox = inbox
        self.full_bodies = full_bodies
        self.fail_on_reply = fail_on_reply
        self.calls: list[tuple[str, str]] = []          # (verb, url)
        self.posted_bodies: list[tuple[str, str]] = []  # (url, body)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("get", url))
        if url.endswith("/msg/publisher"):
            return FakeResp({"messages": self.inbox})
        if "/event/" in url and url.endswith("/full"):
            mid = int(url.split("/event/")[1].split("/full")[0])
            return FakeResp({"body": self.full_bodies.get(mid, "")})
        return FakeResp({})

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("post", url))
        if url.endswith("/ack"):
            mid = int(url.split("/msg/")[1].split("/ack")[0])
            for m in self.inbox:  # mark acked so a re-fetch drains it (drain-loop realism)
                if m.get("id") == mid:
                    m["acknowledged_at"] = "2026-07-07T00:00:00+00:00"
            return FakeResp({"ok": True})
        # a reply/receipt/bounce/escalation/alarm POST to /msg/<recipient>
        if self.fail_on_reply:
            raise RuntimeError("simulated reply POST failure")
        self.posted_bodies.append((url, (json or {}).get("body", "")))
        return FakeResp({"message_id": 9999, "thread_id": "t"})


def _cfg(**over):
    base = dict(enabled=True, lab_url="https://lab.test", terminal_key="k", per_wake_render_cap=5)
    base.update(over)
    return PublisherBusWorkerConfig(**base)


def _msg(mid, sender="baden-baden-desk", topic="render/publisher", acked=False, created_at=None):
    m = {"id": mid, "from_terminal": sender, "topic": topic}
    if acked:
        m["acknowledged_at"] = "2026-07-07T00:00:00+00:00"
    if created_at:
        m["created_at"] = created_at
    return m


def _rendered(**over):
    r = {
        "status": "rendered",
        "surface": "_ops/.../BB-AUK-001/dashboard-v1-pattern-d.html",
        "gates": [
            {"gate": "version-stamp", "verdict": "PASS"},
            {"gate": "lexical(10a-c)", "verdict": "PASS"},
            {"gate": "staleness(9c)", "verdict": "PASS"},
        ],
        "screenshot": "/tmp/shot.png",
        "cost": {"prompt_tokens": 1200, "completion_tokens": 800, "usd": 0.04},
    }
    r.update(over)
    return r


def _acks(http):
    return [u for (v, u) in http.calls if v == "post" and u.endswith("/ack")]


def _replies(http):
    return [u for (v, u) in http.calls if v == "post" and not u.endswith("/ack")]


# --- tests ---------------------------------------------------------------------

def test_disabled_no_http():
    http = FakeHTTP(inbox=[], full_bodies={})
    w = PublisherBusWorker(cfg=_cfg(enabled=False), http_client=http, render_fn=lambda t: _rendered())
    out = w.poll_once()
    assert out["status"] == "disabled"
    assert http.calls == []


def test_missing_config_skips():
    http = FakeHTTP(inbox=[], full_bodies={})
    w = PublisherBusWorker(cfg=_cfg(terminal_key=""), http_client=http, render_fn=lambda t: _rendered())
    out = w.poll_once()
    assert out["status"] == "skipped_config"
    assert "BRISEN_LAB_TERMINAL_KEY_publisher" in out["missing"]


def test_render_happy_path_receipt_then_ack():
    http = FakeHTTP(inbox=[_msg(101)], full_bodies={101: '{"facts": {"x": 1}}'})
    w = PublisherBusWorker(cfg=_cfg(), http_client=http, render_fn=lambda t: _rendered())
    out = w.poll_once()
    assert out["processed"] == 1 and out["acked"] == 1 and out["errors"] == 0
    # ack-after-receipt: the receipt POST precedes the ack POST.
    verbs = [u for (v, u) in http.calls if v == "post"]
    receipt_idx = next(i for i, u in enumerate(verbs) if not u.endswith("/ack"))
    ack_idx = next(i for i, u in enumerate(verbs) if u.endswith("/ack"))
    assert receipt_idx < ack_idx
    # receipt content: gate table + cost + surface (AC5).
    body = http.posted_bodies[0][1]
    assert "render receipt" in body and "version-stamp: PASS" in body
    assert "Cost: prompt=1200" in body and "dashboard-v1-pattern-d.html" in body


def test_bounce_path_no_inline_patch():
    http = FakeHTTP(inbox=[_msg(102)], full_bodies={102: '{"facts": {}}'})
    bounce = {"status": "bounce", "bounce_reason": "loan-cost tile: reserve figure missing"}
    w = PublisherBusWorker(cfg=_cfg(), http_client=http, render_fn=lambda t: bounce)
    out = w.poll_once()
    assert out["bounced"] == 1 and out["acked"] == 1
    body = http.posted_bodies[0][1]
    assert "BOUNCE" in body and "reserve figure missing" in body and "No inline patch" in body


def test_overflow_rewakes_and_drains_full_backlog():
    # F1: cap bounds a CYCLE; overflow must re-wake and drain the rest in the same
    # invocation, not strand it to the next interval.
    inbox = [_msg(200 + i) for i in range(7)]
    full = {200 + i: "{}" for i in range(7)}
    http = FakeHTTP(inbox=inbox, full_bodies=full)
    w = PublisherBusWorker(cfg=_cfg(per_wake_render_cap=3, max_drain_cycles=10),
                           http_client=http, render_fn=lambda t: _rendered())
    out = w.poll_once()
    assert out["processed"] == 7 and out["acked"] == 7          # whole backlog drained
    assert out["overflow"] is True and out["stranded"] is False
    assert out["cycles"] >= 3                                    # 3+3+1 across re-wakes
    assert len(_acks(http)) == 7


def test_stranded_when_backlog_exceeds_cycle_ceiling():
    # F1 safety bound: a backlog larger than cap*max_drain_cycles makes forward
    # progress then yields (stranded), rather than looping unbounded.
    inbox = [_msg(700 + i) for i in range(10)]
    full = {700 + i: "{}" for i in range(10)}
    http = FakeHTTP(inbox=inbox, full_bodies=full)
    w = PublisherBusWorker(cfg=_cfg(per_wake_render_cap=2, max_drain_cycles=2),
                           http_client=http, render_fn=lambda t: _rendered())
    out = w.poll_once()
    assert out["processed"] == 4 and out["cycles"] == 2 and out["stranded"] is True


def test_ack_not_called_when_reply_fails():
    http = FakeHTTP(inbox=[_msg(300)], full_bodies={300: "{}"}, fail_on_reply=True)
    w = PublisherBusWorker(cfg=_cfg(), http_client=http, render_fn=lambda t: _rendered())
    out = w.poll_once()
    assert out["errors"] == 1 and out["acked"] == 0
    # ack-after-reply invariant: a failed receipt POST must leave the inbound unacked.
    assert _acks(http) == []


def test_skip_self_acks_without_render():
    calls = {"n": 0}

    def render_fn(t):
        calls["n"] += 1
        return _rendered()

    http = FakeHTTP(inbox=[_msg(400, sender="publisher")], full_bodies={400: "{}"})
    w = PublisherBusWorker(cfg=_cfg(), http_client=http, render_fn=render_fn)
    out = w.poll_once()
    assert out["acked"] == 1 and calls["n"] == 0
    assert len(_acks(http)) == 1 and _replies(http) == []


def test_gate_fail_escalates_to_lead():
    http = FakeHTTP(inbox=[_msg(500)], full_bodies={500: "{}"})
    failed = _rendered(status="failed", escalate=True, failing_gate="lexical(10c)")
    failed["gates"] = [{"gate": "lexical(10c)", "verdict": "FAIL", "detail": "wall-of-text >2 sentences"}]
    w = PublisherBusWorker(cfg=_cfg(), http_client=http, render_fn=lambda t: failed)
    w.poll_once()
    reply_urls = _replies(http)
    # one receipt to the desk + one escalation to lead
    assert any(u.endswith("/msg/baden-baden-desk") for u in reply_urls)
    assert any(u.endswith("/msg/lead") for u in reply_urls)
    esc_body = next(b for (u, b) in http.posted_bodies if u.endswith("/msg/lead"))
    assert "ESCALATION" in esc_body and "lexical(10c)" in esc_body


def test_queue_age_tripwire_alarms_lead():
    # F2: an old pending ticket must POST an alarm to lead (AH1), not just log.
    old = "2020-01-01T00:00:00+00:00"
    http = FakeHTTP(inbox=[_msg(800, created_at=old)], full_bodies={800: "{}"})
    w = PublisherBusWorker(cfg=_cfg(queue_age_alarm_s=60), http_client=http, render_fn=lambda t: _rendered())
    w.poll_once()
    lead_posts = [(u, b) for (u, b) in http.posted_bodies if u.endswith("/msg/lead")]
    assert lead_posts, "expected a queue-age alarm posted to lead"
    assert "queue-age tripwire" in lead_posts[0][1]


def test_queue_age_tripwire_silent_when_fresh():
    fresh = "2099-01-01T00:00:00+00:00"  # future -> negative age -> never trips
    http = FakeHTTP(inbox=[_msg(801, created_at=fresh)], full_bodies={801: "{}"})
    w = PublisherBusWorker(cfg=_cfg(queue_age_alarm_s=60), http_client=http, render_fn=lambda t: _rendered())
    w.poll_once()
    assert not any(u.endswith("/msg/lead") for (u, _b) in http.posted_bodies)


def test_render_crash_is_fault_tolerant():
    def boom(t):
        raise ValueError("engine exploded")

    http = FakeHTTP(inbox=[_msg(600)], full_bodies={600: "{}"})
    w = PublisherBusWorker(cfg=_cfg(), http_client=http, render_fn=boom)
    out = w.poll_once()
    # a render crash still produces a failed receipt + ack, never crashes the drain.
    assert out["processed"] == 1 and out["acked"] == 1 and out["errors"] == 0
    assert "FAILED" in http.posted_bodies[0][1]


def test_config_from_env_defaults(monkeypatch):
    for k in ("PUBLISHER_BUS_WORKER_ENABLED", "PUBLISHER_BUS_RENDER_CAP",
              "BRISEN_LAB_TERMINAL_KEY_publisher", "LAB_URL", "BRISEN_LAB_URL"):
        monkeypatch.delenv(k, raising=False)
    cfg = publisher_bus_worker_config_from_env()
    assert cfg.enabled is False           # kill-switch default OFF
    assert cfg.per_wake_render_cap == 5   # spec §3 default


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
