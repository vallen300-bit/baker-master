---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_AUTH_COMPLETION_1.md
scope: F1 ONLY (handler edit + tests). F3 = AH1-App execute, NOT B2 scope.
trigger_class: TIER_A_AUTH_TOUCHING
dispatched_at: 2026-05-05T23:1XZ
dispatched_by: ai-head-a (lead)
target_branch: b2/brisen-lab-auth-completion-1
target_repo: vallen300-bit/brisen-lab (NOT baker-master)
review_chain_mandatory:
  - feature-dev:code-architect (post-WRITE design review)
  - feature-dev:code-reviewer (standard pass)
  - feature-dev:code-reviewer SECOND PASS (auth-touching trigger)
  - /security-review (auth-touching → mandatory; AH2 lane)
  - B1 SITUATIONAL REVIEW (auth-touching trigger fires per ai_head_b1_review_triggers.md)
ship_gate: ACs A1+A3+A4+A5+A6+A12+A13 all GREEN per V0.2 brief
---

# CODE_2_PENDING — BRIEF_BRISEN_LAB_AUTH_COMPLETION_1 — F1 (V0.2 architect-folded, 2026-05-05)

## Mailbox

- **Brief:** `briefs/BRIEF_BRISEN_LAB_AUTH_COMPLETION_1.md` (baker-master commit `370c9ba`).
- **Read V0.2 amendment first** (bottom of brief) — V0.1 had two HIGH gaps that V0.2 closes:
  - Edit 2 (POST /msg/<id>/ack authz) was DEAD WORK — `bus.py:442-463` already enforces; V0.2 strikes Edit 2.
  - GET /msg/{terminal} broadcast handling: V0.2 clarifies the existing `%s = ANY(to_terminals)` clause already covers `'*'`-addressed self-broadcasts; new test added.
- **Scope for B2:** F1 ONLY. F3 (provision 9 remaining worker keys) is AH1-App-execute; do NOT touch Render env or 1Password.

## What you're building (F1)

**Repo:** `~/bm-b4-brisen-lab` (or your preferred clone of `vallen300-bit/brisen-lab`). NOT `baker-master`.

**Branch:** `b2/brisen-lab-auth-completion-1` (do NOT clobber `b2/baker-cost-instrumentation-1` or `b2/cortex-phase3b-parallel-cost` — both already merged but branches still exist).

**Files modified (per V0.2):**

1. `bus.py` — ONE handler edit. `GET /msg/{terminal}` (lines 298-349). Add immediately after `reader_slug = _require_worker_slug(x_terminal_key)`:

   ```python
   if reader_slug != terminal:
       raise HTTPException(status_code=403, detail="reader_slug_mismatch")
   ```

   That's it. Do NOT touch the ack handler at line 433 — it already enforces (V0.1 Edit 2 was struck).

2. `tests/test_inbox_read_authz.py` (NEW) — 7 tests per V0.2 §C:
   - `test_get_msg_self_succeeds` — lead → /msg/lead → 200
   - `test_get_msg_self_broadcast_succeeds` — director posts to=['*'], lead → /msg/lead returns the message (regression check: V0.1 was at risk of dropping broadcasts)
   - `test_get_msg_other_403` — lead → /msg/cowork-ah1 → 403 with detail="reader_slug_mismatch"
   - `test_get_msg_cross_slug_attack_403` — b2's key → /msg/lead → 403 (the actual F1 attack scenario; V0.2 §C addition)
   - `test_get_msg_no_key_401` — no X-Terminal-Key header → 401 (regression)
   - REGRESSION-only for ack: `test_ack_self_addressed_succeeds`, `test_ack_not_in_recipients_403_existing_path` (preserve `_is_director` exemption per V0.2 §A)

## Trigger class + review chain (MANDATORY)

This is auth-touching → triggers full chain per `feedback_ai_head_b1_review_triggers.md`:

1. After your write: `feature-dev:code-architect` post-WRITE pass (you invoke).
2. After local pytest GREEN: `feature-dev:code-reviewer` standard pass.
3. **Second-pass `code-reviewer` on the diff** (auth-touching trigger; not optional).
4. **`/security-review`** — AH2 lane runs this on the PR; do NOT merge until verdict PASS.
5. **B1 SITUATIONAL REVIEW** — B1 picks up the PR per the ai_head_b1_review_triggers.md (auth surface = trigger fires). Do not pre-empt — let B1 run their pass.

## Pre-work

- Run `git pull && git status` in your brisen-lab clone (verify clean main).
- `git checkout -b b2/brisen-lab-auth-completion-1`.
- Read V0.2 amendment at the bottom of `briefs/BRIEF_BRISEN_LAB_AUTH_COMPLETION_1.md`.
- Re-read `bus.py:298-349` AND `bus.py:442-463` — confirm V0.2's "ack already enforces" claim by reading the actual code path; if V0.2 is wrong about ack, surface to AH1 (lead) before any code change.

## Definition of done

- ACs A1, A3, A4, A5, A6 from the V0.2 brief all GREEN.
- A12 (`feature-dev:code-reviewer` standard pass) verdict pasted in PR.
- A13 (`/security-review`) verdict pasted in PR.
- Ship-report at `briefs/_reports/B2_brisen_lab_auth_completion_1_F1_<date>.md` per SKILL.md.
- Mailbox flipped to COMPLETE on merge (§3 hygiene).

## Notes

- F3 (9 remaining worker keys provisioning) is intentionally OUT OF SCOPE for B2. AH1-App is executing F3 directly once Director ratifies.
- If you discover a fact-error in V0.2 amendment §A or §B during pre-work — STOP, surface to AH1 (lead) — do NOT improvise a code path that contradicts the brief.
- Tier-A → ratification path runs through `/security-review` PASS + B1 review verdict. Director nod on terminal merge typical for Tier-A.
