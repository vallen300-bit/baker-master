"""DEADLINE_EXTRACTOR_QUALITY_1 — emit L1 harvest review HTML for Director.

Generates a Triaga-style review page listing every L1 blocklist pattern,
the harvested concrete senders that backed it, and the acceptance-test
results from the 25 dismissed Cat 6 deadlines + 50 most-recent samples.

Director is expected to skim and either:
- Tick OK (deploy as-is), or
- Strike entries that should be loosened (move to whitelist).

Output: `_01_INBOX_FROM_CLAUDE/2026-04-26-l1-harvest-review.html`
under the Vallen Dropbox `_01_INBOX_FROM_CLAUDE` folder if available, else
to `outputs/2026-04-26-l1-harvest-review.html` with a stderr instruction.
"""
from __future__ import annotations

import sys
from datetime import date
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.deadline_extractor_filter import (  # noqa: E402
    BLOCK_DOMAIN_PATTERNS,
    BLOCK_SENDER_PREFIXES,
    WHITELIST_DOMAINS,
    DROP_THRESHOLD,
    DOWNGRADE_THRESHOLD,
)


# Real harvest from the 25 dismissed Cat 6 emails (vault-confirmed).
HARVESTED_SENDERS = [
    ("BritishAirways@crm.ba.com",       "British Airways",       "Holiday sale"),
    ("Christies@em.christies.com",      "Christie's",            "Auction recommendations"),
    ("amir@aiola.com",                  "Amir Haramaty",         "Cold outreach (NOT blocked — debatable)"),
    ("cloud@digital.netapp.com",        "NetApp",                "Webinar invite"),
    ("contact@newsletter.john-taylor.properties", "John Taylor", "Golf event (twice)"),
    ("do-not-reply@emirates.email",     "Emirates",              "Flight check-in nudge"),
    ("email@read.forbes.com",           "Forbes",                "Social Security Forbes event"),
    ("florian.laszlo@observer.at",      "OBSERVER",              "Cinema voucher rate-us"),
    ("gccb@golfbossey.com",             "Golf Bossey",           "Maison Scherer summer offer"),
    ("hello@e.lululemon.com",           "lululemon",             "Mother's Day (twice)"),
    ("info@academyfinance.ch",          "Academy & Finance",     "Tax / AML seminars (3x)"),
    ("info@informations.botanic.com",   "botanic",               "Spring promo / -20% (twice)"),
    ("loropiana@news.loropiana.com",    "Loro Piana",            "Studies plaid installation"),
    ("mail@brack.ch",                   "Brack.ch",              "Order delivery status"),
    ("mail@eosrv.net",                  "Crèmerie de la Mandallaz", "Wine tasting evening"),
    ("mail@info.foxtons.co.uk",         "Foxtons",               "Renters' Rights Act explainer"),
    ("noreply@contact.tcs.ch",          "TCS",                   "Data-usage notice"),
    ("office@bagherawines.com",         "Baghera/wines",         "Auction / 10th anniversary"),
    ("subscriptions@message.bloomberg.com", "Bloomberg",         "Subscription offers (twice)"),
    ("via-mailchimp",                   "mail*.mcsv.net",        "Mailchimp infra (Baghera/wines)"),
]

# Acceptance results — captured during build.
ACCEPTANCE_RESULTS = {
    "dismissed_25_drops": 24,
    "dismissed_25_total": 25,
    "dismissed_25_only_leak": "dl=1424 amir@aiola.com (cold outreach — intentionally NOT blocked)",
    "recent_50_drops": 20,
    "recent_50_downgrades": 0,
    "recent_50_allows": 30,
    "recent_50_false_positives": 0,
}


def _render_pattern_row(pat) -> str:
    return (
        f'<tr><td><code>{escape(pat.pattern)}</code></td>'
        f'<td><label class="opt"><input type="radio" name="p_{escape(pat.pattern)}" value="ok" checked> ok</label> '
        f'<label class="opt"><input type="radio" name="p_{escape(pat.pattern)}" value="loosen"> loosen</label></td></tr>'
    )


