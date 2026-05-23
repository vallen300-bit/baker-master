---
status: pending
brief: briefs/BRIEF_RESEARCHER_VERIFY_CITATIONS_1.md
brief_id: RESEARCHER_VERIFY_CITATIONS_1
target_repo: baker-vault (skill file + symlink target) — no baker-master writes, no brisen-lab writes
matter_slug: baker-internal
dispatched_at: 2026-05-23T12:00:00Z
dispatched_by: lead
target: b1
working_branch: b1/researcher-verify-citations-1
reply_to: lead
deadline: 2026-05-24T18:00:00Z
priority: tier-b
---

# CODE_1_PENDING — RESEARCHER_VERIFY_CITATIONS_1 — 2026-05-23

**Brief:** `briefs/BRIEF_RESEARCHER_VERIFY_CITATIONS_1.md` (full text in baker-master `main` @ `cf43ee3`; pull before reading)
**Working branch:** `b1/researcher-verify-citations-1` (cut from baker-vault `main`)
**Repo:** baker-vault ONLY (skill at `_ops/skills/researcher-verify-citations/SKILL.md` + symlink into `~/bm-researcher/.claude/skills/`)
**Pre-requisites:** Phase 1 docs already landed in baker-vault `b15cf7a` (researcher `method.md` + `orientation.md` updated with Step 0 Shape Selector + Step 6.5 verify gate + §8 citation slot template + Baker-first people lookup rule).

## Bottom line

Build the `researcher-verify-citations` skill per the brief's full SKILL.md spec (lines 60-277 of the brief). Phase 2 of the 4-component researcher fine-tuning arc. ~3-4h. No baker-master changes.

## Acceptance criteria (full list — brief Quality Checkpoints 1-13)

1. `~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md` exists at canonical path.
2. Symlink `~/bm-researcher/.claude/skills/researcher-verify-citations` resolves to the canonical path (`readlink` returns `/Users/dimitry/baker-vault/_ops/skills/researcher-verify-citations`).
3. Frontmatter `name: researcher-verify-citations` matches directory name.
4. Frontmatter has `MANDATORY TRIGGERS` line per existing skill convention (mirror `grok-via-xai-api`).
5. Three-way verdict taxonomy + paywall subtype present (`PASS` / `FAIL_MISMATCH` / `UNCERTAIN_UNVERIFIABLE` / `UNCERTAIN_POSSIBLE_WALL`).
6. Strict date priority rule explicit + ordered (`datePublished` > `article:published_time` > visible header > STOP).
7. `dateModified` explicitly excluded from PASS.
8. WebFetch < 1500 chars → mandatory Chrome MCP escalation (not optional).
9. Per-URL 30s timeout + 5-min batch ceiling + explicit `Checked: YES/NO` column all present.
10. Output format matches the markdown table shape in brief lines 209-216.
11. Chrome MCP namespace detection step (`mcp__chrome__*` vs `mcp__Claude_in_Chrome__*`) explicit.
12. Skill does NOT write to vault, call other skills, or invoke Baker write tools.
13. Skill file committed to baker-vault repo (NOT baker-master).

## Ship gate

- Literal `grep` verification of all 4 hard constraints (brief lines 291-315): paste output in ship report.
- `readlink ~/bm-researcher/.claude/skills/researcher-verify-citations` returns canonical path: paste output.
- `head -5 ~/baker-vault/_ops/skills/researcher-verify-citations/SKILL.md` shows correct `name:` frontmatter: paste output.

## Reporting

- Ship PR against baker-vault `main` from branch `b1/researcher-verify-citations-1`.
- **Bus-post `lead` on PR open** with topic `ship/researcher-verify-citations-1` (per brief-reply-to-sender rule — `dispatched_by: lead` ⇒ ship-report to `lead`).
- Do NOT touch baker-master or brisen-lab in this brief.

## Out of scope (Do NOT touch)

- `_ops/agents/researcher/method.md` — Phase 1 doc lane, already landed.
- `_ops/agents/researcher/orientation.md` — Phase 1 doc lane, already landed.
- Other researcher skills (`grok-via-xai-api`, `ui-surface-prebrief`, `whatsapp-send-via-waha`).
- Baker MCP code or schema.
- Researcher CLAUDE.md.

---

## UPDATE 2026-05-23T12:30Z — V0.2 fold (REQUEST_CHANGES on PR #107)

V0.1 shipped fast + clean on the 13 QCs. Gate-4 (`feature-dev:code-reviewer` 2nd-pass) returned PASS-WITH-NITS but flagged **1 CRITICAL + 1 HIGH** — both real semantic gaps in the spec body, not lint nits. Per AH1 SKILL.md §Code-reviewer 2nd-pass Protocol: HIGH/CRITICAL → REQUEST_CHANGES → V0.2 fold + re-fire gate chain.

PR #107 stays open; fold both findings on the same branch `b1/researcher-verify-citations-1` (no force-rewrite — new commit on top).

### Finding 1 — CRITICAL — bare `UNCERTAIN` verdict has no taxonomy entry

**Location:** `_ops/skills/researcher-verify-citations/SKILL.md` — taxonomy table currently at lines 136-144 + body usages.

