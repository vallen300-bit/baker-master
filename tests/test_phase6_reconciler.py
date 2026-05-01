"""Tests for orchestrator.cortex_phase6_reconciler.

Brief: CORTEX_PHASE6_VAULT_RECONCILER_1 §Tests.

Live-PG via ``needs_live_pg``. Auto-skips without TEST_DATABASE_URL.
Exercises:
  * happy path no-op (marker + file + cycle block present)
  * missing file -> file written from scratch with frontmatter + block
  * missing block -> cycle block appended; existing blocks intact
  * idempotent re-run -> second run is no-op
  * proposal_text re-load via _load_proposal_text
  * bounded enumeration honors limit=200
  * error isolation: one re-emit failure does not block other cycles
  * baker_actions audit row written per successful re-emit
"""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest


REPO_MIGRATIONS_DIR = str(
    pathlib.Path(__file__).resolve().parents[1] / "migrations"
)


@pytest.fixture
def live_db(needs_live_pg, monkeypatch):
    import psycopg2
    from config.migration_runner import run_pending_migrations

    run_pending_migrations(needs_live_pg, migrations_dir=REPO_MIGRATIONS_DIR)
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    from memory.store_back import SentinelStoreBack
    SentinelStoreBack._global_instance = None  # type: ignore[attr-defined]

    conn = psycopg2.connect(needs_live_pg)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        SentinelStoreBack._global_instance = None  # type: ignore[attr-defined]


def _create_cycle(conn, *, matter_slug: str, status: str = "approved") -> str:
    cycle_id = str(uuid.uuid4())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by,
            current_phase, status, director_action)
        VALUES (%s, %s, 'test', 'archive', %s, 'gold_approved')
        """,
        (cycle_id, matter_slug, status),
    )
    conn.commit()
    cur.close()
    return cycle_id


def _seed_synthesis(conn, cycle_id: str, proposal_text: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cortex_phase_outputs
            (cycle_id, phase, phase_order, artifact_type, payload)
        VALUES (%s, 'synthesize', 5, 'synthesis', %s::jsonb)
        """,
        (cycle_id, json.dumps({"proposal_text": proposal_text})),
    )
    conn.commit()
    cur.close()


