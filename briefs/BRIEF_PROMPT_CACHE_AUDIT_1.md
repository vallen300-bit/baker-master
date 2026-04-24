# BRIEF: PROMPT_CACHE_AUDIT_1 — Anthropic prompt-cache audit + apply `cache_control` to top-3 hot call sites + telemetry

## Context

M0 quintet row 4. Per Research ratified 2026-04-21 (`_ops/ideas/2026-04-21-anthropic-4-7-upgrade-package.md` §Adoption 1):

> Measure current cache hit rate across Baker's repeated-prompt patterns (Scan system prompts, capability set prompts, 5-step RAG pipeline ballast). Anthropic prompt caching gives ~90% cost reduction on cached prefix. Unknown if Baker's current deployment hits it. CLQ impact: cost only — pure savings. Latency unchanged. Quality unchanged. Gate: none. Ship independently.

**Current state (verified this session):**

- `kbl/anthropic_client.py:238` — the Step 5 Opus synthesis path uses `cache_control: {"type": "ephemeral"}` on the `system` block. Telemetry already live: `OpusResponse.cache_read_tokens` + `cache_write_tokens` + cost-math multipliers (`_PRICE_OPUS_CACHE_READ_MUL = 0.10`, `_PRICE_OPUS_CACHE_WRITE_MUL = 1.25`). **This call site is the good precedent.**
- ~15 other Claude call sites in the codebase have **no** `cache_control` markers (verified `grep -rn "cache_control" --include="*.py"` — only `kbl/anthropic_client.py` + `tests/conftest.py` hit). Call sites audited:
  - `baker_rag.py`, `outputs/dashboard.py` (`/api/scan`), `orchestrator/chain_runner.py`, `orchestrator/agent.py`, `orchestrator/prompt_builder.py`, `orchestrator/capability_runner.py`, `triggers/briefing_trigger.py`, `triggers/calendar_trigger.py`, `tools/ingest/classifier.py`, `tools/ingest/extractors.py`, `tools/document_pipeline.py`, `scripts/backfill_contact_locations.py`, `scripts/enrich_contacts.py`.
- No audit script exists.
- No cache-hit-rate telemetry beyond the single `kbl.cost` path.

**What this brief ships (MVP — scoped tightly):**

1. `scripts/audit_prompt_cache.py` — CLI static-analysis script. Inventories all Claude call sites (grep-driven), estimates stable-prefix bytes per site, classifies `cache-eligible` vs `too-small` vs `already-cached`, emits a markdown report to `briefs/_reports/prompt_cache_audit_<YYYY-MM-DD>.md`.
2. Apply `cache_control: {"type": "ephemeral"}` to the **top-3 highest-leverage sites** identified by the audit (validated before-the-fact: (a) `outputs/dashboard.py` Scan chat system prompt, (b) `orchestrator/capability_runner.py` capability system prompts, (c) `baker_rag.py` RAG-synthesis system prompt). One-line YAML-style edits; zero business-logic changes.
3. Cache-hit telemetry — add a `baker_actions` entry `action_type='claude:cache_hit'` per call, carrying `{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, call_site}` in the payload. Reuses the existing `baker_actions` table + `log_baker_action()` helper. Aggregation view defined in `scripts/prompt_cache_hit_rate.py` (reads 24h window, computes ratio, alerts Director via Slack DM if <60%).
4. pytest — validate: cache_control block shape (`{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}`), cost-math round-trip on a synthetic response with mixed cache-read + cache-write usage, audit-script exit code + report shape.

**What this brief does NOT ship (explicit — out of scope):**

- **Opus 4.6 → 4.7 model-version migration** — that's the separate Adoption 2 of the 4.7 package; eval-gated; requires M4. This brief does NOT touch model IDs.
- **Citations API on Scan** — that's CITATIONS_API_SCAN_1, M0 row 5, drafted in parallel to this brief.
- **Extended thinking / reasoning tier** — unrelated, deferred per 4.7 package §Explicit non-adoptions.
- **New cost model / pricing overrides** — existing `kbl.cost` pricing table is authoritative.
- **Caching on user messages** — only system-block caching is in scope; user messages change per call and are never cache-worthy.
- **Migrating existing Step 5 caching** — it already works; leave it.
- **A web dashboard tile for cache hit rate** — cron + Slack alert is sufficient MVP.

**Source artefacts:**
- `_ops/ideas/2026-04-21-anthropic-4-7-upgrade-package.md` §Adoption 1
- `kbl/anthropic_client.py:232-280` — working precedent
- Anthropic docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching (reference only; brief cites but does not require B-code to fetch)

