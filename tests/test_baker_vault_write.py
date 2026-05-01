"""Tests for baker_mcp/vault_write.py + audit helpers (BAKER_VAULT_WRITE_1).

Coverage:
  H1-H6: 6 happy paths (path validation + GitHub round-trip mocked)
  R1-R6: 6 rejection paths
  B1-B3: 3 behavior tests (409 retry-once, double-409, Bearer redaction)
  Plus: audit-SQL schema-drift guard, _redact() unit test.
"""
from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from baker_mcp.vault_write import (
    VaultWriteError,
    _redact,
    validate_frontmatter,
    validate_path,
    write_vault_file,
)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _mk_response(status: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Build a MagicMock that quacks like httpx.Response for our usage."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.text = text
    r.json.return_value = json_body or {}
    if 200 <= status < 300:
        r.raise_for_status.return_value = None
    else:
        request = httpx.Request("PUT", "https://api.github.com/test")
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status}", request=request, response=r
        )
    return r


def _gh_put_success_payload(commit_sha="c0ffee", content_sha="deadbeef") -> dict:
    return {
        "commit": {"sha": commit_sha},
        "content": {
            "sha": content_sha,
            "html_url": f"https://github.com/vallen300-bit/baker-vault/blob/main/test",
        },
    }


# -------------------------------------------------------------------------
# H1-H6 — happy paths
# -------------------------------------------------------------------------


class TestHappyPaths:
    """Each happy path mocks _gh_get to return None (file new) and _gh_put to return 200/201."""

    def _run(self, path, content, mode):
        with (
            patch("baker_mcp.vault_write._gh_get", return_value=None),
            patch(
                "baker_mcp.vault_write._gh_put",
                return_value=_mk_response(201, _gh_put_success_payload()),
            ),
        ):
            return write_vault_file(path, content, mode, "test commit", "ghp_TESTTOKEN")

    def test_h1_session_state_overwrite(self):
        result = self._run(
            "wiki/matters/oskolkov/_session-state.md",
            "# Session state\n\nLast: smoke test.\n",
            "overwrite",
        )
        assert result["klass"] == "session_state"
        assert result["mode_used"] == "overwrite"
        assert result["commit_sha"] == "c0ffee"

    def test_h2_curated_append_with_frontmatter(self):
        content = (
            "---\n"
            "source: aukera-call-2026-04-30\n"
            "confidence: high\n"
            "provenance: AI Head A synthesis\n"
            "---\n"
            "Body of the curated note.\n"
        )
        result = self._run(
            "wiki/matters/movie/curated/2026-05-01-test-topic.md", content, "append"
        )
        assert result["klass"] == "curated"
        assert result["mode_used"] == "append"

    def test_h3_inbox_handoff_append(self):
        result = self._run(
            "wiki/_inbox/handoff-2026-05-01-ao-to-movie.md",
            "Handoff note body.\n",
            "append",
        )
        assert result["klass"] == "handoff"

    def test_h4_proposed_gold_with_frontmatter(self):
        content = (
            "---\n"
            "source: director-ratification-2026-04-30\n"
            "confidence: high\n"
            "provenance: meeting transcript ID 12345\n"
            "---\n"
            "Proposed gold body.\n"
        )
        result = self._run(
            "wiki/matters/hagenauer-rg7/proposed-gold.md", content, "append"
        )
        assert result["klass"] == "proposed_gold"

    def test_h5_decisions_append(self):
        result = self._run(
            "wiki/matters/oskolkov/decisions/2026-05-01-test-decision.md",
            "Decision body.\n",
            "append",
        )
        assert result["klass"] == "decision"

    def test_h6_red_flags_append(self):
        result = self._run(
            "wiki/matters/oskolkov/red-flags.md", "Red flag note.\n", "append"
        )
        assert result["klass"] == "red_flags"


# -------------------------------------------------------------------------
# R1-R6 — rejection paths
# -------------------------------------------------------------------------


