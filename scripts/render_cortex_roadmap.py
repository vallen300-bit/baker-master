"""Render the LIVE Cortex roadmap from YAML source-of-truth to brisen-docs HTML.

Source: ~/baker-vault/_ops/processes/cortex-roadmap-current.yml (canonical)
Output: docs-site/architecture/cortex-roadmap-current.html (brisen-docs live page)

Pattern C (hybrid versioned-live) per Director ratification 2026-04-30. AI Head A
edits the YAML; this script rebuilds the HTML on every YAML change. brisen-docs
auto-deploys from baker-master/docs-site/ on push.

Status enum: done | in_flight | queued | dropped (NO `parked` per Director).
Backlog lives in ClickUp BAKER space "Cortex Backlog" list (901523104264) —
not in this YAML, queryable via baker_clickup_tasks MCP tool.

Usage:
    python3 scripts/render_cortex_roadmap.py [--vault-root PATH] [--out PATH]

Idempotent. Writes HTML to docs-site/architecture/cortex-roadmap-current.html.
Caller commits + pushes; brisen-docs static-site Render service auto-deploys.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

DEFAULT_VAULT_ROOT = Path.home() / "baker-vault"
DEFAULT_YAML_REL = Path("_ops") / "processes" / "cortex-roadmap-current.yml"
DEFAULT_OUT_REL = Path("docs-site") / "architecture" / "cortex-roadmap-current.html"

REPO_ROOT = Path(__file__).resolve().parents[1]


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Cortex Roadmap (LIVE) — V{version}</title>
<style>
  :root {{
    --bg-page: #fafaf7;
    --bg-card: #fff;
    --bg-card-done: #f5f9ed;
    --bg-card-flight: #fff8e8;
    --bg-card-queue: #f4f0e6;
    --bg-card-dropped: #f5ecec;
    --bg-summary: #f0ece0;
    --bg-callout: #faf7eb;
    --bg-rail: #2c2317;
    --text-body: #1a1a1a;
    --text-header: #4a3a1f;
    --text-muted: #6c5e3f;
    --text-rail: #f5f1e2;
    --border-default: #d6cfb8;
    --border-done: #a8c084;
    --border-flight: #d8b855;
    --border-queue: #c8b878;
    --border-dropped: #c8a8a8;
    --accent: #8c7a4e;
    --accent-locked: #6a8c4e;
    --accent-dropped: #a86c6c;
    --rec-bg: #c2d8a0;
    --rec-text: #2c4a1c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg-page); color: var(--text-body); line-height: 1.5;
  }}
  .wrap {{ max-width: 1180px; margin: 2rem auto; padding: 0 1.5rem 4rem; }}
  header {{ border-bottom: 1px solid var(--border-default); padding-bottom: 1.25rem; margin-bottom: 1.5rem; }}
  h1 {{ color: var(--text-header); font-size: 1.6rem; margin: 0 0 0.5rem; letter-spacing: -0.01em; }}
  .meta {{ color: var(--text-muted); font-size: 0.85rem; }}
  .meta strong {{ color: var(--text-header); }}
  .live-badge {{ display: inline-block; background: var(--rec-bg); color: var(--rec-text); padding: 0.15rem 0.6rem; border-radius: 3px; font-weight: 600; font-size: 0.75rem; letter-spacing: 0.05em; margin-left: 0.5rem; vertical-align: middle; }}
  .legend {{ display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.8rem; color: var(--text-muted); margin-top: 0.75rem; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
  .legend .dot {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
  .dot-done {{ background: var(--bg-card-done); border: 1px solid var(--border-done); }}
  .dot-flight {{ background: var(--bg-card-flight); border: 1px solid var(--border-flight); }}
  .dot-queue {{ background: var(--bg-card-queue); border: 1px solid var(--border-queue); }}
  .dot-dropped {{ background: var(--bg-card-dropped); border: 1px solid var(--border-dropped); }}
  .stage {{ margin: 2.5rem 0 0.75rem; }}
  .stage-title {{ color: var(--text-header); font-size: 1.15rem; font-weight: 700; margin: 0 0 0.25rem; letter-spacing: -0.01em; border-bottom: 1px solid var(--border-default); padding-bottom: 0.4rem; }}
  .stage-meta {{ font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.85rem; }}
  .item {{ background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 6px; padding: 0.85rem 1rem; margin: 0.55rem 0; display: grid; grid-template-columns: 32px 1fr auto; gap: 0.85rem; align-items: start; }}
  .item.done {{ background: var(--bg-card-done); border-color: var(--border-done); }}
  .item.flight {{ background: var(--bg-card-flight); border-color: var(--border-flight); }}
  .item.queue {{ background: var(--bg-card-queue); border-color: var(--border-queue); }}
  .item.dropped {{ background: var(--bg-card-dropped); border-color: var(--border-dropped); }}
  .icon {{ font-size: 1.2rem; text-align: center; line-height: 1.4; }}
  .label {{ font-size: 0.95rem; color: var(--text-header); font-weight: 600; margin-bottom: 0.15rem; }}
  .item .desc {{ font-size: 0.85rem; color: var(--text-body); white-space: pre-wrap; }}
  .item .anchor {{ display: inline-block; margin-top: 0.25rem; font-size: 0.78rem; color: var(--text-muted); font-family: ui-monospace, "SF Mono", Menlo, monospace; }}
  .item .meta-line {{ font-size: 0.78rem; color: var(--text-muted); margin-top: 0.25rem; }}
  .item .meta-line span {{ margin-right: 1rem; }}
  .badge {{ align-self: center; background: var(--accent); color: #fff; padding: 0.18rem 0.55rem; border-radius: 3px; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em; white-space: nowrap; }}
  .badge.done {{ background: var(--accent-locked); }}
  .badge.flight {{ background: #c8901a; }}
  .badge.queue {{ background: var(--accent); }}
  .badge.dropped {{ background: var(--accent-dropped); }}
  .priority {{ display: inline-block; padding: 0.05rem 0.4rem; border-radius: 2px; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; margin-left: 0.4rem; }}
  .priority.critical {{ background: #c84e3a; color: #fff; }}
  .priority.high {{ background: #c8901a; color: #fff; }}
  .priority.medium {{ background: #8c7a4e; color: #fff; }}
  .summary-bar {{ background: var(--bg-summary); border-radius: 6px; padding: 0.85rem 1.1rem; margin: 0.4rem 0 1rem; font-size: 0.88rem; }}
  .summary-bar strong {{ color: var(--text-header); }}
  .callout {{ background: var(--bg-callout); border-left: 3px solid var(--border-queue); padding: 0.6rem 0.85rem; border-radius: 3px; margin: 0.4rem 0 0.6rem 0; font-size: 0.83rem; }}
  .callout strong {{ color: var(--text-header); }}
  .backlog-link {{ display: inline-block; background: var(--bg-rail); color: var(--rec-bg); padding: 0.5rem 0.9rem; border-radius: 4px; text-decoration: none; font-weight: 600; font-size: 0.85rem; margin-top: 0.5rem; }}
  .backlog-link:hover {{ background: #1a1410; }}
  footer {{ margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--border-default); font-size: 0.78rem; color: var(--text-muted); }}
  footer code {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Cortex Roadmap <span class="live-badge">LIVE V{version}</span></h1>
  <div class="meta">
    Cut <strong>{cut_at}</strong>. Source-of-truth: <code>baker-vault/_ops/processes/cortex-roadmap-current.yml</code>. Auto-rendered to HTML on commit. Backlog (not on this page) lives in ClickUp BAKER space "Cortex Backlog" list — <a href="{clickup_backlog_url}" target="_blank">open</a>.
  </div>
  <div class="legend">
    <span><span class="dot dot-done"></span>Done</span>
    <span><span class="dot dot-flight"></span>In flight</span>
    <span><span class="dot dot-queue"></span>Queued (current sprint)</span>
    <span><span class="dot dot-dropped"></span>Dropped (audit trail)</span>
  </div>
</header>

<div class="summary-bar">
  <strong>Cut reason:</strong>
  <div style="white-space: pre-wrap; margin-top: 0.4rem; font-size: 0.84rem;">{cut_reason}</div>
</div>

<div class="summary-bar">
  <strong>Target:</strong>
  <div style="white-space: pre-wrap; margin-top: 0.4rem; font-size: 0.84rem;">{target}</div>
</div>

<div class="stage">
  <h2 class="stage-title">In flight</h2>
  <div class="stage-meta">Active builds. Carries assignee + ETA. Closes to <code>done</code> on ship.</div>
  {in_flight_items}
</div>

<div class="stage">
  <h2 class="stage-title">Queued — current sprint (no PARKED, ever)</h2>
  <div class="stage-meta">Owner + ETA mandatory. ETA cap = 2 weeks. Items past ETA get reprioritized or dropped — never silently shelved. Items not in this sprint live in <a href="{clickup_backlog_url}" target="_blank">ClickUp Cortex Backlog</a>.</div>
  {queued_items}
</div>

<a class="backlog-link" href="{clickup_backlog_url}" target="_blank">→ Open ClickUp Cortex Backlog (queryable backlog)</a>

<div class="stage">
  <h2 class="stage-title">Done</h2>
  <div class="stage-meta">Shipped + verified.</div>
  {done_items}
</div>

<div class="stage">
  <h2 class="stage-title">Dropped (audit trail)</h2>
  <div class="stage-meta">Explicitly killed with reason. Kept for audit; not actionable.</div>
  {dropped_items}
</div>

<div class="callout">
  <strong>Standing rules (Director-ratified):</strong>
  <ul style="margin: 0.4rem 0 0; padding-left: 1.2rem;">
    <li>NO <code>parked</code> status — items either DONE / IN_FLIGHT / QUEUED / DROPPED on this page, or sit as ClickUp tasks in Cortex Backlog with priority + due date + assignee. (Director 2026-04-30: "I do not like anything parked. Parked is never done.")</li>
    <li>Backlog drift detection writes to ClickUp recurring task — NOT Slack DM. (Director 2026-04-30.)</li>
    <li>YAML edits are the SOURCE-OF-TRUTH. Every shipped item flips status in YAML; CI rebuilds this HTML.</li>
    <li>Version cuts every ~2 weeks OR on major architectural shift. Past versions snapshot to <code>cortex-roadmap-vN-YYYY-MM-DD.html</code>.</li>
  </ul>
</div>

<footer>
  Auto-rendered <strong>{rendered_at}</strong> from <code>{yaml_path}</code> by <code>scripts/render_cortex_roadmap.py</code>. Live page: <code>{brisen_docs_url}</code>.
  Supersedes: <code>{supersedes}</code>.
</footer>
</div>
</body>
</html>
"""


