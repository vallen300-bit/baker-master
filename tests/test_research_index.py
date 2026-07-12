"""Tests for the researcher research-memory index (item #8, Option B).

RESEARCHER_TRANCHE2_8_RESEARCH_MEMORY_INDEX (b2, 2026-07-12; lead #9898).

Both scripts HARD-PIN their scan/write/read root to ``$HOME/baker-vault/wiki/research``
(no env/arg config path — same hardening as check_source_monitors.sh / item #12). These
tests exercise them by relocating ``$HOME`` to a temp dir, so the pinned path resolves
into a fixture corpus without the scripts ever exposing a config seam.

Coverage (checkpoint §5):
  * heterogeneous-frontmatter parse (title/date/author vs type/purpose/brief_from)
  * no-frontmatter report flagged-and-indexed, NOT dropped
  * deterministic ordering (date desc, path asc) + idempotent regen
  * search returns the correct subset (AND semantics), read-only
  * empty-corpus clean (no crash, count 0)
  * fail-loud when the index is missing / the research dir is absent
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REGEN = REPO_ROOT / "scripts" / "regen_research_index.sh"
SEARCH = REPO_ROOT / "scripts" / "search_research_index.sh"


# ---- fixtures --------------------------------------------------------------

def _run(script: Path, *args: str, home: Path, check: bool = True):
    env = dict(os.environ, HOME=str(home))
    proc = subprocess.run(
        ["bash", str(script), *args],
        env=env, capture_output=True, text=True,
    )
    if check:
        assert proc.returncode == 0, (
            f"{script.name} {' '.join(args)} exited {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A fake $HOME with a heterogeneous wiki/research corpus."""
    research = tmp_path / "baker-vault" / "wiki" / "research"
    research.mkdir(parents=True)

    # (a) canonical title/date/author frontmatter
    (research / "2026-05-02-multi-agent-fleet.md").write_text(
        "---\n"
        "title: Multi-agent fleet architectures\n"
        "date: 2026-05-02\n"
        "author: AI Head B (deputy)\n"
        "tags: [brisen-lab, multi-agent]\n"
        "---\n\n"
        "## 1. Executive summary\n\nSurvey of fleet patterns for Brisen Lab.\n",
        encoding="utf-8",
    )
    # (b) type/purpose/brief_from shape — NO title, NO date field (date from filename)
    (research / "2026-05-05-ben-aicfo-design.md").write_text(
        "---\n"
        "type: research\n"
        "purpose: Design inputs for BEN, the Brisen finance/CFO shadow agent.\n"
        "brief_from: AI Head A\n"
        "---\n\n"
        "## 1. Executive summary\n\nAI-CFO skillset.\n",
        encoding="utf-8",
    )
    # (c) block-list tags + created (not date)
    (research / "2026-04-14-seed-cluster.md").write_text(
        "---\n"
        "title: NVIDIA Corinthia cluster\n"
        "created: 2026-04-14\n"
        "tags:\n"
        "  - nvidia\n"
        "  - hospitality\n"
        "---\n\n"
        "Body about the consortium.\n",
        encoding="utf-8",
    )
    # (d) NO frontmatter at all — date only derivable from filename
    (research / "2026-06-06-design-image-solutions.md").write_text(
        "# Design image solutions\n\nA note with no frontmatter block at all.\n",
        encoding="utf-8",
    )
    # (e) an _index.md that must be EXCLUDED from the scan (and later overwritten)
    (research / "_index.md").write_text(
        "---\ntitle: old seed\n---\n# stale seed index\n", encoding="utf-8",
    )
    return tmp_path


def _load_index(home: Path) -> dict:
    p = home / "baker-vault" / "wiki" / "research" / "_index.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---- regen: parse + flags + ordering ---------------------------------------

def test_regen_indexes_all_reports_excluding_index_files(corpus):
    _run(REGEN, home=corpus)
    manifest = _load_index(corpus)
    assert manifest["count"] == 4
    paths = [r["path"] for r in manifest["reports"]]
    assert all(p.startswith("wiki/research/") for p in paths)
    assert not any(p.endswith("_index.md") for p in paths)
    assert not any("_index.json" in p for p in paths)


def test_regen_heterogeneous_frontmatter_parse(corpus):
    _run(REGEN, home=corpus)
    by_path = {r["path"]: r for r in _load_index(corpus)["reports"]}

    a = by_path["wiki/research/2026-05-02-multi-agent-fleet.md"]
    assert a["title"] == "Multi-agent fleet architectures"
    assert a["date"] == "2026-05-02"
    assert a["author"] == "AI Head B (deputy)"
    assert a["tags"] == ["brisen-lab", "multi-agent"]
    assert a["flags"] == []

    # type/purpose/brief_from shape: no title field -> derived from filename;
    # no date field -> derived from filename prefix; purpose -> summary.
    b = by_path["wiki/research/2026-05-05-ben-aicfo-design.md"]
    assert b["date"] == "2026-05-05"
    assert b["title"]  # non-empty derived title
    assert "BEN" in b["summary"]
    assert b["flags"] == []  # HAS frontmatter, just a different shape

    # block-list tags + `created` used as the date fallback
    c = by_path["wiki/research/2026-04-14-seed-cluster.md"]
    assert c["date"] == "2026-04-14"
    assert c["tags"] == ["nvidia", "hospitality"]