class TestRejectionPaths:
    def test_r1_curated_overwrite_rejected(self):
        with pytest.raises(VaultWriteError, match="append-only"):
            validate_path(
                "wiki/matters/oskolkov/curated/2026-05-01-test.md", "overwrite"
            )

    def test_r2_gold_md_hard_blocked(self):
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("wiki/matters/oskolkov/gold.md", "append")

    def test_r3_ops_path_hard_blocked(self):
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("_ops/skills/foo.md", "append")

    def test_r4_curated_missing_frontmatter(self):
        with pytest.raises(VaultWriteError, match="requires YAML frontmatter"):
            validate_frontmatter("plain content, no frontmatter\n", "curated")

    def test_r5_curated_empty_frontmatter_value(self):
        content = (
            "---\n"
            "source: \n"  # explicit empty value
            "confidence: high\n"
            "provenance: test\n"
            "---\n"
            "body\n"
        )
        with pytest.raises(VaultWriteError, match="present but empty"):
            validate_frontmatter(content, "curated")

    def test_r6_cortex_meta_hard_blocked(self):
        """Defense-in-depth: alternate gold placement under wiki/_cortex/."""
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("wiki/_cortex/director-gold-global.md", "append")

    # Path-traversal guards (security-review surface)

    def test_path_traversal_dotdot(self):
        with pytest.raises(VaultWriteError, match="traversal"):
            validate_path("wiki/matters/oskolkov/../../../etc/passwd", "append")

    def test_path_absolute_rejected(self):
        with pytest.raises(VaultWriteError, match="traversal"):
            validate_path("/etc/passwd", "append")

    def test_path_backslash_rejected(self):
        with pytest.raises(VaultWriteError, match="traversal"):
            validate_path("wiki\\matters\\oskolkov\\gold.md", "append")

    def test_path_empty_rejected(self):
        with pytest.raises(VaultWriteError):
            validate_path("", "append")

    def test_unmatched_path_rejected(self):
        """Path doesn't match any allowed pattern AND isn't hard-blocked."""
        with pytest.raises(VaultWriteError, match="does not match any allowed pattern"):
            validate_path("wiki/matters/oskolkov/random-file.md", "append")

    def test_slugs_yml_blocked(self):
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("slugs.yml", "append")

    def test_priorities_yml_blocked(self):
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("wiki/_priorities.yml", "append")

    def test_install_path_blocked(self):
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("_install/foo.md", "append")

    def test_invalid_mode_rejected(self):
        with patch("baker_mcp.vault_write._gh_get", return_value=None):
            with pytest.raises(VaultWriteError, match="mode must be"):
                write_vault_file(
                    "wiki/matters/oskolkov/red-flags.md",
                    "body",
                    "delete",  # invalid mode
                    "test",
                    "ghp_TEST",
                )

    # F1 (architect nits #141): control-char rejection — explicit, not via h11.

    def test_f1a_path_with_newline_rejected(self):
        """\\n in path → VaultWriteError 'control characters', not h11 LocalProtocolError."""
        with pytest.raises(VaultWriteError, match="control characters"):
            validate_path(
                "wiki/matters/x/_session-state.md\nX-Injected: yes", "overwrite"
            )

    def test_f1b_path_with_carriage_return_rejected(self):
        """\\r\\n in path → VaultWriteError 'control characters'."""
        with pytest.raises(VaultWriteError, match="control characters"):
            validate_path("wiki/matters/x/_session-state.md\r\n", "overwrite")

    # F2 (architect nits #141): root-level placements hit the hard-blocker
    # explicitly, not the allow-pattern fall-through with the wrong error msg.

    def test_f2a_root_gold_md_hard_blocked(self):
        """Root-level gold.md must be hard-blocked, not 'does not match any allowed pattern'."""
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("gold.md", "append")

    def test_f2b_root_priorities_yml_hard_blocked(self):
        """Root-level _priorities.yml must be hard-blocked, not allow-pattern fall-through."""
        with pytest.raises(VaultWriteError, match="hard-blocked"):
            validate_path("_priorities.yml", "append")


# -------------------------------------------------------------------------
# Allow proposed-gold despite the gold blocker (whitelist precedence)
# -------------------------------------------------------------------------


def test_proposed_gold_not_caught_by_gold_blocker():
    """proposed-gold.md must pass — generic gold blocker can't catch it."""
    klass, ow = validate_path(
        "wiki/matters/oskolkov/proposed-gold.md", "append"
    )
    assert klass == "proposed_gold"
    assert ow is False


def test_proposed_gold_overwrite_rejected():
    """Even though it passes the blocker, overwrite mode is still rejected."""
    with pytest.raises(VaultWriteError, match="append-only"):
        validate_path(
            "wiki/matters/oskolkov/proposed-gold.md", "overwrite"
        )


# -------------------------------------------------------------------------
# B1-B3 — behaviour tests
# -------------------------------------------------------------------------


