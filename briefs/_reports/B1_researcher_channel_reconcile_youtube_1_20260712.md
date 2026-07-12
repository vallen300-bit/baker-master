# B1 ship report — RESEARCHER_CHANNEL_RECONCILE_YOUTUBE_1

- **Brief:** `briefs/_tasks/RESEARCHER_CHANNEL_RECONCILE_YOUTUBE_1.md` @da63179f
- **Dispatch:** lead bus #9807 (topic `dispatch/researcher-channel-reconcile-youtube`)
- **Date:** 2026-07-12
- **Vault PR:** https://github.com/vallen300-bit/baker-vault/pull/182 (branch `b1/researcher-channel-reconcile-youtube`, isolated worktree `/tmp/vault-b1-yt`)
- **Skill symlink:** `~/bm-researcher/.claude/skills/youtube-analyze` → `/Users/dimitry/baker-vault/_ops/skills/youtube-analyze` (installed; not a repo file)

## Done rubric

1. **"What are your channels" matches method.md 1:1** — §2 now carries a per-row **Reach** column (✅/⚠/❌) reconciled to the cage + picker. The seat's self-report (gh/curl blocked, ~6 tool channels) was *correct*; method.md was the stale party. ✅ closed at doc level; per-row live-seat confirmation is the merge-precondition probe (below).
2. **YouTube URL → structured note works live** — host tooling proven (transcript 2089 chars + Gemma 14.0s/283 tok on `dQw4w9WgXcQ`). Researcher-**seat** end-to-end probe (MCP `get-transcript` → synthesise) = merge precondition, run on the researcher session. ⏳ gated.
3. **No cage weakening** — zero cage changes in this arc. ✅

## AC1 — audit table (evidence = config read @origin/main)

Sources: `_ops/hooks/researcher_bash_cage.sh` @origin/main + picker `settings.json` / `settings.local.json` / `.mcp.json`.

| # | Channel (method.md §2) | Doc promised | Verified reality | Verdict |
|---|---|---|---|---|
| 1 | GitHub | `gh search`/`gh api` | cage denies `gh` entirely (deny-by-default; push/exfil surface) | **stale** → WebFetch/Chrome |
| 2 | Perplexity Ask | perplexity MCP | allow-listed + `.mcp.json` server live | ✅ works |
| 3 | General web | WebSearch | allow-listed | ✅ works |
| 4 | Single URL | WebFetch | 5 domains pre-approved in settings.local; new domains prompt | ✅ works (domain-gated) |
| 5 | Authenticated sources | `auth_source_fetch.sh` | cage line 207 vetted + script exists | ✅ works |
| 6 | Standing monitors | `check_source_monitors.sh` | cage line 214 vetted + script exists | ✅ works |
| 7 | Gemma / Gemini | Chrome AI Studio | `fill`/`click`/`type`/`press_key` picker-denied; local Ollama via curl cage-blocked | ⚠ degraded (computer/js_tool/navigate) |
| 8 | Grok DeepSearch | Chrome x.com/i/grok | same Chrome interaction constraint | ⚠ degraded |
| 9 | X verbatim threads | Chrome x.com | read/navigate works; input degraded | ⚠ degraded |
| 10 | LinkedIn | Chrome linkedin.com | same Chrome interaction constraint | ⚠ degraded |
| 11 | Trade press | WebSearch+WebFetch | works (WebFetch domain-gated) | ✅ works |
| 12 | Standards bodies | WebSearch+WebFetch | works | ✅ works |
| 13 | Big4 + law firms | WebSearch+WebFetch | works | ✅ works |
| 14 | Curricula | WebSearch+WebFetch | works | ✅ works |
| 15 | Anthropic marketplaces | `gh api`+WebFetch | `gh` blocked; WebFetch works | **partial** → WebFetch only |
| 16 | Internal Brisen data | Baker MCP | read tools allow; all writes/upserts/`inbox_post` denied | ✅ works (read-only) |
| 17 | 1Password | `op` (when authorised) | `op` not on cage allow-list | ❌ cage-blocked |
| §5 | `Bash — gh…curl` line | gh/curl | all denied by cage | **wrong line — rewritten** |

**Undocumented channels surfaced (added to §2):**
- **YouTube** — `youtube-transcript` MCP (`yt_transcript_mcp.py`, wraps `youtube-transcript-api` v1.2.4). Wired since 2026-06-21; was missing from §2. → **AC2**.
- **Stitch (Google)** — `stitch` MCP in `.mcp.json`; UI-generation, not a research pull-channel. Documented as ⚠ non-research; **lead decision: keep or remove from picker.**

## AC2 — method.md updated

§2 table rewritten with Reach column + YouTube row + Stitch row + corrected gh/op/Chrome rows. §3 Chrome-browsing actor row annotated with the interactive-deny constraint. §5 tool list corrected (Bash deny-by-default; gh/curl/python3/op blocked; YouTube MCP added). Vault PR #182.

## AC3 — YouTube channel install

- **Symlink installed:** `~/bm-researcher/.claude/skills/youtube-analyze` → canonical (matches existing picker symlink pattern). Resolves + SKILL.md readable through link.
- **Host tooling proven (b1 seat):**
  - `youtube-transcript-api` 1.2.4 → transcript fetch OK (2089 chars, control video `dQw4w9WgXcQ`).
  - Ollama `gemma4:latest` → synthesis OK (14.0s, 283 tokens): *"the transcript contains the lyrics to a song…"*
- **Seat caveat (surfaced, not hidden):** the skill's standalone `python3`+`curl localhost:11434` one-liner is **cage-blocked** on the researcher seat. Working path on-seat: MCP `get-transcript` → synthesise in Claude (full Brisen lens) or Gemma via Chrome AI Studio. Documented in the new §2 YouTube row + §5.
- **⏳ Merge precondition (gate plan):** researcher-**seat** live probe — one real URL end-to-end via the MCP tool, returning a structured note — to be run on the researcher session (lead coordinates). I am b1; I cannot drive the researcher seat.

## AC4 — no silent gaps

- `gh` / `curl` / `op`: documented as **intentionally** cage-blocked with routing alternative (option **b**). No re-enable — `gh`/`curl` are exfil/push surfaces the cage deliberately denies (RESEARCHER_GIT_WRAPPER_CAGE_CLOSE_1).
- `auth_source_fetch.sh` + `check_source_monitors.sh`: already vetted on origin/main → no cage PR needed (option a not required). The shared `~/baker-vault` checkout was **stale** (cage + method.md both behind origin/main) — flagged as the local-checkout-drift lesson; all analysis was done against origin/main via the isolated worktree.

## Notes for lead

- **No cage PR** this arc (the two vetted scripts already present on origin/main; nothing to re-enable).
- **Stitch MCP** keep/remove is a lead call — surfaced, not decided.
- **Merge sequence:** review + merge PR #182; then run the AC3 researcher-seat live probe (merge precondition for declaring the YouTube channel live). Symlink is already in place so the seat can probe immediately.
