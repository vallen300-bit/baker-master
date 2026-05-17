"""Tests for kbl.report_renderer — JSON-by-default + Director-gated convert.

The default (``save_investigation_json``) is exercised end-to-end with a
fake client. PDF / HTML conversion is exercised with a mocked pandoc binary
so the test suite does not depend on a system-installed renderer.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from kbl import report_renderer
from kbl.report_renderer import (
    RendererError,
    RendererUnavailableError,
    convert_to_html,
    convert_to_pdf,
    save_investigation_json,
)


class _FakeClient:
    """Stand-in for ClaimsmaxClient — captures call args, returns fixed payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def investigate_status(self, run_id: str) -> dict[str, Any]:
        self.calls.append(run_id)
        return self.payload


def _completion_payload(report_md: str = "# Investigation\n\n## Summary\nAll good.") -> dict[str, Any]:
    return {
        "run_id": "r-abc",
        "status": "complete",
        "started_at": "2026-05-17T08:00:00Z",
        "ended_at": "2026-05-17T08:03:00Z",
        "step_count": 12,
        "title": "Test investigation",
        "query": "Did pandoc render?",
        "report": report_md,
        "error": None,
    }


# --------------------------- save_investigation_json ---------------------------


def test_save_investigation_json_writes_parseable_file(tmp_path: Path) -> None:
    payload = _completion_payload()
    client = _FakeClient(payload)
    fixed_now = datetime(2026, 5, 17, 9, 0, 0, tzinfo=timezone.utc)

    out = save_investigation_json(
        run_id="r-abc",
        matter_slug="hagenauer-rg7",
        topic_slug="pagitsch-defects",
        client=client,
        dropbox_root=tmp_path,
        now=fixed_now,
    )

    out_path = Path(out)
    assert out_path.exists()
    assert out_path.name == "2026-05-17-pagitsch-defects.json"
    assert out_path.parent == tmp_path / "hagenauer-rg7" / "research"

    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk["run_id"] == "r-abc"
    assert on_disk["status"] == "complete"
    assert on_disk["report"].startswith("# Investigation")


def test_save_investigation_json_creates_missing_parent_dirs(tmp_path: Path) -> None:
    client = _FakeClient(_completion_payload())
    target_root = tmp_path / "deep" / "tree" / "that" / "does" / "not" / "exist"
    out = save_investigation_json(
        run_id="r-1",
        matter_slug="mo-vie",
        topic_slug="topic",
        client=client,
        dropbox_root=target_root,
    )
    assert Path(out).exists()


def test_save_investigation_json_requires_args() -> None:
    client = _FakeClient(_completion_payload())
    with pytest.raises(ValueError, match="run_id"):
        save_investigation_json("", "m", "t", client=client)
    with pytest.raises(ValueError, match="matter_slug"):
        save_investigation_json("r", "", "t", client=client)
    with pytest.raises(ValueError, match="topic_slug"):
        save_investigation_json("r", "m", "", client=client)


@pytest.mark.parametrize(
    "bad_slug",
    ["..", "../etc", "a/../b", "..\\windows", "with/slash", "with\\backslash", "null\x00byte", "."],
)
def test_save_investigation_json_rejects_path_traversal_slugs(tmp_path: Path, bad_slug: str) -> None:
    """M2: matter_slug + topic_slug must not let callers escape the matter dir."""
    client = _FakeClient(_completion_payload())
    with pytest.raises(ValueError):
        save_investigation_json("r", bad_slug, "ok-topic", client=client, dropbox_root=tmp_path)
    with pytest.raises(ValueError):
        save_investigation_json("r", "ok-matter", bad_slug, client=client, dropbox_root=tmp_path)


# --------------------------- convert_to_pdf ---------------------------


