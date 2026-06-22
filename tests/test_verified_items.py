"""BAKER_DASHBOARD_V2_EVIDENCE_PACKET_1: tests for the evidence-packet schema +
state machine.

Two tiers:
  1. Pure-logic tests (always run) — FSM legality, evidence-field gating,
     dismissal-reason / ratify-actor vocab, migration parse-level checks.
  2. Live-PG round-trip (gated via tests/conftest.py::needs_live_pg) — applies
     the migration, then proves the full lifecycle and the same-transaction
     audit invariant (AC3): every state change writes a verification_events row.

Live tests redirect models.verified_items._get_conn / _put_conn at the live test
DB so the suite never touches prod and is independent of config env.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import models.verified_items as vi

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required")
from psycopg2 import errors as pg_errors  # noqa: E402


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "20260622c_dashboard_v2_evidence_packet.sql"

_SECTION_RE = re.compile(r"^--\s*==\s*migrate:(up|down)\s*==\s*$", re.MULTILINE)


def _strip_comment_leader(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("--"):
        rest = stripped[2:]
        if rest.startswith(" "):
            return line.replace("-- ", "", 1)
        return line.replace("--", "", 1)
    return line


def _parse_sections(sql_text: str) -> dict:
    matches = list(_SECTION_RE.finditer(sql_text))
    if not matches:
        raise RuntimeError("no `-- == migrate:(up|down) ==` markers found")
    sections: dict = {}
    for i, m in enumerate(matches):
        label = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql_text)
        body = sql_text[start:end].strip()
        if label == "down":
            body = "\n".join(
                _strip_comment_leader(line) for line in body.splitlines()
            ).strip()
        sections[label] = body
    return sections


# ============================================================================
# Tier 1 — pure logic (no DB)
# ============================================================================


def test_states_vocab():
    assert vi.STATES == frozenset({"candidate", "verified", "ratified", "dismissed"})


def test_valid_transitions_graph():
    # candidate can promote or be dismissed; cannot jump to ratified.
    assert vi.is_valid_transition("candidate", "verified")
    assert vi.is_valid_transition("candidate", "dismissed")
    assert not vi.is_valid_transition("candidate", "ratified")
    # verified can ratify or dismiss.
    assert vi.is_valid_transition("verified", "ratified")
    assert vi.is_valid_transition("verified", "dismissed")
    # ratified can only be dismissed (supersede).
    assert vi.is_valid_transition("ratified", "dismissed")
    assert not vi.is_valid_transition("ratified", "verified")
    # dismissed is terminal.
    for s in vi.STATES:
        assert not vi.is_valid_transition("dismissed", s)
    # no self-transitions.
    for s in ("candidate", "verified", "ratified"):
        assert not vi.is_valid_transition(s, s)
    # unknown from_state is never valid.
    assert not vi.is_valid_transition(None, "candidate")
    assert not vi.is_valid_transition("bogus", "verified")


def test_dismiss_reasons_vocab():
    expected = {
        "marketing", "duplicate", "wrong_matter", "stale", "not_important",
        "already_handled", "system_noise", "false_deadline", "false_promise", "other",
    }
    assert vi.DISMISS_REASONS == frozenset(expected)
    assert len(vi.DISMISS_REASONS) == 10


def test_ratify_actor_vocab():
    assert vi.RATIFY_ACTOR_TYPES == frozenset(
        {"director", "head_of_desk", "cortex_tier_b"}
    )


def test_missing_evidence_fields_complete_packet():
    packet = {
        "source_refs": [{"table": "email_messages", "id": "1"}],
        "claim": "Counterparty missed the SW deadline.",
        "confidence": "high",
        "source_trust": "known_counterparty",
        "verification_summary": "Checked the email + matter timeline.",
        "counterargument": "Could be an auto-reply, not a real commitment.",
    }
    assert vi.missing_evidence_fields(packet) == []


def test_missing_evidence_fields_empty_packet():
    miss = vi.missing_evidence_fields({})
    assert set(miss) == set(vi.REQUIRED_EVIDENCE_FIELDS)


def test_missing_evidence_fields_empty_source_refs_and_blank_strings():
    packet = {
        "source_refs": [],            # empty list -> missing
        "claim": "   ",               # whitespace -> missing
        "confidence": "low",
        "source_trust": "vip",
        "verification_summary": "x",
        "counterargument": None,      # None -> missing
    }
    miss = set(vi.missing_evidence_fields(packet))
    assert miss == {"source_refs", "claim", "counterargument"}


# ---- helper-level guard rails that short-circuit before touching the DB ----


def test_transition_rejects_invalid_state(monkeypatch):
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    r = vi.transition_item(1, "bogus_state", "system", "actor")
    assert r["ok"] is False and r["error"] == "invalid_state"


def test_transition_rejects_missing_actor(monkeypatch):
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    assert vi.transition_item(1, "verified", "", "actor")["error"] == "missing_actor"
    assert vi.transition_item(1, "verified", "system", "  ")["error"] == "missing_actor"


def test_ratify_rejects_anonymous_actor(monkeypatch):
    """AC5 — a non-allowlisted actor_type cannot ratify; rejected before DB."""
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    r = vi.ratify_item(1, "random_bot", "bot-7")
    assert r["ok"] is False and r["error"] == "bad_ratify_actor"


def test_dismiss_rejects_unstructured_reason(monkeypatch):
    """AC6 — dismissal reason must be in the structured set; rejected before DB."""
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    r = vi.dismiss_item(1, "because-i-said-so", "director", "dv")
    assert r["ok"] is False and r["error"] == "bad_dismiss_reason"


def test_create_states_vocab():
    """Creation is restricted to `candidate` ONLY (deputy-codex G0 F1 — verified
    was removed so the sole audited route to verified is transition_item;
    ratified/dismissed likewise only via audited transitions)."""
    assert vi.CREATE_STATES == frozenset({"candidate"})


def test_create_rejects_direct_ratified(monkeypatch):
    """AC5 — a complete-evidence row cannot be minted directly in `ratified`
    (which would record an actor_type='system' creation event = anonymous
    ratification). Rejected before the DB is reached."""
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    monkeypatch.setattr(vi, "_put_conn", lambda c: None)
    item = vi.create_verified_item(
        item_type="deadline", claim="direct-ratify attempt", created_by="system",
        state="ratified",
        source_refs=[{"table": "email_messages", "id": "1"}], confidence="high",
        source_trust="director", verification_summary="x", counterargument="y",
    )
    assert item is None


def test_create_rejects_direct_dismissed(monkeypatch):
    """`dismissed` is terminal + needs a reason — not a creation state."""
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    monkeypatch.setattr(vi, "_put_conn", lambda c: None)
    assert vi.create_verified_item(
        item_type="alert", claim="x", created_by="system", state="dismissed",
    ) is None


def test_create_rejects_direct_verified_without_seed_authorization(monkeypatch):
    """deputy-codex G0 F1 / STOP cond 4 — a runtime create directly in `verified`
    (no seed authorization) is refused before the DB is reached, even with a
    complete evidence packet. The only audited route to `verified` is
    transition_item; a direct create would record an anonymous actor_type='system'
    mint that bypasses the cortex/human verifier."""
    monkeypatch.setattr(vi, "_get_conn", lambda: pytest.fail("DB should not be reached"))
    monkeypatch.setattr(vi, "_put_conn", lambda c: None)
    assert "verified" not in vi.CREATE_STATES
    assert vi.create_verified_item(
        item_type="deadline", claim="direct-verified mint attempt", created_by="system",
        state="verified",
        source_refs=[{"table": "email_messages", "id": "1"}], confidence="high",
        source_trust="director", verification_summary="x", counterargument="y",
    ) is None


def test_fault_tolerant_no_connection(monkeypatch):
    """Degraded DB returns structured/empty results, never raises."""
    monkeypatch.setattr(vi, "_get_conn", lambda: None)
    monkeypatch.setattr(vi, "_put_conn", lambda c: None)
    assert vi.create_signal_candidate("t", "1", "deadline", "s", "gemini-2.5-pro") is None
    assert vi.create_verified_item("deadline", "c", "system") is None
    assert vi.transition_item(1, "verified", "system", "a")["error"] == "db_error"
    assert vi.list_items() == []
    assert vi.get_events(1) == []


# ---- migration parse-level ----


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_migration_parses_to_up_and_down():
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert "up" in sections and "down" in sections
    for tbl in ("signal_candidates", "verified_items", "verification_events"):
        assert f"CREATE TABLE IF NOT EXISTS {tbl}" in sections["up"]
        assert f"DROP TABLE IF EXISTS {tbl}" in sections["down"]


def test_migration_up_is_idempotent_ddl():
    """Every CREATE in UP uses IF NOT EXISTS (additive + re-runnable)."""
    up = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))["up"]
    creates = re.findall(r"CREATE (TABLE|INDEX|UNIQUE INDEX)([^\n;]*)", up)
    assert creates, "expected CREATE statements in UP"
    for kind, tail in creates:
        assert "IF NOT EXISTS" in tail, f"non-idempotent CREATE {kind}: {tail.strip()}"


def test_migration_has_no_concurrently():
    """Runner applies the file in one tx; CREATE INDEX CONCURRENTLY would abort."""
    up = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))["up"]
    assert "CONCURRENTLY" not in up.upper()


def test_migration_down_is_commented_in_raw_file():
    """The raw DOWN section must ship commented so the runner can't drop tables."""
    raw = MIGRATION_PATH.read_text(encoding="utf-8")
    down_marker = raw.index("== migrate:down ==")
    down_raw = raw[down_marker:]
    for line in down_raw.splitlines():
        if "DROP TABLE" in line:
            assert line.lstrip().startswith("--"), f"uncommented DROP in raw file: {line}"


