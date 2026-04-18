"""Tests for kbl.loop.load_gold_context_by_matter (LOOP-GOLD-READER-1).

Leg 1 read. Covers:
    - Happy path: multiple Gold files concatenated + ordered
    - Zero-Gold: empty / missing matter dir -> ""
    - Silver exclusion: voice != gold
    - Malformed frontmatter: excluded silently (Silver-like)
    - Permission error: raises LoopReadError
    - Vault-path resolution via env var + explicit override
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from textwrap import dedent

import pytest

from kbl.loop import LoopReadError, load_gold_context_by_matter

FIXTURES = Path(__file__).parent / "fixtures" / "gold_reader_vault"


# ------------------------------ happy path ------------------------------


def test_happy_path_two_gold_files_concatenated() -> None:
    """hagenauer-rg7 has 2 Gold + 1 Silver — only Gold appears, in order."""
    out = load_gold_context_by_matter(
        "hagenauer-rg7", vault_path=str(FIXTURES)
    )
    assert out, "expected non-empty Gold context"
    # Both Gold markers present; Silver is not.
    assert "<!-- GOLD: wiki/hagenauer-rg7/2026-04-01_kick_off.md -->" in out
    assert "<!-- GOLD: wiki/hagenauer-rg7/2026-04-03_hassa_reply.md -->" in out
    assert "2026-04-05_draft.md" not in out


def test_happy_path_ordering_is_chronological() -> None:
    """Filename sort (date-prefix convention) produces chronological order."""
    out = load_gold_context_by_matter(
        "hagenauer-rg7", vault_path=str(FIXTURES)
    )
    pos_apr_01 = out.index("2026-04-01_kick_off.md")
    pos_apr_03 = out.index("2026-04-03_hassa_reply.md")
    assert pos_apr_01 < pos_apr_03


def test_happy_path_preserves_frontmatter_in_each_block() -> None:
    """Spec: each file's own frontmatter is included verbatim in the block
    (so downstream prompt can ground on matter slug + created date)."""
    out = load_gold_context_by_matter(
        "hagenauer-rg7", vault_path=str(FIXTURES)
    )
    assert "voice: gold" in out
    assert "matter: hagenauer-rg7" in out


def test_happy_path_body_included() -> None:
    out = load_gold_context_by_matter(
        "hagenauer-rg7", vault_path=str(FIXTURES)
    )
    assert "Hagenauer kickoff" in out
    assert "Hassa reply synthesized" in out


def test_happy_path_single_gold_file() -> None:
    """mo-vie has exactly one Gold file — block still renders."""
    out = load_gold_context_by_matter("mo-vie", vault_path=str(FIXTURES))
    assert "<!-- GOLD: wiki/mo-vie/2026-04-02_egger_sync.md -->" in out
    assert "Egger sync notes" in out


def test_happy_path_blocks_separated_by_blank_line() -> None:
    """Two adjacent Gold entries get a single blank line between them so the
    prompt reader can scan page-break boundaries without parsing."""
    out = load_gold_context_by_matter(
        "hagenauer-rg7", vault_path=str(FIXTURES)
    )
    assert "\n\n<!-- GOLD:" in out


# ------------------------------ zero-Gold (Inv 1) ------------------------------


def test_missing_matter_dir_returns_empty(tmp_path: Path) -> None:
    """Matter dir absent = brand-new matter, no Gold yet. Not a fault."""
    # Build an otherwise-valid vault with no matter dir.
    (tmp_path / "wiki").mkdir()
    out = load_gold_context_by_matter(
        "brand-new-matter", vault_path=str(tmp_path)
    )
    assert out == ""


def test_empty_matter_dir_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "wiki" / "gamma").mkdir(parents=True)
    out = load_gold_context_by_matter("gamma", vault_path=str(tmp_path))
    assert out == ""


def test_matter_dir_with_only_silver_returns_empty(tmp_path: Path) -> None:
    """All-Silver matter: read succeeds, zero-Gold is valid Inv 1 state."""
    mdir = tmp_path / "wiki" / "silver-only"
    mdir.mkdir(parents=True)
    (mdir / "2026-04-10_note.md").write_text(
        dedent(
            """\
            ---
            voice: silver
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    out = load_gold_context_by_matter("silver-only", vault_path=str(tmp_path))
    assert out == ""


# ------------------------------ frontmatter edge cases ------------------------------


def test_missing_frontmatter_file_excluded(tmp_path: Path) -> None:
    """Plain markdown with no `---` fences is treated as Silver."""
    mdir = tmp_path / "wiki" / "mx"
    mdir.mkdir(parents=True)
    (mdir / "2026-04-10_raw.md").write_text(
        "# Just a heading\n\nNo frontmatter.\n", encoding="utf-8"
    )
    assert load_gold_context_by_matter("mx", vault_path=str(tmp_path)) == ""