def test_no_frontmatter_flagged_not_dropped(corpus):
    _run(REGEN, home=corpus)
    by_path = {r["path"]: r for r in _load_index(corpus)["reports"]}
    d = by_path["wiki/research/2026-06-06-design-image-solutions.md"]
    assert "no-frontmatter" in d["flags"]      # flagged
    assert d["date"] == "2026-06-06"           # still dated from filename
    assert d["title"]                          # still titled
    # and it is present -> not dropped (count already asserts 4 total)


def test_regen_deterministic_date_desc_path_asc(corpus):
    _run(REGEN, home=corpus)
    reports = _load_index(corpus)["reports"]
    dates = [r["date"] for r in reports]
    assert dates == sorted(dates, reverse=True)  # date descending
    # newest first
    assert reports[0]["path"] == "wiki/research/2026-06-06-design-image-solutions.md"


def test_regen_idempotent(corpus):
    _run(REGEN, home=corpus)
    first = _load_index(corpus)["reports"]
    _run(REGEN, home=corpus)
    second = _load_index(corpus)["reports"]
    # the reports array is byte-stable across runs (only the `generated` stamp moves)
    assert first == second


def test_regen_also_regenerates_human_index_md(corpus):
    _run(REGEN, home=corpus)
    md = (corpus / "baker-vault" / "wiki" / "research" / "_index.md").read_text(encoding="utf-8")
    assert "GENERATED FILE" in md
    assert "stale seed index" not in md          # old seed overwritten
    assert "Multi-agent fleet architectures" in md


def test_regen_check_mode_writes_nothing(corpus):
    proc = _run(REGEN, "--check", home=corpus)
    assert "DRY-RUN" in proc.stdout
    assert not (corpus / "baker-vault" / "wiki" / "research" / "_index.json").exists()


def test_regen_rejects_unknown_arg(corpus):
    proc = _run(REGEN, "--wat", home=corpus, check=False)
    assert proc.returncode != 0
    assert "unknown arg" in proc.stderr


def test_regen_empty_corpus_clean(tmp_path):
    (tmp_path / "baker-vault" / "wiki" / "research").mkdir(parents=True)
    _run(REGEN, home=tmp_path)
    manifest = _load_index(tmp_path)
    assert manifest["count"] == 0
    assert manifest["reports"] == []


def test_regen_missing_research_dir_fails_loud(tmp_path):
    proc = _run(REGEN, home=tmp_path, check=False)
    assert proc.returncode == 3
    assert "research dir missing" in proc.stderr


# ---- search: subset + read-only + fail-loud --------------------------------

def test_search_returns_correct_subset(corpus):
    _run(REGEN, home=corpus)
    proc = _run(SEARCH, "--json", "multi-agent", home=corpus)
    hits = json.loads(proc.stdout)
    assert len(hits) == 1
    assert hits[0]["path"] == "wiki/research/2026-05-02-multi-agent-fleet.md"


def test_search_and_semantics(corpus):
    _run(REGEN, home=corpus)
    # both keywords present in exactly one report
    hits = json.loads(_run(SEARCH, "--json", "nvidia", "consortium", home=corpus).stdout)
    assert len(hits) == 1
    assert hits[0]["path"] == "wiki/research/2026-04-14-seed-cluster.md"
    # a keyword that appears nowhere -> empty
    assert json.loads(_run(SEARCH, "--json", "nonexistentxyz", home=corpus).stdout) == []


def test_search_matches_tags_and_author(corpus):
    _run(REGEN, home=corpus)
    by_tag = json.loads(_run(SEARCH, "--json", "brisen-lab", home=corpus).stdout)
    assert [h["path"] for h in by_tag] == ["wiki/research/2026-05-02-multi-agent-fleet.md"]
    by_author = json.loads(_run(SEARCH, "--json", "deputy", home=corpus).stdout)
    assert any("multi-agent-fleet" in h["path"] for h in by_author)


def test_search_requires_a_keyword(corpus):
    _run(REGEN, home=corpus)
    proc = _run(SEARCH, home=corpus, check=False)
    assert proc.returncode != 0
    assert "no keywords" in proc.stderr


def test_search_fails_loud_when_index_missing(corpus):
    # regen NOT run -> no _index.json
    proc = _run(SEARCH, "anything", home=corpus, check=False)
    assert proc.returncode == 3
    assert "index missing" in proc.stderr


def test_search_does_not_write(corpus):
    _run(REGEN, home=corpus)
    research = corpus / "baker-vault" / "wiki" / "research"
    before = {p.name: p.stat().st_mtime_ns for p in research.iterdir()}
    _run(SEARCH, "--json", "multi-agent", home=corpus)
    after = {p.name: p.stat().st_mtime_ns for p in research.iterdir()}
    assert before == after  # read-only: no new files, no mtime changes