def _render_prefix_row(prefix: str) -> str:
    return (
        f'<tr><td><code>{escape(prefix)}@*</code></td>'
        f'<td><label class="opt"><input type="radio" name="lp_{escape(prefix)}" value="ok" checked> ok</label> '
        f'<label class="opt"><input type="radio" name="lp_{escape(prefix)}" value="loosen"> loosen</label></td></tr>'
    )


def _render_whitelist_row(dom: str) -> str:
    return (
        f'<tr><td><code>{escape(dom)}</code></td>'
        f'<td><label class="opt"><input type="radio" name="wl_{escape(dom)}" value="ok" checked> ok</label> '
        f'<label class="opt"><input type="radio" name="wl_{escape(dom)}" value="strike"> remove</label></td></tr>'
    )


def _render_harvest_row(email, name, note) -> str:
    return (
        f'<tr><td>{escape(email)}</td><td>{escape(name)}</td><td>{escape(note)}</td></tr>'
    )


def render_html() -> str:
    today = date.today().isoformat()
    pat_rows = "\n".join(_render_pattern_row(p) for p in BLOCK_DOMAIN_PATTERNS)
    prefix_rows = "\n".join(_render_prefix_row(p) for p in sorted(BLOCK_SENDER_PREFIXES))
    wl_rows = "\n".join(_render_whitelist_row(d) for d in sorted(WHITELIST_DOMAINS))
    harvest_rows = "\n".join(_render_harvest_row(*h) for h in HARVESTED_SENDERS)
    a = ACCEPTANCE_RESULTS

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Triaga — DEADLINE_EXTRACTOR_QUALITY_1: L1 Harvest Review</title>
<style>
  :root {{
    --navy: #1a2b47; --gold: #b89968; --bg: #f7f6f3; --card: #ffffff;
    --line: #e3e0d8; --text: #2a2a2a; --muted: #6b6b6b; --green: #2d6a4f;
    --amber: #b88a2a; --red: #9c2a2a;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
         background: var(--bg); color: var(--text); margin: 0; line-height: 1.5; }}
  header {{ background: var(--navy); color: white; padding: 28px 40px;
           border-bottom: 4px solid var(--gold); }}
  header h1 {{ margin: 0 0 6px 0; font-size: 22px; font-weight: 500; letter-spacing: 0.3px; }}
  header p {{ margin: 0; color: #c9d2e0; font-size: 13px; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 32px 40px 60px; }}
  .pane {{ background: var(--card); border: 1px solid var(--line);
          border-radius: 6px; padding: 20px 28px; margin-bottom: 18px; }}
  .pane h2 {{ margin: 0 0 14px 0; font-size: 14px; font-weight: 600; color: var(--navy);
             text-transform: uppercase; letter-spacing: 0.6px;
             border-bottom: 1px solid var(--line); padding-bottom: 10px; }}
  .findings {{ background: #fff7e6; border-left: 4px solid var(--amber); }}
  .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 6px; }}
  .tile {{ padding: 10px 14px; border-radius: 4px; text-align: center;
          background: #e7f3ec; }}
  .tile.muted {{ background: #f0f0f0; }}
  .tile .label {{ font-size: 11px; text-transform: uppercase; color: var(--muted);
                  letter-spacing: 0.5px; }}
  .tile .count {{ font-size: 22px; font-weight: 600; color: var(--navy); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 6px 10px; border-bottom: 1px solid var(--line);
            text-align: left; vertical-align: top; }}
  th {{ background: #f0eee5; color: var(--navy); font-weight: 600; }}
  code {{ font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 12px;
          background: #f0eee5; padding: 1px 5px; border-radius: 3px; }}
  .opt {{ display: inline-flex; align-items: center; gap: 3px; margin-right: 8px;
          font-size: 11px; }}
  footer {{ font-size: 11px; color: var(--muted); padding: 18px 40px; }}
</style>
</head>
<body>
<header>
  <h1>DEADLINE_EXTRACTOR_QUALITY_1 — L1 Harvest Review</h1>
  <p>Director tick-approval before deploy. Generated {today}. B1 / AI Head B (Build-reviewer).</p>
</header>
<main>

<section class="pane findings">
<h2>Findings — acceptance results</h2>
<div class="summary">
  <div class="tile"><div class="label">Dismissed-25 dropped</div><div class="count">{a['dismissed_25_drops']}/{a['dismissed_25_total']}</div></div>
  <div class="tile"><div class="label">Recent-50 dropped</div><div class="count">{a['recent_50_drops']}/50</div></div>
  <div class="tile"><div class="label">Recent-50 false-pos</div><div class="count">{a['recent_50_false_positives']}/{a['recent_50_drops']}</div></div>
  <div class="tile muted"><div class="label">Target FP rate</div><div class="count">≤10%</div></div>
</div>
<p style="margin-top:14px;font-size:13px;">
  <strong>Single leak (intentional):</strong> {escape(a['dismissed_25_only_leak'])} —
  cold-outreach from a real human; would require sender-level (not domain-level) blocking.
  Recommended: leave as-is, rely on Director Scan triage.
</p>
</section>

<section class="pane">
<h2>L1 — domain-pattern blocklist ({len(BLOCK_DOMAIN_PATTERNS)} patterns)</h2>
<p style="font-size:12px;color:var(--muted);">
  Each pattern is matched (regex .match) against the domain part of <code>sender_email</code>.
  Whitelist takes precedence — patterns won't fire on whitelisted domains.
</p>
<table>
<thead><tr><th>Regex pattern</th><th>Director tick</th></tr></thead>
<tbody>
{pat_rows}
</tbody>
</table>
</section>

<section class="pane">
<h2>L1 — local-part prefix blocklist ({len(BLOCK_SENDER_PREFIXES)} prefixes)</h2>
<p style="font-size:12px;color:var(--muted);">
  Match against the part before the @, lowercased. Bulk-mail conventions —
  <code>noreply@*</code>, <code>marketing@*</code>, etc.
</p>
<table>
<thead><tr><th>Local-part prefix</th><th>Director tick</th></tr></thead>
<tbody>
{prefix_rows}
</tbody>
</table>
</section>

<section class="pane">
<h2>Whitelist — domain-level overrides ({len(WHITELIST_DOMAINS)} domains)</h2>
<p style="font-size:12px;color:var(--muted);">
  Whitelisted domains (and any subdomain) bypass both L1 and L2. Curated from
  VIP register + transactional vendors.
</p>
<table>
<thead><tr><th>Whitelisted domain</th><th>Director tick</th></tr></thead>
<tbody>
{wl_rows}
</tbody>
</table>
</section>

<section class="pane">
<h2>Harvested senders — anchor data (25 dismissed Cat 6 deadlines)</h2>
<table>
<thead><tr><th>Sender email</th><th>Display name</th><th>Reason</th></tr></thead>
<tbody>
{harvest_rows}
</tbody>
</table>
</section>

<section class="pane">
<h2>L2 — keyword scorer thresholds</h2>
<p style="font-size:13px;">
  L2 runs only when L1 doesn't hit. Thresholds:
  <code>DROP ≥ {DROP_THRESHOLD}</code>,
  <code>DOWNGRADE ≥ {DOWNGRADE_THRESHOLD}</code>.
  Each promo regex contributes its weight once per email; signal-negators
  (capital call, loan repayment, court / hearing, contract / signature) subtract.
</p>
</section>

</main>
<footer>
  Drafted by AI Head B, harvested + replayed by B1. Reply with "OK" to deploy as-is,
  or strike specific patterns / prefixes / whitelist entries above. Audit log
  (<code>deadline_extractor_suppressions</code>) captures every drop +
  downgrade for first-30-day Director review per brief §11 risk register.
</footer>
</body>
</html>
"""


def main() -> int:
    dropbox_inbox = Path.home() / "Vallen Dropbox" / "Dimitry vallen" / "_01_INBOX_FROM_CLAUDE"
    out_path: Path
    if dropbox_inbox.is_dir():
        out_path = dropbox_inbox / f"{date.today().isoformat()}-l1-harvest-review.html"
    else:
        out_path = REPO_ROOT / "outputs" / f"{date.today().isoformat()}-l1-harvest-review.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"[INFO] Dropbox _01_INBOX_FROM_CLAUDE not found.\n"
            f"       Emitted to repo fallback: {out_path}\n"
            f"       Move manually to Director's Triaga inbox.",
            file=sys.stderr,
        )

    out_path.write_text(render_html(), encoding="utf-8")
    print(f"[OK] L1 harvest review HTML written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
