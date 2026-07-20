"""LAB_COCKPIT_REDESIGN_1 D6 — wake-on-open verb: guards, dedupe, audit.

Exercises the pure guard/selection logic and send_wake with a fake tmux runner
so no real tmux/Lab is needed (CI-safe).
"""
import json
import subprocess
from pathlib import Path

import pytest

from scripts import cockpit_controller as controller


def _settings(tmp_path):
    return controller.Settings(
        bind_host="127.0.0.1",
        manifest_path=tmp_path / "m.json",
        credential_path=tmp_path / "cred",
        static_dir=tmp_path / "static",
        fleet_script=tmp_path / "fleet.sh",
        wake_audit_path=tmp_path / "wake_audit.log",
    )


ENTRY = controller.ManifestEntry(slug="b3", alias="b3", port=17603)


@pytest.fixture
def fake_tmux(monkeypatch):
    calls = []

    def _fake(settings, args):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_run_tmux", _fake)
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    return calls


UNACKED_ROW = {
    "unacked_count": 2,
    "is_working": False,
    "needs_go": False,
    "unacked_messages": [
        {"id": 12063, "topic": "ao-room-architecture", "created_at": "2026-07-16T20:00:00Z"},
        {"id": 12099, "topic": "later-topic", "created_at": "2026-07-17T09:00:00Z"},
    ],
}


def test_oldest_unacked_picks_earliest_created_at():
    assert controller._oldest_unacked(UNACKED_ROW["unacked_messages"]) == (12063, "ao-room-architecture")
    assert controller._oldest_unacked([]) is None
    assert controller._oldest_unacked(None) is None


@pytest.mark.parametrize("row,reason", [
    (None, "no telemetry"),
    ({"needs_go": True, "unacked_count": 3, "unacked_messages": [{"id": 1, "topic": "t", "created_at": "z"}]}, "needs_go (GO flow owns it)"),
    ({"is_working": True, "unacked_count": 3, "unacked_messages": [{"id": 1, "topic": "t", "created_at": "z"}]}, "working"),
    ({"unacked_count": 0}, "no unacked"),
    ({"unacked_count": 2, "unacked_messages": []}, "no unacked message id"),
])
def test_wake_guards_skip(row, reason):
    assert controller.wake_skip_reason(row) == reason


def test_wake_allowed_when_unacked_and_idle():
    assert controller.wake_skip_reason(UNACKED_ROW) is None


def test_send_wake_happy_path_sends_line_and_audits(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {}
    res = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=1000.0, last_wake=last)
    assert res["sent"] is True
    # D3 — the nudge carries the visible [wake] origin tag.
    assert res["line"] == "[wake] check bus #12063 ao-room-architecture"
    # WAKE_COMPOSER_SUBMIT_FIX_1: literal line, settle, Enter, settle, submit-Return
    assert fake_tmux[0] == ["send-keys", "-t", "b3", "-l", "[wake] check bus #12063 ao-room-architecture"]
    assert fake_tmux[1] == ["send-keys", "-t", "b3", "Enter"]
    assert fake_tmux[2] == ["send-keys", "-t", "b3", "Enter"]
    # WAKE_INJECT_SUBMIT_FIX_2 D2 — then a verify pass: redraw (C-l) + capture-pane.
    # fake_tmux returns empty stdout → composer not holding → verified submitted,
    # so NO recovery Enter fires.
    assert fake_tmux[3] == ["send-keys", "-t", "b3", "C-l"]
    assert fake_tmux[4] == ["capture-pane", "-t", "b3", "-p"]
    assert len(fake_tmux) == 5  # no recovery Enter on a clean submit
    assert res["verified"] == "submitted"
    assert last["b3"]["last_injection"] == 1000.0
    assert last["b3"]["message_last"] == {
        "12063": {"at": 1000.0, "window": controller.WAKE_DEDUPE_SECONDS},
    }
    # audit line written
    audited = [json.loads(l) for l in settings.wake_audit_path.read_text().splitlines()]
    assert audited[-1]["slug"] == "b3" and audited[-1]["msg_id"] == 12063


