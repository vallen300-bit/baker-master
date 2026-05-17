"""Investigation output renderer — JSON by default, convert on instruction.

Default flow (always run after a ClaimsMax /investigate completes):

    save_investigation_json(run_id, matter_slug, topic_slug) -> json_path

writes the slim status projection (status, query, report, step_count,
started_at, ended_at) to
``~/Vallen Dropbox/Dimitry vallen/1_ACTIVE_PROJECTS/<matter>/research/<YYYY-MM-DD>-<topic>.json``.

Director-gated conversions (run only when Director explicitly instructs the
matter Desk to convert):

    convert_to_pdf(json_path)  -> pdf_path  (sibling of the JSON)
    convert_to_html(json_path) -> html_path (under docs-site/<matter>/)

No size heuristic; no auto-render. Director ratified 2026-05-17 — produce
cheap default (JSON), promote selectively.

Pandoc is required for both conversions; absence raises
``RendererUnavailableError`` with a remediation hint.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ─────────────────────────── exceptions ───────────────────────────


class RendererError(RuntimeError):
    """Base class for renderer failures."""


class RendererUnavailableError(RendererError):
    """``pandoc`` binary missing or invocation failed."""


# ─────────────────────────── constants ───────────────────────────

_DROPBOX_ROOT = (
    Path.home()
    / "Vallen Dropbox"
    / "Dimitry vallen"
    / "1_ACTIVE_PROJECTS"
)
_DOCS_SITE_ROOT = Path.home() / "Desktop" / "baker-code" / "docs-site"


# ─────────────────────────── public surface ───────────────────────────


def save_investigation_json(
    run_id: str,
    matter_slug: str,
    topic_slug: str,
    *,
    client: Optional[object] = None,
    dropbox_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> str:
    """Fetch the final ``/investigate/{run_id}`` projection and persist it as JSON.

    Cheap default — runs after every investigation regardless of size.

    Args:
        run_id: ClaimsMax investigation run identifier.
        matter_slug: matter folder under ``1_ACTIVE_PROJECTS/``.
        topic_slug: short kebab-case topic name; embedded in the filename.
        client: optional injected ``ClaimsmaxClient`` (defaults to a fresh
            instance). Passed in by tests.
        dropbox_root: optional override of the Dropbox active-projects root.
            Used by tests; defaults to the canonical Director path.
        now: optional clock injection for tests.

    Returns:
        Absolute path of the JSON file written.
    """
    if not run_id:
        raise ValueError("run_id is required")
    if not matter_slug:
        raise ValueError("matter_slug is required")
    if not topic_slug:
        raise ValueError("topic_slug is required")

    if client is None:
        from kbl.claimsmax_client import ClaimsmaxClient  # local import; avoids env requirement at import time
        client = ClaimsmaxClient()

    status_payload = client.investigate_status(run_id)  # type: ignore[attr-defined]

    root = dropbox_root if dropbox_root is not None else _DROPBOX_ROOT
    research_dir = root / matter_slug / "research"
    research_dir.mkdir(parents=True, exist_ok=True)

    stamp = (now or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%d")
    json_path = research_dir / f"{stamp}-{topic_slug}.json"

    json_path.write_text(json.dumps(status_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(json_path)


def convert_to_pdf(json_path: str, *, pandoc_bin: Optional[str] = None) -> str:
    """Render the investigation's markdown report into a PDF sibling of the JSON.

    Runs only when Director instructs the matter Desk to convert.
    """
    md_path, pdf_path = _prepare_markdown_sibling(json_path, suffix=".pdf")
    _pandoc_render(md_path, pdf_path, mode="pdf", pandoc_bin=pandoc_bin)
    return str(pdf_path)


def convert_to_html(
    json_path: str,
    *,
    pandoc_bin: Optional[str] = None,
    docs_site_root: Optional[Path] = None,
) -> str:
    """Render the investigation's markdown report into a standalone HTML.

    Writes under ``docs-site/<matter>/<basename>.html``. The caller (matter Desk)
    is responsible for committing + pushing ``docs-site`` so Render publishes
    the page to brisen-docs.onrender.com.
    """
    json_p = Path(json_path).expanduser().resolve()
    if not json_p.exists():
        raise FileNotFoundError(f"investigation JSON not found: {json_path}")

    matter_slug = _matter_slug_from_json_path(json_p)
    out_root = docs_site_root if docs_site_root is not None else _DOCS_SITE_ROOT
    out_dir = out_root / matter_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / (json_p.stem + ".html")

    md_path = _write_markdown_tempfile(json_p)
    try:
        _pandoc_render(md_path, html_path, mode="html", pandoc_bin=pandoc_bin)
    finally:
        try:
            md_path.unlink()
        except OSError:
            pass
    return str(html_path)


# ─────────────────────────── private helpers ───────────────────────────


def _prepare_markdown_sibling(json_path: str, *, suffix: str) -> tuple[Path, Path]:
    """Materialise the JSON's ``report`` field as a markdown file beside it.

    Returns ``(markdown_path, output_path_with_suffix)``.
    """
    json_p = Path(json_path).expanduser().resolve()
    if not json_p.exists():
        raise FileNotFoundError(f"investigation JSON not found: {json_path}")
    md_path = json_p.with_suffix(".md")
    out_path = json_p.with_suffix(suffix)

    report_md = _extract_report_markdown(json_p)
    md_path.write_text(report_md, encoding="utf-8")
    return md_path, out_path


def _write_markdown_tempfile(json_p: Path) -> Path:
    """Write the JSON's markdown report to a temp file next to the JSON.

    Used by HTML conversion where the .md file is transient (output goes to
    docs-site, not next to the JSON).
    """
    md_path = json_p.with_suffix(".md")
    md_path.write_text(_extract_report_markdown(json_p), encoding="utf-8")
    return md_path


def _extract_report_markdown(json_p: Path) -> str:
    """Read the JSON file and return the ``report`` markdown body.

    Falls back to a stub markdown body if the report is null or missing
    (investigation still running / errored). The caller still gets a
    pandoc-renderable input.
    """
    try:
        payload = json.loads(json_p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RendererError(f"investigation JSON is not valid JSON: {json_p}: {e}") from e

    report = payload.get("report") if isinstance(payload, dict) else None
    if report:
        return str(report)

    status = payload.get("status", "unknown") if isinstance(payload, dict) else "unknown"
    query = payload.get("query", "") if isinstance(payload, dict) else ""
    return (
        f"# Investigation: {query or '(no query)'}\n\n"
        f"_Status: {status} — no report markdown available._\n"
    )


def _pandoc_render(md_path: Path, out_path: Path, *, mode: str, pandoc_bin: Optional[str]) -> None:
    """Invoke pandoc to render markdown into the target format.

    ``mode`` is ``"pdf"`` or ``"html"``. Missing binary or non-zero exit raises
    ``RendererUnavailableError`` so callers can surface as a deploy blocker.
    """
    binary = pandoc_bin or shutil.which("pandoc")
    if not binary:
        raise RendererUnavailableError(
            "pandoc binary not found on PATH. Install via brew (macOS) "
            "or add to Render runtime (Dockerfile/aptfile) before conversion."
        )

    if mode == "pdf":
        cmd = [binary, str(md_path), "-o", str(out_path)]
    elif mode == "html":
        cmd = [binary, "-s", str(md_path), "-o", str(out_path)]
    else:
        raise ValueError(f"unknown pandoc mode: {mode}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise RendererUnavailableError(f"pandoc invocation failed: {e}") from e

    if result.returncode != 0:
        raise RendererUnavailableError(
            f"pandoc exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )


def _matter_slug_from_json_path(json_p: Path) -> str:
    """Recover the matter slug from a path under ``1_ACTIVE_PROJECTS/<matter>/research/...``.

    Falls back to ``"misc"`` when the path doesn't conform — keeps HTML
    generation working from anywhere (tests, ad-hoc local renders).
    """
    parts = json_p.parts
    try:
        idx = parts.index("research")
        if idx >= 1:
            return parts[idx - 1]
    except ValueError:
        pass
    return "misc"
