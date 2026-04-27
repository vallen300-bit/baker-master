"""Tests for scripts.autopoll_state — frontmatter state machine helper.

BRIEF_B_CODE_AUTOPOLL_1 §"Quality Checkpoints" #1 mandates ≥12 tests
covering: parse, transitions (legal + illegal), body preservation,
claimed_at auto-populate, heartbeat, find_stale_claims, Slack push mock.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.autopoll_state import (  # noqa: E402
    LEGAL_TRANSITIONS,
    VALID_STATUSES,
    find_stale_claims,
    heartbeat,
    push_state_transition,
    read_state,
    transition_state,
)


OPEN_FRONTMATTER = """---
status: OPEN
brief: briefs/BRIEF_FAKE.md
trigger_class: LOW
dispatched_at: 2026-04-27T22:55:00Z
dispatched_by: ai-head-a
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: true
---

# CODE_TEST — fixture body

Body line 1.
Body line 2 with **markdown** and `code`.

```yaml
embedded: yaml-block-should-not-be-parsed-as-frontmatter
```

End of body.
"""


@pytest.fixture
def mailbox(tmp_path) -> Path:
    p = tmp_path / "CODE_TEST_PENDING.md"
    p.write_text(OPEN_FRONTMATTER)
    return p


def _body_after_split(text: str) -> str:
    end = text.find("\n---\n", 4)
    return text[end + 5:]


# 1
def test_read_state_parses_frontmatter(mailbox: Path) -> None:
    fm = read_state(mailbox)
    assert fm["status"] == "OPEN"
    assert fm["brief"] == "briefs/BRIEF_FAKE.md"
    assert fm["claimed_by"] is None
    assert fm["autopoll_eligible"] is True


# 2
def test_read_state_missing_frontmatter_raises(tmp_path: Path) -> None:
    p = tmp_path / "no_fm.md"
    p.write_text("# just a heading\n\nno frontmatter here.\n")
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        read_state(p)


# 3
def test_read_state_unterminated_frontmatter_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad_fm.md"
    p.write_text("---\nstatus: OPEN\nthis frontmatter never closes\n")
    with pytest.raises(ValueError, match="unterminated"):
        read_state(p)


# 4
def test_transition_open_to_in_progress_auto_populates_claimed_at(
    mailbox: Path,
) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    fm = read_state(mailbox)
    assert fm["status"] == "IN_PROGRESS"
    assert fm["claimed_by"] == "b3"
    assert fm["claimed_at"] is not None
    parsed = datetime.fromisoformat(fm["claimed_at"])
    assert parsed.tzinfo is not None


# 5
def test_transition_explicit_claimed_at_is_respected(mailbox: Path) -> None:
    fixed = "2026-04-27T22:00:00+00:00"
    transition_state(
        mailbox, to="IN_PROGRESS", claimed_by="b2", claimed_at=fixed
    )
    fm = read_state(mailbox)
    assert fm["claimed_at"] == fixed


# 6
def test_transition_illegal_open_to_complete_rejected(mailbox: Path) -> None:
    with pytest.raises(ValueError, match="illegal transition"):
        transition_state(mailbox, to="COMPLETE")
    fm = read_state(mailbox)
    assert fm["status"] == "OPEN"


# 7
def test_transition_invalid_status_rejected(mailbox: Path) -> None:
    with pytest.raises(ValueError, match="invalid status"):
        transition_state(mailbox, to="DONE")


# 8
def test_transition_legal_chain_in_progress_to_blocked_to_in_progress(
    mailbox: Path,
) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    transition_state(
        mailbox, to="BLOCKED-AI-HEAD-Q", blocker_question="need helper path?"
    )
    fm = read_state(mailbox)
    assert fm["status"] == "BLOCKED-AI-HEAD-Q"
    assert fm["blocker_question"] == "need helper path?"
    transition_state(mailbox, to="IN_PROGRESS")
    assert read_state(mailbox)["status"] == "IN_PROGRESS"


# 9
def test_transition_complete_to_retired_legal_then_terminal(
    mailbox: Path,
) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    transition_state(
        mailbox, to="COMPLETE", ship_report="briefs/_reports/x.md"
    )
    transition_state(mailbox, to="RETIRED")
    fm = read_state(mailbox)
    assert fm["status"] == "RETIRED"
    with pytest.raises(ValueError, match="illegal transition"):
        transition_state(mailbox, to="OPEN")


# 10
def test_transition_in_progress_to_open_for_stale_recovery(
    mailbox: Path,
) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    transition_state(mailbox, to="OPEN", claimed_by=None, claimed_at=None)
    fm = read_state(mailbox)
    assert fm["status"] == "OPEN"
    assert fm["claimed_by"] is None


# 11
def test_body_preservation_byte_perfect_after_round_trip(
    mailbox: Path,
) -> None:
    original_body = _body_after_split(mailbox.read_text())
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    heartbeat(mailbox)
    transition_state(
        mailbox, to="COMPLETE", ship_report="briefs/_reports/x.md"
    )
    final_body = _body_after_split(mailbox.read_text())
    assert final_body == original_body


# 12
def test_heartbeat_updates_field_only(mailbox: Path) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    before = read_state(mailbox)
    heartbeat(mailbox)
    after = read_state(mailbox)
    assert after["last_heartbeat"] is not None
    assert after["status"] == before["status"]
    assert after["claimed_by"] == before["claimed_by"]


# 13
def test_find_stale_claims_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert find_stale_claims(tmp_path) == []


# 14
def test_find_stale_claims_skips_open_and_fresh(tmp_path: Path) -> None:
    open_box = tmp_path / "CODE_1_PENDING.md"
    open_box.write_text(OPEN_FRONTMATTER)

    fresh = tmp_path / "CODE_2_PENDING.md"
    fresh.write_text(OPEN_FRONTMATTER)
    transition_state(fresh, to="IN_PROGRESS", claimed_by="b2")
    heartbeat(fresh)

    stale = find_stale_claims(tmp_path, max_age_minutes=60)
    assert stale == []


# 15
def test_find_stale_claims_returns_only_stale(tmp_path: Path) -> None:
    stale_box = tmp_path / "CODE_3_PENDING.md"
    stale_box.write_text(OPEN_FRONTMATTER)
    transition_state(stale_box, to="IN_PROGRESS", claimed_by="b3")
    old_hb = (
        datetime.now(timezone.utc) - timedelta(minutes=120)
    ).isoformat()
    text = stale_box.read_text()
    stale_box.write_text(
        text.replace("last_heartbeat: null", f"last_heartbeat: {old_hb}")
    )

    fresh_box = tmp_path / "CODE_4_PENDING.md"
    fresh_box.write_text(OPEN_FRONTMATTER)
    transition_state(fresh_box, to="IN_PROGRESS", claimed_by="b4")
    heartbeat(fresh_box)

    stale = find_stale_claims(tmp_path, max_age_minutes=60)
    assert [p.name for p in stale] == ["CODE_3_PENDING.md"]


# 16
def test_find_stale_claims_skips_no_heartbeat_yet(tmp_path: Path) -> None:
    just_claimed = tmp_path / "CODE_5_PENDING.md"
    just_claimed.write_text(OPEN_FRONTMATTER)
    transition_state(just_claimed, to="IN_PROGRESS", claimed_by="b5")
    assert find_stale_claims(tmp_path, max_age_minutes=0) == []


# 17
def test_legal_transitions_table_matches_brief() -> None:
    assert VALID_STATUSES == {
        "OPEN",
        "IN_PROGRESS",
        "BLOCKED-AI-HEAD-Q",
        "BLOCKED-DIRECTOR-Q",
        "COMPLETE",
        "RETIRED",
    }
    assert LEGAL_TRANSITIONS["OPEN"] == {"IN_PROGRESS"}
    assert LEGAL_TRANSITIONS["IN_PROGRESS"] == {
        "BLOCKED-AI-HEAD-Q",
        "BLOCKED-DIRECTOR-Q",
        "COMPLETE",
        "OPEN",
    }
    assert LEGAL_TRANSITIONS["RETIRED"] == set()


# 18
def test_push_state_transition_dual_channel_high_signal(
    mailbox: Path,
) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    fake = type("Mod", (), {})()
    calls: list[tuple[str, str]] = []
    fake.post_to_channel = lambda ch, txt: calls.append((ch, txt)) or True

    with patch.dict(sys.modules, {"outputs.slack_notifier": fake}):
        with patch.dict(
            "os.environ",
            {"BAKER_OVERNIGHT_CHANNEL_ID": "C_OVERNIGHT_TEST"},
        ):
            push_state_transition(mailbox, to="IN_PROGRESS")

    channels = [c for c, _ in calls]
    assert "C_OVERNIGHT_TEST" in channels
    assert "D0AFY28N030" in channels
    assert all("CODE_TEST_PENDING.md" in t for _, t in calls)
    assert all("(b3)" in t for _, t in calls)


# 19
def test_push_state_transition_low_signal_skips_dm(mailbox: Path) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")
    transition_state(
        mailbox, to="COMPLETE", ship_report="briefs/_reports/x.md"
    )
    transition_state(mailbox, to="RETIRED")
    fake = type("Mod", (), {})()
    calls: list[tuple[str, str]] = []
    fake.post_to_channel = lambda ch, txt: calls.append((ch, txt)) or True

    with patch.dict(sys.modules, {"outputs.slack_notifier": fake}):
        push_state_transition(mailbox, to="RETIRED")

    channels = [c for c, _ in calls]
    assert "D0AFY28N030" not in channels
    assert len(calls) == 1


# 20
def test_push_state_transition_silent_on_import_failure(
    mailbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transition_state(mailbox, to="IN_PROGRESS", claimed_by="b3")

    def boom(name, *_args, **_kwargs):
        if name == "outputs.slack_notifier":
            raise ImportError("simulated")
        return original_import(name, *_args, **_kwargs)

    import builtins

    original_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", boom)

    push_state_transition(mailbox, to="IN_PROGRESS")