def test_compose_click_wake_line_top_n_with_sender_and_more():
    """COCKPIT_CARD_CLICK_WAKE_INJECT_1 — the click nudge carries count + top-3
    '#id topic (from sender)' + a '+K more' tail, oldest id first."""
    row = {"unacked_count": 4, "unacked_messages": [
        {"id": 10, "topic": "alpha", "from_terminal": "lead", "created_at": "2026-07-19T01:00:00Z"},
        {"id": 11, "topic": "beta", "from_terminal": "codex", "created_at": "2026-07-19T02:00:00Z"},
        {"id": 12, "topic": "gamma", "from_terminal": "lead", "created_at": "2026-07-19T03:00:00Z"},
        {"id": 13, "topic": "delta", "from_terminal": "codex", "created_at": "2026-07-19T04:00:00Z"},
    ]}
    line = controller.compose_click_wake_line(row)
    assert line == (
        "[wake] check your bus: 4 unacked — #10 alpha (from lead), "
        "#11 beta (from codex), #12 gamma (from lead) +1 more"
    )
    # oldest id first so _composer_holds' #\d+ anchor still matches the dedupe key.
    assert line.index("#10") < line.index("#11")


def test_compose_click_wake_line_omits_sender_when_absent():
    """The leaner glance row (no from_terminal) still composes — sender omitted."""
    row = {"unacked_count": 1, "unacked_messages": [
        {"id": 7, "topic": "t", "created_at": "z"}]}
    assert controller.compose_click_wake_line(row) == "[wake] check your bus: 1 unacked — #7 t"


def test_send_wake_click_origin_uses_rich_line(tmp_path, fake_tmux):
    """A click-origin wake injects the rich line; the sweep/default stays terse."""
    settings = _settings(tmp_path)
    rich = controller.send_wake(
        settings, ENTRY, UNACKED_ROW, now=1000.0, last_wake={},
        audit_source="cockpit_click",
    )
    assert rich["line"].startswith("[wake] check your bus: 2 unacked — #12063 ao-room-architecture")
    bare = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=2000.0, last_wake={})
    assert bare["line"] == "[wake] check bus #12063 ao-room-architecture"


def test_codex_family_verify_skips_c_l_repaint(tmp_path, fake_tmux):
    entry = controller.ManifestEntry(slug="deputy-codex", alias="aihead2", port=17603)
    result = controller.send_wake(
        _settings(tmp_path), entry, UNACKED_ROW, now=1000.0, last_wake={}
    )

    assert result["verified"] == "submitted"
    assert ["send-keys", "-t", "deputy-codex", "C-l"] not in fake_tmux
    assert ["capture-pane", "-t", "deputy-codex", "-p"] in fake_tmux


def test_send_wake_verify_off_skips_pane_reads(tmp_path, fake_tmux):
    """verify=False preserves the FIX_1 three-call shape (used where a pane read
    is not wanted, e.g. deterministic unit paths)."""
    res = controller.send_wake(
        _settings(tmp_path), ENTRY, UNACKED_ROW, now=1000.0, last_wake={}, verify=False,
    )
    assert res["sent"] is True and "verified" not in res
    assert len(fake_tmux) == 3  # literal, Enter, Enter — no capture-pane


def test_wake_inject_writes_is_text_then_separate_cr():
    """D4 single-source: literal text, then a bare CR as its OWN write — never a
    newline coalesced into the text or wrapped in a bracketed paste."""
    writes = controller.wake_inject_writes("[wake] check bus #7 topic")
    assert writes == [("literal", "[wake] check bus #7 topic"), ("cr", "\r")]
    assert "\n" not in writes[0][1] and "\x1b[200~" not in writes[0][1]


LINE7 = "[wake] check bus #7 topic"


