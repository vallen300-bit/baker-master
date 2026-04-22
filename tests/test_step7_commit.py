"""Tests for ``kbl.steps.step7_commit`` — vault commit + push under
flock mutex. The last pipeline step.

Strategy
--------

A real git workflow per test: ``tmp_path`` gets a bare ``remote.git``
repo + a working ``vault`` clone pointing at it. Step 7's code runs
``git pull/add/commit/push`` end-to-end against these paths — no
subprocess mocking for the happy-path git flow. Specific failure cases
monkeypatch narrow surfaces (``os.replace``, ``subprocess.run``) to
inject faults.

Mock-mode (``BAKER_VAULT_DISABLE_PUSH=true``) runs the same flow without
``git push`` so tests that don't want remote coupling can skip it.

DB is a MagicMock that responds to the three SQLs Step 7 issues:
``SELECT final_markdown, target_vault_path``, the cross-link SELECT,
and the retry ALTER/UPDATE pair. Commit/rollback counts are auto-tracked.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from kbl.exceptions import CommitError, VaultLockTimeoutError
from kbl.steps import step7_commit
from kbl.steps.step7_commit import (
    _append_or_replace_stub,
    _assert_path_inside_vault,
    _atomic_write,
    _extract_primary_and_title,
    _inv4_guard_target_path,
    commit,
)


# ---------------------------- git helpers ----------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_vault(tmp_path: Path) -> Tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    vault = tmp_path / "vault"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "clone", str(remote), str(vault)],
        capture_output=True,
        text=True,
        check=True,
    )
    # seed commit so pull --rebase has a base + remote-tracking main.
    _git(vault, "checkout", "-b", "main")
    (vault / "README.md").write_text("seed\n", encoding="utf-8")
    (vault / "wiki").mkdir()
    _git(vault, "add", "README.md")
    _git(
        vault,
        "-c",
        "user.email=seed@test",
        "-c",
        "user.name=Seed",
        "commit",
        "-m",
        "seed",
    )
    _git(vault, "push", "-u", "origin", "main")
    return vault, remote


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    v, r = _init_vault(tmp_path)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(v))
    monkeypatch.setenv("BAKER_VAULT_FLOCK_TIMEOUT_SECONDS", "2")
    # Default to mock-mode: most tests don't care about the push itself.
    monkeypatch.setenv("BAKER_VAULT_DISABLE_PUSH", "true")
    yield v, r


# ---------------------------- draft builder ----------------------------


def _final_markdown(
    title: str = "AO Tonbach commit April tranche",
    primary: Optional[str] = "ao",
    body: str = "Body paragraph with enough length to be normal." * 5,
) -> str:
    primary_line = f"primary_matter: {primary}" if primary else "primary_matter: null"
    return (
        "---\n"
        f"title: {title}\n"
        "voice: silver\n"
        "author: pipeline\n"
        "created: 2026-04-19T12:00:00Z\n"
        "source_id: email:abc123\n"
        f"{primary_line}\n"
        "related_matters: []\n"
        "vedana: opportunity\n"
        "triage_score: 72\n"
        "triage_confidence: 0.81\n"
        "---\n"
        f"\n{body}\n"
    )


# ---------------------------- mock conn ----------------------------


def _mock_conn(
    final_markdown: str,
    target_vault_path: str,
    stubs: Optional[List[Tuple[str, str]]] = None,
) -> MagicMock:
    """MagicMock that answers Step 7's 3 SQL shapes:
    1. ``SELECT final_markdown, target_vault_path ...`` — the signal row
    2. ``SELECT target_slug, stub_row ...`` — unrealized stubs
    3. UPDATE/ALTER — swallowed
    Every call is logged in ``conn._calls`` for post-hoc assertions.
    """
    conn = MagicMock()
    calls: List[Tuple[str, Any]] = []
    stubs = stubs or []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            calls.append((sql, params))
            s = sql.lower()
            if "select final_markdown" in s:
                cur.fetchone.return_value = (final_markdown, target_vault_path)
            elif "from kbl_cross_link_queue" in s and "select target_slug" in s:
                cur.fetchall.return_value = list(stubs)
            else:
                cur.fetchone.return_value = None
                cur.fetchall.return_value = []

        cur.execute.side_effect = _execute
        return cur

    def _cursor() -> MagicMock:
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = calls
    return conn


def _sql_matches(conn: MagicMock, needle: str) -> List[Tuple[str, Any]]:
    n = needle.lower()
    return [c for c in conn._calls if n in c[0].lower()]


# ---------------------------- _atomic_write ----------------------------


def test_atomic_write_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "c.md"
    _atomic_write(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"


def test_atomic_write_cleans_tmp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "x.md"
    monkeypatch.setattr(
        "kbl.steps.step7_commit.os.replace",
        MagicMock(side_effect=OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        _atomic_write(p, "content")
    # Orphan tmpfile cleaned up; no .tmp files in the dir.
    leftover = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert leftover == []


# ---------------------------- _append_or_replace_stub ----------------------------


def test_stub_append_to_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "_links.md"
    row = "<!-- stub:signal_id=42 --> - 2026-04-19 | wiki/ao/foo.md | threat | excerpt"
    _append_or_replace_stub(p, row)
    assert row in p.read_text(encoding="utf-8")


def test_stub_replace_existing_same_signal_id(tmp_path: Path) -> None:
    p = tmp_path / "_links.md"
    old = (
        "<!-- stub:signal_id=42 --> - 2026-03-01 | wiki/ao/old.md | routine | old\n"
    )
    p.write_text(old, encoding="utf-8")
    new = "<!-- stub:signal_id=42 --> - 2026-04-19 | wiki/ao/new.md | threat | new"
    _append_or_replace_stub(p, new)
    content = p.read_text(encoding="utf-8")
    assert "old.md" not in content
    assert "new.md" in content
    # Exactly one line with this marker.
    assert content.count("<!-- stub:signal_id=42 -->") == 1


def test_stub_sort_newest_first(tmp_path: Path) -> None:
    p = tmp_path / "_links.md"
    row_old = "<!-- stub:signal_id=1 --> - 2026-01-10 | wiki/ao/a.md | routine | a"
    row_new = "<!-- stub:signal_id=2 --> - 2026-04-19 | wiki/ao/b.md | threat | b"
    _append_or_replace_stub(p, row_old)
    _append_or_replace_stub(p, row_new)
    content = p.read_text(encoding="utf-8")
    # Newer row appears above older.
    assert content.index("b.md") < content.index("a.md")


def test_stub_preserves_prefix_prose(tmp_path: Path) -> None:
    p = tmp_path / "_links.md"
    p.write_text(
        "---\n"
        "title: Cross-links for ao\n"
        "---\n"
        "\n"
        "# Cross-links\n"
        "\n",
        encoding="utf-8",
    )
    row = "<!-- stub:signal_id=5 --> - 2026-04-19 | wiki/ao/x.md | routine | x"
    _append_or_replace_stub(p, row)
    content = p.read_text(encoding="utf-8")
    assert "# Cross-links" in content
    assert row in content


def test_stub_without_marker_rejected(tmp_path: Path) -> None:
    p = tmp_path / "_links.md"
    with pytest.raises(CommitError, match="signal_id marker"):
        _append_or_replace_stub(p, "no marker here")


# ---------------------------- path containment ----------------------------


def test_assert_path_inside_vault_accepts_child(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _assert_path_inside_vault(vault / "wiki" / "x.md", vault)


def test_assert_path_inside_vault_rejects_sibling(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "outside").mkdir()
    with pytest.raises(CommitError, match="outside vault"):
        _assert_path_inside_vault(tmp_path / "outside" / "x.md", vault)


# ---------------------------- Inv 4 guard ----------------------------


def test_inv4_guard_blocks_director_authored_file(tmp_path: Path) -> None:
    p = tmp_path / "ao" / "2026-04-19_x.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "title: Director note\n"
        "author: director\n"
        "voice: gold\n"
        "---\n"
        "\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(CommitError, match="Director-authored"):
        _inv4_guard_target_path(p)


def test_inv4_guard_allows_pipeline_authored_file(tmp_path: Path) -> None:
    p = tmp_path / "ao" / "2026-04-19_x.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "title: Pipeline\n"
        "author: pipeline\n"
        "voice: silver\n"
        "---\n"
        "\nbody\n",
        encoding="utf-8",
    )
    _inv4_guard_target_path(p)  # should not raise


def test_inv4_guard_noop_on_missing_file(tmp_path: Path) -> None:
    _inv4_guard_target_path(tmp_path / "does_not_exist.md")  # should not raise


# ---------------------------- _extract_primary_and_title ----------------------------


def test_extract_primary_and_title_standard() -> None:
    md = _final_markdown(title="Foo bar baz", primary="ao")
    primary, title = _extract_primary_and_title(md)
    assert primary == "ao"
    assert title == "Foo bar baz"


def test_extract_primary_null() -> None:
    md = _final_markdown(primary=None)
    primary, title = _extract_primary_and_title(md)
    assert primary is None


# ---------------------------- commit() happy paths ----------------------------


def test_commit_happy_path_no_stubs(vault) -> None:
    vault_dir, _ = vault
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_tonbach.md",
        stubs=[],
    )

    commit(signal_id=10, conn=conn)

    # File landed at the canonical path.
    main_file = vault_dir / "wiki" / "ao" / "2026-04-19_tonbach.md"
    assert main_file.is_file()
    assert "voice: silver" in main_file.read_text(encoding="utf-8")

    # Git log has one new commit beyond seed (authored by pipeline).
    log = _git(vault_dir, "log", "--pretty=%an|%ae|%s").stdout.strip().splitlines()
    assert len(log) == 2
    name, email, subject = log[0].split("|")
    assert name == "Baker Pipeline"
    assert email == "pipeline@brisengroup.com"
    assert subject == "Silver: ao — AO Tonbach commit April tranche (sig:10)"

    # DB: mark_running internal commit + mark_completed UPDATE fired.
    update_done = _sql_matches(conn, "SET ")
    assert any("status = %s" in c[0] and c[1] == ("commit_running", 10) for c in update_done)
    # completed UPDATE used status='completed'.
    complete_calls = [
        c for c in update_done
        if "committed_at = NOW()" in c[0]
    ]
    assert len(complete_calls) == 1


def test_commit_happy_path_with_stubs(vault) -> None:
    vault_dir, _ = vault
    stub_row = "<!-- stub:signal_id=20 --> - 2026-04-19 | wiki/ao/file.md | threat | body"
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_tonbach.md",
        stubs=[("movie", stub_row)],
    )

    commit(signal_id=20, conn=conn)

    main_file = vault_dir / "wiki" / "ao" / "2026-04-19_tonbach.md"
    assert main_file.is_file()
    links_file = vault_dir / "wiki" / "movie" / "_links.md"
    assert links_file.is_file()
    assert stub_row in links_file.read_text(encoding="utf-8")

    # Realize UPDATE fired for this stub.
    realize = _sql_matches(conn, "UPDATE kbl_cross_link_queue")
    assert any(c[1] and c[1][1] == ["movie"] for c in realize)


def test_commit_toast_cleanup_nulls_out_heavy_columns(vault) -> None:
    """§4.9: after state='done', opus_draft_markdown + final_markdown are
    NULLed out. Asserted against the SQL parameters."""
    _, _ = vault
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_toast.md",
        stubs=[],
    )
    commit(signal_id=30, conn=conn)

    # Find the completed UPDATE and assert the NULL columns are in the
    # SET clause.
    done = [c for c in conn._calls if "committed_at = NOW()" in c[0]]
    assert len(done) == 1
    sql, params = done[0]
    assert "opus_draft_markdown = NULL" in sql
    assert "final_markdown = NULL" in sql
    # params = (status, commit_sha, signal_id, running_status)
    assert params[0] == "completed"
    assert params[2] == 30


def test_commit_idempotent_rerun_no_unrealized_stubs(vault) -> None:
    """A re-run with no unrealized stubs should still succeed — no
    _links.md writes, but the main file + commit still happen. Simulates
    a retry after a crash between main-file write and DB finalize (rare)."""
    vault_dir, _ = vault
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_rerun.md",
        stubs=[],  # no unrealized
    )
    commit(signal_id=40, conn=conn)
    # No _links.md should have been written.
    for links in vault_dir.rglob("_links.md"):
        raise AssertionError(f"unexpected _links.md at {links}")


# ---------------------------- commit() failure paths ----------------------------


def test_commit_fs_write_failure_rolls_back_and_marks_failed(vault) -> None:
    vault_dir, _ = vault
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_fail.md",
        stubs=[],
    )

    with patch(
        "kbl.steps.step7_commit._atomic_write",
        side_effect=OSError("disk full"),
    ):
        with pytest.raises(CommitError, match="vault write failed"):
            commit(signal_id=50, conn=conn)

    # No commit happened in the vault (seed only).
    log = _git(vault_dir, "log", "--pretty=%s").stdout.strip().splitlines()
    assert log == ["seed"]

    # State flipped to commit_failed.
    failed = [
        c for c in conn._calls
        if c[1] and len(c[1]) == 2 and c[1][0] == "commit_failed"
    ]
    assert failed, "commit_failed state flip missing"


def test_commit_push_retry_exhausted_resets_hard_and_marks_failed(
    vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both push attempts fail → git reset --hard ORIG_HEAD + commit_failed."""
    vault_dir, _ = vault
    # Enable the real push code path.
    monkeypatch.setenv("BAKER_VAULT_DISABLE_PUSH", "false")
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_push.md",
        stubs=[],
    )

    real_run = subprocess.run
    push_fail_count = [0]

    def _wrapped_run(cmd, *a, **kw):
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "push":
            push_fail_count[0] += 1
            raise subprocess.CalledProcessError(
                returncode=1, cmd=cmd, output="", stderr="non-fast-forward"
            )
        return real_run(cmd, *a, **kw)

    with patch("kbl.steps.step7_commit.subprocess.run", side_effect=_wrapped_run):
        with pytest.raises(CommitError, match="push failed"):
            commit(signal_id=60, conn=conn)

    assert push_fail_count[0] == 2

    # Local HEAD reset: log should be just seed (our local commit was
    # discarded via git reset --hard ORIG_HEAD).
    log = _git(vault_dir, "log", "--pretty=%s").stdout.strip().splitlines()
    assert log == ["seed"]