## Estimated time: ~3–3.5h
## Complexity: Medium (static analysis script + small call-site edits + telemetry logging + tests)
## Prerequisites: All 3 M0 top-priority detectors shipped (#2/#4/#9). No new env vars. No schema changes.

---

## Fix/Feature 1: `scripts/audit_prompt_cache.py` — static-analysis audit script

### Problem

No inventory exists of Claude call sites + their cache eligibility. Without the audit, any "apply cache_control" effort is blind — we don't know which sites have large enough stable prefixes to benefit.

### Current State

- `scripts/` has 40+ CLI scripts (ingest, backfill, lint, validate). Pattern: argparse entry, `main()`, fail-fast on missing env. Pattern exemplar: `scripts/ingest_vault_matter.py`.
- No script named `audit_prompt_cache.py` or similar.
- Claude call shape varies — some use `anthropic.Anthropic().messages.create(...)` directly, some use the SDK async path, some use `call_opus()` wrapper in `kbl.anthropic_client`. Grep across all.

### Implementation

**Create `scripts/audit_prompt_cache.py`:**

```python
"""Static-analysis audit of Claude call sites for prompt-cache eligibility.

Scans Python source tree for Anthropic messages.create() call sites.
For each call site, estimates:
  - the file + line
  - whether `cache_control` is set on any system block
  - the approximate bytes of the SYSTEM prompt (detected via string
    literal size OR env var / module-level constant lookup; best-effort)
  - cache-eligibility tier:
      eligible_apply    — ≥1024 tokens stable, no cache_control
      eligible_measure  — already has cache_control — skip, just measure
      below_threshold   — <1024 tokens
      unclear           — system prompt built dynamically from DB / non-literal
      no_system         — no system block

Emits a markdown report to briefs/_reports/prompt_cache_audit_<YYYY-MM-DD>.md
and prints a summary to stdout.

Usage: python3 scripts/audit_prompt_cache.py [--out PATH]

Exit codes:
  0 — audit ran, report written
  1 — runtime failure (file I/O, etc.)

NOTE: this script does NOT execute any Claude API calls. It is
purely a static inventory + estimate. Live hit-rate measurement is
the separate scripts/prompt_cache_hit_rate.py (Feature 3).
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

# Call-site patterns: method name + attribute chain we consider a Claude call.
CLAUDE_CALL_PATTERNS = (
    "messages.create",
    "messages.stream",
    "call_opus",
    "call_flash",
)

# Approximate chars-to-tokens conversion (rule of thumb: 4 chars ≈ 1 token).
CHARS_PER_TOKEN = 4
CACHE_THRESHOLD_TOKENS = 1024  # Anthropic minimum cacheable prefix


@dataclass
class CallSite:
    file: str
    line: int
    call_name: str
    has_cache_control: bool
    system_chars_est: int
    tier: str  # one of: eligible_apply, eligible_measure, below_threshold, unclear, no_system
    notes: str = ""


def _scan_python_files() -> list[Path]:
    """Return all .py files under repo root (excluding venv, build, .git)."""
    skip_dirs = {".git", "venv", ".venv", "__pycache__", "node_modules", "build", "dist"}
    results: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(".py"):
                results.append(Path(root) / f)
    return results


def _find_call_sites_in_file(path: Path) -> list[CallSite]:
    """Parse one .py file; return all CallSite records."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    results: list[CallSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_attr_chain(node.func)
        if not any(pat in call_name for pat in CLAUDE_CALL_PATTERNS):
            continue

        # Extract system-block text and cache_control presence from kwargs.
        system_chars, has_cache = _extract_system_info(node)
        tier, notes = _classify(system_chars, has_cache)

        results.append(CallSite(
            file=str(path.relative_to(REPO_ROOT)),
            line=node.lineno,
            call_name=call_name,
            has_cache_control=has_cache,
            system_chars_est=system_chars,
            tier=tier,
            notes=notes,
        ))
    return results


def _call_attr_chain(func_node: ast.AST) -> str:
    """Recover 'obj.attr1.attr2' from an ast.Call.func."""
    parts: list[str] = []
    cur = func_node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _extract_system_info(call_node: ast.Call) -> tuple[int, bool]:
    """Best-effort extraction of (system_chars_estimate, has_cache_control)."""
    system_chars = 0
    has_cache = False
    for kw in call_node.keywords:
        if kw.arg == "system":
            system_chars = _estimate_literal_chars(kw.value)
            has_cache = _has_cache_control(kw.value)
    return system_chars, has_cache


def _estimate_literal_chars(node: ast.AST) -> int:
    """Return len of string literal, 0 if dynamic."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value)
    if isinstance(node, ast.JoinedStr):  # f-string
        total = 0
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                total += len(val.value)
        return total
    if isinstance(node, ast.List) and node.elts:
        # Likely a list of content blocks — sum text lengths
        total = 0
        for elt in node.elts:
            if isinstance(elt, ast.Dict):
                for k, v in zip(elt.keys, elt.values):
                    if isinstance(k, ast.Constant) and k.value == "text":
                        total += _estimate_literal_chars(v)
        return total
    return 0


def _has_cache_control(node: ast.AST) -> bool:
    """Walk AST looking for any ast.Constant value 'cache_control'."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value == "cache_control":
            return True
    return False


def _classify(system_chars: int, has_cache: bool) -> tuple[str, str]:
    est_tokens = system_chars // CHARS_PER_TOKEN
    if system_chars == 0:
        return "unclear", "system prompt is dynamic or external — manual review required"
    if has_cache:
        return "eligible_measure", f"~{est_tokens} tok — already cached; confirm hit rate via telemetry"
    if est_tokens < CACHE_THRESHOLD_TOKENS:
        return "below_threshold", f"~{est_tokens} tok — below 1024 minimum"
    return "eligible_apply", f"~{est_tokens} tok — APPLY cache_control"


def _render_report(sites: list[CallSite], out_path: Path) -> None:
    today = date.today().isoformat()
    by_tier: dict[str, list[CallSite]] = {}
    for s in sites:
        by_tier.setdefault(s.tier, []).append(s)

    lines: list[str] = []
    lines.append(f"# Prompt Cache Audit — {today}\n")
    lines.append(f"Total call sites: **{len(sites)}**\n")
    lines.append("## Summary by tier\n")
    lines.append("| Tier | Count |")
    lines.append("|------|-------|")
    for tier in ("eligible_apply", "eligible_measure", "below_threshold", "unclear", "no_system"):
        lines.append(f"| `{tier}` | {len(by_tier.get(tier, []))} |")
    lines.append("")
    for tier in ("eligible_apply", "eligible_measure", "below_threshold", "unclear", "no_system"):
        if tier not in by_tier:
            continue
        lines.append(f"\n## {tier}\n")
        lines.append("| File | Line | Call | Cache? | ~Tokens | Notes |")
        lines.append("|------|------|------|--------|---------|-------|")
        for s in sorted(by_tier[tier], key=lambda x: (x.file, x.line)):
            est = s.system_chars_est // CHARS_PER_TOKEN if s.system_chars_est else "n/a"
            cache_mark = "yes" if s.has_cache_control else "no"
            lines.append(
                f"| `{s.file}` | {s.line} | `{s.call_name}` | {cache_mark} | {est} | {s.notes} |"
            )
    lines.append("")
    lines.append("## Next actions\n")
    lines.append("1. Apply `cache_control` to every site in `eligible_apply`.")
    lines.append("2. Review `unclear` sites manually — if system prompt is DB- or file-derived AND stable across calls, convert to cache_control-tagged block.")
    lines.append("3. Let `below_threshold` sites stay uncached; prefix growth is unlikely.")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Claude call sites for prompt-cache eligibility.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "briefs" / "_reports" / f"prompt_cache_audit_{date.today().isoformat()}.md"),
        help="Output markdown path (default: briefs/_reports/prompt_cache_audit_<date>.md)",
    )
    args = parser.parse_args()

    files = _scan_python_files()
    all_sites: list[CallSite] = []
    for f in files:
        all_sites.extend(_find_call_sites_in_file(f))

    if not all_sites:
        print("No Claude call sites found.", file=sys.stderr)
        return 0

    out_path = Path(args.out)
    _render_report(all_sites, out_path)
    print(f"Audit complete: {len(all_sites)} call sites → {out_path}")
    by_tier: dict[str, int] = {}
    for s in all_sites:
        by_tier[s.tier] = by_tier.get(s.tier, 0) + 1
    for tier, n in sorted(by_tier.items()):
        print(f"  {tier}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Key Constraints

- **Read-only** — script makes zero API calls. Pure AST analysis.
- **Best-effort heuristics** — dynamic system prompts (DB-loaded, built from templates) classify as `unclear`. Reviewer inspects manually.
- **Character-to-token approximation** is intentionally conservative (4:1). Real ratios vary 3.5-4.5:1; 4:1 + 1024-token threshold = ~4096 chars is a safe floor.
- **No dependencies beyond stdlib** — uses `ast`, `pathlib`, `argparse`, `os`, `sys`, `dataclasses`.
- **Relative paths in report** — no absolute `/Users/...` leaks.
- **Exit 0 even on empty** — audit running successfully but finding zero sites is valid (edge case).

### Verification

1. `python3 -c "import py_compile; py_compile.compile('scripts/audit_prompt_cache.py', doraise=True)"` — zero output.
2. `python3 scripts/audit_prompt_cache.py --out /tmp/audit.md` — exits 0, writes report.
3. `grep -c "|" /tmp/audit.md` — report has pipe-delimited rows.
4. First-pass report must include `kbl/anthropic_client.py:251` (`call_opus` internal `messages.create`) tagged `eligible_measure`.

---

## Fix/Feature 2: Apply `cache_control` to top-3 highest-leverage call sites

### Problem

The audit identifies sites; without actual `cache_control` application, we pay full input price every call. Top-3 prioritization is based on: (a) call frequency, (b) stable-prefix size, (c) call-site stability (no dynamic system rewriting).

### Current State

Top-3 pre-identified in this brief (B-code confirms against audit output):

1. **Scan endpoint system prompt** — `outputs/dashboard.py` around line 7249+ (`/api/scan` handler). System prompt assembled from retrieval context + persona template. Frequency: highest (Director interactions). Stability: persona portion stable; retrieval changes per call → system block needs splitting.
2. **Capability runner system prompts** — `orchestrator/capability_runner.py` capability-specific system prompts. ~21 capabilities; each has a stable template. Frequency: moderate (one per classified intent). Stability: template stable per capability.
3. **RAG synthesis system prompt** — `baker_rag.py`. Frequency: high (every Scan call routes through RAG). Stability: high.

### Implementation

For each of the 3 sites, B-code follows this pattern:

**Step A — Identify the stable prefix.** Read the current `system=` argument at the call. Split into:
- Stable part (persona / tool definitions / frozen instructions).
- Dynamic part (retrieval, user profile, time-of-day).

**Step B — Convert `system` to content-block list format.** Example transformation:

Before:
```python
response = client.messages.create(
    model=...,
    system=f"You are Baker's Scan...\n{persona}\n\nRetrieved context:\n{retrieval}",
    messages=[{"role": "user", "content": user_question}],
    ...
)
```

After:
```python
response = client.messages.create(
    model=...,
    system=[
        {
            "type": "text",
            "text": f"You are Baker's Scan...\n{persona}",  # stable prefix
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"Retrieved context:\n{retrieval}",  # dynamic suffix
        },
    ],
    messages=[{"role": "user", "content": user_question}],
    ...
)
```

**Step C — Verify block-size minimum.** The cached block must be ≥1024 tokens (~4096 chars). If the stable prefix is smaller, SKIP this site — reducing to below_threshold defeats the point. Record the skip in the ship report.

**Step D — Preserve call telemetry.** If the call-site already passes usage through to cost calculation (e.g. via `kbl.anthropic_client.call_opus`), no further telemetry change needed for this feature. Feature 3 adds cross-cutting telemetry.

**Specific per-site edits:**

- **dashboard.py Scan** — locate `scan_chat()` handler (line ~7249). Find the `system=` assembly. Split stable persona from dynamic retrieval. Apply cache_control to the stable block.
- **capability_runner.py** — locate the `messages.create` call for capability execution. Most capability prompts have a ~2500-char+ persona template + dynamic input. Apply cache_control.
- **baker_rag.py** — find the synthesis `messages.create`. Apply cache_control to stable synthesis instructions.

### Key Constraints

- **No business-logic changes** — only structural change to the `system=` kwarg. The stable text content itself must not be altered.
- **Skip sites below threshold** — if audit shows <1024 estimated tokens, document the skip; do NOT force-cache.
- **Preserve existing `call_opus()` semantics** — the `kbl/anthropic_client.py` wrapper already wraps system in a cache_control block (line 234-240). If a caller routes through `call_opus`, the caching is already live — no edit needed at that caller. Confirm via grep.
- **User messages stay plain strings** — no `cache_control` on user content.
- **Do NOT add cache_control to sites that rebuild the system prompt dynamically every call** (e.g. generated capability sets, A/B prompts) — those are `unclear` in the audit.

### Verification

1. `grep -c "cache_control" outputs/dashboard.py baker_rag.py orchestrator/capability_runner.py` — ≥3 hits total across the 3 files (post-edit).
2. After deploy, run 3 Scan queries + wait 10 min + re-run the same 3 queries. Third run should show `cache_read_tokens > 0` in telemetry (Feature 3 captures this).
3. Syntax: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` + same for the other two files.