class TestBehaviour:
    def test_b1_409_then_success(self):
        """First PUT returns 409, second PUT (after sha refresh) succeeds."""
        success_payload = _gh_put_success_payload()
        gh_get_mock = MagicMock(return_value={"sha": "old_sha", "content": base64.b64encode(b"existing\n").decode("ascii")})
        gh_put_mock = MagicMock(
            side_effect=[
                _mk_response(409),
                _mk_response(201, success_payload),
            ]
        )
        with (
            patch("baker_mcp.vault_write._gh_get", gh_get_mock),
            patch("baker_mcp.vault_write._gh_put", gh_put_mock),
        ):
            result = write_vault_file(
                "wiki/matters/oskolkov/red-flags.md",
                "new line\n",
                "append",
                "test",
                "ghp_TEST",
            )
        assert result["commit_sha"] == "c0ffee"
        # _gh_get called twice: initial fetch + retry-after-409 refresh
        assert gh_get_mock.call_count == 2
        assert gh_put_mock.call_count == 2

    def test_b2_double_409_raises(self):
        """Both PUTs return 409 → VaultWriteError 'persistent 409 Conflict'."""
        gh_put_mock = MagicMock(
            side_effect=[_mk_response(409), _mk_response(409)]
        )
        with (
            patch("baker_mcp.vault_write._gh_get", return_value=None),
            patch("baker_mcp.vault_write._gh_put", gh_put_mock),
        ):
            with pytest.raises(VaultWriteError, match="persistent 409 Conflict"):
                write_vault_file(
                    "wiki/matters/oskolkov/red-flags.md",
                    "new line\n",
                    "append",
                    "test",
                    "ghp_TEST",
                )

    def test_b3_403_body_redacted_via_redact(self):
        """403 body containing Bearer ghp_xxx must be redacted by _redact()."""
        s = "Bad credentials. Authorization: Bearer ghp_AAAA1234567890BBBB"
        out = _redact(s)
        assert "ghp_AAAA1234567890BBBB" not in out
        assert "Bearer REDACTED" in out

    def test_append_concatenates_with_separator_newline(self):
        """Append flow: existing content without trailing newline gets a separator added."""
        existing_b64 = base64.b64encode(b"line1").decode("ascii")  # no trailing \n
        captured = {}

        def fake_put(path, content_b64, message, sha, token):
            captured["content"] = base64.b64decode(content_b64).decode("utf-8")
            captured["sha"] = sha
            return _mk_response(201, _gh_put_success_payload())

        with (
            patch(
                "baker_mcp.vault_write._gh_get",
                return_value={"sha": "abc123", "content": existing_b64},
            ),
            patch("baker_mcp.vault_write._gh_put", side_effect=fake_put),
        ):
            write_vault_file(
                "wiki/matters/oskolkov/red-flags.md",
                "line2",
                "append",
                "test",
                "ghp_TEST",
            )
        assert captured["content"] == "line1\nline2"
        assert captured["sha"] == "abc123"

    def test_append_no_separator_if_existing_has_trailing_newline(self):
        existing_b64 = base64.b64encode(b"line1\n").decode("ascii")
        captured = {}

        def fake_put(path, content_b64, message, sha, token):
            captured["content"] = base64.b64decode(content_b64).decode("utf-8")
            return _mk_response(201, _gh_put_success_payload())

        with (
            patch(
                "baker_mcp.vault_write._gh_get",
                return_value={"sha": "abc123", "content": existing_b64},
            ),
            patch("baker_mcp.vault_write._gh_put", side_effect=fake_put),
        ):
            write_vault_file(
                "wiki/matters/oskolkov/red-flags.md",
                "line2",
                "append",
                "test",
                "ghp_TEST",
            )
        assert captured["content"] == "line1\nline2"


# -------------------------------------------------------------------------
# _redact() unit tests
# -------------------------------------------------------------------------


class TestRedact:
    def test_redact_strips_bearer_token(self):
        s = "Authorization: Bearer ghp_AAAA1234567890BBBB"
        out = _redact(s)
        assert "ghp_" not in out
        assert "Bearer REDACTED" in out

    def test_redact_strips_url_embedded_token(self):
        s = "git pull https://x-access-token:ghp_SECRET123@github.com/foo/bar.git"
        out = _redact(s)
        assert "ghp_SECRET123" not in out
        assert "https://x-access-token:REDACTED@" in out

    def test_redact_handles_none(self):
        assert _redact(None) == ""

    def test_redact_handles_clean_string(self):
        assert _redact("nothing sensitive here") == "nothing sensitive here"

    def test_redact_handles_both_forms_in_one_string(self):
        s = (
            "url=https://x-access-token:ghp_AAA@github.com/foo/bar.git "
            "header=Authorization: Bearer ghp_BBB"
        )
        out = _redact(s)
        assert "ghp_AAA" not in out
        assert "ghp_BBB" not in out


# -------------------------------------------------------------------------
# Audit-SQL schema-drift guard (per Lesson #42 / brief §Tests file structure)
# -------------------------------------------------------------------------