@pytest.mark.parametrize("pane,injected,parked", [
    ("", LINE7, False),                                                               # empty pane
    ("some scrollback\n> [wake] check bus #7 topic\n✻ Zesting…", LINE7, False),        # submitted: plain `>` line, no box marker
    ("╭────╮\n│ ❯ [wake] check bus #7 topic │\n╰────╯", LINE7, True),                  # parked: tagged + boxed
    ("❯ [wake] check bus #7 topic", LINE7, True),                                      # parked: prompt-glyph line
    ("│ ❯ [wake] check bus #99 x │", LINE7, False),                                    # tagged+boxed but different id
    # AC3 — a HUMAN line with no [wake] tag must NEVER read as parked, even when it
    # contains the same `check bus #7` text and sits boxed at the prompt.
    ("│ ❯ check bus #7 my-own-note │", LINE7, False),
    ("╭────╮\n│ ❯ check bus #7 mine │\n╰────╯", LINE7, False),
    # defensive: an untagged needle can never match (guards misuse).
    ("│ ❯ [wake] check bus #7 topic │", "check bus #7", False),
])
def test_composer_holds_requires_tag_and_id(pane, injected, parked):
    assert controller._composer_holds(pane, injected) is parked


def _capturing_fake(monkeypatch, pane_sequence):
    """fake _run_tmux where capture-pane returns successive panes from a list
    (last value repeats); every other command returns rc0 empty."""
    calls = []
    panes = list(pane_sequence)

    def _fake(settings, args):
        calls.append(list(args))
        if args[:1] == ["capture-pane"]:
            pane = panes.pop(0) if len(panes) > 1 else (panes[0] if panes else "")
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout=pane, stderr="")
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_run_tmux", _fake)
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    return calls


def test_send_wake_recovers_a_parked_nudge(tmp_path, monkeypatch):
    """D2/AC2 — first capture shows the nudge boxed (parked); after ONE recovery
    Enter the second capture is clean -> verified 'recovered', exactly one extra
    Enter, no bus flag."""
    parked = "│ ❯ [wake] check bus #12063 ao-room-architecture │"
    calls = _capturing_fake(monkeypatch, [parked, ""])  # parked then clear
    flags = []
    monkeypatch.setattr(controller, "_post_park_flag", lambda *a: flags.append(a))
    res = controller.send_wake(_settings(tmp_path), ENTRY, UNACKED_ROW, now=1.0, last_wake={})
    assert res["verified"] == "recovered"
    enters = [c for c in calls if c == ["send-keys", "-t", "b3", "Enter"]]
    assert len(enters) == 3  # 2 FIX_1 submit-Returns + exactly 1 recovery Enter
    assert flags == []  # recovered -> no fail-loud flag


def test_send_wake_unrecoverable_park_fails_loud(tmp_path, monkeypatch):
    """D2/AC2 — nudge stays boxed after the recovery Enter -> verified
    'park_unrecovered', exactly one recovery Enter, and the fail-loud bus flag
    fires."""
    parked = "│ ❯ [wake] check bus #12063 ao-room-architecture │"
    calls = _capturing_fake(monkeypatch, [parked, parked])  # never clears
    flags = []
    monkeypatch.setattr(controller, "_post_park_flag", lambda *a: flags.append(a))
    res = controller.send_wake(_settings(tmp_path), ENTRY, UNACKED_ROW, now=1.0, last_wake={})
    assert res["verified"] == "park_unrecovered"
    assert res["disposition"] == "undelivered"
    assert res["reason"] == "park_unrecovered"
    assert res["skipped"] == "park_unrecovered"
    enters = [c for c in calls if c == ["send-keys", "-t", "b3", "Enter"]]
    assert len(enters) == 3  # never more than one recovery Enter (double-submit guard)
    assert len(flags) == 1 and flags[0][1] == "b3"


def test_send_wake_unreadable_pane_takes_no_action(tmp_path, monkeypatch):
    """A failed capture (rc!=0) must not trigger a false recovery or a false
    flag — verified 'unknown', no recovery Enter, no bus post."""
    calls = []

    def _fake(settings, args):
        calls.append(list(args))
        rc = 1 if args[:1] == ["capture-pane"] else 0
        return subprocess.CompletedProcess(args=list(args), returncode=rc, stdout="", stderr="x")

    monkeypatch.setattr(controller, "_run_tmux", _fake)
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    flags = []
    monkeypatch.setattr(controller, "_post_park_flag", lambda *a: flags.append(a))
    res = controller.send_wake(_settings(tmp_path), ENTRY, UNACKED_ROW, now=1.0, last_wake={})
    assert res["verified"] == "unknown"
    assert res["disposition"] == "undelivered"
    assert res["reason"] == "unverified"
    assert res["skipped"] == "unverified"
    enters = [c for c in calls if c == ["send-keys", "-t", "b3", "Enter"]]
    assert len(enters) == 2  # only the FIX_1 submit-Returns, no recovery
    assert flags == []