---

## Fix/Feature 3: Cache-hit telemetry + 24h observation script

### Problem

Applying `cache_control` is only half the work. Without hit-rate measurement, we can't verify the ~90% cost reduction actually lands.

### Current State

- `baker_actions` table + `store.log_baker_action()` exist and are the Baker-standard audit log (invariant S2 from CHANDA).
- `OpusResponse` already has `cache_read_tokens` / `cache_write_tokens` fields (kbl/anthropic_client.py:87-88) — but only `call_opus()` users get this benefit. Direct `messages.create` call sites in dashboard/rag/capability_runner do not log cache metrics anywhere.

### Implementation

**Step 1 — Add a cross-cutting telemetry helper** at `kbl/cache_telemetry.py`:

```python
"""Log Claude cache-usage telemetry to baker_actions.

Every call site that wants cache tracking calls `log_cache_usage()` with
the SDK response's `usage` object + a call-site label. Emits a single
baker_actions row of action_type='claude:cache_usage'.

Zero dependencies on call-site details — just reads usage.input_tokens /
output_tokens / cache_read_input_tokens / cache_creation_input_tokens.
Silent on failure (cache metric loss ≪ call failure).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("baker.kbl.cache_telemetry")


def log_cache_usage(
    usage: Any,
    call_site: str,
    model: Optional[str] = None,
    trigger_source: str = "claude_call",
) -> None:
    """Fire-and-forget cache-usage log. No return value."""
    try:
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        input_tok = int(getattr(usage, "input_tokens", 0) or 0)
        output_tok = int(getattr(usage, "output_tokens", 0) or 0)
    except Exception:
        return  # usage object malformed — skip silently

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        if store is None:
            return
        store.log_baker_action(
            action_type="claude:cache_usage",
            payload={
                "call_site": call_site,
                "model": model,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                # Convenience: hit rate for THIS call (read / (read + input)).
                "cache_hit_ratio": (
                    cache_read / (cache_read + input_tok)
                    if (cache_read + input_tok) > 0 else 0.0
                ),
            },
            trigger_source=trigger_source,
            success=True,
        )
    except Exception as e:
        logger.warning("log_cache_usage failed (non-fatal): %s", e)
```