def test_malformed_yaml_frontmatter_excluded_silently(tmp_path: Path) -> None:
    """Broken YAML inside the fence — don't crash the matter read; skip."""
    mdir = tmp_path / "wiki" / "mx"
    mdir.mkdir(parents=True)
    (mdir / "2026-04-10_broken.md").write_text(
        "---\nvoice: [not: closed\n---\nbody\n",
        encoding="utf-8",
    )
    (mdir / "2026-04-11_ok.md").write_text(
        "---\nvoice: gold\n---\nreal gold body\n",
        encoding="utf-8",
    )
    out = load_gold_context_by_matter("mx", vault_path=str(tmp_path))
    assert "real gold body" in out
    assert "broken" not in out


def test_voice_case_insensitive(tmp_path: Path) -> None:
    """`voice: Gold` / `voice: GOLD` must also count."""
    mdir = tmp_path / "wiki" / "mx"
    mdir.mkdir(parents=True)
    (mdir / "2026-04-10.md").write_text(
        "---\nvoice: Gold\n---\nbody\n", encoding="utf-8"
    )
    out = load_gold_context_by_matter("mx", vault_path=str(tmp_path))
    assert "body" in out


def test_voice_other_value_excluded(tmp_path: Path) -> None:
    mdir = tmp_path / "wiki" / "mx"
    mdir.mkdir(parents=True)
    (mdir / "2026-04-10.md").write_text(
        "---\nvoice: draft\n---\nshould skip\n", encoding="utf-8"
    )
    assert load_gold_context_by_matter("mx", vault_path=str(tmp_path)) == ""


def test_voice_missing_key_excluded(tmp_path: Path) -> None:
    mdir = tmp_path / "wiki" / "mx"
    mdir.mkdir(parents=True)
    (mdir / "2026-04-10.md").write_text(
        "---\nmatter: mx\n---\nno voice key\n", encoding="utf-8"
    )
    assert load_gold_context_by_matter("mx", vault_path=str(tmp_path)) == ""


def test_non_md_files_ignored(tmp_path: Path) -> None:
    """Non-.md entries in the matter dir don't influence the output."""
    mdir = tmp_path / "wiki" / "mx"
    mdir.mkdir(parents=True)
    (mdir / "attachment.pdf").write_bytes(b"pdf bytes")
    (mdir / "2026-04-10.md").write_text(
        "---\nvoice: gold\n---\nthe only gold\n", encoding="utf-8"
    )
    out = load_gold_context_by_matter("mx", vault_path=str(tmp_path))
    assert "the only gold" in out
    assert "attachment.pdf" not in out


# ------------------------------ error paths ------------------------------


@pytest.mark.skipif(
    os.geteuid() == 0, reason="chmod-based permission test needs non-root"
)
def test_permission_error_on_unreadable_file_raises(tmp_path: Path) -> None:
    mdir = tmp_path / "wiki" / "locked"
    mdir.mkdir(parents=True)
    locked = mdir / "2026-04-10.md"
    locked.write_text("---\nvoice: gold\n---\nbody\n", encoding="utf-8")
    locked.chmod(0)
    try:
        with pytest.raises(LoopReadError, match="failed to read"):
            load_gold_context_by_matter("locked", vault_path=str(tmp_path))
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_vault_env_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    with pytest.raises(LoopReadError, match="BAKER_VAULT_PATH"):
        load_gold_context_by_matter("any")


def test_empty_matter_slug_raises() -> None:
    with pytest.raises(LoopReadError, match="non-empty string"):
        load_gold_context_by_matter("", vault_path=str(FIXTURES))
    with pytest.raises(LoopReadError, match="non-empty string"):
        load_gold_context_by_matter(None, vault_path=str(FIXTURES))  # type: ignore[arg-type]


def test_vault_path_via_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES))
    out = load_gold_context_by_matter("mo-vie")
    assert "Egger sync notes" in out


def test_vault_path_arg_wins_over_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit ``vault_path`` must override the env var."""
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))  # empty-ish vault
    out = load_gold_context_by_matter("mo-vie", vault_path=str(FIXTURES))
    assert "Egger sync notes" in out


def test_matter_dir_that_is_actually_a_file_raises(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "mx").write_text("not a dir", encoding="utf-8")
    with pytest.raises(LoopReadError, match="expected a directory"):
        load_gold_context_by_matter("mx", vault_path=str(tmp_path))