def test_audit_insert_uses_verified_columns(monkeypatch):
    """Capture the cursor.execute() args and assert column tuple matches schema.

    This catches schema-drift regression even without a live DB. If
    information_schema columns drift away from the brief's contract, the
    INSERT/UPDATE SQL strings must change too — this test fails loud.
    """
    captured: list[tuple] = []

    class FakeCur:
        def __init__(self):
            pass

        def execute(self, sql, params=None):
            captured.append((sql, params))

        def fetchone(self):
            return {"id": 999}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self, cursor_factory=None):
            return FakeCur()

        def commit(self):
            pass

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr("psycopg2.connect", lambda **kw: FakeConn())

    from baker_mcp.baker_mcp_server import _emit_vault_write_audit

    audit_id = _emit_vault_write_audit(
        "wiki/matters/oskolkov/red-flags.md", "append", "test"
    )
    assert audit_id == 999
    assert len(captured) == 1
    sql, params = captured[0]
    assert "INSERT INTO baker_actions" in sql
    # Column-list assertion — fail loud on schema drift.
    for col in (
        "action_type",
        "target_task_id",
        "payload",
        "trigger_source",
        "success",
    ):
        assert col in sql, f"missing column {col} in audit INSERT — schema drift?"
    # success param is None to mark "in flight"
    assert params[0] == "vault_write"
    assert params[-1] is None  # success=NULL


def test_audit_update_uses_verified_columns(monkeypatch):
    """UPDATE path uses success/payload/target_space_id/error_message columns."""
    captured: list[tuple] = []

    class FakeCur:
        def execute(self, sql, params=None):
            captured.append((sql, params))

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self, cursor_factory=None):
            return FakeCur()

        def commit(self):
            pass

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr("psycopg2.connect", lambda **kw: FakeConn())

    from baker_mcp.baker_mcp_server import _update_vault_write_audit

    _update_vault_write_audit(
        42,
        success=True,
        payload_extra={
            "klass": "red_flags",
            "commit_sha": "abc",
            "html_url": "https://example",
            "bytes_written": 100,
        },
    )
    assert len(captured) == 1
    sql, params = captured[0]
    assert "UPDATE baker_actions" in sql
    for col in ("success", "payload", "target_space_id", "error_message"):
        assert col in sql, f"missing column {col} in audit UPDATE — schema drift?"


def test_audit_emit_returns_none_on_db_failure(monkeypatch):
    """If _write raises, audit emit returns None (best-effort, never crashes caller)."""
    def _boom(**kw):
        raise RuntimeError("DB unreachable")

    monkeypatch.setattr("psycopg2.connect", _boom)

    from baker_mcp.baker_mcp_server import _emit_vault_write_audit

    assert _emit_vault_write_audit("wiki/x/red-flags.md", "append", "test") is None


def test_audit_update_noop_on_null_id():
    """Passing audit_id=None must not crash and not call _write."""
    from baker_mcp.baker_mcp_server import _update_vault_write_audit

    # Should simply return; would fail if it tried to connect.
    _update_vault_write_audit(None, success=True)


# -------------------------------------------------------------------------
# Append from non-existent file
# -------------------------------------------------------------------------


def test_append_creates_file_when_missing():
    """If _gh_get returns None (404), append acts as create with no sha."""
    captured = {}

    def fake_put(path, content_b64, message, sha, token):
        captured["sha"] = sha
        captured["content"] = base64.b64decode(content_b64).decode("utf-8")
        return _mk_response(201, _gh_put_success_payload())

    with (
        patch("baker_mcp.vault_write._gh_get", return_value=None),
        patch("baker_mcp.vault_write._gh_put", side_effect=fake_put),
    ):
        result = write_vault_file(
            "wiki/matters/oskolkov/red-flags.md",
            "first content\n",
            "append",
            "test",
            "ghp_TEST",
        )
    assert captured["sha"] is None
    assert captured["content"] == "first content\n"
    assert result["klass"] == "red_flags"


# -------------------------------------------------------------------------
# Frontmatter — non-required classes pass even without frontmatter
# -------------------------------------------------------------------------


def test_frontmatter_not_required_for_session_state():
    # Should not raise — session_state has no frontmatter requirement
    validate_frontmatter("any content\n", "session_state")


def test_frontmatter_not_required_for_handoff():
    validate_frontmatter("any content\n", "handoff")


def test_frontmatter_present_but_unclosed():
    """Frontmatter that opens but never closes → reject curated."""
    content = "---\nsource: foo\nconfidence: high\nprovenance: bar\n"
    with pytest.raises(VaultWriteError, match="missing closing"):
        validate_frontmatter(content, "curated")