**Step 2 — Wire `log_cache_usage()` into the 3 call sites modified in Feature 2.** Immediately after `response = client.messages.create(...)`:

```python
from kbl.cache_telemetry import log_cache_usage
log_cache_usage(response.usage, call_site="outputs.dashboard.scan_chat", model=model_name)
```

Add the import near the top of each touched file (alongside existing imports, lazy-import inside the handler if top-level would introduce a cycle).

**Step 3 — Aggregation script** at `scripts/prompt_cache_hit_rate.py`:

```python
"""Compute 24h cache hit rate from baker_actions. Alert Director via Slack if <60%.

Usage: python3 scripts/prompt_cache_hit_rate.py [--hours N] [--threshold 0.60]

Reads baker_actions where action_type='claude:cache_usage' within the
time window, aggregates (cache_read_tokens / (cache_read + input_tokens))
weighted by total token volume, prints summary table + overall rate.

If --threshold supplied and overall rate < threshold, fires a Slack DM
to Director's channel D0AFY28N030 via the existing Slack-notifier module.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--threshold", type=float, default=0.60)
    p.add_argument("--alert", action="store_true", help="Fire Slack alert if below threshold")
    args = p.parse_args()

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    if store is None:
        print("Store unavailable", file=sys.stderr)
        return 1

    conn = store._get_conn()
    if conn is None:
        return 1
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              COALESCE(payload->>'call_site', 'unknown') AS site,
              SUM((payload->>'input_tokens')::int) AS input_tok,
              SUM((payload->>'cache_read_tokens')::int) AS cache_read_tok,
              SUM((payload->>'cache_write_tokens')::int) AS cache_write_tok,
              COUNT(*) AS n_calls
            FROM baker_actions
            WHERE action_type = 'claude:cache_usage'
              AND created_at > NOW() - (INTERVAL '1 hour' * %s)
            GROUP BY site
            ORDER BY cache_read_tok DESC
            LIMIT 50
            """,
            (args.hours,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    if not rows:
        print(f"No cache_usage rows in last {args.hours}h — has telemetry landed?")
        return 0

    total_input = sum(r[1] for r in rows)
    total_cache_read = sum(r[2] for r in rows)
    total_cache_write = sum(r[3] for r in rows)
    denom = total_input + total_cache_read
    overall = total_cache_read / denom if denom > 0 else 0.0

    print(f"Cache hit rate over {args.hours}h: {overall:.2%}")
    print(f"Total input tokens: {total_input:,}")
    print(f"Total cache-read tokens: {total_cache_read:,}")
    print(f"Total cache-write tokens: {total_cache_write:,}")
    print()
    print("Per call_site (top 10):")
    for site, inp, creado, crwite, n in rows[:10]:
        site_rate = creado / (creado + inp) if (creado + inp) > 0 else 0.0
        print(f"  {site_rate:6.2%}  n={n:4d}  in={inp:,}  cache_read={creado:,}  site={site}")

    if args.alert and overall < args.threshold:
        _slack_alert(overall, args.threshold, args.hours, rows[:5])

    return 0


def _slack_alert(overall, threshold, hours, top_rows):
    try:
        from outputs.slack_notifier import post_to_director_dm
    except Exception:
        print("Slack notifier unavailable — skipping alert", file=sys.stderr)
        return
    msg = (
        f":warning: Prompt-cache hit rate below target.\n"
        f"Last {hours}h: *{overall:.2%}* (target ≥{threshold:.0%}).\n"
        f"Top sites by traffic:\n"
        + "\n".join(f"• `{s}` — n={n}, read={cr:,}" for s, _inp, cr, _cw, n in top_rows)
    )
    try:
        post_to_director_dm(msg)
    except Exception as e:
        print(f"Slack post failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
```