def render_item(item: dict, status: str) -> str:
    """Render a single item as an HTML card."""
    klass = status
    label = item.get("label", item.get("id", "(unlabeled)"))
    icon = {"done": "✓", "in_flight": "⏳", "queued": "→", "dropped": "✕"}.get(status, "•")
    badge_text = status.upper().replace("_", " ")

    desc = item.get("description") or item.get("rationale") or item.get("dropped_reason") or ""

    # Meta line — different fields per status
    meta_bits = []
    if status == "done":
        if item.get("shipped_at"):
            meta_bits.append(f"<span><strong>Shipped:</strong> {item['shipped_at']}</span>")
        if item.get("promoted_from_parked"):
            meta_bits.append(f"<span style='color: var(--accent-locked);'>↑ promoted from parked</span>")
        if item.get("deviation_note"):
            meta_bits.append(f"<span><strong>Deviation:</strong> {item['deviation_note']}</span>")
    elif status == "in_flight":
        if item.get("started_at"):
            meta_bits.append(f"<span><strong>Started:</strong> {item['started_at']}</span>")
        if item.get("assignee"):
            meta_bits.append(f"<span><strong>Owner:</strong> {item['assignee']}</span>")
        if item.get("eta"):
            meta_bits.append(f"<span><strong>ETA:</strong> {item['eta']}</span>")
    elif status == "queued":
        if item.get("owner"):
            meta_bits.append(f"<span><strong>Owner:</strong> {item['owner']}</span>")
        if item.get("eta"):
            meta_bits.append(f"<span><strong>ETA:</strong> {item['eta']}</span>")
    elif status == "dropped":
        if item.get("dropped_at"):
            meta_bits.append(f"<span><strong>Dropped:</strong> {item['dropped_at']}</span>")
        if item.get("superseded_by"):
            meta_bits.append(f"<span><strong>Superseded by:</strong> {item['superseded_by']}</span>")

    priority_html = ""
    if item.get("priority"):
        priority_html = f'<span class="priority {item["priority"]}">{item["priority"]}</span>'

    anchor_html = ""
    if item.get("anchor"):
        anchor_html = f'<div class="anchor">{item["anchor"]}</div>'

    meta_html = ""
    if meta_bits:
        meta_html = f'<div class="meta-line">{"".join(meta_bits)}</div>'

    return f"""
  <div class="item {klass}">
    <div class="icon">{icon}</div>
    <div>
      <div class="label">{label}{priority_html}</div>
      <div class="desc">{desc.strip()}</div>
      {meta_html}
      {anchor_html}
    </div>
    <div class="badge {klass}">{badge_text}</div>
  </div>"""


