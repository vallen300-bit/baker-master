# PLAUD_SENTINEL_1 — Tier B task entry

**Promoted from:** `baker-vault/_ops/ideas/2026-04-26-plaud-sentinel-integration.md` (RA spec, 2026-04-26)
**Promotion authority:** AI Head A Tier B per Director authorization
**Director authorization (verbatim):** *"ok, pls give a task to AI Head to integrate Plaud now"* (Director, late afternoon Sunday 2026-04-26)
**Brief:** `briefs/BRIEF_PLAUD_SENTINEL_1.md`

---

## Status

**State:** DRAFTED, **dispatch held on 2 gates**:

1. **🚦 Gate 1 — Token provisioning:** `BAKER_PLAUD_API_TOKEN` in 1Password under name (Director picks). B-code fetches via `op` CLI per `reference_1password_secrets`. Director confirms before B-code dispatch.
2. **🚦 Gate 2 — Plaud Pro tier:** Q1 default assumes Pro with API access. If only personal/free tier provisioned, brief degrades to "manual export pipeline" — Director must confirm tier OR ratify pipeline downgrade.

Both gates clear → AI Head A dispatches B3 (recommended target — idle post-PR-#62 merge).

## §4 questions — Director-resolved (defaults adopted)

| Q | Default → Director resolution |
|---|---|
| Q1 Plaud product + tier | **Pro tier with API access** (per dispatch message). If wrong, surface as blocker. |
| Q2 Capture scope | **Ingest ALL recordings.** Filter at retrieval if narrower scope wanted later. |
| Q3 Storage destination | **New `plaud_notes` table** (different signal class from meetings; per-source retention). |

## §2 busy-check (per b-code-dispatch-coordination.md)

State at draft time (2026-04-26):
- **B1:** mailbox COMPLETE (PR #61 merged 92e4129; PR #63 review trigger TBD post-Plaud build for situational review). On main behind 5.
- **B2:** in flight on WIKI_LINT_1 (dispatched ec25c38). Worktree on main; branch `wiki-lint-1` not yet visible — B2 may not have picked up dispatch yet OR working in another clone.
- **B3:** mailbox COMPLETE (PR #62 merged 5ae6545). On main. **RECOMMENDED dispatch target.**
- **B4:** reserved for fix-backs.

Recommend dispatch to **B3** when both gates clear.

## Trigger classes hit (B1 situational review per 2026-04-24-b1-situational-review-trigger.md)

3 of 7 trigger classes hit:
1. **Secrets handling** — `BAKER_PLAUD_API_TOKEN` fetched via op CLI.
2. **External API** — new Plaud cloud integration.
3. **Cross-capability state writes** — new `plaud_notes` table + Qdrant collection + scheduler job.

→ B1 reviews PR before AI Head A merges.

## Post-merge actions (AI Head A handles)

1. Update `baker-vault/_ops/shadow-org/sentinels.md` — move Plaud from §3 (planned) → §2 (live).
2. Append to `_ops/agents/ai-head/actions_log.md` (or create if absent) — Director auth quoted + execution path.
3. §3 hygiene: mark `briefs/_tasks/CODE_3_PENDING.md` COMPLETE.

## Cross-references

- Spec: `baker-vault/_ops/ideas/2026-04-26-plaud-sentinel-integration.md`
- Sister artifact: `baker-vault/_ops/shadow-org/sentinels.md`
- Cat 5 close anchor: Block 2 Cat 5 (Brisen Shadow Org sentinels inventory)
- Charter: `_ops/processes/ai-head-autonomy-charter.md`
- Dispatch coord: `_ops/processes/b-code-dispatch-coordination.md`
- B1 situational review: `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`
- Memory: `feedback_migration_bootstrap_drift.md`, `feedback_no_ship_by_inspection.md`, `reference_1password_secrets.md`
