"""Server-side bus drain worker for the Publisher agent.

PUBLISHER_AGENT_INSTALL_1 Part 2. Publisher is the sole final renderer of
Director-facing HTML from structured desk facts (spec SPEC_PUBLISHER_AGENT_v1).
This worker polls Publisher's bus inbox for render tickets, renders each via an
injected render function, and posts a render RECEIPT (ticket id, gate PASS/FAIL
table, screenshot path, cost telemetry) back to the sender — ACKing ONLY after
the receipt (or bounce) is posted.

Design (brief constraint 4 — no new plumbing): the poll -> process -> reply ->
ack-after-reply shape is reused verbatim from ``clerk_bus_worker.ClerkBusWorker``.
Differences from clerk:
  * Stateless — the render drain slice needs no session store (spec: no writes /
    read-only). Dedup rides on the bus ACK (unacked filter + ack-after-reply),
    same at-least-once residual window clerk documents. Re-rendering identical
    facts is idempotent, so a duplicate render is low-harm.
  * The unit of work is a RENDER, not a model chat. The actual rendering engine
    (structured facts -> HTML + deterministic gates + verify-dashboard-render) is
    injected as ``render_fn`` and built in a later slice; this module owns only
    the drain, the receipt/bounce contract, and the per-wake cap.

Render function contract — ``render_fn(ticket: dict) -> dict`` returns:
  status:        "rendered" | "bounce" | "failed"
  surface:       target rendered-surface path (str)
  gates:         list of {"gate": str, "verdict": "PASS"|"FAIL", "detail": str}
  screenshot:    verification screenshot path (str)         [AC5 evidence]
  cost:          {"prompt_tokens", "completion_tokens", "usd"} (dict) [AC5]
  bounce_reason: named ambiguity when status == "bounce"    [AC3 — no inline patch]
  escalate:      bool — set when >2 fix-rerun cycles exhausted (spec §3)
  failing_gate:  str — named for the AH1 escalation
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger("baker.publisher_bus_worker")

_PUBLISHER_SLUG = "publisher"
_ESCALATION_SLUG = "lead"  # AH1 governance/escalation lane (spec §8)
RenderFn = Callable[[dict[str, Any]], dict[str, Any]]


class PublisherBusConfigError(RuntimeError):
    """Raised when the worker is enabled without the required runtime config."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _terminal_key_from_env() -> str:
    return (
        os.getenv("BRISEN_LAB_TERMINAL_KEY_publisher")
        or os.getenv("BRISEN_LAB_TERMINAL_KEY_PUBLISHER")
        or ""
    ).strip()


@dataclass
class PublisherBusWorkerConfig:
    enabled: bool
    lab_url: str
    terminal_key: str
    poll_limit: int = 10
    per_wake_render_cap: int = 5          # spec §3: default 5 renders bound a cycle
    http_timeout_s: float = 10.0
    queue_age_alarm_s: float = 1800.0     # spec §6.4 queue-age tripwire (default 30m)
    escalate_gate_fail: bool = True

    @property
    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not self.terminal_key:
            missing.append("BRISEN_LAB_TERMINAL_KEY_publisher")
        if not self.lab_url:
            missing.append("BRISEN_LAB_URL")
        return missing


def publisher_bus_worker_config_from_env() -> PublisherBusWorkerConfig:
    lab_url = (
        os.getenv("LAB_URL")
        or os.getenv("BRISEN_LAB_URL")
        or os.getenv("BRISEN_LAB_DAEMON_URL")
        or "https://brisen-lab.onrender.com"
    ).rstrip("/")
    return PublisherBusWorkerConfig(
        enabled=_env_bool("PUBLISHER_BUS_WORKER_ENABLED", False),
        lab_url=lab_url,
        terminal_key=_terminal_key_from_env(),
        poll_limit=_bounded_int("PUBLISHER_BUS_POLL_LIMIT", 10, 1, 25),
        per_wake_render_cap=_bounded_int("PUBLISHER_BUS_RENDER_CAP", 5, 1, 20),
        http_timeout_s=_bounded_float("PUBLISHER_BUS_HTTP_TIMEOUT_S", 10.0, 1.0, 60.0),
        queue_age_alarm_s=_bounded_float("PUBLISHER_BUS_QUEUE_AGE_ALARM_S", 1800.0, 60.0, 86400.0),
        escalate_gate_fail=_env_bool("PUBLISHER_BUS_ESCALATE_GATE_FAIL", True),
    )


def publisher_bus_poll_interval_seconds() -> int:
    return _bounded_int("PUBLISHER_BUS_POLL_INTERVAL_S", 60, 15, 300)


def _default_render_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    # The rendering engine is a later Part-2/3 slice; keep the drain shippable and
    # loud rather than silently no-op. Tests inject a fake render_fn.
    from orchestrator.publisher_render import render_ticket  # type: ignore

    return render_ticket(ticket)