# ============================================================================
# Tier 2 — live-PG round-trip (gated)
# ============================================================================


def _apply_migration(conn):
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    with conn.cursor() as cur:
        # Defensive: drop residue from a prior failed run, then apply UP.
        cur.execute(sections["down"])
        conn.commit()
        cur.execute(sections["up"])
        conn.commit()
        # Idempotency — UP twice must not error.
        cur.execute(sections["up"])
        conn.commit()


@pytest.fixture
def live_vi(needs_live_pg, monkeypatch):
    """Apply the migration against the live test DB and redirect the model's
    connection helpers there. Yields the DSN."""
    conn = psycopg2.connect(needs_live_pg)
    try:
        _apply_migration(conn)
    finally:
        conn.close()

    def _get():
        return psycopg2.connect(needs_live_pg)

    def _put(c):
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    monkeypatch.setattr(vi, "_get_conn", _get)
    monkeypatch.setattr(vi, "_put_conn", _put)
    return needs_live_pg


def test_migration_creates_tables_and_indexes(live_vi):
    conn = psycopg2.connect(live_vi)
    try:
        with conn.cursor() as cur:
            for t in ("signal_candidates", "verified_items", "verification_events"):
                cur.execute("SELECT to_regclass(%s)::text", (f"public.{t}",))
                assert cur.fetchone()[0] == t, f"{t} missing after UP"
            for idx in (
                "idx_verified_items_state",
                "idx_verified_items_people",
                "idx_verification_events_item",
                "idx_signal_candidates_status",
            ):
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=%s",
                    (idx,),
                )
                assert cur.fetchone(), f"index {idx} missing"
    finally:
        conn.close()