def render(yml: dict) -> str:
    """Render the full HTML page from YAML data."""
    # Sort queued by priority + ETA
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    queued = sorted(
        yml.get("queued", []) or [],
        key=lambda x: (priority_order.get(x.get("priority", "medium"), 99), x.get("eta", "9999-99-99")),
    )

    in_flight_items = "\n".join(render_item(i, "in_flight") for i in yml.get("in_flight", []) or [])
    queued_items = "\n".join(render_item(i, "queued") for i in queued)
    done_items = "\n".join(render_item(i, "done") for i in yml.get("done", []) or [])
    dropped_items = "\n".join(render_item(i, "dropped") for i in yml.get("dropped", []) or [])

    backlog = yml.get("backlog", {}) or {}

    return HTML_TEMPLATE.format(
        version=yml.get("version", "?"),
        cut_at=yml.get("cut_at", "?"),
        cut_reason=yml.get("cut_reason", "").strip(),
        target=yml.get("target", "").strip(),
        clickup_backlog_url=backlog.get("list_url", "#"),
        in_flight_items=in_flight_items or "<p style='color: var(--text-muted); font-style: italic;'>(none in flight)</p>",
        queued_items=queued_items or "<p style='color: var(--text-muted); font-style: italic;'>(none queued)</p>",
        done_items=done_items or "<p style='color: var(--text-muted); font-style: italic;'>(none done)</p>",
        dropped_items=dropped_items or "<p style='color: var(--text-muted); font-style: italic;'>(none dropped)</p>",
        rendered_at=date.today().isoformat(),
        yaml_path=str(DEFAULT_YAML_REL),
        brisen_docs_url=yml.get("brisen_docs_url", ""),
        supersedes=yml.get("supersedes", ""),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--vault-root", type=Path, default=DEFAULT_VAULT_ROOT,
        help=f"baker-vault checkout root (default: {DEFAULT_VAULT_ROOT})",
    )
    parser.add_argument(
        "--yaml", type=Path, default=None,
        help=f"YAML source path (default: <vault-root>/{DEFAULT_YAML_REL})",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help=f"HTML output path (default: <repo-root>/{DEFAULT_OUT_REL})",
    )
    args = parser.parse_args(argv)

    yaml_path = args.yaml if args.yaml else args.vault_root / DEFAULT_YAML_REL
    out_path = args.out if args.out else REPO_ROOT / DEFAULT_OUT_REL

    if not yaml_path.is_file():
        print(f"ERROR: YAML source not found: {yaml_path}", file=sys.stderr)
        return 1

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print(f"ERROR: YAML must be a dict at top level (got {type(data).__name__})", file=sys.stderr)
        return 1

    html = render(data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"[OK] Rendered {yaml_path} → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
