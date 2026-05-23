---
status: changes_requested
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
director_auth: 2026-05-22 chat — "go" on §X batch-ratification (Group B item 1); V0.2 fold within same auth scope
severity_anchor: MEDIUM XSS finding (V0.1) elevated to CRITICAL XSS bypasses on V0.2 (Gate 4)
v01_pr: 246
v01_shipped_at: 2026-05-23T10:28Z
v01_gate_status:
  gate_1_static: PASS-WITH-NITS (feature-dev:code-reviewer agent a9772c0724454efe2)
  gate_2_security_review: deferred to V0.2
  gate_3_cross_lane_architecture: SKIPPED (no arch change)
  gate_4_2nd_pass_code_reviewer: FAIL (feature-dev:code-reviewer agent a6f4a89af61548ef8) — 2 CRITICAL + 1 HIGH
v02_required_fixes_count: 4 blocking (2 CRIT + 2 HIGH) + 1 MED + 3 LOW optional
v02_dispatched_at: 2026-05-23T10:35:00Z
gate_chain:
  gate_1_static: RE-RUN required on V0.2
  gate_2_security_review: RE-RUN required on V0.2 (deferred from V0.1)
  gate_3_cross_lane_architecture: SKIPPABLE (no arch change)
  gate_4_2nd_pass_code_reviewer: RE-RUN required on V0.2
estimated_effort_v02: 1-1.5h
ui_surface_prebrief: brief's §Surface contract already satisfies; no re-run needed
---

# CODE_3_PENDING — MD_SCHEME_ALLOWLIST_1 — V0.2 fold dispatch — 2026-05-23

**V0.1 PR:** #246 (https://github.com/vallen300-bit/baker-master/pull/246) — REQUEST_CHANGES posted as comment 4525074080.
**Working branch:** `b3/md-scheme-allowlist-1` (continue on same branch — DO NOT branch new).
**Target repo:** `baker-master` — clone at `~/bm-b3/`.

## Bottom line

Gate 4 (2nd-pass) found **2 CRITICAL XSS bypasses + 1 HIGH redirect** that V0.1 + b3's /security-review missed. Gate 1 found 1 HIGH (embedded whitespace bypass). 4 blocking findings + 1 MEDIUM + 3 LOW optional. Push V0.2 on same branch (additional commits, not force-rewrite); on V0.2 push AH1-T re-fires gate chain.

## Blocking findings (MUST fix in V0.2)

### CRITICAL 1 — `javascript%3Aalert(1)` percent-encoded scheme bypass

Files: `outputs/static/app.js` + `outputs/static/mobile.js`, `_safeHref()`

`esc()` does NOT encode `%`. URL `javascript%3Aalert(1)` has no literal `:` so scheme regex `/^([a-zA-Z][a-zA-Z0-9+\-.]*):/` fails to match → function returns string verbatim. Browser URL-decodes href attribute values before navigation (HTML/URL spec §4.1) → `%3A` → `:` at click time → `javascript:alert(1)` executes.

**FIX (choose one):**
```javascript
// Option A: decode before scheme check
const trimmed = url.trim().replace(/[\t\n\r]/g, '');
let decoded;
try { decoded = decodeURIComponent(trimmed); } catch { decoded = trimmed; }
// then run scheme regex against `decoded`, not `trimmed`

// Option B: explicit reject of percent-encoded delimiter
if (/^[a-zA-Z][a-zA-Z0-9+\-.]*%3[Aa]/.test(trimmed)) return '#';
// then proceed with existing check on `trimmed`
```

Recommendation: Option A (decode-first) — closer to actual browser behavior, catches future percent-encoded delimiters too. Wrap `decodeURIComponent` in try/catch (malformed `%XX` throws).

### CRITICAL 2 — `"` in URL breaks href attribute (attribute injection / XSS)

Files: `outputs/static/app.js` link callback + `outputs/static/mobile.js` symmetric

`esc()` (DOM `textContent`-based) encodes `<`, `>`, `&` but NOT `"`. Link regex `([^)]+)` allows `"` in URL capture. URL `https://x.com"onclick=alert(1)//` passes `_safeHref` (https allowlisted) → output `<a href="https://x.com"onclick=alert(1)//" ...>` — `"` terminates attribute, injects arbitrary HTML.

**FIX:** Use the existing `escAttr()` helper (already in `app.js` near top — review it for mobile.js parity; if missing in mobile.js, lift the function or use `.replace(/"/g, '&quot;')`).