def test_commit_push_rebase_retry_succeeds(
    vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First push fails, rebase + second push succeeds."""
    vault_dir, _ = vault
    monkeypatch.setenv("BAKER_VAULT_DISABLE_PUSH", "false")
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_rebase.md",
        stubs=[],
    )

    real_run = subprocess.run
    state = {"push_attempts": 0}

    def _wrapped_run(cmd, *a, **kw):
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "push":
            state["push_attempts"] += 1
            if state["push_attempts"] == 1:
                raise subprocess.CalledProcessError(
                    returncode=1, cmd=cmd, output="", stderr="non-fast-forward"
                )
        return real_run(cmd, *a, **kw)

    with patch("kbl.steps.step7_commit.subprocess.run", side_effect=_wrapped_run):
        commit(signal_id=70, conn=conn)

    assert state["push_attempts"] == 2
    log = _git(vault_dir, "log", "--pretty=%s").stdout.strip().splitlines()
    assert "Silver: ao — AO Tonbach commit April tranche (sig:70)" in log


def test_commit_flock_timeout_marks_failed(
    vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_dir, _ = vault
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_lock.md",
        stubs=[],
    )

    with patch(
        "kbl.steps.step7_commit.acquire_vault_lock",
        side_effect=VaultLockTimeoutError("simulated 2s timeout"),
    ):
        with pytest.raises(VaultLockTimeoutError):
            commit(signal_id=80, conn=conn)

    # commit_failed state flip happened.
    failed = [
        c for c in conn._calls
        if c[1] and len(c[1]) == 2 and c[1][0] == "commit_failed"
    ]
    assert failed


def test_commit_missing_env_vault_path_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/x.md",
        stubs=[],
    )
    with pytest.raises(CommitError, match="BAKER_VAULT_PATH"):
        commit(signal_id=90, conn=conn)


def test_commit_inv4_collision_refuses(vault) -> None:
    """If target_vault_path exists with author: director, abort."""
    vault_dir, _ = vault
    target_rel = "wiki/ao/2026-04-19_collision.md"
    target_abs = vault_dir / target_rel
    target_abs.parent.mkdir(parents=True, exist_ok=True)
    target_abs.write_text(
        "---\n"
        "title: Collision\n"
        "author: director\n"
        "voice: gold\n"
        "---\n"
        "\nbody\n",
        encoding="utf-8",
    )
    _git(vault_dir, "add", target_rel)
    _git(
        vault_dir,
        "-c",
        "user.email=seed@test",
        "-c",
        "user.name=Seed",
        "commit",
        "-m",
        "director-seeded",
    )
    _git(vault_dir, "push")

    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path=target_rel,
        stubs=[],
    )
    with pytest.raises(CommitError, match="Director-authored"):
        commit(signal_id=100, conn=conn)


def test_commit_inv4_collision_after_rebase_refuses(
    vault, tmp_path: Path
) -> None:
    """Race: Director pushes a Gold file to origin between our last sync
    and Step 7's pull. The guard must fire AFTER pull-rebase so it sees
    the freshly-pulled Director commit and refuses — not before, when
    our local clone still looks empty at that path.

    Setup: 2 clones of the same bare remote. Clone A = Mac Mini (the
    Step 7 target). Clone B = Director's dev Mac. Clone B writes +
    pushes while Clone A is still at the old HEAD.
    """
    vault_dir, remote_dir = vault
    target_rel = "wiki/ao/2026-04-19_race.md"

    # Confirm Clone A has no local copy of the target yet.
    assert not (vault_dir / target_rel).exists()

    # Clone B: second working clone pointing at the same bare remote.
    clone_b = tmp_path / "clone_b"
    subprocess.run(
        ["git", "clone", str(remote_dir), str(clone_b)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(clone_b, "checkout", "main")

    director_abs = clone_b / target_rel
    director_abs.parent.mkdir(parents=True, exist_ok=True)
    director_body = (
        "---\n"
        "title: Director race note\n"
        "author: director\n"
        "voice: gold\n"
        "---\n"
        "\nDirector body content.\n"
    )
    director_abs.write_text(director_body, encoding="utf-8")
    _git(clone_b, "add", target_rel)
    _git(
        clone_b,
        "-c",
        "user.email=director@test",
        "-c",
        "user.name=Director",
        "commit",
        "-m",
        "director: race file",
    )
    _git(clone_b, "push", "origin", "main")

    # Clone A still at seed locally; target file still absent locally.
    assert not (vault_dir / target_rel).exists()

    # Step 7 runs on Clone A and happens to target the same path.
    conn = _mock_conn(
        final_markdown=_final_markdown(title="Pipeline race try"),
        target_vault_path=target_rel,
        stubs=[],
    )

    with pytest.raises(CommitError, match="Director-authored"):
        commit(signal_id=130, conn=conn)

    # Guard fired AFTER pull-rebase: Director's file is now present on
    # Clone A and was NOT overwritten by Step 7's silver content.
    final = (vault_dir / target_rel).read_text(encoding="utf-8")
    assert "author: director" in final
    assert "Director body content." in final
    assert "voice: silver" not in final

    # State flipped to commit_failed.
    failed = [
        c for c in conn._calls
        if c[1] and len(c[1]) == 2 and c[1][0] == "commit_failed"
    ]
    assert failed, "commit_failed state flip missing"

    # Local log on Clone A: Director's commit on top of seed — no
    # Step 7 commit was added.
    log = _git(vault_dir, "log", "--pretty=%s").stdout.strip().splitlines()
    assert log == ["director: race file", "seed"]


def test_commit_mock_mode_does_not_push(vault, monkeypatch: pytest.MonkeyPatch) -> None:
    """``BAKER_VAULT_DISABLE_PUSH=true`` skips push; commit still lands
    locally."""
    vault_dir, remote_dir = vault
    # The vault fixture already sets DISABLE_PUSH=true.
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_mock.md",
        stubs=[],
    )
    commit(signal_id=110, conn=conn)

    local_log = _git(vault_dir, "log", "--pretty=%s").stdout.strip().splitlines()
    assert "Silver: ao — AO Tonbach commit April tranche (sig:110)" in local_log

    # Remote still has only the seed commit — nothing pushed.
    remote_log = subprocess.run(
        ["git", "-C", str(remote_dir), "log", "--pretty=%s", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()
    assert remote_log == ["seed"]


# ---------------------------- CHANDA Inv 9 positive ----------------------------


def test_chanda_inv9_writes_land_only_under_vault_wiki(vault) -> None:
    """Step 7 IS the vault writer. Assert every file it creates is under
    ``{BAKER_VAULT_PATH}/wiki/``."""
    vault_dir, _ = vault
    stub_row = "<!-- stub:signal_id=120 --> - 2026-04-19 | wiki/ao/f.md | routine | x"
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_inv9.md",
        stubs=[("movie", stub_row)],
    )
    commit(signal_id=120, conn=conn)

    # Walk all tracked files newly added by this commit. They must all
    # start with "wiki/".
    rev = subprocess.run(
        ["git", "-C", str(vault_dir), "show", "--name-only",
         "--pretty=format:", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()
    changed = [f for f in rev if f]
    assert changed, "expected at least one changed file"
    for f in changed:
        assert f.startswith("wiki/"), f"write escaped vault/wiki: {f}"


# =====================================================================
# OBSERVABILITY_STEP7_PLUS_POLLER_DOC_1 — Step 7 happy-path emit_log
# =====================================================================


def _info_messages(mock_emit_log) -> List[str]:
    """Collect the ``message`` (4th arg) of each INFO emit_log call."""
    out: List[str] = []
    for call in mock_emit_log.call_args_list:
        args, _kw = call.args, call.kwargs
        if args and args[0] == "INFO":
            out.append(args[3] if len(args) >= 4 else _kw.get("message", ""))
    return out


def test_step7_happy_path_logs_entry_with_target_path(vault) -> None:
    """Happy-path Step 7 fires an INFO emit_log at entry with
    ``target=<target_vault_path>`` + ``primary_matter`` + ``stub_count``.
    This is the single-line anchor for every Step 7 trail in kbl_log.

    No vault state changes under the test (we already have 27 existing
    tests for that). Only the emit_log side is asserted."""
    vault_dir, _ = vault
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_observability.md",
        stubs=[],
    )

    with patch("kbl.steps.step7_commit.emit_log") as m_emit:
        commit(signal_id=701, conn=conn)

    info_msgs = _info_messages(m_emit)
    entry_msgs = [m for m in info_msgs if m.startswith("step7 entry:")]
    assert len(entry_msgs) == 1, f"expected one step7 entry log, got {entry_msgs}"
    entry = entry_msgs[0]
    assert "target=wiki/ao/2026-04-19_observability.md" in entry
    assert "primary_matter='ao'" in entry
    assert "stub_count=0" in entry

    # Component tag + signal_id routed correctly.
    entry_call = next(
        c for c in m_emit.call_args_list
        if c.args[0] == "INFO" and c.args[3].startswith("step7 entry:")
    )
    assert entry_call.args[1] == "step7_commit"
    assert entry_call.args[2] == 701

    # No WARN/ERROR on the happy path.
    for c in m_emit.call_args_list:
        assert c.args[0] not in ("WARN", "ERROR"), (
            f"happy path emitted {c.args[0]}: {c.args}"
        )


def test_step7_happy_path_push_success_fires_info(
    vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``BAKER_VAULT_DISABLE_PUSH=false`` (push enabled), a
    successful Step 7 emits the ``git push success`` INFO AND does NOT
    emit the shadow-mode INFO. Validates the ``else`` branch of the
    push gate."""
    monkeypatch.setenv("BAKER_VAULT_DISABLE_PUSH", "false")

    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_pushsuccess.md",
        stubs=[],
    )

    with patch("kbl.steps.step7_commit.emit_log") as m_emit:
        commit(signal_id=702, conn=conn)

    info_msgs = _info_messages(m_emit)

    # Push-success fired exactly once.
    push_msgs = [m for m in info_msgs if m.startswith("git push success:")]
    assert len(push_msgs) == 1, f"expected one push-success log, got {push_msgs}"
    assert "sha=" in push_msgs[0]
    assert "branch=main" in push_msgs[0]

    # Shadow-mode INFO NOT emitted on the push-enabled path.
    shadow_msgs = [m for m in info_msgs if m.startswith("shadow-mode:")]
    assert shadow_msgs == [], (
        f"unexpected shadow-mode log on push-enabled path: {shadow_msgs}"
    )

    # Terminal signal-completed INFO fires post-push.
    completed_msgs = [m for m in info_msgs if m.startswith("signal completed:")]
    assert len(completed_msgs) == 1


