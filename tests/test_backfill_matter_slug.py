"""DEADLINE_MATTER_SLUG_BACKFILL_1 — Scope B backfill-script tests.

Covers the four required cases from the brief:
  T1. Dry-run with 0 NULL rows → empty proposal, exit 0, no DB writes
  T2. Dry-run with mixed M+U buckets → proposal written, counts correct
  T3. --apply happy path → matched rows updated, idempotent on re-run
  T4. --apply with one bad row → savepoint preserves other rows' UPDATEs

All four are unit-style: the DB and the classifier are monkeypatched. This
keeps the suite self-contained (no live PG required) while still exercising
the SAVEPOINT pattern via a recording fake-cursor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``scripts/`` importable for the test.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))


# ---------------------------------------------------------------------------
# Fake DB primitives — record SQL + simulate per-row outcomes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Records every SQL statement + simulates UPDATE rowcount + forced errors.

    ``force_error_for_ids`` is a set of deadline IDs whose UPDATE should raise.
    ``existing_ids`` is the set of IDs that exist and still have NULL
    matter_slug (an UPDATE on those returns rowcount=1; otherwise 0).
    """

    def __init__(
        self,
        existing_ids: set[int] | None = None,
        force_error_for_ids: set[int] | None = None,
    ):
        self.statements: list[tuple[str, tuple]] = []
        self.rowcount = 0
        self._existing_ids = existing_ids or set()
        self._force_error_for_ids = force_error_for_ids or set()
        # Tracks which IDs have already been UPDATEd in this transaction so a
        # second UPDATE of the same id during --apply returns rowcount=0
        # (idempotency on re-run).
        self._updated_ids: set[int] = set()

    # Read paths — kept minimal; only used by dry-run.
    _SELECT_ROWS: list[tuple] = []

    def execute(self, sql: str, params: tuple | list | None = None):
        params = tuple(params or ())
        norm = " ".join(sql.split()).upper()
        self.statements.append((norm, params))

        if norm.startswith("SAVEPOINT") or norm.startswith("RELEASE SAVEPOINT") or norm.startswith("ROLLBACK TO SAVEPOINT"):
            self.rowcount = 0
            return

        if norm.startswith("UPDATE DEADLINES SET MATTER_SLUG"):
            slug = params[0]
            rid = params[1]
            if rid in self._force_error_for_ids:
                raise RuntimeError(f"simulated unique-constraint failure on id={rid}")
            if rid in self._existing_ids and rid not in self._updated_ids:
                self._updated_ids.add(rid)
                self.rowcount = 1
            else:
                # row missing or already-populated → 0 affected (idempotent)
                self.rowcount = 0
            return

        if norm.startswith("SELECT"):
            self.rowcount = len(self._SELECT_ROWS)
            return

        if norm.startswith("DELETE"):
            self.rowcount = 0
            return

        self.rowcount = 0

    def fetchall(self):
        return list(self._SELECT_ROWS)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _install_fake_db(monkeypatch, cursor: _FakeCursor) -> _FakeConn:
    """Make ``scripts.backfill_matter_slug`` use a fake conn/cursor."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")
    fake_conn = _FakeConn(cursor)
    monkeypatch.setattr(bms, "get_conn", lambda: fake_conn)
    monkeypatch.setattr(bms, "put_conn", lambda c: None)
    return fake_conn


# ---------------------------------------------------------------------------
# T1 — dry-run with 0 NULL rows → empty proposal, exit 0, no DB writes
# ---------------------------------------------------------------------------


def test_dry_run_zero_rows_empty_proposal(monkeypatch, tmp_path, capsys):
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    # No rows returned from the SELECT.
    monkeypatch.setattr(bms, "_query_null_matter_slug", lambda: [])

    # Classifier should never be called for an empty input — make it loud if it is.
    def _classify_should_not_be_called(rows):
        if rows:
            raise AssertionError("_classify called with non-empty rows in T1")
        return [], []

    monkeypatch.setattr(bms, "_classify", _classify_should_not_be_called)

    # Redirect proposal output to tmp_path so we don't pollute /tmp during tests.
    real_path_cls = bms.Path

    def _path_intercept(p):
        s = str(p)
        if s.startswith("/tmp/backfill_matter_slug_proposal_"):
            return tmp_path / Path(s).name
        return real_path_cls(p)

    from pathlib import Path

    monkeypatch.setattr(bms, "Path", _path_intercept)

    rc = bms.main([])
    assert rc == 0

    # The proposal file should exist + report M=0 / U=0.
    files = list(tmp_path.glob("backfill_matter_slug_proposal_*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "Bucket M (Matched, auto-apply candidate): **0 rows**" in content
    assert "Bucket U (Unmatched, manual review):      **0 rows**" in content


# ---------------------------------------------------------------------------
# T2 — dry-run with mixed match / no-match → M + U buckets, no DB writes
# ---------------------------------------------------------------------------


def test_dry_run_mixed_buckets_proposal(monkeypatch, tmp_path):
    import importlib
    from pathlib import Path

    bms = importlib.import_module("backfill_matter_slug")

    rows = [
        (101, "Cupial handover top 4 schlussabrechnung", "snippet 101", "email"),
        (102, "Random unrelated text with no matter context", "snippet 102", "calendar"),
        (103, "Hagenauer judgement update", "snippet 103", "fireflies"),
    ]
    monkeypatch.setattr(bms, "_query_null_matter_slug", lambda: rows)

    # Stub the classifier so the test does not depend on matter_registry state.
    def _fake_match(desc, snippet, store):
        if "Cupial" in desc:
            return "Cupial"
        if "Hagenauer" in desc:
            return "Hagenauer"
        return None

    monkeypatch.setattr(
        "orchestrator.pipeline._match_matter_slug", _fake_match,
    )

    # SentinelStoreBack._get_global_instance must not blow up — give a stub.
    from memory.store_back import SentinelStoreBack
    monkeypatch.setattr(
        SentinelStoreBack, "_get_global_instance",
        classmethod(lambda cls: object()),
    )

    # Redirect proposal output to tmp_path.
    real_path_cls = bms.Path

    def _path_intercept(p):
        s = str(p)
        if s.startswith("/tmp/backfill_matter_slug_proposal_"):
            return tmp_path / Path(s).name
        return real_path_cls(p)

    monkeypatch.setattr(bms, "Path", _path_intercept)

    rc = bms.main([])
    assert rc == 0

    files = list(tmp_path.glob("backfill_matter_slug_proposal_*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    # Two matched (cupial + hagenauer-rg7), one unmatched.
    assert "Bucket M (Matched, auto-apply candidate): **2 rows**" in content
    assert "Bucket U (Unmatched, manual review):      **1 rows**" in content
    assert "Cupial → cupial" in content
    assert "Hagenauer → hagenauer-rg7" in content
    assert "classifier returned None (no match)" in content


# ---------------------------------------------------------------------------
# T3 — --apply happy path: matched rows updated; idempotent on re-run
# ---------------------------------------------------------------------------


def _write_ratified_file(tmp_path, pairs: list[tuple[int, str]]) -> Path:
    """Write a minimal ratified-mapping file with a Bucket M table."""
    lines = [
        "# proposal",
        "",
        "## Bucket M (Matched) — N rows",
        "",
        "| id | description | matter_name raw → canonical slug | source_type | reason |",
        "|---:|---|---|---|---|",
    ]
    for rid, slug in pairs:
        lines.append(f"| {rid} | description {rid} | raw → {slug} | email | reason |")
    lines.append("")
    lines.append("## Bucket U (Unmatched) — 0 rows")
    lines.append("")
    path = tmp_path / "ratified.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_apply_happy_path_then_idempotent_rerun(monkeypatch, tmp_path):
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    cur = _FakeCursor(existing_ids={101, 103})
    fake_conn = _install_fake_db(monkeypatch, cur)

    pairs = [(101, "cupial"), (103, "hagenauer-rg7")]
    ratified = _write_ratified_file(tmp_path, pairs)

    rc = bms.main(["--apply", str(ratified)])
    assert rc == 0
    assert fake_conn.committed is True

    # Inspect statement log for the SAVEPOINT pattern and two successful
    # UPDATEs (rowcount=1 each).
    sql_only = [s[0] for s in cur.statements]
    assert sql_only.count("SAVEPOINT ROW_SP") == 2
    assert sql_only.count("RELEASE SAVEPOINT ROW_SP") == 2
    assert (
        sum(1 for s in sql_only if s.startswith("UPDATE DEADLINES SET MATTER_SLUG"))
        == 2
    )

    # Second --apply with the same ratified file → idempotent: both rows
    # already populated, so UPDATE rowcount drops to 0 (no failure).
    cur2 = _FakeCursor(existing_ids=set())  # no row remains NULL
    fake_conn2 = _install_fake_db(monkeypatch, cur2)
    rc2 = bms.main(["--apply", str(ratified)])
    assert rc2 == 0
    assert fake_conn2.committed is True


# ---------------------------------------------------------------------------
# T4 — --apply with one bad row: SAVEPOINT preserves other rows' UPDATEs
# ---------------------------------------------------------------------------


def test_apply_one_bad_row_savepoint_preserves_others(monkeypatch, tmp_path):
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    # Row 102 will raise during UPDATE; 101 + 103 succeed.
    cur = _FakeCursor(
        existing_ids={101, 102, 103},
        force_error_for_ids={102},
    )
    fake_conn = _install_fake_db(monkeypatch, cur)

    pairs = [(101, "cupial"), (102, "bad-slug"), (103, "hagenauer-rg7")]
    ratified = _write_ratified_file(tmp_path, pairs)

    rc = bms.main(["--apply", str(ratified)])
    # One row failed → exit 1, but the other two must still have been
    # committed (savepoint pattern — not a whole-transaction rollback).
    assert rc == 1
    assert fake_conn.committed is True
    assert fake_conn.rolled_back is False

    sql_only = [s[0] for s in cur.statements]
    # 3 SAVEPOINTs (one per row).
    assert sql_only.count("SAVEPOINT ROW_SP") == 3
    # 2 RELEASEs (101, 103) + 1 ROLLBACK TO (102).
    assert sql_only.count("RELEASE SAVEPOINT ROW_SP") == 2
    assert sql_only.count("ROLLBACK TO SAVEPOINT ROW_SP") == 1
    # Successful UPDATEs for 101 and 103 ran before the bad row error
    # AND a SAVEPOINT was opened around the failing UPDATE.
    update_params = [s[1] for s in cur.statements if s[0].startswith("UPDATE DEADLINES SET MATTER_SLUG")]
    assert (101 in [p[1] for p in update_params])
    assert (103 in [p[1] for p in update_params])


# ---------------------------------------------------------------------------
# T5 — safety rails: BAKER_BACKFILL_DRY_RUN_ONLY env blocks --apply
# ---------------------------------------------------------------------------


def test_apply_blocked_by_dry_run_only_env(monkeypatch, tmp_path):
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    monkeypatch.setenv("BAKER_BACKFILL_DRY_RUN_ONLY", "1")
    ratified = _write_ratified_file(tmp_path, [(101, "cupial")])

    # If get_conn were called we'd fail loudly — block must trigger first.
    def _no_db():
        raise AssertionError("get_conn must not be called when env blocks --apply")

    monkeypatch.setattr(bms, "get_conn", _no_db)

    rc = bms.main(["--apply", str(ratified)])
    assert rc == 2


# ---------------------------------------------------------------------------
# T6 + T7 — DEADLINE_SIGNAL_HYGIENE_1 Scope C: --cleanup-strays
# ---------------------------------------------------------------------------


def test_cleanup_strays_partitions_fixable_vs_null_out(monkeypatch):
    """The two stray rows from the brief (Oskolkov-RG7 + Financing...) test
    both branches: one normalizes to a canonical slug (fixable), one doesn't
    (null_out)."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    # Fake canonical_slugs() — a small registry.
    monkeypatch.setattr(
        bms.slug_registry,
        "canonical_slugs",
        lambda: {"hagenauer-rg7", "cupial", "mo-vie"},
    )

    # Fake normalize — Oskolkov-RG7 → hagenauer-rg7 (re-classified);
    # 'Financing Vienna' → None (no canonical match).
    def _fake_normalize(raw):
        if raw == "Oskolkov-RG7":
            return "hagenauer-rg7"
        return None

    monkeypatch.setattr(bms.slug_registry, "normalize", _fake_normalize)

    rows = [
        (501, "Oskolkov-RG7", "stray row 1"),
        (502, "Financing Vienna & Baden-Baden", "stray row 2"),
        (503, "cupial", "canonical — not a stray"),
    ]
    fixable, null_out = bms._classify_strays(rows)

    assert (501, "Oskolkov-RG7", "hagenauer-rg7") in fixable
    assert (502, "Financing Vienna & Baden-Baden", None) in null_out
    # 503 is canonical and must NOT appear in either bucket.
    assert all(r[0] != 503 for r in fixable + null_out)