def test_full_lifecycle_candidate_verified_ratified(live_vi):
    """AC8 — create candidate -> promote verified -> ratify; every step audited."""
    cand_id = vi.create_signal_candidate(
        "email_messages", "test-evp-1", "deadline",
        "Counterparty acknowledged the SW deadline.",
        "gemini-2.5-pro", source_trust="known_counterparty",
        matter_slug="hagenauer-rg7", people=["Hassa"],
    )
    assert isinstance(cand_id, int)

    item_id = vi.create_verified_item(
        item_type="deadline",
        claim="Counterparty must deliver SW spec by 2026-07-01.",
        created_by="sentinel:proactive_pm",
        matter_slug="hagenauer-rg7",
        people=["Hassa"],
        source_type="email",
        source_trust="known_counterparty",
        source_refs=[{"table": "email_messages", "id": "test-evp-1"}],
        confidence="high",
        verification_summary="Checked email thread + matter timeline.",
        counterargument="Could be a non-binding acknowledgement.",
        signal_candidate_id=cand_id,
        extraction_model="gemini-2.5-pro",
    )
    assert isinstance(item_id, int)

    # Creation event present (NULL -> candidate).
    events = vi.get_events(item_id)
    assert len(events) == 1
    assert events[0]["from_state"] is None and events[0]["to_state"] == "candidate"

    # Promote candidate -> verified.
    r = vi.transition_item(
        item_id, "verified", "cortex", "opus-verifier",
        rationale="Evidence packet complete.", model="claude-opus-4-8",
    )
    assert r["ok"] is True and r["from_state"] == "candidate" and r["to_state"] == "verified"

    # Ratify verified -> ratified by Director.
    r2 = vi.ratify_item(item_id, "director", "dvallen", rationale="Confirmed real.")
    assert r2["ok"] is True and r2["to_state"] == "ratified"

    # Audit trail now has 3 rows in order.
    events = vi.get_events(item_id)
    assert [e["to_state"] for e in events] == ["candidate", "verified", "ratified"]

    # Row reflects the final state.
    rows = vi.list_items(state="ratified", matter_slug="hagenauer-rg7")
    assert any(row["id"] == item_id for row in rows)
    # Person filter (GIN containment).
    by_person = vi.list_items(person="Hassa")
    assert any(row["id"] == item_id for row in by_person)