class PublisherBusWorker:
    def __init__(
        self,
        *,
        cfg: PublisherBusWorkerConfig | None = None,
        http_client: httpx.Client | None = None,
        render_fn: RenderFn | None = None,
    ):
        self.cfg = cfg or publisher_bus_worker_config_from_env()
        self.http = http_client or httpx.Client(timeout=self.cfg.http_timeout_s)
        self.render_fn = render_fn or _default_render_ticket

    # ---- drain -----------------------------------------------------------------

    def poll_once(self) -> dict[str, Any]:
        if not self.cfg.enabled:
            return {"status": "disabled", "processed": 0, "acked": 0, "errors": 0}

        missing = self.cfg.missing_required
        if missing:
            logger.warning("publisher bus worker skipped; missing config: %s", ",".join(missing))
            return {"status": "skipped_config", "missing": missing, "processed": 0, "acked": 0, "errors": 0}

        try:
            messages = self._fetch_inbox()
        except Exception as e:
            logger.warning("publisher inbox fetch failed: %s", type(e).__name__)
            return {"status": "fetch_failed", "processed": 0, "acked": 0, "errors": 1}

        pending = [m for m in messages if not m.get("acknowledged_at")]
        self._queue_age_tripwire(pending)

        stats: dict[str, Any] = {
            "status": "ok",
            "fetched": len(messages),
            "pending": len(pending),
            "processed": 0,
            "acked": 0,
            "bounced": 0,
            "errors": 0,
            "overflow": len(pending) > self.cfg.per_wake_render_cap,
        }
        for msg in pending[: self.cfg.per_wake_render_cap]:
            try:
                result = self.process_message(msg)
                stats["processed"] += 1
                if result.get("acked"):
                    stats["acked"] += 1
                if result.get("status") == "bounce":
                    stats["bounced"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.exception("publisher bus message failed id=%s error=%s", msg.get("id"), type(e).__name__)

        # spec §3: the cap bounds a cycle, never strands the queue. Signal that a
        # re-wake should drain the remainder immediately rather than wait a full interval.
        if stats["overflow"]:
            logger.info(
                "publisher queue over per-wake cap (%d pending > %d cap) — re-wake to continue draining",
                len(pending), self.cfg.per_wake_render_cap,
            )
        return stats

    def process_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        message_id = int(msg["id"])
        sender = str(msg.get("from_terminal") or msg.get("sender") or "").strip()
        topic = str(msg.get("topic") or "render/publisher").strip()

        if sender == _PUBLISHER_SLUG:
            self._ack_message(message_id)
            return {"status": "skipped_self", "acked": True}
        if not sender:
            return {"status": "skipped_invalid", "acked": False}

        task = self._fetch_full_body(message_id)
        if not task:
            logger.warning("publisher bus message skipped; full body unavailable id=%s", message_id)
            return {"status": "skipped_invalid", "acked": False}

        ticket = self._parse_ticket(message_id, sender, topic, task)
        result = self._render(ticket)
        status = str(result.get("status") or "failed")

        if status == "bounce":
            # AC3: no inline patch — the fact goes BACK to the sending desk with the
            # ambiguity named. Publisher has no content authority.
            body = self._format_bounce(message_id, result)
        else:
            body = self._format_receipt(message_id, result)

        self._post_reply(recipient=sender, topic=topic, body=body, parent_id=message_id)

        # spec §3: >2 fix-rerun cycles exhausted with a failing gate -> escalate to AH1.
        if self.cfg.escalate_gate_fail and result.get("escalate"):
            self._escalate_gate_failure(message_id, topic, result)

        # ack-after-reply (clerk invariant): the inbound is only cleared once the
        # receipt/bounce has been delivered, so a mid-flight failure re-drains it.
        self._ack_message(message_id)
        return {"status": status, "acked": True}

    # ---- render ----------------------------------------------------------------

    def _parse_ticket(self, message_id: int, sender: str, topic: str, body: str) -> dict[str, Any]:
        # Schema-first handoff (spec §2: JSON contract, not prose). Non-JSON bodies
        # are wrapped as {"raw": ...} so the render engine can bounce a malformed ticket.
        try:
            parsed = json.loads(body)
            payload = parsed if isinstance(parsed, dict) else {"raw": body}
        except (ValueError, TypeError):
            payload = {"raw": body}
        payload.setdefault("ticket_id", message_id)
        payload.setdefault("from_terminal", sender)
        payload.setdefault("topic", topic)
        return payload

    def _render(self, ticket: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.render_fn(ticket)
            if isinstance(result, dict):
                return result
            return {"status": "failed", "bounce_reason": "render_fn returned non-dict result"}
        except BaseException as e:  # render failure must never crash the drain
            logger.warning("publisher render failed: %s", type(e).__name__)
            return {"status": "failed", "gates": [], "failing_gate": type(e).__name__,
                    "bounce_reason": f"render raised {type(e).__name__}"}

    # ---- bus I/O (mirrors clerk_bus_worker) ------------------------------------

    def _fetch_inbox(self) -> list[dict[str, Any]]:
        resp = self.http.get(
            f"{self.cfg.lab_url}/msg/{_PUBLISHER_SLUG}",
            params={"limit": self.cfg.poll_limit},
            headers={"X-Terminal-Key": self.cfg.terminal_key},
            timeout=self.cfg.http_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("messages", [])
        if not isinstance(data, list):
            return []
        return [m for m in data if isinstance(m, dict)]

    def _fetch_full_body(self, message_id: int) -> str:
        try:
            resp = self.http.get(
                f"{self.cfg.lab_url}/event/{message_id}/full",
                headers={"X-Terminal-Key": self.cfg.terminal_key},
                timeout=self.cfg.http_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("publisher full body fetch failed id=%s error=%s", message_id, type(e).__name__)
            return ""
        if not isinstance(data, dict):
            return ""
        body = data.get("body")
        return body.strip() if isinstance(body, str) else ""

    def _post_reply(self, *, recipient: str, topic: str, body: str, parent_id: int) -> dict[str, Any]:
        payload = {
            "kind": "dispatch",
            "body": body,
            "to": [recipient],
            "tier_required": "B",
            "topic": topic,
            "parent_id": parent_id,
        }
        resp = self.http.post(
            f"{self.cfg.lab_url}/msg/{recipient}",
            headers={"X-Terminal-Key": self.cfg.terminal_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.cfg.http_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _escalate_gate_failure(self, message_id: int, topic: str, result: dict[str, Any]) -> None:
        gate = str(result.get("failing_gate") or "unknown")
        body = (
            f"Publisher render ESCALATION for ticket #{message_id}: "
            f"gate '{gate}' still FAIL after 2 fix-rerun cycles (spec §3). "
            f"Surface: {result.get('surface') or '?'}. Render not shipped."
        )
        try:
            self._post_reply(recipient=_ESCALATION_SLUG, topic=f"escalation/{topic}", body=body, parent_id=message_id)
        except Exception as e:
            logger.warning("publisher escalation post failed id=%s error=%s", message_id, type(e).__name__)

    def _ack_message(self, message_id: int) -> None:
        resp = self.http.post(
            f"{self.cfg.lab_url}/msg/{message_id}/ack",
            headers={"X-Terminal-Key": self.cfg.terminal_key},
            timeout=self.cfg.http_timeout_s,
        )
        resp.raise_for_status()

    # ---- formatting ------------------------------------------------------------

    def _format_receipt(self, message_id: int, result: dict[str, Any]) -> str:
        status = str(result.get("status") or "failed")
        lines = [
            f"Publisher render receipt for ticket #{message_id}",
            f"Verdict: {status.upper()}",
            f"Surface: {result.get('surface') or '(none)'}",
        ]
        gates = result.get("gates")
        if isinstance(gates, list) and gates:
            lines.append("Gates:")
            for g in gates:
                if not isinstance(g, dict):
                    continue
                verdict = str(g.get("verdict") or "?")
                detail = str(g.get("detail") or "")
                lines.append(f"  - {g.get('gate', '?')}: {verdict}" + (f" ({detail})" if detail else ""))
        screenshot = result.get("screenshot")
        if screenshot:
            lines.append(f"Screenshot: {screenshot}")
        cost = result.get("cost")
        if isinstance(cost, dict):
            lines.append(
                "Cost: prompt={p} completion={c} usd={u}".format(
                    p=cost.get("prompt_tokens", "?"),
                    c=cost.get("completion_tokens", "?"),
                    u=cost.get("usd", "?"),
                )
            )
        if result.get("escalate"):
            lines.append(f"ESCALATED to {_ESCALATION_SLUG}: gate '{result.get('failing_gate') or '?'}' failed after 2 reruns.")
        return "\n".join(lines)

    def _format_bounce(self, message_id: int, result: dict[str, Any]) -> str:
        reason = str(result.get("bounce_reason") or "fact missing or ambiguous")
        return (
            f"Publisher BOUNCE for ticket #{message_id} — cannot render.\n"
            f"Named ambiguity: {reason}\n"
            "No inline patch made — Publisher owns FORM only, not content. "
            "Supply the missing/corrected fact and re-send the render ticket."
        )

    # ---- tripwire --------------------------------------------------------------

    def _queue_age_tripwire(self, pending: list[dict[str, Any]]) -> None:
        # spec §6.4: alarm AH1 (log surface here) if the oldest pending ticket
        # exceeds the age threshold while the loop is live.
        oldest = self._oldest_age_seconds(pending)
        if oldest is not None and oldest > self.cfg.queue_age_alarm_s:
            logger.warning(
                "publisher queue-age tripwire: oldest pending render ticket is %.0fs old (> %.0fs threshold)",
                oldest, self.cfg.queue_age_alarm_s,
            )

    @staticmethod
    def _oldest_age_seconds(pending: list[dict[str, Any]]) -> float | None:
        now = datetime.now(timezone.utc)
        ages: list[float] = []
        for m in pending:
            created = m.get("created_at")
            if not isinstance(created, str):
                continue
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ages.append((now - ts).total_seconds())
            except (ValueError, TypeError):
                continue
        return max(ages) if ages else None


def poll_publisher_bus() -> dict[str, Any]:
    cfg = publisher_bus_worker_config_from_env()
    with httpx.Client(timeout=cfg.http_timeout_s) as http_client:
        return PublisherBusWorker(cfg=cfg, http_client=http_client).poll_once()
