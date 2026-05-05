# CODE_4_PENDING — BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1 — 2026-05-05

**Brief:** baker-master `briefs/BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md` (Tier A, ~3-4 hours, 12 ACs)
**Working branches (TWO PRs, cross-repo):**
- `b4/brisen-lab-surface-6a-partial-unique-index-1` (brisen-lab repo)
- `b4/baker-master-surface-6a-hook-retry-1` (baker-master repo)
**Pre-requisites:** brisen-lab main HEAD `bc1e3e6` (Surface 6 merged) + baker-master main HEAD `bad7c6d` (this brief commit)
**Acceptance criteria:** per brief §ACs (12 testable items, A1-A12)
**Ship gate:** literal `pytest` GREEN both sides — no by-inspection (Lesson #52)
**Heartbeat:** 12h cadence binding (per SKILL.md `59f23c4` §B-code stall chase)

**Read first (MANDATORY):**
1. `briefs/BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md` — full spec + 5 features + 12 ACs
2. `~/baker-vault/_ops/agents/b4/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

**Path forward:**
1. Read brief BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md cover-to-cover
2. **Pre-work — verify migration runner CONCURRENTLY-handling** (Sequencing step 3): inspect `~/bm-b4-brisen-lab/start.sh` (or migration runner). If runner wraps `.sql` files in BEGIN/COMMIT, surface to AH1 BEFORE writing migration.
3. **Pre-apply prod sanity check:** run duplicate-detect SELECT against prod brisen-lab DB. Surface to AH1 if non-empty.
4. Implement Feature 1 (migration) on `b4/brisen-lab-surface-6a-partial-unique-index-1` branch in brisen-lab repo
5. Apply locally + verify `pg_index.indisvalid = TRUE` post-CONCURRENTLY
6. Implement Feature 2 (handler 409 + observability) in brisen-lab `bus.py`
7. Implement Feature 3 (regression tests with threading.Barrier + 20× loop) in brisen-lab `tests/`
8. Implement Feature 5 (hook retry-on-409 with jitter, max-retry=1) in baker-master `.claude/hooks/user-prompt-submit-confirm.py` on `b4/baker-master-surface-6a-hook-retry-1` branch
9. Implement Feature 4 (cutover runbook in baker-vault `_ops/processes/v2-bridge-cutover-runbook.md`)
10. Live pytest GREEN both repos
11. Open TWO PRs (brisen-lab + baker-master)
12. Ship via PL paste-block per SKILL.md §"PL ship-report contract"
13. 4-gate review chain on each PR: live pytest + AH2 /security-review + architect spot-check + feature-dev:code-reviewer 2nd-pass

**Critical pre-merge gates (from architect post-WRITE review):**
- Hook retry-on-409 (Feature 5) is NEW scope, cross-repo — without it, race-loser silently fails fail-open. V0.3.7 hook does NOT retry on non-200 today (verified at `.claude/hooks/user-prompt-submit-confirm.py:216-217`).
- Migration runner CONCURRENTLY-handling: verify upfront before writing migration (cannot run inside transaction block).
- pg_index.indisvalid check post-CONCURRENTLY: INVALID index from duplicate-mid-build silently masks future re-runs via `IF NOT EXISTS`. Hard ship-blocker.
- DROP INDEX CONCURRENTLY for symmetry/online-safety.
- psycopg2 version: verify ≥2.8 in requirements.txt; fallback `e.pgcode == '23505'` if uncertain.
- Test determinism: `threading.Barrier(2)` + 20× loop + reject SQLite at conftest.

**Merge order (mandatory):** brisen-lab PR FIRST → baker-master PR second. Brisen-lab daemon emits 409 first; baker-master hook retries against the now-409-emitting daemon. Reverse order = hook retries against daemon that doesn't emit 409 → no-op, harmless but unverifiable.

**Anchor:** Director ratification 2026-05-05 ("agreed" → "go Surface 6a"); brief commit `bad7c6d` baker-master main; architect post-WRITE review agent `abd0422d6c3f380b8` 2026-05-05.

---

## Prior CODE_4 task (archive reference)
BRIEF_BRISEN_LAB_V2_BRIDGE_1 V0.3.7 — COMPLETE 2026-05-05. baker-master PR #157 squash-merged 2026-05-05T20:57:19Z (commit `57ab073`); brisen-lab PR #2 squash-merged 2026-05-05T20:57:08Z (commit `bc1e3e6`). All 4 gates cleared (B4 pytest + AH2 /security-review + architect + code-reviewer). `BRISEN_LAB_V2_ENABLED=false` stays on Render until Surface 6a (this brief) ships + Tier-B cutover Director-ratified. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