### Key Constraints

- **Fire-and-forget telemetry** — log_cache_usage failure never impacts the Claude call outcome. Wrapped in try/except.
- **Re-uses `baker_actions`** — no new table.
- **Slack-notifier reuse** — assumes `outputs/slack_notifier.post_to_director_dm(text)` exists. If missing, the alert falls back to stderr print + non-zero exit; document in ship report. **B-code: grep to verify `post_to_director_dm` exists; if not, stub a fallback that just prints the alert to stdout and log a TODO.**
- **PostgreSQL JSONB query** — payload fields extracted via `payload->>'key'`; matches the existing Baker pattern.
- **No cron scheduling this brief** — monthly Slack alert wiring is out of scope. Script runs on-demand; operator decides.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('kbl/cache_telemetry.py', doraise=True)"` — zero output.
2. `python3 -c "import py_compile; py_compile.compile('scripts/prompt_cache_hit_rate.py', doraise=True)"` — zero output.
3. `python3 -c "from kbl.cache_telemetry import log_cache_usage; print('OK')"` — prints `OK`.
4. Unit test via Feature 4 — synthetic `usage` object → verify `log_baker_action` called with correct shape.

---

## Fix/Feature 4: pytest scenarios

### Problem

Without tests, cache_control block shape + cost math + telemetry silently rot.