def _write_sample_json(tmp_path: Path, matter: str = "hagenauer-rg7", report_md: str | None = None) -> Path:
    research = tmp_path / matter / "research"
    research.mkdir(parents=True)
    p = research / "2026-05-17-pagitsch-defects.json"
    payload = _completion_payload(report_md if report_md is not None else "# Report\n\nbody")
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_convert_to_pdf_runs_pandoc_and_returns_path(tmp_path: Path) -> None:
    json_p = _write_sample_json(tmp_path)
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"%PDF-1.4 stub")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(report_renderer.shutil, "which", return_value="/usr/local/bin/pandoc"), \
         patch.object(report_renderer.subprocess, "run", side_effect=_fake_run):
        pdf_path = convert_to_pdf(str(json_p))

    assert Path(pdf_path).exists()
    assert pdf_path.endswith(".pdf")
    assert calls and calls[0][0] == "/usr/local/bin/pandoc"


def test_convert_to_pdf_missing_pandoc_raises_unavailable(tmp_path: Path) -> None:
    json_p = _write_sample_json(tmp_path)
    with patch.object(report_renderer.shutil, "which", return_value=None):
        with pytest.raises(RendererUnavailableError, match="pandoc"):
            convert_to_pdf(str(json_p))


def test_convert_to_pdf_pandoc_nonzero_exit_raises_unavailable(tmp_path: Path) -> None:
    json_p = _write_sample_json(tmp_path)
    failing = subprocess.CompletedProcess([], 1, stdout="", stderr="LaTeX missing")
    with patch.object(report_renderer.shutil, "which", return_value="/usr/local/bin/pandoc"), \
         patch.object(report_renderer.subprocess, "run", return_value=failing):
        with pytest.raises(RendererUnavailableError, match="LaTeX missing"):
            convert_to_pdf(str(json_p))


def test_convert_to_pdf_missing_json_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        convert_to_pdf(str(tmp_path / "nope.json"))


def test_convert_to_pdf_cleans_up_md_sibling_on_success(tmp_path: Path) -> None:
    """H1: the .md staged next to the JSON must not survive a successful render."""
    json_p = _write_sample_json(tmp_path)
    md_sibling = json_p.with_suffix(".md")

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"%PDF-1.4 stub")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"), \
         patch.object(report_renderer.subprocess, "run", side_effect=_fake_run):
        convert_to_pdf(str(json_p))

    assert not md_sibling.exists(), "PDF conversion must remove the .md artefact"


def test_convert_to_pdf_cleans_up_md_sibling_on_failure(tmp_path: Path) -> None:
    """H1: even when pandoc errors, the .md staging file must be removed."""
    json_p = _write_sample_json(tmp_path)
    md_sibling = json_p.with_suffix(".md")
    failing = subprocess.CompletedProcess([], 1, stdout="", stderr="LaTeX missing")
    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"), \
         patch.object(report_renderer.subprocess, "run", return_value=failing):
        with pytest.raises(RendererUnavailableError):
            convert_to_pdf(str(json_p))
    assert not md_sibling.exists()


def test_convert_to_pdf_pandoc_timeout_raises_unavailable(tmp_path: Path) -> None:
    """M3: pandoc that hangs past the timeout maps to RendererUnavailableError."""
    json_p = _write_sample_json(tmp_path)
    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"), \
         patch.object(
             report_renderer.subprocess,
             "run",
             side_effect=subprocess.TimeoutExpired(cmd=["pandoc"], timeout=120.0),
         ):
        with pytest.raises(RendererUnavailableError, match="timeout"):
            convert_to_pdf(str(json_p))


# --------------------------- convert_to_html ---------------------------