**Problem:** Bare `UNCERTAIN` (no subtype suffix) is used 5+ times in the spec body where no defined verdict slot exists:
- Year-only date match (date section) → spec says `UNCERTAIN`
- Redirect domain change (redirect handling) → spec says `UNCERTAIN`
- 404 / fabricated URL (failure-modes table) → spec says `UNCERTAIN with reason "URL does not resolve"`
- Output format example row 4 (timeout) → uses bare `UNCERTAIN` + `Checked: NO`

But the verdict taxonomy table only defines: `PASS` / `FAIL_MISMATCH` / `UNCERTAIN_UNVERIFIABLE` / `UNCERTAIN_POSSIBLE_WALL` / `Checked: NO`. Bare `UNCERTAIN` has no row, no remediation, no semantic.

Result: two Researchers running this skill on the same 404 fabricated URL would produce different verdict labels — some would write `UNCERTAIN`, some `UNCERTAIN_UNVERIFIABLE`, some `Checked: NO`. The 404 case (strong hallucination signal) could be silently downgraded to "page existed but field missing." This breaks the output contract.

**Fix:** Add a third catch-all UNCERTAIN row to the taxonomy table:

| Verdict | Meaning | Remediation |
|---|---|---|
| `UNCERTAIN` | Verified-real page but a specific check could not complete (year-only date match, domain redirect, URL 404/unresolvable). Distinct from `UNCERTAIN_UNVERIFIABLE` (page exists but key field missing) and `UNCERTAIN_POSSIBLE_WALL` (paywall suspected). | Downgrade Confidence to MEDIUM, mark "UNVERIFIED" in claim, or remove. For 404 specifically: note "URL does not resolve" in Reasoning column. |

Then update the three bare-`UNCERTAIN` usages in the body (date year-only, redirect domain, 404 failure-mode) to point at this taxonomy row. The 404 vs domain-redirect vs year-only distinction lives in the Reasoning column, not a new verdict.

### Finding 2 — HIGH — Short Shape inline-compressed citation format silently skipped

**Location:** `_ops/skills/researcher-verify-citations/SKILL.md` — Extraction logic section (~lines 30-37).

**Problem:** The Extraction logic describes canonical block-form citation slots only:

```
Claim: <statement>
URL: <https://...>
Pub date: <YYYY-MM-DD or "not visible">
...
```

But Phase 1 `method.md` §8 (and the SKILL frontmatter "Short Shape capped at 5 URLs" language) defines an inline-compressed format for Short Shape reports:

```
<statement> [URL, pub_date, tier, confidence]
```

If a Short Shape report arrives with compressed slots, the extraction step finds zero block-form matches → produces an empty verification run → no verdict table → no action-required summary. The Researcher is not alerted that verification produced zero findings on a draft that has 5 citations — false-pass-by-empty-output.

**Fix:** Add a sentence to the Extraction logic section:

> For Short Shape reports, also extract inline-compressed slots of the form `<statement> [URL, pub_date, tier, confidence]` appended after a statement. Treat each as a minimal block with URL + pub_date; byline and quote checks are N/A for compressed slots (record `—` in those columns; verdict still applies on the date check + URL refetch alone).

Plus: if extraction returns zero slots from a non-empty draft, the skill MUST emit a loud-fail line at the top of the output, NOT a silent empty table:

> If extraction finds zero citation slots in a draft that contains URLs, emit: `**EXTRACTION ERROR:** Found {N} URLs in draft but zero parseable citation slots. Researcher must reformat citations per `method.md` §8 before re-running this skill.`

### What to add to V0.2

1. Taxonomy table — add `UNCERTAIN` row per Finding 1 fix above.
2. Update three body sites (date year-only / redirect domain / 404 failure-mode entry) to reference the new taxonomy row.
3. Extraction logic — add Short Shape inline-compressed extraction sentence per Finding 2 fix above.
4. Extraction logic — add zero-slot loud-fail rule per Finding 2 fix above.
5. Update the failure-modes table at the bottom to confirm "Fabricated URLs" row now maps to `UNCERTAIN` (not bare-`UNCERTAIN` with no taxonomy backing).

### Ship gate (V0.2 incremental)

- Re-run all original ship-gate checks; paste output again in PR description (or comment).
- New check: `grep -c "^| .UNCERTAIN.* | Verified-real page" SKILL.md` → expected ≥1 (confirms new taxonomy row present).
- New check: `grep -c "inline-compressed" SKILL.md` → expected ≥1 (confirms Short Shape extraction added).
- New check: `grep -c "EXTRACTION ERROR" SKILL.md` → expected ≥1 (confirms loud-fail rule added).

### Reporting (unchanged target)

- Same branch `b1/researcher-verify-citations-1` (no force-rewrite — new commit on top).
- Bus-post `lead` with topic `ship/researcher-verify-citations-1-v0-2-rerun` on V0.2 push.
- Gate chain re-fires on V0.2 commit; merge follows clear verdict.

ETA: ~30-45 min (taxonomy table edit + Extraction logic edit + 3 body sites + ship-gate re-run). Smaller than V0.1.