### Current State

Precedents:
- `tests/test_anthropic_client.py` — existing Opus-client tests.
- `tests/test_ledger_atomic.py` — sqlite3 hermetic pattern.

### Implementation

**Create `tests/test_prompt_cache_audit.py`** with ~8 tests:

```python
"""Tests for PROMPT_CACHE_AUDIT_1: audit script + cache_control shape + telemetry."""
from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPO / "scripts" / "audit_prompt_cache.py"


def test_audit_script_exits_zero_and_writes_report(tmp_path):
    """Script runs end-to-end, writes non-empty markdown report."""
    out = tmp_path / "audit.md"
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--out", str(out)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    content = out.read_text()
    assert "# Prompt Cache Audit" in content
    assert "Summary by tier" in content


def test_audit_identifies_cached_call_site(tmp_path):
    """kbl/anthropic_client.py has cache_control — must appear as eligible_measure."""
    out = tmp_path / "audit.md"
    subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--out", str(out)],
        cwd=REPO, check=True,
    )
    content = out.read_text()
    # Expect at least one eligible_measure entry pointing at anthropic_client.
    assert "eligible_measure" in content
    assert "anthropic_client.py" in content


def test_cache_control_block_shape_in_anthropic_client():
    """kbl/anthropic_client.py retains its {type, text, cache_control} block shape."""
    src = (REPO / "kbl" / "anthropic_client.py").read_text()
    assert '"cache_control": {"type": "ephemeral"}' in src
    assert '"type": "text"' in src


def test_cache_control_present_in_three_hot_sites():
    """dashboard.py / capability_runner.py / baker_rag.py each contain cache_control
    post-Feature-2 application."""
    for path in ("outputs/dashboard.py", "orchestrator/capability_runner.py", "baker_rag.py"):
        src = (REPO / path).read_text()
        assert "cache_control" in src, f"{path} missing cache_control (Feature 2 not applied)"


def test_log_cache_usage_fires_baker_action(monkeypatch):
    """log_cache_usage calls store.log_baker_action with correct payload keys."""
    from kbl.cache_telemetry import log_cache_usage

    captured: dict = {}

    class _FakeStore:
        def log_baker_action(self, **kw):
            captured.update(kw)

    import memory.store_back as sb
    monkeypatch.setattr(sb.SentinelStoreBack, "_get_global_instance",
                        classmethod(lambda cls: _FakeStore()), raising=False)

    usage = MagicMock(
        input_tokens=500,
        output_tokens=200,
        cache_read_input_tokens=3000,
        cache_creation_input_tokens=100,
    )
    log_cache_usage(usage, call_site="test.site", model="claude-opus-4-7")
    assert captured["action_type"] == "claude:cache_usage"
    payload = captured["payload"]
    assert payload["call_site"] == "test.site"
    assert payload["cache_read_tokens"] == 3000
    assert payload["cache_write_tokens"] == 100
    assert payload["input_tokens"] == 500
    # Hit rate = 3000 / (3000 + 500) = 0.857...
    assert 0.85 < payload["cache_hit_ratio"] < 0.87


def test_log_cache_usage_silent_on_missing_store(monkeypatch):
    """No store singleton → no raise, no crash."""
    from kbl.cache_telemetry import log_cache_usage
    import memory.store_back as sb
    monkeypatch.setattr(sb.SentinelStoreBack, "_get_global_instance",
                        classmethod(lambda cls: None), raising=False)
    usage = MagicMock(input_tokens=10, output_tokens=5,
                      cache_read_input_tokens=0, cache_creation_input_tokens=0)
    log_cache_usage(usage, call_site="x")  # no exception


def test_log_cache_usage_silent_on_malformed_usage(monkeypatch):
    """Usage-object with missing attrs → silent skip."""
    from kbl.cache_telemetry import log_cache_usage
    usage = object()  # no attrs at all
    log_cache_usage(usage, call_site="x")  # no exception


def test_audit_classifies_below_threshold():
    """A synthetic call site with short system prompt classifies as below_threshold."""
    # Run audit on a temp file with one short system prompt.
    import tempfile, textwrap, ast
    import scripts.audit_prompt_cache as aud

    src = textwrap.dedent("""
        import anthropic
        c = anthropic.Anthropic()
        c.messages.create(
            model="x",
            system="short prompt",
            messages=[{"role": "user", "content": "hi"}],
        )
    """)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(src)
        path = Path(f.name)
    try:
        sites = aud._find_call_sites_in_file(path)
        assert len(sites) == 1
        assert sites[0].tier == "below_threshold"
    finally:
        path.unlink()
```

