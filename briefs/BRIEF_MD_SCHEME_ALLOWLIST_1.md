---
brief_id: MD_SCHEME_ALLOWLIST_1
authored_by: lead (AH1-Terminal)
authored_at: 2026-05-22T17:20:00Z
matter_slug: baker-internal
target_repo: baker-master
priority: tier-b
tier: B
director_ratified: 2026-05-22 chat — "go" on §X batch-ratification (Group B item 1)
reply_to: lead
severity_anchor: MEDIUM finding (gate-2 + deputy on prior PR review)
---

# BRIEF_MD_SCHEME_ALLOWLIST_1

## Bottom line

The `md()` markdown-to-HTML converter in `outputs/static/app.js:567` and `outputs/static/mobile.js:238` extracts the URL from `[text](url)` markdown into an `<a href="$2">` without validating the URL scheme. A malicious markdown like `[click](javascript:alert(1))` renders as `<a href="javascript:alert(1)" ...>` — clicking executes attacker-controlled JS in the dashboard origin.

`esc()` is called on the input before regex replacements; it escapes HTML entities but does NOT sanitize URL schemes. The HTML-entity escape leaves `javascript:alert(1)` as-is in the href, and the browser treats it as a navigation that runs the script.

Fix: add a scheme allowlist. Permit `https:`, `http:`, `mailto:`, `tel:`, and relative URLs (`/`, `#`, `?`). Reject `javascript:`, `data:`, `file:`, `vbscript:`. Reject malformed / empty URLs. Apply the same fix in both files.

## Context

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** click a link inside dashboard-rendered markdown to navigate (EXISTING behavior). This brief restricts which click destinations are rendered — `javascript:` becomes inert / replaced with `#`.
2. **Backend route:** N/A — client-side rendering of server-supplied markdown content. md() is invoked across many panels (Cortex synth output, Director DMs, dossier rendering, etc.).
3. **Endpoint contract:** N/A — client-side helper function.
4. **State location:** N/A — md() reads its input as a JavaScript string argument from various server-supplied payloads. No state shape change.
5. **UI repo (= state repo):** `baker-master` — `outputs/static/app.js` (desktop dashboard) + `outputs/static/mobile.js` (mobile UI). Surface: dashboard + mobile.
6. **Director surface preference:** N/A — security hardening on existing surface, not a new surface choice.
7. **Gate-1+2 reviewer instruction:** "Reviewers MUST manually exercise rejection by rendering `[evil](javascript:alert(1))` through md() in a test (or DevTools console) and confirming the produced `<a>` has a safe href (e.g. `#` or `about:blank`). Code-shape review (regex matches, etc.) is necessary but NOT sufficient — verify the rejection branch actually fires."

## Director ratification

2026-05-22 chat — "go" on §X batch-ratification, Group B item 1. Concept ratified by Director; AH1 owns implementation design.

## Scope

**In scope:**
- `outputs/static/app.js` — patch the regex-replace for `[text](url)` to validate `url` scheme before href insertion.
- `outputs/static/mobile.js` — same patch applied symmetrically.
- New test: `tests/test_md_scheme_allowlist.py` (or extend existing test if one exists) — exercise allow + reject schemes.

**Out of scope:**
- Other XSS surfaces (image src, iframe, etc.) — not introduced by md(), out of scope for this brief.
- Server-side markdown rendering (e.g. dossier HTML at `outputs/dashboard.py:11842`) — same issue may exist there; flagged as candidate follow-up brief, NOT in this scope.

## Acceptance criteria

**AC1 — Scheme allowlist enforced in both files.**
md() in both `outputs/static/app.js` and `outputs/static/mobile.js` rejects URLs whose scheme is not in the allowlist. Allowlist: `https:`, `http:`, `mailto:`, `tel:`. Relative URLs (starting with `/`, `#`, `?`, or no scheme at all) are allowed. Anything else → rendered href becomes `#` (safe inert).

**AC2 — Implementation symmetric.**
Same allowlist + same rejection behavior in both files. Reviewer must verify the two implementations match (diff the relevant block); no drift.

**AC3 — Allow path tested.**
Unit test confirms allow schemes render correctly:
- `[link](https://example.com)` → `<a href="https://example.com" ...>link</a>`
- `[mail](mailto:foo@bar.com)` → `<a href="mailto:foo@bar.com" ...>mail</a>`
- `[anchor](#section)` → `<a href="#section" ...>anchor</a>`
- `[relative](/api/foo)` → `<a href="/api/foo" ...>relative</a>`