def test_cleanup_strays_dry_run_writes_proposal(monkeypatch, tmp_path, capsys):
    """`--cleanup-strays` (no --apply) must write a markdown proposal file
    listing fixable + null_out buckets, AND must not write to DB."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    monkeypatch.setattr(
        bms,
        "_query_stray_matter_slugs",
        lambda: [
            (501, "Oskolkov-RG7", "row 1"),
            (502, "Financing Vienna & Baden-Baden", "row 2"),
        ],
    )
    monkeypatch.setattr(
        bms.slug_registry,
        "canonical_slugs",
        lambda: {"hagenauer-rg7", "cupial"},
    )
    monkeypatch.setattr(
        bms.slug_registry,
        "normalize",
        lambda r: "hagenauer-rg7" if r == "Oskolkov-RG7" else None,
    )

    # Redirect proposal output to tmp_path.
    real_path = bms.Path
    monkeypatch.setattr(
        bms,
        "Path",
        lambda p: (
            tmp_path / real_path(p).name
            if str(p).startswith("/tmp/cleanup_stray_")
            else real_path(p)
        ),
    )

    # If _apply_stray_cleanup were called we'd fail — dry run must not write.
    monkeypatch.setattr(
        bms,
        "_apply_stray_cleanup",
        lambda f, n: pytest.fail("_apply_stray_cleanup invoked during dry-run"),
    )

    rc = bms.main(["--cleanup-strays"])
    assert rc == 0

    out = capsys.readouterr().out.strip().splitlines()
    proposal_path = real_path(out[-1])
    assert proposal_path.exists()
    body = proposal_path.read_text(encoding="utf-8")
    assert "Bucket F — Fixable" in body
    assert "Bucket N — Null-out" in body
    assert "Oskolkov-RG7" in body
    assert "hagenauer-rg7" in body
    assert "Financing Vienna" in body


# ---------------------------------------------------------------------------
# T8 — DEADLINE_SIGNAL_HYGIENE_1 Scope C H1 (2026-05-13 REQUEST_CHANGES):
# --apply must require the ratified proposal file path + 24h staleness +
# parse the file (NO re-derive at exec time).
# ---------------------------------------------------------------------------


def _write_stray_proposal_file(path: Path, fixable: list, null_out: list) -> None:
    """Write a fixture proposal file in the same format _write_stray_proposal
    emits, so the parser round-trips."""
    lines = [
        "# DEADLINE_SIGNAL_HYGIENE_1 — Scope C stray cleanup proposal",
        "",
        "## Bucket F — Fixable (UPDATE matter_slug = canonical)",
        "",
    ]
    if fixable:
        lines.append("| id | current_slug | proposed_slug |")
        lines.append("|----|--------------|---------------|")
        for rid, current, proposed in fixable:
            lines.append(f"| {rid} | `{current}` | `{proposed}` |")
    else:
        lines.append("_(none)_")
    lines += ["", "## Bucket N — Null-out (UPDATE matter_slug = NULL)", ""]
    if null_out:
        lines.append("| id | current_slug |")
        lines.append("|----|--------------|")
        for rid, current, _ in null_out:
            lines.append(f"| {rid} | `{current}` |")
    else:
        lines.append("_(none)_")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_cleanup_strays_apply_missing_path_returns_2(monkeypatch, tmp_path):
    """--cleanup-strays --apply with a non-existent file path must exit 2."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    # If get_conn were called we'd fail — the staleness/parse gate must trip first.
    monkeypatch.setattr(
        bms,
        "get_conn",
        lambda: pytest.fail("get_conn must not be called on missing-path"),
    )

    rc = bms.main(["--cleanup-strays", "--apply", str(tmp_path / "nonexistent.md")])
    assert rc == 2