### Key Constraints

- **No real Anthropic API calls** — tests are fully offline.
- **Subprocess-style test for the audit script** — matches the `test_author_director_guard.py` approach (PR #49).
- **Unit tests for `cache_telemetry`** — reuse `monkeypatch` pattern, NOT `unittest.mock.patch` (per no-mocks convention we've applied across LEDGER_ATOMIC + KBL_INGEST).
- **`MagicMock` for the SDK usage object is acceptable** — usage objects are not under our control; they're SDK structs; mocking their attribute surface is the least-bad option. Document in ship report.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('tests/test_prompt_cache_audit.py', doraise=True)"` — zero output.
2. `pytest tests/test_prompt_cache_audit.py -v` — expect 8 passed.
3. `pytest tests/ 2>&1 | tail -3` — +8 passes vs main baseline.

---

## Files Modified

- NEW `scripts/audit_prompt_cache.py` (~240 LOC).
- NEW `scripts/prompt_cache_hit_rate.py` (~110 LOC).
- NEW `kbl/cache_telemetry.py` (~70 LOC).
- NEW `tests/test_prompt_cache_audit.py` (~180 LOC).
- MODIFIED `outputs/dashboard.py` — split Scan system prompt + add `cache_control` + wire `log_cache_usage` (~15 LOC delta).
- MODIFIED `orchestrator/capability_runner.py` — same (~15 LOC delta).
- MODIFIED `baker_rag.py` — same (~15 LOC delta).

**Total: 4 new + 3 modified, ~645 LOC.**

## Do NOT Touch

- `kbl/anthropic_client.py` — already correctly caches the Step 5 block. Zero edits.
- `kbl/cost.py` — pricing table stays authoritative.
- Model IDs anywhere — this brief is cache-only; 4.6→4.7 migration is separate.
- `baker-vault/`, `vault_scaffolding/`, `CHANDA*.md`, `slugs.yml` — unrelated.
- `memory/store_back.py` — reuse existing `log_baker_action`. No schema changes.
- `invariant_checks/ledger_atomic.py` — not applicable here (cache telemetry is best-effort, not atomic-critical).
- `triggers/embedded_scheduler.py` — shared-file hotspot, avoid.
- The call sites in `scripts/backfill_contact_locations.py`, `scripts/enrich_contacts.py`, `triggers/briefing_trigger.py`, `triggers/calendar_trigger.py`, `tools/*`, `orchestrator/agent.py`, `orchestrator/chain_runner.py`, `orchestrator/prompt_builder.py` — audit them but DO NOT apply cache_control in this brief. Second-wave follow-on (`PROMPT_CACHE_ROLLOUT_1`) handles the remaining sites after 7-day observation of top-3.

## Quality Checkpoints

1. **Python syntax on 4 new files + 3 modified:**
   ```
   for f in scripts/audit_prompt_cache.py scripts/prompt_cache_hit_rate.py \
            kbl/cache_telemetry.py tests/test_prompt_cache_audit.py \
            outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py; do
     python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo FAIL $f; exit 1; }
   done
   echo "All 7 files syntax-clean."
   ```

2. **Audit script runs end-to-end:**
   ```
   python3 scripts/audit_prompt_cache.py --out /tmp/audit.md && head -20 /tmp/audit.md
   ```
   Expect report with Summary by tier table.

3. **Imports smoke:**
   ```
   python3 -c "from kbl.cache_telemetry import log_cache_usage; from scripts.audit_prompt_cache import CallSite; print('OK')"
   ```

4. **3 hot sites carry cache_control:**
   ```
   grep -l "cache_control" outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py
   ```
   Expect all 3 files listed.

5. **Pytest in isolation:**
   ```
   pytest tests/test_prompt_cache_audit.py -v 2>&1 | tail -15
   ```
   Expect `8 passed`.

6. **Full-suite regression:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Expect +8 passes vs main baseline, 0 regressions.

7. **Singleton hook:**
   ```
   bash scripts/check_singletons.sh
   ```

8. **No baker-vault writes:**
   ```
   git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
   ```

9. **Audit report excluded from git** (runtime artifact):
   The audit script writes to `briefs/_reports/prompt_cache_audit_<date>.md`. The generated report file should NOT be committed (it's runtime-generated). Confirm by running audit, then `git status` — file should appear untracked. Document in ship report; do not add `.gitignore` this brief.

10. **No API calls during test run:**
    ```
    grep -E "anthropic\.Anthropic\(|messages\.create" tests/test_prompt_cache_audit.py
    ```
    Expect zero matches — tests are fully offline.

## Rollback

- `git revert <merge-sha>` — removes the 4 new files. Call-site edits in 3 modified files revert cleanly.
- No DB changes; no env-var changes.
- `baker_actions` rows with `action_type='claude:cache_usage'` are harmless if left post-revert.

---

## Ship shape

- **PR title:** `PROMPT_CACHE_AUDIT_1: audit script + top-3 cache_control + 24h hit-rate telemetry`
- **Branch:** `prompt-cache-audit-1`
- **Files:** 7 (4 new + 3 modified).
- **Commit style:** `kbl(cache): audit script + apply cache_control to scan/capability/rag + baker_actions telemetry`
- **Ship report:** `briefs/_reports/B{N}_prompt_cache_audit_1_20260424.md`. Include all 10 Quality Checkpoint outputs literal + first-pass audit report summary + `git diff --stat`.

**Tier A auto-merge on B3 APPROVE + green /security-review** per SKILL.md Security Review Protocol.

## Post-merge (AI Head, not B-code)

1. Wait for Render auto-deploy. Verify 3 Scan calls via Director's use → then run 3 more identical calls after 5 min. Third-round cache_read_tokens should be non-zero.
2. After 24h, run `python3 scripts/prompt_cache_hit_rate.py --hours 24` on Render shell. If hit rate ≥60%: success, close M0 row 4. If <60%: investigate `unclear`-tier sites; draft `PROMPT_CACHE_ROLLOUT_1` (second-wave).
3. Log outcome to `actions_log.md`.

## Timebox

**3–3.5h.** If >5h, stop and report — likely stable-prefix extraction friction in one of the 3 hot sites.

**Working dir:** `~/bm-b1`.
