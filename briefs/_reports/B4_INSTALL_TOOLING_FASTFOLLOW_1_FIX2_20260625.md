# B4 ship report — INSTALL_TOOLING_FASTFOLLOW_1 FIX 2

- **Dispatch:** bus #4315 (brief) + #4358 (Option (b) decision) from `lead`
- **Branch:** `b4/install-tooling-fastfollow-1-fix2`
- **PR:** #428 (baker-master)
- **Ship bus post:** #4362 → lead

## Decision context

Director-ratified **Option (b)** (lead #4358): repoint refs to each agent's own fresh clone, not a symlink. Rationale proven in FIX 1 escalation — `bus_post.sh` is byte-identical across clones; the stale artifact is the sourced sibling `agent_identity_generated.sh` (`bus_post.sh:18` derives `SCRIPT_DIR` from `$0`'s dirname). A symlink of `bus_post.sh` alone leaves the stale sibling in play (TEST A reject / TEST B pass).

## baker-master — SHIPPED (PR #428)

- **`tests/fixtures/session-start-bus-drain.sh`** (canonical SessionStart drain hook): reply-hint footer resolves a fresh `bus_post.sh` via candidate ladder — `$CLAUDE_PROJECT_DIR/scripts/bus_post.sh` → `~/bm-<slug>/scripts/bus_post.sh` → `~/bm-aihead1/...`; last-resort names the per-role clone. Never the stale Desktop clone. Live b4 render → `/Users/dimitry/bm-b4/scripts/bus_post.sh`.
- **`scripts/codex-bus-reply.sh` + `codexarch-bus-reply.sh`**: dropped stale Desktop fallback (now `bm-aihead1` → `bm-b1`).
- **`orchestrator/cortex_runner.py`**: doc comment depointed.

**Verification (literal).**
- `tests/test_bus_drain_hook.py` → **13 passed**, 1 failed.
- The 1 failure is `test_user_global_matches_repo` — **fails by design** (drift detector) until AH runs the documented pre-merge deploy: `cp tests/fixtures/session-start-bus-drain.sh ~/.claude/hooks/session-start-bus-drain.sh`. Not a regression.
- New assertions: happy-path excludes `Desktop/baker-code` + names per-role clone; `test_reply_hint_prefers_claude_project_dir` covers own-clone branch.
- `bash -n` clean on fixture + both codex scripts; `py_compile` clean on cortex_runner.

**Gate plan.** G2 codex MEDIUM → G3 AH2 (deputy) → G4 lead.

## baker-vault — NOT shipped, handed to lead (#4362)

Vault-commit territory (CHANDA Inv 9) and **broader than "orientation files"**. Full live-ref inventory:
- `_ops/agents/{b1,b2,b3,b4}/orientation.md` (primary-channel doc ~line 129 + posting pattern ~line 142)
- `_ops/processes/agent-bus-posting-contract.md` (canonical contract) + `_ops/skills/agent-bus-posting-contract/SKILL.md`
- `_ops/skills/harness-setup/{SKILL.md,checklist.md}` + `_ops/skills/install-agent-to-brisen-lab/SKILL.md` + `_ops/processes/install-agent-to-brisen-lab-sop.md`
- `_ops/reconciler/nightly_cron.sh` + `com.baker.state-reconciler.plist` — **runtime that executes the stale path; same bug class**
- `_ops/agents/aihead2/PINNED.md` + assorted `_ops/briefs/*` (historical; likely skip)

Suggested mapping (docs): `~/Desktop/baker-code/scripts/bus_post.sh` → `~/bm-<role>/scripts/bus_post.sh`. Reconciler runtime needs the same fresh-clone fix as codex-reply. Awaiting lead's call: open a baker-vault PR (I can) vs land via Mac Mini / Director.