def test_dismiss_with_structured_reason_persists(live_vi):
    """AC6 — a separate item dismissed as duplicate carries the reason + audit."""
    item_id = vi.create_verified_item(
        item_type="alert", claim="Possible duplicate quiet-thread card.",
        created_by="sentinel:proactive_pm", matter_slug="ao",
    )
    assert isinstance(item_id, int)
    r = vi.dismiss_item(item_id, "duplicate", "director", "dvallen",
                        rationale="Already tracked under item 42.")
    assert r["ok"] is True and r["to_state"] == "dismissed"

    rows = vi.list_items(state="dismissed", matter_slug="ao")
    found = next(row for row in rows if row["id"] == item_id)
    assert found["dismiss_reason"] == "duplicate"
    # Dismiss reason also recorded in the audit event delta.
    ev = vi.get_events(item_id)[-1]
    assert ev["to_state"] == "dismissed" and ev["evidence_delta"].get("dismiss_reason") == "duplicate"


def test_invalid_transition_candidate_to_ratified_rejected(live_vi):
    """AC8 invalid-transition: cannot jump candidate -> ratified; no audit row added."""
    item_id = vi.create_verified_item(
        item_type="deadline", claim="Direct-ratify attempt.",
        created_by="system",
    )
    before = len(vi.get_events(item_id))
    r = vi.ratify_item(item_id, "director", "dvallen")
    assert r["ok"] is False and r["error"] == "invalid_transition"
    # No event appended, state unchanged.
    assert len(vi.get_events(item_id)) == before
    assert vi.list_items(state="candidate")  # still a candidate somewhere
    row = next(x for x in vi.list_items() if x["id"] == item_id)
    assert row["state"] == "candidate"