def _seed_marker(
    conn,
    cycle_id: str,
    *,
    outcome: str = "helpful",
    cited_ids: list = None,
) -> None:
    """Insert a reflector_complete marker WITHOUT calling
    write_proposed_actions_to_vault (simulates the gap the reconciler fixes)."""
    cited_ids = cited_ids or []
    payload = {
        "reflected_at": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome,
        "cited_ids": cited_ids,
        "unknown_ids": [],
        "had_invalid_tokens": False,
        "had_any_citation_match": bool(cited_ids),
    }
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cortex_phase_outputs
            (cycle_id, phase, phase_order, artifact_type, payload)
        VALUES (%s, 'archive', 6, 'reflector_complete', %s::jsonb)
        """,
        (cycle_id, json.dumps(payload)),
    )
    conn.commit()
    cur.close()


def _vault_path(staging_root: pathlib.Path, matter_slug: str) -> pathlib.Path:
    return staging_root / "matters" / matter_slug / "proposed-config-deltas.md"


# --------------------------------------------------------------------------
# Test 1: happy path no-op — marker exists, vault file exists with cycle block
# --------------------------------------------------------------------------


def test_happy_path_no_op_when_block_present(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes
    from orchestrator.cortex_phase6_reflector import write_proposed_actions_to_vault

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-noop-{suffix}"
    cycle_id = _create_cycle(live_db, matter_slug=matter)
    _seed_marker(live_db, cycle_id, outcome="helpful", cited_ids=[])

    # Pre-write the vault block (simulating a healthy Reflector run).
    vault = write_proposed_actions_to_vault(
        cycle_id=cycle_id,
        matter_slug=matter,
        proposal_text="proposal body",
        cited_ids=[],
        triaga_outcome="helpful",
        today_iso="2026-05-01",
        staging_root=tmp_path,
    )
    snapshot_before = vault.read_text(encoding="utf-8")

    counts = reconcile_vault_writes(staging_root=tmp_path)
    assert counts["re_emitted"] == 0
    # File untouched (byte-identical).
    assert vault.read_text(encoding="utf-8") == snapshot_before


# --------------------------------------------------------------------------
# Test 2: missing file — marker exists, vault file absent
# --------------------------------------------------------------------------


def test_missing_file_re_emits_with_frontmatter(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-missing-file-{suffix}"
    cycle_id = _create_cycle(live_db, matter_slug=matter)
    _seed_synthesis(live_db, cycle_id, "synthesis text for missing file")
    _seed_marker(live_db, cycle_id, outcome="helpful")

    vault = _vault_path(tmp_path, matter)
    assert not vault.exists()

    counts = reconcile_vault_writes(staging_root=tmp_path)
    assert counts["re_emitted"] == 1
    assert counts["missing_file"] == 1
    assert vault.exists()

    text = vault.read_text(encoding="utf-8")
    # Frontmatter present (validate_frontmatter required keys).
    assert text.startswith("---\n")
    assert "type: matter\n" in text
    assert f"slug: {matter}\n" in text
    # Cycle block landed.
    assert f"## Cycle {cycle_id} \u2014" in text
    assert "synthesis text for missing file" in text


# --------------------------------------------------------------------------
# Test 3: missing block — file present, other cycle blocks intact, append
# --------------------------------------------------------------------------


def test_missing_block_appends_intact(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes
    from orchestrator.cortex_phase6_reflector import write_proposed_actions_to_vault

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-missing-block-{suffix}"

    # Cycle A: written normally (frontmatter + block).
    cycle_a = _create_cycle(live_db, matter_slug=matter)
    write_proposed_actions_to_vault(
        cycle_id=cycle_a,
        matter_slug=matter,
        proposal_text="prior cycle body",
        cited_ids=[],
        triaga_outcome="helpful",
        today_iso="2026-04-25",
        staging_root=tmp_path,
    )

    # Cycle B: marker only — block absent (drift).
    cycle_b = _create_cycle(live_db, matter_slug=matter)
    _seed_synthesis(live_db, cycle_b, "drift cycle body")
    _seed_marker(live_db, cycle_b, outcome="harmful")

    counts = reconcile_vault_writes(staging_root=tmp_path)
    assert counts["re_emitted"] == 1
    assert counts["missing_block"] == 1

    vault = _vault_path(tmp_path, matter)
    text = vault.read_text(encoding="utf-8")
    # Both cycle blocks present.
    assert f"## Cycle {cycle_a} \u2014" in text
    assert f"## Cycle {cycle_b} \u2014" in text
    # Prior cycle body untouched.
    assert "prior cycle body" in text
    assert "drift cycle body" in text


# --------------------------------------------------------------------------
# Test 4: idempotent re-run
# --------------------------------------------------------------------------


def test_idempotent_back_to_back_runs(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-idempotent-{suffix}"
    cycle_id = _create_cycle(live_db, matter_slug=matter)
    _seed_synthesis(live_db, cycle_id, "idempotent body")
    _seed_marker(live_db, cycle_id, outcome="helpful")

    counts1 = reconcile_vault_writes(staging_root=tmp_path)
    assert counts1["re_emitted"] == 1

    counts2 = reconcile_vault_writes(staging_root=tmp_path)
    assert counts2["re_emitted"] == 0
    assert counts2["missing_file"] == 0
    assert counts2["missing_block"] == 0


# --------------------------------------------------------------------------
# Test 5: proposal_text re-load — reconciler reads from cortex_phase_outputs
# --------------------------------------------------------------------------


def test_proposal_text_reloaded_from_synthesis(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-reload-{suffix}"
    cycle_id = _create_cycle(live_db, matter_slug=matter)

    distinctive = f"DISTINCTIVE-MARKER-{suffix}-from-synthesis"
    _seed_synthesis(live_db, cycle_id, distinctive)
    # Marker payload deliberately omits proposal_text; reconciler must reload.
    _seed_marker(live_db, cycle_id, outcome="helpful")

    counts = reconcile_vault_writes(staging_root=tmp_path)
    assert counts["re_emitted"] == 1

    vault = _vault_path(tmp_path, matter)
    assert distinctive in vault.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Test 6: bounded enumeration — limit=2 across 3 markers, second run sweeps
# rest. (Brief example uses 250/200; we shrink for test speed but verify
# bounded ordering is honored.)
# --------------------------------------------------------------------------


def test_bounded_enumeration_respects_limit(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-bounded-{suffix}"
    cycle_ids = []
    for _ in range(3):
        c = _create_cycle(live_db, matter_slug=matter)
        _seed_synthesis(live_db, c, f"body {c}")
        _seed_marker(live_db, c, outcome="helpful")
        cycle_ids.append(c)

    counts = reconcile_vault_writes(limit=2, staging_root=tmp_path)
    # Reconciler enumerated AT MOST 2 of OUR markers; other suites running on
    # the same DB may seed additional markers, so checked >= 2 is the safe
    # floor and re_emitted reflects only what we touched.
    assert counts["checked"] <= 2
    # First run wrote 1 or 2 of our cycles' blocks.
    assert counts["re_emitted"] >= 1

    vault = _vault_path(tmp_path, matter)
    text_after_first = vault.read_text(encoding="utf-8")
    blocks_present_first = sum(
        1 for c in cycle_ids if f"## Cycle {c} \u2014" in text_after_first
    )
    assert blocks_present_first >= 1
    assert blocks_present_first <= 2

    # Second run picks up remaining cycles (also bounded).
    reconcile_vault_writes(limit=10, staging_root=tmp_path)
    text_after_second = vault.read_text(encoding="utf-8")
    blocks_present_second = sum(
        1 for c in cycle_ids if f"## Cycle {c} \u2014" in text_after_second
    )
    assert blocks_present_second == 3


# --------------------------------------------------------------------------
# Test 7: error isolation — one cycle's re-emit raises; others still re-emit
# --------------------------------------------------------------------------


def test_error_isolation_one_failure_others_succeed(live_db, tmp_path, monkeypatch):
    from orchestrator import cortex_phase6_reconciler

    suffix = uuid.uuid4().hex[:8]
    matter_a = f"reconcile-err-a-{suffix}"
    matter_b = f"reconcile-err-b-{suffix}"

    cycle_a = _create_cycle(live_db, matter_slug=matter_a)
    _seed_synthesis(live_db, cycle_a, "body A")
    _seed_marker(live_db, cycle_a, outcome="helpful")

    cycle_b = _create_cycle(live_db, matter_slug=matter_b)
    _seed_synthesis(live_db, cycle_b, "body B")
    _seed_marker(live_db, cycle_b, outcome="helpful")

    real_write = cortex_phase6_reconciler.write_proposed_actions_to_vault
    raised_for: dict = {}

    def flaky(*args, **kwargs):
        if kwargs.get("matter_slug") == matter_a and not raised_for.get("a"):
            raised_for["a"] = True
            raise OSError("simulated FS failure for cycle A")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(
        cortex_phase6_reconciler, "write_proposed_actions_to_vault", flaky
    )

    counts = cortex_phase6_reconciler.reconcile_vault_writes(staging_root=tmp_path)
    # cycle B still re-emitted despite cycle A failure.
    assert counts["re_emit_failed"] == 1
    assert counts["re_emitted"] >= 1
    vault_b = _vault_path(tmp_path, matter_b)
    assert vault_b.exists()
    assert f"## Cycle {cycle_b} \u2014" in vault_b.read_text(encoding="utf-8")
    # cycle A vault file NOT created (write raised before any append).
    assert not _vault_path(tmp_path, matter_a).exists()


# --------------------------------------------------------------------------
# Test 8: baker_actions audit row — written per successful re-emit
# --------------------------------------------------------------------------


def test_audit_row_written_per_re_emit(live_db, tmp_path):
    from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes

    suffix = uuid.uuid4().hex[:8]
    matter = f"reconcile-audit-{suffix}"
    cycle_id = _create_cycle(live_db, matter_slug=matter)
    _seed_synthesis(live_db, cycle_id, "audit body")
    _seed_marker(live_db, cycle_id, outcome="helpful", cited_ids=[])

    counts = reconcile_vault_writes(staging_root=tmp_path)
    assert counts["re_emitted"] == 1

    cur = live_db.cursor()
    cur.execute(
        """
        SELECT action_type, target_task_id, payload, trigger_source, success
          FROM baker_actions
         WHERE action_type = %s
           AND target_task_id = %s
         ORDER BY id DESC
         LIMIT 1
        """,
        ("cortex_reflector_reconcile", cycle_id),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    action_type, target_task_id, payload, trigger_source, success = row
    assert action_type == "cortex_reflector_reconcile"
    assert target_task_id == cycle_id
    assert trigger_source == "cortex_phase6_reconciler"
    assert success is True
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["matter_slug"] == matter
    assert payload["outcome"] == "helpful"
    assert payload["replay_date"]  # non-empty
    assert payload["marker_created_at"]
    assert payload["vault_path"].endswith("proposed-config-deltas.md")
    assert payload["reason"] == "missing_file"
