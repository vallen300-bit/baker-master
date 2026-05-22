---
status: pending
brief: briefs/BRIEF_MD_SCHEME_ALLOWLIST_1.md
brief_id: MD_SCHEME_ALLOWLIST_1
target_repo: baker-master
working_dir: ~/bm-b3
working_branch: b3/md-scheme-allowlist-1
matter_slug: baker-internal
dispatched_at: 2026-05-22T17:30:00Z
dispatched_by: lead
target: b3
reply_to: lead
deadline: 2026-05-23T18:00:00Z
priority: tier-b
director_auth: 2026-05-22 chat — "go" on §X batch-ratification (Group B item 1)
severity_anchor: MEDIUM XSS finding from prior gate-2 + deputy review
prior_mailbox_state: superseded — previous CODE_3_PENDING.md was PLAUD_TRANSCRIPT_BY_MATTER_1 shipped (PR #242 squash-merged fcade01 2026-05-22T13:36Z). b3 idle since.
gate_chain:
  gate_1_static: REQUIRED (AH1 fires feature-dev:code-reviewer)
  gate_2_security_review: REQUIRED (security hardening brief — must run /security-review)
  gate_3_cross_lane_architecture: SKIPPABLE (no architecture change — pure input sanitization on existing helper)
  gate_4_2nd_pass_code_reviewer: REQUIRED per SKILL.md §Code-reviewer 2nd-pass criteria 4 (external-surface — dashboard rendering) + 7 (high-stakes judgment — XSS class)
estimated_effort: 1.5-2h
ui_surface_prebrief: completed at brief authoring time (brief §Surface contract block satisfies)
---

# CODE_3_PENDING — MD_SCHEME_ALLOWLIST_1 — 2026-05-22

**Brief:** `briefs/BRIEF_MD_SCHEME_ALLOWLIST_1.md` (commit `0d9482a` on main, PR #244 merged)
**Working branch:** `b3/md-scheme-allowlist-1` (off origin/main in baker-master)
**Target repo:** `baker-master` — clone at `~/bm-b3/`.
**Pre-requisites:** none.

## Bottom line

`md()` markdown-to-HTML converter at `outputs/static/app.js:567` and `outputs/static/mobile.js:238` renders `[text](url)` into `<a href="$2">` without validating url scheme. `javascript:`, `data:`, `file:`, `vbscript:` schemes pass through esc() (which escapes HTML entities but not URL schemes) and execute on click. Add scheme allowlist; reject non-allowed schemes to inert `#`.

Apply same fix in both files; symmetric implementation.

## Pre-flight

1. `cd ~/bm-b3 && git fetch origin main && git checkout main && git pull --ff-only origin main`
2. Confirm `briefs/BRIEF_MD_SCHEME_ALLOWLIST_1.md` exists at HEAD.
3. `git checkout -b b3/md-scheme-allowlist-1`

## Implementation

Read full brief at `~/bm-b3/briefs/BRIEF_MD_SCHEME_ALLOWLIST_1.md` for spec.

Suggested helper (placement: top of `md()` body in both files, before the link regex):

```javascript
function _safeHref(url) {
    if (!url) return '#';
    const trimmed = url.trim();
    if (trimmed.startsWith('#') || trimmed.startsWith('/') || trimmed.startsWith('?')) return trimmed;
    const schemeMatch = trimmed.match(/^([a-zA-Z][a-zA-Z0-9+\-.]*):/);
    if (!schemeMatch) return trimmed;
    const scheme = schemeMatch[1].toLowerCase();
    if (scheme === 'https' || scheme === 'http' || scheme === 'mailto' || scheme === 'tel') return trimmed;
    return '#';
}
```

Then update the link regex (in both files):

```javascript
h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
    return '<a href="' + _safeHref(url) + '" target="_blank" rel="noopener">' + label + '</a>';
});
```

## Acceptance criteria

Per brief §Acceptance criteria — AC1 (allowlist enforced) + AC2 (symmetric) + AC3 (allow path tested) + AC4 (reject path tested) + AC5 (edge cases tested) + AC6 (code comment documenting esc() interaction) + AC7 (no regression).

## Open question — STOP gate

None. Brief is complete.

## Ship gate

- Literal `pytest` green; PR description includes pytest stdout
- `bash scripts/check_singletons.sh` exits 0
- /security-review pass / NO_FINDINGS — REQUIRED gate before merge

## Reporting (bus reply-to-sender)

On PR open, bus-post `lead` per `dispatched_by`:

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/md-scheme-allowlist-1 — PR #<N> open in baker-master; both md() implementations patched + symmetric; <X> new tests in test_md_scheme_allowlist.py; pytest <Y/Y>; awaiting gate chain (gates 1+2+4 required; 3 skippable)." \
  ship/md-scheme-allowlist-1
```

## Heartbeat cadence (per §B-code stall chase)

Minimum every 12h while actively building. Two consecutive 12h misses → `lead` auto-surfaces stall to Director. Given ~1.5-2h scope, expect single completion event.