def test_send_wake_never_recovers_human_composed_text(tmp_path, monkeypatch):
    """AC3 (codex #12917) — a HUMAN line that happens to contain the same
    `check bus #<id>` text, sitting boxed at the prompt with NO [wake] tag, must
    NEVER trip a recovery Enter (that would auto-submit the human's text).
    _composer_holds requires the machine tag, so this reads as submitted."""
    human = "│ ❯ check bus #12063 my own note, still editing │"  # no [wake] tag
    calls = _capturing_fake(monkeypatch, [human, human])
    flags = []
    monkeypatch.setattr(controller, "_post_park_flag", lambda *a: flags.append(a))
    res = controller.send_wake(_settings(tmp_path), ENTRY, UNACKED_ROW, now=1.0, last_wake={})
    assert res["verified"] == "submitted"        # our tagged nudge cleared; human text ignored
    enters = [c for c in calls if c == ["send-keys", "-t", "b3", "Enter"]]
    assert len(enters) == 2                       # FIX_1 Returns only — NO recovery Enter
    assert flags == []


def test_send_wake_settles_between_text_and_enters(tmp_path, monkeypatch):
    """WAKE_COMPOSER_SUBMIT_FIX_1: the composer needs time to absorb the pasted
    text before Enter, and the submit-Return needs a settle gap too — otherwise
    a banner/busy composer parks the line unsubmitted (gap 5, bus #12631)."""
    sleeps = []
    calls = []

    def _fake(settings, args):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_run_tmux", _fake)
    monkeypatch.setattr(controller.time, "sleep", lambda s: sleeps.append(s))
    res = controller.send_wake(_settings(tmp_path), ENTRY, UNACKED_ROW, now=1000.0, last_wake={}, verify=False)
    assert res["sent"] is True
    assert sleeps == [controller.WAKE_SUBMIT_SETTLE_S, controller.WAKE_SUBMIT_SETTLE_S]


def test_send_wake_submit_return_failure_is_logged_not_raised(tmp_path, monkeypatch):
    """The trailing submit-Return is best-effort: a bare Return is a no-op when
    the first Enter already submitted, so its failure must never fail the wake."""
    calls = []

    def _fake(settings, args):
        calls.append(list(args))
        rc = 1 if len(calls) == 3 else 0  # only the submit-Return fails
        return subprocess.CompletedProcess(args=list(args), returncode=rc, stdout="", stderr="boom")

    monkeypatch.setattr(controller, "_run_tmux", _fake)
    res = controller.send_wake(_settings(tmp_path), ENTRY, UNACKED_ROW, now=1000.0, last_wake={}, verify=False)
    assert res["sent"] is True  # wake still reports sent
    assert len(calls) == 3


def test_send_wake_dedupes_within_window(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": {"last_injection": 900.0, "message_last": {"12063": 900.0}}}
    res = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=900.0 + controller.WAKE_DEDUPE_SECONDS - 1, last_wake=last)
    assert res["sent"] is False and res["skipped"] == "deduped"
    assert fake_tmux == []  # nothing sent


def test_send_wake_fires_again_after_window(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": {"last_injection": 900.0, "message_last": {"12063": 900.0}}}
    res = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=900.0 + controller.WAKE_DEDUPE_SECONDS + 1, last_wake=last)
    assert res["sent"] is True


