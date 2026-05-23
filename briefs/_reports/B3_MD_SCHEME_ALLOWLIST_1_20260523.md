---
brief_id: MD_SCHEME_ALLOWLIST_1
builder: b3
shipped_at: 2026-05-23T10:28:34Z
pr: 246
branch: b3/md-scheme-allowlist-1
target_repo: baker-master
matter_slug: baker-internal
severity_anchor: MEDIUM XSS finding
gate_chain_status:
  gate_1_static: PENDING (AH1 to fire feature-dev:code-reviewer)
  gate_2_security_review: PASS — NO_FINDINGS at confidence>=8 (B3 ran in-line)
  gate_3_cross_lane_architecture: SKIPPABLE (no architecture change)
  gate_4_2nd_pass_code_reviewer: PENDING (external-surface + XSS class)
reply_to: lead
bus_message_id: 710
---

# B3 — MD_SCHEME_ALLOWLIST_1 — completion report

## Shipped

PR #246 — `b3/md-scheme-allowlist-1` against `main` in `baker-master`.

Commit `9b59901`: scheme allowlist for `md()` link hrefs in both `outputs/static/app.js` and `outputs/static/mobile.js`. Byte-identical `_safeHref(url)` helper at top of each `md()` body; link regex replaced with a callback that wraps the URL through the helper. Cache-bust bumped (`app.js?v=118→119`, `mobile.js?v=41→42`) per iOS PWA frontend rule.

## Files touched

- `outputs/static/app.js` (+14 / -1) — helper + callback
- `outputs/static/mobile.js` (+14 / -1) — helper + callback
- `outputs/static/index.html` (+1 / -1) — cache-bust
- `outputs/static/mobile.html` (+1 / -1) — cache-bust
- `tests/test_md_scheme_allowlist.py` (+241 / 0) — new

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| AC1 — allowlist enforced | ✅ | `_safeHref` rejects non-allowlist schemes to `'#'` in both files |
| AC2 — symmetric impl | ✅ | `test_implementations_are_symmetric` asserts byte-identical helper block |
| AC3 — allow path tested | ✅ | 7 cases × 2 files via Node-subprocess functional layer |
| AC4 — reject path tested | ✅ | 6 cases (javascript / data / file / vbscript / mixed-case / leading-ws) × 2 files |
| AC5 — edge cases | ✅ | mixed-case + leading-ws + entity-encoded `:` covered |
| AC6 — esc() interaction docs | ✅ | comment above helper documents the two-layer model in both files |
| AC7 — no regression | ✅ (vs baseline) | see "pytest" below — pre-existing flakiness disclosed in PR description |

## Ship gates

- **Targeted pytest:** 15/15 passed in 0.39s
- **Full suite:** 85F / 2241P / 30E / 99 skipped vs baseline 84F / 2227P / 30E / 99. Delta = +14 new passes + 1 unrelated `test_mcp_vault_tools.py` test-ordering flake (passes 41/41 in isolation). My changes do not move the needle.
- **`bash scripts/check_singletons.sh`:** `OK: No singleton violations found.`
- **`/security-review`:** NO_FINDINGS at confidence ≥ 8. Considered + dismissed: control-character bypass of `_safeHref` (modern browsers don't strip leading C0 controls before scheme detection); attribute injection via label/url (`esc()` runs first, entity-encodes `"`); test-harness `node` subprocess (argv-style, no shell, no user input). One non-blocking defense-in-depth note: optional `replace(/[\x00-\x1F\x7F]/g, '')` at `_safeHref` entry.
- **Node parse check:** both edited JS files parse cleanly.

## Bus

- Ack: bus #707 (dispatch from lead) — HTTP 200 at session start
- Ship report: bus #710 (`ship/md-scheme-allowlist-1` → lead)

## Open items for lead

- Gate 1 (static review) — pending AH1 `feature-dev:code-reviewer` run
- Gate 4 (2nd-pass) — pending per SKILL.md §"2nd-pass criteria" 4 (external surface — dashboard rendering) + 7 (high-stakes — XSS class)
- Mailbox `CODE_3_PENDING.md` — overwrite to COMPLETE on merge per `_ops/processes/b-code-dispatch-coordination.md` §3

## Notes for follow-up

Brief §Scope flagged `outputs/dashboard.py:11842` (server-side dossier HTML rendering) as candidate follow-up for the same issue class. Not in this brief's scope; surfaced here for lead triage.
