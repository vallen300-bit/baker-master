---
status: COMPLETE
brief: briefs/BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1.md
trigger_class: LOW
dispatched_at: 2026-05-01T09:30:00Z
dispatched_by: ai-head-a
claimed_at: 2026-05-01T10:00:00Z
claimed_by: b3
last_heartbeat: 2026-05-01T10:30:00Z
blocker_question: null
ship_report: briefs/_reports/B3_vault_write_followup_nits_1_20260501.md
pr: https://github.com/vallen300-bit/baker-master/pull/142
autopoll_eligible: false
---

# CODE_3 — DISPATCH (BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1)

**Status:** OPEN — 2026-05-01T09:30Z by AI Head A (Director-cleared post-#141 merge)
**Brief:** `briefs/BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1.md` (LOW class, ~1-2h, Tier B)
**Builder:** B3 (B3 reserved for AI Head A per Director 2026-05-01)
**Branch (cut from latest main):** `b3/vault-write-followup-nits-1`
**Tier:** **Tier B** — autonomous merge on green per `_ops/processes/ai-head-autonomy-charter.md` §3
**autopoll_eligible:** false — paste-block dispatch; cold-start required

## Why this exists

`/architect-review` on PR #141 returned APPROVE WITH NITS — 2 MEDIUM
correctness follow-ups, both filtered as non-exploitable by `/security-review`.
Architect explicitly recommended a follow-up commit (matches PR #125→#127 +
#129→#132 pattern). This dispatch closes that loop.

## Task summary

Edit `baker_mcp/vault_write.py` (2-line change in 2 spots) + add 4 unit tests
to `tests/test_baker_vault_write.py`. Brief has full prescription including
exact line citations + before/after code snippets + 4 test cases (F1.a, F1.b,
F2.a, F2.b).

**Files touched:** 2.

**Critical: do NOT touch:**
- `_PROPOSED_GOLD_RE` at `baker_mcp/vault_write.py:67` — broadened blocker
  must NOT catch legitimate `wiki/matters/<slug>/proposed-gold.md`.
- `_ALLOWED_PATTERNS` at `baker_mcp/vault_write.py:28-48`.
- `baker_mcp/baker_mcp_server.py` — no API surface change.
- `outputs/dashboard.py` — no MCP route change.

## Dispatch steps

```bash
cd ~/bm-b3
git fetch origin
git checkout main && git pull --ff-only origin main
gh pr list --state open --limit 20    # Lesson #54 precheck
git checkout -b b3/vault-write-followup-nits-1

# Read brief in full (~110 lines)
cat briefs/BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1.md

# Implement F1 + F2 per brief §Scope
# F1: validate_path() control-char rejection, before traversal check
# F2: _BLOCKED_PATTERNS — broaden 2 entries to ^(wiki/)?.* form
# Test F1.a, F1.b, F2.a, F2.b per brief §Scope §File 2

# Quality checkpoints (brief §Quality checkpoints):
pytest tests/test_baker_vault_write.py -v          # expect 45/45 (41 prior + 4 new)
python3 -c "import py_compile; py_compile.compile('baker_mcp/vault_write.py', doraise=True)"
bash scripts/check_singletons.sh

# Push + open PR per brief §Quality checkpoints (full gh pr create command in brief)
git push -u origin b3/vault-write-followup-nits-1
gh pr create --title "fix(vault): vault_write.py architect-nit followup (control chars + root-path blockers) (BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1)" \
  --body "$(see brief for full body template)"
```

## Acceptance criteria

- 4 new tests pass (F1.a, F1.b, F2.a, F2.b).
- 41 prior tests pass byte-for-byte (regression guard).
- `validate_path()` rejects control characters (`\n`, `\r`, `\x00`) BEFORE
  the traversal check, with message containing "control characters".
- `_BLOCKED_PATTERNS` matches root-level `gold.md` + `_priorities.yml` via
  the broadened `^(wiki/)?.*` form.
- PR opened with brief link in body; Tier B autonomous-merge on green.
- Ship report: `briefs/_reports/B3_vault_write_followup_nits_1_<date>.md`.

## On completion

1. Open PR.
2. Update this mailbox to `status: COMPLETE` with PR link + ship-report path
   (or reach out via paste-block if blocker hit).
3. AI Head A reviews + merges on green (autonomous Tier B per charter §3).

## Companion context

- PR #141 (parent) merged 2026-05-01T09:01Z as `77e05d5`. Live on Render
  (deploy `dep-d7q6o0faqgkc7396skng`, live 09:11Z). curl-verified.
- PR #140 (sibling) merged 2026-05-01T09:02Z as `3cc06e8`. f2ecb49 collapse
  deploy was rolling at dispatch time (~20 min in update_in_progress); will
  finish in background while B3 builds.
- This brief is cosmetic correctness, not a blocker. Build at LOW priority;
  no need to rush past quality checkpoints.