def test_send_wake_new_message_inside_old_window_fires_after_seat_floor(
    tmp_path, fake_tmux
):
    settings = _settings(tmp_path)
    last = {"b3": {"last_injection": 900.0, "message_last": {"12063": 900.0}}}
    newer = {
        **UNACKED_ROW,
        "unacked_messages": [
            {"id": 12099, "topic": "later-topic", "created_at": "2026-07-17T09:00:00Z"},
        ],
    }
    res = controller.send_wake(
        settings,
        ENTRY,
        newer,
        now=900.0 + controller.WAKE_SEAT_FLOOR_SECONDS + 1,
        last_wake=last,
        verify=False,
    )
    assert res["sent"] is True
    assert last["b3"]["message_last"]["12099"] == {
        "at": 961.0,
        "window": controller.WAKE_DEDUPE_SECONDS,
    }


def test_send_wake_new_message_respects_seat_floor(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": {"last_injection": 900.0, "message_last": {"12063": 900.0}}}
    newer = {
        **UNACKED_ROW,
        "unacked_messages": [
            {"id": 12099, "topic": "later-topic", "created_at": "2026-07-17T09:00:00Z"},
        ],
    }
    res = controller.send_wake(
        settings,
        ENTRY,
        newer,
        now=900.0 + controller.WAKE_SEAT_FLOOR_SECONDS - 1,
        last_wake=last,
    )
    assert res["sent"] is False and res["skipped"] == "seat_floor"
    assert fake_tmux == []


def test_send_wake_same_message_repeat_does_not_double_wake(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": {"last_injection": 900.0, "message_last": {"12063": 900.0}}}
    res = controller.send_wake(
        settings,
        ENTRY,
        UNACKED_ROW,
        now=900.0 + controller.WAKE_SEAT_FLOOR_SECONDS + 1,
        last_wake=last,
    )
    assert res["sent"] is False and res["skipped"] == "deduped"
    assert fake_tmux == []


def test_send_wake_command_repeat_window_is_120_seconds(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    command_row = {
        **UNACKED_ROW,
        "unacked_messages": [
            {
                "id": 12063,
                "kind": "dispatch",
                "topic": "ao-room-architecture",
                "created_at": "2026-07-16T20:00:00Z",
            },
        ],
    }
    last = {"b3": {"last_injection": 900.0, "message_last": {"12063": 900.0}}}
    res = controller.send_wake(
        settings,
        ENTRY,
        command_row,
        now=900.0 + 121,
        last_wake=last,
        verify=False,
    )
    assert res["sent"] is True
    assert last["b3"]["message_last"]["12063"] == {
        "at": 1021.0,
        "window": controller.WAKE_COMMAND_DEDUPE_SECONDS,
    }


def test_send_wake_audits_suppressed_count_for_coalesced_repeat(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    command_row = {
        **UNACKED_ROW,
        "unacked_messages": [
            {
                "id": 12063,
                "kind": "dispatch",
                "topic": "ao-room-architecture",
                "created_at": "2026-07-16T20:00:00Z",
            },
        ],
    }
    last = {}
    first = controller.send_wake(
        settings, ENTRY, command_row, now=1000.0, last_wake=last, verify=False,
    )
    suppressed = controller.send_wake(
        settings, ENTRY, command_row, now=1061.0, last_wake=last, verify=False,
    )
    final = controller.send_wake(
        settings, ENTRY, command_row, now=1121.0, last_wake=last, verify=False,
    )
    assert first["sent"] is True
    assert suppressed["sent"] is False and suppressed["skipped"] == "deduped"
    assert final["sent"] is True
    audit = [
        json.loads(line)
        for line in settings.wake_audit_path.read_text().splitlines()
    ]
    assert "suppressed_count" not in audit[0]
    assert audit[1]["skipped"] == "deduped"
    assert audit[1]["suppressed_count"] == 1
    assert audit[-1]["suppressed_count"] == 1


def test_send_wake_prunes_expired_suppression_count_with_message_window(
    tmp_path, fake_tmux
):
    """A coalesced message's suppression counter expires with its dedupe entry."""
    settings = _settings(tmp_path)
    last = {}

    first = controller.send_wake(
        settings, ENTRY, UNACKED_ROW, now=0.0, last_wake=last, verify=False,
    )
    suppressed = controller.send_wake(
        settings, ENTRY, UNACKED_ROW, now=61.0, last_wake=last, verify=False,
    )
    newer = {
        **UNACKED_ROW,
        "unacked_messages": [
            {
                "id": 12099,
                "topic": "later-topic",
                "created_at": "2026-07-17T09:00:00Z",
            },
        ],
    }
    next_message = controller.send_wake(
        settings, ENTRY, newer, now=601.0, last_wake=last, verify=False,
    )

    assert first["sent"] is True
    assert suppressed["sent"] is False and suppressed["skipped"] == "deduped"
    assert next_message["sent"] is True
    assert last["b3"]["suppressed_count"] == {}
    assert "12063" not in last["b3"]["message_last"]
    assert "12099" in last["b3"]["message_last"]


def test_send_wake_force_bypasses_dedupe_but_still_submits(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": {"last_injection": 1000.0, "message_last": {"12063": 1000.0}}}
    res = controller.send_wake(
        settings,
        ENTRY,
        UNACKED_ROW,
        now=1001.0,
        last_wake=last,
        force=True,
    )
    assert res["sent"] is True
    assert res["verified"] == "submitted"
    assert len(fake_tmux) == 5


def test_send_wake_click_debounce_coalesces_repeat_across_pages(tmp_path, fake_tmux):
    """P2a (codex FAIL #13397): a click nudge (force=1) bypasses the per-message
    dedupe + seat-floor by design, so the ONLY prior idempotence was a per-PAGE JS
    debounce — which a reload / second tab / delayed repeat defeats. The server-side
    per-slug click window coalesces those repeats regardless of the originating page."""
    settings = _settings(tmp_path)
    last = {}
    first = controller.send_wake(
        settings, ENTRY, UNACKED_ROW, now=1000.0, last_wake=last,
        force=True, audit_source="cockpit_click", verify=False,
    )
    assert first["sent"] is True
    assert last["b3"]["last_click_injection"] == 1000.0
    fake_tmux.clear()
    # A second click within the window — e.g. a reopened tab that never saw the first
    # page's JS debounce — is coalesced server-side. Nothing is injected.
    second = controller.send_wake(
        settings, ENTRY, UNACKED_ROW,
        now=1000.0 + controller.WAKE_CLICK_DEBOUNCE_SECONDS - 0.1,
        last_wake=last, force=True, audit_source="cockpit_click", verify=False,
    )
    assert second["sent"] is False and second["skipped"] == "click_deduped"
    assert fake_tmux == []


def test_send_wake_click_debounce_releases_after_window(tmp_path, fake_tmux):
    """A genuine later re-nudge (past the click window) still fires — the debounce
    only coalesces rapid repeats, it does not permanently mute the seat."""
    settings = _settings(tmp_path)
    last = {}
    controller.send_wake(
        settings, ENTRY, UNACKED_ROW, now=1000.0, last_wake=last,
        force=True, audit_source="cockpit_click", verify=False,
    )
    later = controller.send_wake(
        settings, ENTRY, UNACKED_ROW,
        now=1000.0 + controller.WAKE_CLICK_DEBOUNCE_SECONDS + 0.1,
        last_wake=last, force=True, audit_source="cockpit_click", verify=False,
    )
    assert later["sent"] is True


def test_send_wake_click_debounce_is_click_origin_only(tmp_path, fake_tmux):
    """The click debounce is independent of the protected dedupe/typed-repeat state:
    a non-click forced wake neither arms it nor is blocked by a recent click window."""
    settings = _settings(tmp_path)
    last = {"b3": {"last_click_injection": 1000.0, "message_last": {}}}
    res = controller.send_wake(
        settings, ENTRY, UNACKED_ROW, now=1000.5, last_wake=last,
        force=True, verify=False,
    )
    assert res["sent"] is True  # not click_deduped despite a recent click window


def test_send_wake_guarded_seat_is_noop(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    res = controller.send_wake(settings, ENTRY, {"is_working": True, "unacked_count": 5}, now=1.0, last_wake={})
    assert res["sent"] is False and res["skipped"] == "working"
    assert fake_tmux == []