```javascript
// In the link replacement callback:
h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
    return '<a href="' + escAttr(_safeHref(url)) + '" target="_blank" rel="noopener">' + label + '</a>';
});
```

If `escAttr` does not exist in mobile.js, define it inline (consistent with the app.js helper) or apply minimal `.replace(/"/g, '&quot;')` after `_safeHref()`.

### HIGH 1 — `//evil.com` protocol-relative URL bypass

Files: `outputs/static/app.js` + `outputs/static/mobile.js`, `_safeHref()`

`trimmed.startsWith('/')` passes `//evil.com/malicious` as "relative" path. Browsers treat `//host/path` as scheme-relative (inherits https from page context) → external navigation. With `target="_blank"` → phishing / open-redirect vector.

**FIX:**
```javascript
if (trimmed.startsWith('#') || trimmed.startsWith('?')) return trimmed;
if (trimmed.startsWith('/') && !trimmed.startsWith('//')) return trimmed;
// (and the `//` URL now falls through to the scheme regex, which won't match `//` so returns `'#'`)
```

### HIGH 2 — embedded `\t`/`\n`/`\r` bypass

Files: `outputs/static/app.js` + `outputs/static/mobile.js`, `_safeHref()`

`.trim()` strips edges only, not embedded whitespace. `java\tscript:alert(1)` → scheme regex `[a-zA-Z][a-zA-Z0-9+\-.]*` does not match `\t` so regex fails → returns verbatim. Browsers strip `\t\n\r` during href URL parsing (WHATWG URL spec §4.1) → `javascript:alert(1)` reconstituted at click.

**FIX:** combined with CRITICAL 1 Option A:
```javascript
const trimmed = url.trim().replace(/[\t\n\r]/g, '');
```

## MEDIUM — Node test harness can't simulate browser URL-decode

File: `tests/test_md_scheme_allowlist.py`

`_run_node_harness()` runs `_safeHref` source in Node.js — no browser URL-decoding behavior. Tests for `javascript%3Aalert(1)` would pass in Node, fail in browser (false confidence).

**FIX:**
- Add explicit `[%3A](javascript%3Aalert(1))` to REJECT_CASES (V0.2 must REJECT after CRITICAL 1 fix).
- Add `[tab](java\tscript:alert(1))` and `[newline](java\nscript:alert(1))` to REJECT_CASES (HIGH 2 coverage).
- Add `[//attacker](//evil.com/malicious)` to REJECT_CASES (HIGH 1 coverage).
- Add `[quote](https://x.com"onclick=alert(1)//)` to REJECT_CASES (CRITICAL 2 coverage — assertion: `'onclick=' not in out` AND `'"' encoded as &quot;` in href).
- Add code comment in test file noting Node-vs-browser parity gap; ideally Playwright/headless follow-up (NOT in scope this brief).

## LOW (optional, may fold for hygiene)

- `test_safehref_comment_documents_esc_interaction` uses arbitrary 600-char preamble check — brittle to refactor. Tighten to scoped search.
- `_extract_safehref_block` regex requires `\n}\n` trailing newline — fragile on file-end. Use `\n}(?:\s|$)` pattern.
- `test_functional_empty_input` doesn't assert whitespace-only inputs (`" "`, `"   "`) return `"#"`. Add assertions.

## V0.2 ship gate

- ALL 4 blocking findings fixed.
- ALL 5 new test cases added (2 CRIT + 2 HIGH + 1 sentinel-doc) — assertions must be meaningful (verify actual rejection-to-`#`, not stub `assert True`).
- Targeted pytest still 100% pass; full suite delta vs baseline acceptable (PR description quotes literal output).
- `_safeHref` blocks in both files remain byte-identical (re-verify `test_implementations_are_symmetric`).
- /security-review on V0.2 — pass / NO_FINDINGS REQUIRED (b3 self-run; AH1 re-runs gate 2 independently).

## Reporting

On V0.2 push, bus-post `lead` per `dispatched_by`:

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/md-scheme-allowlist-1-v02 — V0.2 pushed on b3/md-scheme-allowlist-1; all 4 blocking findings folded + 5 new test cases; targeted pytest <X/X>; full suite delta <Y>; awaiting AH1 gate chain re-run (gates 1+2+4)." \
  ship/md-scheme-allowlist-1-v02
```

## Director ratification (carry-over)

2026-05-22 "go" on §X batch-ratification (Group B item 1) covers V0.1 dispatch + gate chain authority + V0.2 fold within same auth. No re-ratification needed for V0.2.

## Heartbeat cadence

Minimum every 12h while actively building. ~1-1.5h scope expected to complete V0.2 in single session.