def test_step7_shadow_mode_fires_info_not_warn(vault) -> None:
    """With ``BAKER_VAULT_DISABLE_PUSH=true`` (the fixture default), a
    successful Step 7 emits an INFO-level ``shadow-mode: skipping git
    push`` line that mirrors the existing ``logger.info`` trace into
    kbl_log, AND does NOT emit a WARN/ERROR (happy path, not failure).

    Before this brief, shadow-mode commits left no kbl_log breadcrumb —
    the fix mirrors logger.info into emit_log."""
    conn = _mock_conn(
        final_markdown=_final_markdown(),
        target_vault_path="wiki/ao/2026-04-19_shadow.md",
        stubs=[],
    )

    with patch("kbl.steps.step7_commit.emit_log") as m_emit:
        commit(signal_id=703, conn=conn)

    info_msgs = _info_messages(m_emit)
    shadow_msgs = [m for m in info_msgs if m.startswith("shadow-mode:")]
    assert len(shadow_msgs) == 1, (
        f"expected one shadow-mode INFO, got {shadow_msgs}"
    )
    assert "BAKER_VAULT_DISABLE_PUSH=true" in shadow_msgs[0]
    assert "sha=" in shadow_msgs[0]

    # Push-success INFO NOT emitted on the shadow-mode path.
    push_msgs = [m for m in info_msgs if m.startswith("git push success:")]
    assert push_msgs == [], (
        f"unexpected push-success log on shadow-mode path: {push_msgs}"
    )

    # No WARN/ERROR (the brief's explicit contract on the happy path).
    for c in m_emit.call_args_list:
        assert c.args[0] not in ("WARN", "ERROR"), (
            f"shadow-mode happy path emitted {c.args[0]}: {c.args}"
        )

    # Terminal signal-completed INFO still fires (advance to completed
    # happens regardless of push/shadow).
    completed_msgs = [m for m in info_msgs if m.startswith("signal completed:")]
    assert len(completed_msgs) == 1
