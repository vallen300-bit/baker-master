---
dispatch: CODEX_SKILL_ACCESS_WIRING_1
to: b4
from: cowork-ah1
dispatched_by: cowork-ah1
status: PENDING
dispatched_at: 2026-06-08
authored: 2026-06-08
target_repo: baker-vault (+ ~/.codex, ~/bm-codex-arch) — NOT baker-master app code
estimated_time: ~45-60min
complexity: low-medium
reply_to: lead
priority: tier-b
gate_plan: G0 codex (brief) -> G1 functional (run the 7 verification steps) -> G3 codex (code) -> commit. No G2 (no auth/data surface).
brief_path: briefs/BRIEF_CODEX_SKILL_ACCESS_WIRING_1.md
prior_mailbox_state: superseded — M365_GRAPH_MAIL_POLL_2 COMPLETE (PR #292 merged, dormant AC pass)
anchor: codex-arch had no skill registry on the NVIDIA MO dashboard dispatch (cowork-ah1, 2026-06-08)
---

# B4 dispatch — CODEX_SKILL_ACCESS_WIRING_1

Make Codex agents able to access every Brisen skill the way Claude-Code agents do — durably.

Full brief: `briefs/BRIEF_CODEX_SKILL_ACCESS_WIRING_1.md`. Read it fully.

**Already shipped by cowork-ah1 (vault `e04eeb4`):** `_ops/skills/SKILLS_INDEX.md` (186-skill catalog, absolute paths) + `_ops/skills/gen_skills_index.py` (stdlib generator). Your job = make it self-maintaining + auto-loaded + documented.

Four tasks:
1. Add `--check` mode to `gen_skills_index.py` (exit 1 if index stale).
2. Wire a staleness guard into `~/baker-vault/.githooks/pre-commit` (fires only when a `_ops/skills/*/SKILL.md` is staged). Match the existing guards' fail-loud pattern.
3. Add the skill-catalog + "skills are files, read-and-follow, never call" rule to `~/.codex/AGENTS.md` (global — covers all Codex lanes) and as a session-start read in `_ops/agents/codex-arch/AGENTS.md` + the byte-identical live `~/bm-codex-arch/AGENTS.md`.
4. Add the Codex dispatch convention to `_ops/processes/cross-agent-knowledge-dispatch.md`.

**Do NOT touch:** the 186 SKILL.md files, CODE_3's brief / lead's dashboard wave, baker-master app code.

Ship report: literal output of the 7 verification steps in the brief (not "by inspection"). Bus `lead`.