def test_cleanup_strays_apply_stale_file_returns_2(monkeypatch, tmp_path):
    """A ratified file >24h old must be rejected (staleness rail)."""
    import importlib
    import os
    import time as _time

    bms = importlib.import_module("backfill_matter_slug")

    proposal = tmp_path / "cleanup_stray_old.md"
    _write_stray_proposal_file(
        proposal, [(501, "Oskolkov-RG7", "hagenauer-rg7")], []
    )
    # Force mtime to 25h ago.
    old = _time.time() - (25 * 3600)
    os.utime(proposal, (old, old))

    monkeypatch.setattr(
        bms,
        "get_conn",
        lambda: pytest.fail("get_conn must not be called on stale file"),
    )

    rc = bms.main(["--cleanup-strays", "--apply", str(proposal)])
    assert rc == 2


def test_cleanup_strays_apply_uses_ratified_set_not_redrive(
    monkeypatch, tmp_path
):
    """REQUEST_CHANGES H1 — apply must use the exact rows from the ratified
    proposal file. If prod state has drifted since the dry-run (new strays
    appeared / existing ones cleared), the apply must NOT silently widen to
    the freshly-derived set."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    proposal = tmp_path / "cleanup_stray_ratified.md"
    _write_stray_proposal_file(
        proposal,
        [(501, "Oskolkov-RG7", "hagenauer-rg7")],
        [(502, "Financing Vienna & Baden-Baden", None)],
    )

    # If --apply re-derives (calls _query_stray_matter_slugs), this would
    # widen scope to id=999. The H1 fix must keep apply set bound to
    # the ratified file (501 + 502 only).
    def _drifted_query():
        return [
            (501, "Oskolkov-RG7", "old row"),
            (502, "Financing Vienna & Baden-Baden", "old row"),
            (999, "NewlyAppearedStray", "drifted row"),  # MUST NOT be applied
        ]

    monkeypatch.setattr(bms, "_query_stray_matter_slugs", _drifted_query)

    captured: dict = {}

    def _fake_apply(fixable, null_out):
        captured["fixable"] = list(fixable)
        captured["null_out"] = list(null_out)
        return {"affected": len(fixable) + len(null_out), "failed": []}

    monkeypatch.setattr(bms, "_apply_stray_cleanup", _fake_apply)

    rc = bms.main(["--cleanup-strays", "--apply", str(proposal)])
    assert rc == 0
    # The ratified set is exactly 501 (fixable) + 502 (null_out). 999 must NOT appear.
    ids_applied = (
        [r[0] for r in captured["fixable"]]
        + [r[0] for r in captured["null_out"]]
    )
    assert 501 in ids_applied
    assert 502 in ids_applied
    assert 999 not in ids_applied, (
        "H1 regression: --cleanup-strays --apply re-derived from prod and "
        "applied a row that wasn't in the ratified proposal file"
    )


def test_cleanup_strays_apply_blocked_by_dry_run_only_env(
    monkeypatch, tmp_path
):
    """Env-var kill switch must also block --cleanup-strays --apply."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    proposal = tmp_path / "cleanup_stray_envblock.md"
    _write_stray_proposal_file(
        proposal, [(501, "Oskolkov-RG7", "hagenauer-rg7")], []
    )

    monkeypatch.setenv("BAKER_BACKFILL_DRY_RUN_ONLY", "1")
    monkeypatch.setattr(
        bms,
        "get_conn",
        lambda: pytest.fail("get_conn must not be called when env blocks apply"),
    )

    rc = bms.main(["--cleanup-strays", "--apply", str(proposal)])
    assert rc == 2


def test_parse_stray_proposal_rejects_empty_proposed_slug(tmp_path):
    """Safety rail 3: Bucket F row with empty proposed_slug must raise."""
    import importlib

    bms = importlib.import_module("backfill_matter_slug")

    bad = tmp_path / "stray_bad.md"
    bad.write_text(
        "## Bucket F — Fixable (UPDATE matter_slug = canonical)\n"
        "\n"
        "| id | current_slug | proposed_slug |\n"
        "|----|--------------|---------------|\n"
        "| 501 | `Oskolkov-RG7` | `` |\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="empty proposed_slug"):
        bms._parse_stray_proposal(bad)