**AC4 — Reject path tested.**
Unit test confirms reject schemes render as inert `#`:
- `[evil](javascript:alert(1))` → `<a href="#" ...>evil</a>`
- `[data](data:text/html,<script>alert(1)</script>)` → `<a href="#" ...>data</a>`
- `[file](file:///etc/passwd)` → `<a href="#" ...>file</a>`
- `[vb](vbscript:msgbox(1))` → `<a href="#" ...>vb</a>`

**AC5 — Edge cases tested.**
- Mixed-case scheme: `[evil](JaVaScRiPt:alert(1))` → rejected (case-insensitive match).
- Whitespace prefix: `[evil]( javascript:alert(1))` → rejected (trim before scheme check).
- Unicode/encoded scheme: `[evil](javascript&#58;alert(1))` — rendered after esc() which already escapes the `:` → no longer matches `javascript:`. Test that this still produces a safe href (either rejected by URL parsing or rendered with encoded `:` which the browser does not interpret as a scheme).

**AC6 — esc() interaction documented.**
Code comment near the link regex documents that esc() runs FIRST (escapes HTML entities) but does NOT sanitize schemes — the allowlist is the second layer. Future maintainers should not remove either.

**AC7 — No regression in existing tests.**
Full `pytest` green. No existing snapshot tests of md() output broken (if any). If existing test asserts that `[evil](javascript:alert(1))` renders the dangerous href, update the test to assert the new safe behavior.

## Implementation notes

Suggested helper (placement: top of md() body, before the link regex):

```javascript
function _safeHref(url) {
    // Allow: https, http, mailto, tel, relative URLs (#, /, ?, or no scheme)
    // Reject: javascript, data, file, vbscript, anything else with a scheme
    if (!url) return '#';
    const trimmed = url.trim();
    // Relative URL: no scheme prefix
    if (trimmed.startsWith('#') || trimmed.startsWith('/') || trimmed.startsWith('?')) return trimmed;
    const schemeMatch = trimmed.match(/^([a-zA-Z][a-zA-Z0-9+\-.]*):/);
    if (!schemeMatch) return trimmed;  // no scheme → relative
    const scheme = schemeMatch[1].toLowerCase();
    if (scheme === 'https' || scheme === 'http' || scheme === 'mailto' || scheme === 'tel') return trimmed;
    return '#';  // reject
}
```

Then update the link regex:

```javascript
// Before:
h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

// After:
h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
    return '<a href="' + _safeHref(url) + '" target="_blank" rel="noopener">' + label + '</a>';
});
```

Note: `_safeHref` output is used as an HTML attribute value. Existing `esc()` already escaped `&<>"'` in the input; the regex captured the post-escape string. Quote characters in the URL would already be escaped by esc(). Trust the existing entity-escape for attribute safety; this brief only adds scheme validation.

## Test plan

New file: `tests/test_md_scheme_allowlist.py` — pytest-based (use jsdom or pyppeteer if needed, OR write tests that exercise the regex+function directly via subprocess node call OR via reading the file and asserting the new regex pattern is present).

Simplest pattern (no JS test runtime needed):
- Read the file content via Python.
- Assert: the link replacement no longer uses `'$2'` as a literal substitution.
- Assert: `_safeHref` function exists in both files.
- (Optional) integration test via `playwright` if already available.

If the team prefers a real JS test: use a minimal node-based test (no full jsdom) that loads the function definitions and asserts behavior. Document choice in PR.

## Ship gate

- Literal `pytest` green; PR description includes pytest stdout.
- Bash command runs clean: `bash scripts/check_singletons.sh`
- /security-review on the PR — pass / NO_FINDINGS (security hardening — should be quick clear).
- NO "pass by inspection."

## Gate-1 + Gate-2 reviewer instructions

Reviewers MUST manually exercise the rejection path. Either:
(a) Open the deployed dashboard in DevTools, paste `md('[evil](javascript:alert(1))')` into the console, and verify the produced HTML has `href="#"`.
(b) Read the new unit tests and confirm they cover the AC3-AC5 rejection cases AND the assertions are meaningful (not stub assertions).

Code-shape review (regex correctness, helper placement) is necessary but NOT sufficient — verify the rejection branch actually fires for at least one of the dangerous schemes.

## Reporting

Bus-post `lead` on PR open. Reply target per `dispatched_by` field in mailbox UPDATE.

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/md-scheme-allowlist-1 — PR #<N> open in baker-master; both md() implementations patched + symmetric; <X> new tests in test_md_scheme_allowlist.py; pytest <Y/Y>; awaiting gate chain (gates 1+2 required; 3+4 skippable for sec-hardening only)." \
  ship/md-scheme-allowlist-1
```
