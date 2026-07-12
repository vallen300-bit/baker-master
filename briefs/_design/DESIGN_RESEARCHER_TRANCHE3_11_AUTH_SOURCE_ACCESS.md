---
title: DESIGN — Researcher Tranche-3 #11 Authenticated-source access
item: "#11 (researcher-capability-extension-brief @22ab300)"
author: b2
date: 2026-07-12
status: DESIGN CLEARED (codex #9391 CHANGES incorporated) — building to this spec
dispatch: deputy #9337 (Director order via lead #9334)
discipline: additive read-only cage amendment (NOT "untouched" — codex F3) · design-verified with codex · build -> codex build-gate -> lead merge · no self-merge
---

> **CODEX DESIGN-VERIFY (#9391) — LOCKED DECISIONS incorporated below:**
> - **F1 HIGH:** Lane A must ENFORCE, not advise. The wrapper DRIVES the authenticated
>   read internally via CDP against the running port-9222 Chrome; it never merely
>   "emits a URL" for the researcher to navigate. (§3 rewritten.)
> - **F2/Q4:** `RESEARCHER_BASH_CAGE_ENFORCE=1` is LIVE (settings.json:3). Build + test
>   assume ENFORCE-on. WARN is not acceptable for this feature.
> - **F3:** This is an **additive exact-path read-only cage amendment** (adds one vetted
>   path to `IS_VETTED`), not "cages untouched". Framed honestly; no deny relaxed.
> - **Q1:** wrapper-drives-CDP read; real URL parser; https-only; exact/suffix host
>   allow-list; reject userinfo + non-web schemes; verify FINAL post-redirect host before
>   extraction.
> - **Q2:** additive read-only amendment acceptable under the gate; still route via lead
>   PR merge, no self-ship.
> - **Q3:** baked script constant for the allow-list (no researcher-writable config).

# #11 Authenticated-source access — DESIGN (pre-build, for codex design-verify)

## 1. Problem

Researcher hits `402`/anti-bot login walls on paywalled specs + journals (IEEE, ACM DL,
SSRN full-text, Nature/Springer, standards portals) via `WebFetch`. `method.md:32` already
records "Auth-walled URLs return 402; use Chrome MCP instead" — but there is no vetted,
domain-bounded, read-only path that actually delivers logged-in content, so deep-dives
silently degrade to abstract-only.

## 2. Hard constraints (from the researcher cage — must be preserved)

- **Chrome WRITE verbs are HARD-DENIED** for the researcher: `mcp__chrome__*` /
  `mcp__Claude_in_Chrome__*` `fill`, `fill_form`, `click`, `type_text`, `press_key`,
  `drag`, `upload_file`, `handle_dialog` (`~/bm-researcher/.claude/settings.json:90-105`).
  **The researcher therefore CANNOT enter credentials** — this is the credential-exfil
  guard and it stays.
- Chrome **READ** verbs are allowed: `navigate_page`, `take_snapshot`, `evaluate_script`.
- **Bash cage** = exact-canonical-path allow-list of vetted scripts under
  `~/bm-b1/scripts/` etc. (`researcher_bash_cage.sh:170-202`); no raw `curl`/`python`/`gh`,
  no command-substitution/redirects. A new capability script must live at a pinned
  absolute path OUTSIDE `wiki/research/` and be added to the `IS_VETTED` case.
- **Write cage**: researcher writes ONLY to `baker-vault/wiki/research/**` + its session
  memory (`researcher_write_cage.sh:52-53`). Unchanged.
- **Lethal-trifecta split** (P1 closure): no send/write MCP verbs, no self-edit of
  orientation/method, no arbitrary shell. Every part of this design is read-only.

## 3. Design — read-the-logged-in-profile, never log in

The port-9222 debug Chrome (`chrome-debug-recovery.md`) runs a persistent profile
(`~/.chrome-debug-profile/`) whose **cookies already carry the Director's logged-in
sessions**. Authenticated access = **read the already-authenticated DOM**, with the
credential living only in the browser profile — it never touches the researcher.

Two lanes, ranked:

### Lane A (primary) — vetted wrapper DRIVES a cookie-authenticated CDP read (ENFORCED)
The single enforced entry point is a vetted, cage-trusted script
**`~/bm-b1/scripts/auth_source_fetch.sh <url>`**. Like `read_message.sh`/`check_inbox.sh`,
it is cage-trusted so it may use `python3` internally; the researcher never drives Chrome
for this feature (structural enforcement, not method discipline — codex F1/Q1).

The script (all internal, no researcher discretion between validate and extract):
1. **Parse the URL with a real parser** (`urllib.parse`), enforce: **https-only**;
   **no userinfo** (`user:pass@`); host resolves to the **pinned allow-list**
   `AUTH_SOURCE_DOMAINS` (baked constant, NOT researcher-writable — codex Q3) by
   **exact or dotted-suffix** match (`arxiv.org` / `*.arxiv.org`); reject any other
   scheme/host ⇒ non-zero exit + `domain_not_allowlisted`. This kills the prompt-injected
   "read evil.com cookies" vector structurally.
2. **Drive the running port-9222 Chrome over CDP** (the profile that already holds the
   Director's logins): discover a target via `GET http://127.0.0.1:9222/json`, open a
   fresh tab, `Page.navigate` to the validated URL, wait for load, then
   `Runtime.evaluate('document.body.innerText')`. **No `fill`/`click`/`type` — no
   credential entry.** Cookie auth on the profile renders full text.
3. **Verify the FINAL post-redirect host** (`document.location.host` from CDP) against the
   same allow-list BEFORE returning any text (codex Q1) — a redirect off-allow-list ⇒
   discard + non-zero exit. Close the tab.
4. Print extracted text to stdout; log the request (url + verdict) to the cage log. Never
   accepts credentials; never writes outside stdout + the cage log.

### Lane B (fallback) — trusted-actor pre-cache for interactive/JS-heavy walls
When a source needs a fresh interactive login or step-up auth (Bloomberg, Refinitiv,
some journal SSO), a **trusted actor** (Director or a b-code, out of band) logs into the
9222 profile ONCE and/or saves the rendered doc into an allowlisted cache
(`/tmp/research-*/` per `open_report.sh:34-89` roots). The researcher reads the cached
artifact via the existing `open_report.sh` race-free reader. Credential entry stays with
the trusted actor; the researcher only reads the artifact.

## 4. Deliverables (when codex clears this design → build)

1. **`~/bm-b1/scripts/auth_source_fetch.sh`** — domain-allow-list guard + audit log +
   URL-contract emitter (Lane A). Mirrors `read_message.sh`/`check_inbox.sh` lineage:
   `set -euo pipefail`, hard-pinned constants, no arg-driven exec, numeric/URL-only args.
2. **Cage allow-list entry** for that exact path in `researcher_bash_cage.sh` `IS_VETTED`
   case (this is a cage edit — but an *additive allow-list of a new vetted read-only
   script*, NOT a relaxation of any existing deny; flag explicitly for codex whether this
   counts as "cage untouched" or needs a lead sign-off beyond the codex gate).
3. **`method.md` channel-table row** (routed via lead/codex, NOT researcher self-edit):
   "Authenticated sources — `auth_source_fetch.sh` + Chrome READ verbs, domain-gated".
4. **Domain allow-list** seeded with the standards/journal hosts above; extension is a
   lead-approved edit to the script constant.
5. Tests: allow-listed host passes; non-allowlisted host rejected; `../`/scheme-abuse
   rejected; no-arg/multi-arg rejected. (Shellcheck + a bats-style or pytest harness
   matching however the existing vetted scripts are tested.)

## 5. Open questions for codex design-verify

- **Q1 — enforcement strength.** Lane A wrapper-emits-URL + method discipline (light,
  but relies on the researcher then using read verbs correctly) vs wrapper-drives-a-
  headless-read (strong, but puts curl/headless-Chrome inside the cage-trusted script).
  Which does codex want as the shipped enforcement?
- **Q2 — cage edit classification.** Adding one vetted read-only script to the
  `IS_VETTED` allow-list — is that inside "cages UNTOUCHED" (additive, no deny relaxed),
  or does it require an explicit lead ratification beyond the codex gate?
- **Q3 — domain allow-list location.** Baked constant in the script (my default, keeps it
  in the cage-trusted file) vs a separate pinned config the script reads.
- **Q4 — ENFORCE posture.** Bash cage currently ships WARN (codex #6559). Does #11 assume
  ENFORCE-on for the domain guard to matter, or is WARN acceptable at first ship?

## 6. What this design explicitly does NOT do

- No `fill`/`click`/`type_text` — no credential entry by the researcher.
- No write outside `wiki/research/**` + session memory + the cage audit log.
- No new send/write MCP verb ungated.
- No self-edit of orientation/method by the researcher (method row routes via lead/codex).
