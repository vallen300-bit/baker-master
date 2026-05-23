# BRIEF: RESEARCHER_VERIFY_CITATIONS_1 — Build verify-citations skill for Researcher picker

## Context

Three hallucination scars across two Brisen agents within five days:
1. **Hag Desk (2026-05-20):** wrote "Brisen sent termination notice 15 March 2026" — wrong party, disputed date, no source.
2. **Researcher (2026-05-22):** fabricated "Stefan Spiegel" as MO VIE GM name (no Baker entry, no LinkedIn URL).
3. **Researcher (2026-05-23):** cited 13-year-old STR data (March 2013 CoStar article) as Feb 2026 figures. The page footer's "© 2026 CoStar Group" matched the claimed year; the article date inside the page was 14 March 2013.

Existing failure modes "stale dates" + "fabricated URLs" are documented in `~/baker-vault/_ops/agents/researcher/method.md` lines 95-118 as text rules — they drift under deadline pressure. Director directive 2026-05-23: convert discipline rules into mandatory tool calls.

External research validates the design:
- **Anthropic Citations API** (https://claude.com/blog/introducing-citations-api): one published customer (Endex) went 10% → 0% source-hallucination rate.
- **Perplexity pattern** (https://ziptie.dev/blog/how-perplexity-ai-answers-work/): citations injected pre-generation as numbered slots; model cannot invent slot 8 if 7 slots passed.
- **Elicit pattern**: model can only name entities present in retrieved records (slot-binding).

This brief is **Phase 2** of a four-component upgrade. Phase 1 (documentation changes to `method.md` + `orientation.md`) is AH1 lane and **must land first**.

## Estimated time: ~3-4h
## Complexity: Medium
## Prerequisites:
- Phase 1 documentation changes landed (citation slot template in `method.md` §8, Step 6.5 added to HOW table, Short Shape selector in Step 0, Baker-first people lookup standing rule in `orientation.md`)
- Brief reader has Bash + WebFetch + Chrome MCP namespaces available

---

## Fix/Feature 1: Build researcher-verify-citations skill

### Problem
Researcher's existing verification step (HOW table Step 6, `method.md:69`) is a text rule: *"Chrome MCP visit any Grok-cited URL before trusting; drop fabricated."* It fires only on Grok URLs and only as a discipline reminder. The three scars above all happened despite this rule existing. The fix: replace the rule with a mandatory skill invocation that produces a per-claim verdict table before the draft is written to file.

### Current State
- **Researcher picker:** `~/bm-researcher/`. Picker CLAUDE.md at `~/bm-researcher/CLAUDE.md`.
- **Researcher orientation:** `~/baker-vault/_ops/agents/researcher/orientation.md` (179 lines).
- **Researcher method:** `~/baker-vault/_ops/agents/researcher/method.md` (130 lines, includes existing failure-mode table 95-118).
- **HOW table:** `method.md:60-74`, 12 steps from "Brief intake" to "Paste-block to AH1".
- **Existing skills in researcher picker** (all symlinks to `~/baker-vault/_ops/skills/`): `grok-via-xai-api`, `ui-surface-prebrief`, `whatsapp-send-via-waha`. None for verification.
- **Baker MCP tools available:** `baker_vip_contacts` (search), `baker_upsert_vip` (write), confirmed against `~/bm-aihead1-cowork/.claude/docs/baker-mcp-api.md`.
- **Chrome MCP namespaces present:** `mcp__chrome__*` (DevTools Protocol path) AND `mcp__Claude_in_Chrome__*` (Chrome extension path). Researcher's `method.md:105` documents that tool names differ across these two namespaces.

### Implementation

**Step 1 — Create canonical skill directory + SKILL.md:**

```bash
mkdir -p ~/baker-vault/_ops/skills/researcher-verify-citations
# Then write SKILL.md per shape below
```

**Step 2 — Symlink into researcher picker:**

```bash
ln -s /Users/dimitry/baker-vault/_ops/skills/researcher-verify-citations \
      /Users/dimitry/bm-researcher/.claude/skills/researcher-verify-citations
```

Mirror the pattern already used by `grok-via-xai-api`, `ui-surface-prebrief`, `whatsapp-send-via-waha` in the same picker.

**Step 3 — SKILL.md content (full spec):**

```markdown
---
name: researcher-verify-citations
description: |
  Mandatory pre-output verification skill for Researcher (Brisen multi-source research agent). Runs as Step 6.5 in the 4-tier HOW sequence before file-write. Takes the draft markdown report, extracts every cited URL + claimed publication date + claimed byline + claimed quoted text, refetches each URL via WebFetch (with Chrome MCP auto-escalation on thin content), confirms date/byline/quote actually appear in the fetched content, returns a per-claim verdict table with verdicts: PASS / FAIL_MISMATCH / UNCERTAIN_UNVERIFIABLE / UNCERTAIN_POSSIBLE_WALL.

  MANDATORY TRIGGERS: verify citations, fact-check report, pre-output verify, researcher draft check, citation verification, verify-citations skill, Step 6.5, verify-before-write.

  Use this skill on EVERY researcher draft before writing to wiki/research/. Mandatory on Short Shape (capped at 5 URLs) AND Full Shape (full URL set, ≤5-min batch ceiling). Skip ONLY when Director explicit "skip verify, time-critical".
---

# researcher-verify-citations — V1 skill

You are about to run pre-output verification on a Researcher draft report. This skill is mandatory before writing the final file. Goal: catch hallucinated citations, stale dates, paywalled-as-real sources, and fabricated quotes BEFORE they ship.

## Input contract

Researcher invokes this skill with the draft markdown content. The draft must follow the citation slot template (method.md §8, Phase 1 prerequisite):

```
Claim: <statement>
URL: <https://...>
Pub date: <YYYY-MM-DD or "not visible">
Byline: <name | institutional | not found>
Accessed: <YYYY-MM-DD>
Tier: <primary | secondary | aggregator>
Confidence: <HIGH | MEDIUM | LOW>
[Optional] Quote: "<verbatim snippet>"
```

## Extraction logic

Extract every citation block from the draft. Skip:
- URLs inside fenced code blocks (` ``` ` blocks)
- URLs inside the "Method appendix" section (method-log links — they're audit, not claims)
- URLs in comparison-table cells where the cell is a system-name reference (not a citation block)

For each citation: capture URL, claimed pub_date, claimed byline, claimed quoted text (if present), assigned tier + confidence.

## Refetch logic — per URL

### Step A — WebFetch first (cheap path)
- Call `WebFetch` with the URL.
- If WebFetch returns **< 1500 chars of visible text content** → MANDATORY escalation to Chrome MCP (Step B). Do NOT terminate on thin WebFetch content. SPAs and paywalls both surface this signal.

### Step B — Chrome MCP escalation (when WebFetch is thin OR explicitly required)
- **Detect active Chrome MCP namespace at invocation time:**
  - Try `mcp__chrome__navigate_page` first (DevTools Protocol path, port 9222).
  - On "tool not found" error, fall back to `mcp__Claude_in_Chrome__navigate`.
  - Cache the detected namespace for the rest of the batch (avoid re-detecting per URL).
- Use the corresponding snapshot tool: `mcp__chrome__take_snapshot` OR `mcp__Claude_in_Chrome__get_page_text`.
- **Per-URL hard timeout: 30 seconds.** On timeout → record `Checked: NO (timeout)`. Never PASS.

### Step C — Paywall detection
- After fetch, if content < 800 chars OR contains cookie-consent/subscription keywords ("subscribe", "paywall", "sign in to read", "premium content", "members only") but no detectable article body → record verdict `UNCERTAIN_POSSIBLE_WALL`.
- Do NOT collapse paywall with "fabricated URL" verdict. They have different remediation (paywall → manual Chrome MCP with login; fabricated → drop claim).

### Step D — JS-rendered SPA detection
- If WebFetch returns a shell HTML with `<div id="app"></div>`, `<div id="root"></div>`, or similar with no article text → mandatory Chrome MCP escalation, no exception.

## Date verification — STRICT field priority

Match in this EXACT order. Stop at first match:

1. **`json-ld datePublished`** — look for `<script type="application/ld+json">` blocks containing `"@type":"Article"` with `datePublished` field.
2. **`<meta property="article:published_time">`** — OpenGraph article published time meta tag.
3. **Visible date in article header region** — first 500 chars of visible text after the article's first `<h1>`, OR within byline area, OR within a `<time>` element near the headline.

**Do NOT match on:**
- `dateModified` (would have passed the Feb 2013 STR slip — page had 2026 cookie-consent update)
- Site copyright year (`© 2026 CoStar Group` is footer, not article date)
- URL-embedded year/date (often wrong; can be SEO slugs)
- Visible "Updated:" label without explicit "Published:" alongside

If only `dateModified` or copyright-year matches → verdict `UNCERTAIN_UNVERIFIABLE` with reason "only modified/copyright date found, not original publish date".

**Year-only match** (claimed pub_date year = page year, but no month-level match) → UNCERTAIN. Not PASS.

### Date format handling

The verifier must parse all of:
- ISO 8601: `2026-05-23T...`
- "Month DD, YYYY": `May 23, 2026`
- "DD Month YYYY": `23 May 2026` + German `23. Mai 2026`
- "DD.MM.YYYY": `23.05.2026`
- Russian month names: январь / февраль / март / апрель / май / июнь / июль / август / сентябрь / октябрь / ноябрь / декабрь
- German month names: Januar / Februar / März / April / Mai / Juni / Juli / August / September / Oktober / November / Dezember
- Twitter/X timestamps: `2h ago`, `May 23`, absolute UTC
- YouTube: upload date in description metadata

Unparseable date → record `Date: UNPARSEABLE` + verdict UNCERTAIN.

## Byline verification — SOFT check

PASS if ANY name component (first OR last name) appears within:
- json-ld `author` block (canonical), OR
- `<meta name="author">` tag, OR
- First 200 chars of visible text after the article's first `<h1>` (header region), OR
- Author bio section explicitly tagged (`<a rel="author">`, `<div class="author*">`, etc.)

UNCERTAIN if neither name component appears anywhere on the page.

FAIL_MISMATCH only if a different author is explicitly attributed (rare — e.g., article clearly bylined to "Jane Doe" but claim says "John Smith").

**Defensive patterns:**
- Multi-author bylines (wire copy): pass if any one matches.
- Substring collision: require word-boundary match. "Spiegel" must not match "Der Spiegel" (publication name) — require first OR last name with `\b` boundary.
- Honorific differences: strip "Dr.", "Prof.", "Mr.", "Ms.", "Frau", "Herr", etc., before compare.
- Non-Latin scripts (Cyrillic, Greek, etc.): byline check is best-effort; UNCERTAIN is acceptable.

## Quote verification — when present in claim

Normalize BOTH claim quote and fetched content before compare:
- Smart quotes `"`/`"`/`'`/`'` → straight quotes `"`/`'`
- Em-dash `—` + en-dash `–` → hyphen `-`
- Non-breaking space ` ` → regular space
- Collapse multiple whitespace → single space
- Strip trailing ellipsis `...` or `…`

Compare normalized quote substring against normalized fetched content:
- PASS if normalized quote appears verbatim in normalized fetched content.
- UNCERTAIN if claim quote is a fragment + original is longer (substring match within reasonable window — both endpoints align ≥ 80% overlap).
- FAIL_MISMATCH if claim quote contains words or phrases NOT in fetched content.

**Always report the ORIGINAL (un-normalized) strings in the Reasoning column.** This lets a human spot a real mismatch vs. an encoding artifact.

## Redirect handling

Log BOTH URLs in output:
- `Cited URL: <original from claim>`
- `Resolved URL: <after all 3xx redirects followed>`

If resolved URL has a different domain than cited URL → record verdict `UNCERTAIN` with reason "domain changed on redirect — editorial provenance may differ". Subdomain changes (`www.example.com` ↔ `example.com`) are fine; TLD or apex changes are not.

## Verdict taxonomy (THREE-WAY + paywall subtype)

| Verdict | Meaning | Remediation |
|---|---|---|
| `PASS` | All checks succeeded for this claim | Ship as-is |
| `FAIL_MISMATCH` | Page exists, but date/byline/quote does NOT match claim | Rewrite claim or remove |
| `UNCERTAIN_UNVERIFIABLE` | Page real but key field missing (only dateModified, no quote findable, etc.) | Downgrade Confidence to LOW, mark "UNVERIFIED", or remove |
| `UNCERTAIN_POSSIBLE_WALL` | 200 but thin content + paywall signals | Manual Chrome MCP with login session, OR find alternative source |
| `Checked: NO` | Timeout / bridge drop / unrecoverable error | Retry manually; never PASS without checking |

## Output format

Markdown table appended to the draft. Researcher reads + rewrites/removes failed claims before file write.

```
| # | Cited URL | Resolved URL | Date check | Byline check | Quote check | Verdict | Checked | Reasoning |
|---|---|---|---|---|---|---|---|---|
| 1 | https://anthropic.com/blog/citations | (same) | PASS (json-ld datePublished 2025-06-23) | PASS (visible header) | PASS | PASS | YES | All checks clean |
| 2 | https://costar.com/news/vienna-luxury | (same) | UNCERTAIN_UNVERIFIABLE (only dateModified=2026, no datePublished — page actually dated 2013-03-14 in visible header) | PASS | — | UNCERTAIN_UNVERIFIABLE | YES | Strict priority: dateModified alone insufficient; visible header shows 2013 article date |
| 3 | https://wsj.com/article/xyz | (same) | — | — | — | UNCERTAIN_POSSIBLE_WALL | YES | 200 OK, body 412 chars, contains "Subscribe to continue reading" — paywall suspected |
| 4 | https://twitter.com/user/status/123 | https://x.com/user/status/123 | — | — | — | UNCERTAIN | NO (timeout 30s) | Chrome MCP timeout; x.com 402 anti-bot likely; manual recheck via logged-in session |
```

End with overall summary:
```
**Verification summary:** {N} claims checked, {P} PASS, {F} FAIL_MISMATCH, {U} UNCERTAIN_UNVERIFIABLE, {W} UNCERTAIN_POSSIBLE_WALL, {T} Checked=NO. Batch time: {m}m {s}s.

**Action required:** Researcher must (a) remove or rewrite any FAIL_MISMATCH claims, (b) downgrade any HIGH confidence claim with UNCERTAIN verdict to MEDIUM or remove, (c) manually re-verify any "Checked: NO" entries before ship. **Final report MUST NOT contain HIGH-confidence claims with non-PASS verdicts.**
```

## Batch ceiling — HARD constraints

- **Per-URL timeout: 30 seconds.** Hard cap on each fetch attempt (WebFetch OR Chrome MCP). Single retry allowed within the 30s budget.
- **Batch ceiling: 5 minutes wall-clock total.** On batch timeout: surface partial results with explicit `Checked: NO (batch timeout)` markers on unchecked URLs. Never collapse silently to PASS.
- **Short Shape reports: cap at 5 URLs.** Verify the bottom-line citations only (the load-bearing claims).
- **Full Shape reports: full URL set.** May approach 5-min ceiling; document expected time at invocation.

## Composition

- Calls: `WebFetch`, `mcp__chrome__*` OR `mcp__Claude_in_Chrome__*` (namespace-detected), bash for date normalization.
- Does NOT call: any other skill (no recursion), Baker MCP write tools (read-only), git, external API beyond the cited URLs themselves.
- Does NOT write: to vault, to baker DB, to git.
- Output: markdown table appended to draft. Consumed by Researcher (rewrite-or-remove) and audit-readable by AH1.

## Cost + latency

- Per-URL: ~5-15s WebFetch, ~15-30s Chrome MCP if escalated.
- 5 URLs Short Shape: ~1-3 min batch.
- 10-15 URLs Full Shape: ~3-7 min batch (caps at 5 min).
- API cost: $0. Skill uses already-available tool calls; no extra LLM invocations.

## Failure modes this skill prevents

(Cross-reference `~/baker-vault/_ops/agents/researcher/method.md` failure-mode table lines 95-118)

| Failure mode | How this skill catches it |
|---|---|
| Stale dates cited as current (Feb 2013 STR scar) | Date Step D strict priority rule — `dateModified`/copyright/URL-embedded year do NOT pass |
| Fabricated URLs (Grok-output hallucination) | Refetch confirms page exists; 404 → verdict UNCERTAIN with reason "URL does not resolve" |
| Paywall returning 200 with marketing summary | Paywall detection Step C — thin content + cookie-consent keywords flagged |
| AI Studio silent model fallback | Publication-date check catches mismatched-source citations |
| JS-rendered SPA empty body | Auto-escalation to Chrome MCP when WebFetch < 1500 chars |
| Quote drift (smart quotes, em-dashes) | Normalization before compare; both originals reported for triage |
| Redirect domain change (acquired publication) | Both URLs logged; domain change → UNCERTAIN |
| Chrome bridge drop mid-batch | Per-URL + batch timeouts + explicit `Checked: NO` column |

## What this skill does NOT do

- Does NOT verify Baker-internal claims (matter records, deadlines, VIP entries) — out of scope.
- Does NOT verify person identity for named individuals — covered by Baker-first people lookup standing rule in `orientation.md` (separate Phase 1 doc).
- Does NOT score source tier (primary/secondary/aggregator) — assigned by Researcher at draft time; this skill verifies only that the page exists + claimed date matches.
- Does NOT replace human review on filing-bound or court-bound text — separate AH1 sourcing-pass still required for those.
- Does NOT auto-rewrite claims — outputs verdicts only; Researcher does the rewrite.

## First-use bootstrap

On first invocation after install:
1. Confirm at start: `"researcher-verify-citations V1 loaded — beginning verification of {N} claims."`
2. Run extraction.
3. Run refetch + verification per URL.
4. Emit verdict table.
5. End with action-required summary.
```

### Key Constraints (reviewer's 4 must-haves — must appear in SKILL.md verbatim)

1. **Three-way verdict taxonomy** (PASS / FAIL_MISMATCH / UNCERTAIN_UNVERIFIABLE) plus UNCERTAIN_POSSIBLE_WALL subtype plus explicit `Checked: NO` for timeouts. Do NOT collapse to 2-way pass/fail.

2. **Strict date-field priority** locked: `datePublished` > `article:published_time` > visible header > stop. `dateModified` alone = UNCERTAIN, not PASS. (Would have caught the Feb 2013 STR slip.)

3. **WebFetch < 1500 chars → mandatory Chrome MCP escalation.** Not optional. SPAs + paywalls both surface this signal.

4. **Per-URL 30s timeout + 5-min batch ceiling + explicit "Checked: YES/NO" column.** Partial results never silently collapse to PASS.

### Verification

```bash
# 1. Skill file exists at canonical path:
test -f ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md && echo "OK"

# 2. Symlink resolves from picker:
ls -la ~/bm-researcher/.claude/skills/researcher-verify-citations
readlink ~/bm-researcher/.claude/skills/researcher-verify-citations
# Expected: /Users/dimitry/baker-vault/_ops/skills/researcher-verify-citations

# 3. Frontmatter `name` matches directory name:
head -5 ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md | grep "^name: researcher-verify-citations"

# 4. All 4 hard constraints present in body:
grep -c "FAIL_MISMATCH\|UNCERTAIN_UNVERIFIABLE\|UNCERTAIN_POSSIBLE_WALL" ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md
# Expected: ≥3 hits

grep -c "datePublished.*article:published_time" ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md
# Expected: ≥1

grep -c "1500 chars" ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md
# Expected: ≥1

grep -c "30s\|30 second\|5 min\|5-min" ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md
# Expected: ≥4
```

**Live test (Phase 3, post-Phase-2):**
- Hand the skill a deliberately-broken draft:
  - One PASS claim (current Anthropic blog with verified date)
  - One stale-date trap (a 2013 article cited as 2026)
  - One fabricated URL (typo'd domain that 404s)
  - One paywalled source (e.g., WSJ article)
  - One x.com tweet that may trip 402 anti-bot
- Confirm verdicts: 1 PASS + 1 UNCERTAIN_UNVERIFIABLE + 1 UNCERTAIN (URL fails resolve) + 1 UNCERTAIN_POSSIBLE_WALL + 1 Checked=NO
- Confirm the action-required summary lists each non-PASS correctly

---

## Files Modified
- None — Phase 1 docs handled separately by AH1.

## Files Created
- `~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md` — canonical skill location (committed to baker-vault repo)
- `~/bm-researcher/.claude/skills/researcher-verify-citations` (symlink) — picker visibility

## Do NOT Touch
- `~/baker-vault/_ops/agents/researcher/method.md` — Phase 1 doc lane, AH1 owns
- `~/baker-vault/_ops/agents/researcher/orientation.md` — Phase 1 doc lane, AH1 owns
- Other researcher skills (`grok-via-xai-api`, `ui-surface-prebrief`, `whatsapp-send-via-waha`) — out of scope
- Baker MCP code or schema — verify-citations is read-only consumer of `WebFetch` + Chrome MCP, no Baker writes
- Researcher CLAUDE.md (`~/bm-researcher/CLAUDE.md`) — Phase 1 doc lane

## Quality Checkpoints

1. Skill file exists at canonical path `~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md`
2. Symlink resolves correctly from picker (`readlink` returns canonical path)
3. Frontmatter `name: researcher-verify-citations` matches directory name
4. Frontmatter has MANDATORY TRIGGERS section per existing skill convention (see grok-via-xai-api as exemplar)
5. Three-way verdict taxonomy present in body (PASS / FAIL_MISMATCH / UNCERTAIN_UNVERIFIABLE / UNCERTAIN_POSSIBLE_WALL)
6. Strict date priority rule is explicit and ordered (datePublished > article:published_time > visible header > STOP)
7. `dateModified` is explicitly excluded from PASS list
8. WebFetch < 1500 chars → Chrome MCP escalation is explicit and mandatory (not "or" / "optional")
9. Per-URL timeout 30s + batch ceiling 5 min + `Checked: YES/NO` column all present
10. Output format matches the markdown table shape specified
11. Chrome MCP namespace detection step (`mcp__chrome__*` vs `mcp__Claude_in_Chrome__*`) is explicit
12. Skill does NOT write to vault, call other skills, or invoke Baker write tools
13. Skill file is committed to baker-vault repo (per skill-install convention) — `cd ~/baker-vault && git add _ops/skills/researcher-verify-citations/SKILL.md && git commit`

## Verification SQL (post Phase 3 live test — informational only)

```sql
-- Confirm Baker VIP entries were created during the Phase 3 live researcher session
-- (corollary: Baker-first lookup standing rule from Phase 1 fires correctly)
SELECT name, role, linkedin_url, added_at, source_of_introduction
  FROM vip_contacts
  WHERE added_at > NOW() - INTERVAL '7 days'
    AND (source_of_introduction ILIKE '%researcher%'
         OR source_of_introduction ILIKE '%verify%')
  ORDER BY added_at DESC
  LIMIT 20;
```

This SQL is NOT a build target — it's an informational check that the Phase 1 Baker-first lookup discipline took root during Phase 3 testing.

---

## Risks + lessons applied

| Anti-pattern (from `tasks/lessons.md` + write-brief skill) | Mitigation in this brief |
|---|---|
| Function name guessing | Verified `baker_vip_contacts` + `baker_upsert_vip` exact names against `~/bm-aihead1-cowork/.claude/docs/baker-mcp-api.md`. Verified `mcp__chrome__navigate_page` + `mcp__Claude_in_Chrome__navigate` namespaces against `method.md:105` |
| Brief snippet wrong signature | SKILL.md content above does not invoke any function the skill itself needs to import; all tool calls go through the harness (WebFetch, mcp__chrome__*, mcp__Claude_in_Chrome__*) which are runtime-resolved. No hardcoded signatures in skill body that could rot. |
| Untracked briefs | Code Brisen MUST `cd ~/baker-vault && git add _ops/skills/researcher-verify-citations/SKILL.md && git commit -m "..."` after creation. baker-vault repo, NOT baker-master. |
| Already-implemented brief | Searched git log + filesystem for prior `verify-citations` / `researcher-verify` work: none found. |
| Editing an applied migration | Not applicable — no DB schema changes. |
| Slow external calls need timeouts | Explicit 30s per-URL + 5-min batch ceiling. |
| Multiple pollers must be independent | Each URL refetch is independent; one failure does not cascade. |
| New integrations need health monitoring | Phase 3 live test verifies skill fires correctly on first researcher session. AH1 audits next 3 researcher reports for skill compliance. |

## Estimated cost

- B-code time: ~3-4h to write SKILL.md per spec, create symlink, commit to baker-vault
- Live test (Phase 3): ~30 min researcher session + AH1 audit
- API cost: $0 (skill uses already-available tool calls; no extra LLM invocation)
- Baker MCP impact: none (read-only consumer; no schema changes)

---

## Sequencing reminder for AH1 dispatch

| Phase | Lane | Owner | Time | Status |
|---|---|---|---|---|
| Phase 1: Docs (method.md + orientation.md + CLAUDE.md) | Cowork-AH1 (baker-vault edits) | cowork-ah1 | ~1h | Must land before Phase 2 |
| Phase 2: Skill build (this brief) | b1 via lead dispatch | b1 | ~3-4h | Awaiting Phase 1 |
| Phase 3: Live test | AH1 + researcher | lead or cowork | ~30 min | After Phase 2 ship |
| Phase 4 (optional): Strip rule pile from orientation | Cowork-AH1 | cowork-ah1 | ~30 min | After Phase 3 observation, per Director Q1 ratification |