def test_promote_blocked_when_evidence_missing(live_vi):
    """AC4 — candidate without a complete evidence packet cannot reach verified,
    and no audit event is written for the failed attempt."""
    item_id = vi.create_verified_item(
        item_type="deadline", claim="Thin candidate, no evidence yet.",
        created_by="system",  # no source_refs/confidence/etc.
    )
    before = len(vi.get_events(item_id))
    r = vi.transition_item(item_id, "verified", "cortex", "opus-verifier")
    assert r["ok"] is False and r["error"] == "missing_evidence"
    assert set(r["detail"]) <= set(vi.REQUIRED_EVIDENCE_FIELDS)
    assert len(vi.get_events(item_id)) == before  # AC3 — no half-write


def test_audit_and_state_change_share_one_transaction(live_vi):
    """AC3 — a successful transition writes BOTH the new state AND exactly one
    new verification_events row; counts move together."""
    item_id = vi.create_verified_item(
        item_type="alert", claim="Atomicity probe.", created_by="system",
        source_refs=[{"table": "alerts", "id": "x"}], confidence="medium",
        source_trust="internal_system", verification_summary="checked",
        counterargument="maybe noise",
    )
    conn = psycopg2.connect(live_vi)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM verification_events WHERE verified_item_id=%s",
                (item_id,),
            )
            n_before = cur.fetchone()[0]
        r = vi.transition_item(item_id, "verified", "cortex", "opus-verifier")
        assert r["ok"] is True
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM verified_items WHERE id=%s", (item_id,))
            assert cur.fetchone()[0] == "verified"
            cur.execute(
                "SELECT count(*) FROM verification_events WHERE verified_item_id=%s",
                (item_id,),
            )
            assert cur.fetchone()[0] == n_before + 1
    finally:
        conn.close()


def test_db_check_blocks_dismissed_without_reason(live_vi):
    """Defence-in-depth: the table CHECK rejects a dismissed row with no reason
    even if someone bypasses the model layer with raw SQL."""
    conn = psycopg2.connect(live_vi)
    try:
        with conn.cursor() as cur:
            with pytest.raises(pg_errors.CheckViolation):
                cur.execute(
                    "INSERT INTO verified_items (state, item_type, claim, created_by) "
                    "VALUES ('dismissed', 'alert', 'no reason given', 'system')"
                )
        conn.rollback()
    finally:
        conn.close()


def test_db_check_blocks_verified_without_evidence(live_vi):
    """Defence-in-depth: the table CHECK rejects a verified row missing the
    evidence packet even via raw SQL (source_refs defaults to empty array)."""
    conn = psycopg2.connect(live_vi)
    try:
        with conn.cursor() as cur:
            with pytest.raises(pg_errors.CheckViolation):
                cur.execute(
                    "INSERT INTO verified_items (state, item_type, claim, created_by) "
                    "VALUES ('verified', 'alert', 'no evidence', 'system')"
                )
        conn.rollback()
    finally:
        conn.close()


def test_db_check_rejects_non_array_source_refs_for_verified(live_vi):
    """Codex finding 2: a raw INSERT cannot satisfy the evidence CHECK with a
    non-array source_refs ('{}'::jsonb object or a scalar). Each must raise
    CheckViolation — not a non-array jsonb_array_length error."""
    conn = psycopg2.connect(live_vi)
    try:
        for bad in ("'{}'::jsonb", "'5'::jsonb", "'\"x\"'::jsonb"):
            with conn.cursor() as cur:
                with pytest.raises(pg_errors.CheckViolation):
                    cur.execute(
                        "INSERT INTO verified_items "
                        "(state, item_type, claim, created_by, confidence, "
                        " source_trust, verification_summary, counterargument, source_refs) "
                        f"VALUES ('verified', 'alert', 'bad refs', 'system', 'high', "
                        f"'vip', 'checked', 'maybe', {bad})"
                    )
            conn.rollback()
    finally:
        conn.close()