def test_convert_to_html_writes_under_docs_site(tmp_path: Path) -> None:
    json_p = _write_sample_json(tmp_path, matter="mo-vie")
    docs_site = tmp_path / "docs-site"

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        Path(cmd[cmd.index("-o") + 1]).write_text("<html>stub</html>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(report_renderer.shutil, "which", return_value="/usr/local/bin/pandoc"), \
         patch.object(report_renderer.subprocess, "run", side_effect=_fake_run):
        html_path = convert_to_html(str(json_p), docs_site_root=docs_site)

    assert Path(html_path).exists()
    assert Path(html_path).parent == docs_site / "mo-vie"
    assert Path(html_path).name.endswith(".html")
    assert Path(html_path).read_text(encoding="utf-8") == "<html>stub</html>"


def test_convert_to_html_raises_when_docs_site_root_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H2: no BAKER_DOCS_SITE_ROOT env + no kwarg = fail loud, not phantom path."""
    json_p = _write_sample_json(tmp_path)
    monkeypatch.delenv("BAKER_DOCS_SITE_ROOT", raising=False)
    with pytest.raises(RendererUnavailableError, match="BAKER_DOCS_SITE_ROOT"):
        convert_to_html(str(json_p))


def test_convert_to_html_uses_env_var_when_no_kwarg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H2: BAKER_DOCS_SITE_ROOT env supplies the default when no kwarg passed."""
    json_p = _write_sample_json(tmp_path, matter="cupial")
    docs_site = tmp_path / "docs-site"
    monkeypatch.setenv("BAKER_DOCS_SITE_ROOT", str(docs_site))

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        Path(cmd[cmd.index("-o") + 1]).write_text("<html>ok</html>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"), \
         patch.object(report_renderer.subprocess, "run", side_effect=_fake_run):
        html_path = convert_to_html(str(json_p))

    assert Path(html_path).parent == docs_site / "cupial"


def test_convert_to_html_raises_when_docs_site_parent_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H2: pointing at a path whose parent doesn't exist is treated as unreachable."""
    json_p = _write_sample_json(tmp_path)
    monkeypatch.setenv("BAKER_DOCS_SITE_ROOT", str(tmp_path / "missing-parent" / "docs-site"))
    with pytest.raises(RendererUnavailableError, match="parent does not exist"):
        convert_to_html(str(json_p))


def test_convert_to_html_falls_back_to_misc_when_path_not_under_research(tmp_path: Path) -> None:
    p = tmp_path / "orphan.json"
    p.write_text(json.dumps(_completion_payload()), encoding="utf-8")
    docs_site = tmp_path / "docs-site"

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        Path(cmd[cmd.index("-o") + 1]).write_text("ok", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"), \
         patch.object(report_renderer.subprocess, "run", side_effect=_fake_run):
        html_path = convert_to_html(str(p), docs_site_root=docs_site)

    assert Path(html_path).parent == docs_site / "misc"


# --------------------------- markdown extraction edge cases ---------------------------


def test_renderer_uses_stub_when_report_null(tmp_path: Path) -> None:
    """A still-running investigation has report=None — render still succeeds with a stub body."""
    research = tmp_path / "m" / "research"
    research.mkdir(parents=True)
    p = research / "x.json"
    payload = _completion_payload()
    payload["report"] = None
    payload["status"] = "running"
    p.write_text(json.dumps(payload), encoding="utf-8")
    captured_md: list[str] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        md_path = Path(cmd[1])
        captured_md.append(md_path.read_text(encoding="utf-8"))
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"stub")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"), \
         patch.object(report_renderer.subprocess, "run", side_effect=_fake_run):
        convert_to_pdf(str(p))

    assert captured_md and "Status: running" in captured_md[0]


def test_renderer_raises_on_invalid_json(tmp_path: Path) -> None:
    research = tmp_path / "m" / "research"
    research.mkdir(parents=True)
    p = research / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with patch.object(report_renderer.shutil, "which", return_value="/pandoc"):
        with pytest.raises(RendererError, match="not valid JSON"):
            convert_to_pdf(str(p))


# --------------------------- _matter_slug_from_json_path ---------------------------


def test_matter_slug_from_json_path_returns_segment_before_research() -> None:
    p = Path("/dropbox/1_ACTIVE_PROJECTS/hagenauer-rg7/research/2026-05-17-defects.json")
    assert report_renderer._matter_slug_from_json_path(p) == "hagenauer-rg7"


def test_matter_slug_from_json_path_falls_back_when_no_research_segment() -> None:
    p = Path("/tmp/orphan.json")
    assert report_renderer._matter_slug_from_json_path(p) == "misc"


def test_matter_slug_from_json_path_rejects_parent_dir_candidate() -> None:
    """Validator must reject ``..`` as the slug segment before ``research/``."""
    p = Path("/dropbox/foo/../research/x.json")
    assert report_renderer._matter_slug_from_json_path(p) == "misc"


def test_matter_slug_from_json_path_rejects_research_at_root() -> None:
    """No segment before ``research/`` (idx==0) falls back without validation."""
    p = Path("research/x.json")
    assert report_renderer._matter_slug_from_json_path(p) == "misc"
