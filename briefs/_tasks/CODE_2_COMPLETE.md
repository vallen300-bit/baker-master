---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_AUTH_COMPLETION_1.md
brief_version: V0.4 (V0.5 §T doc-prose fold; F1 scope unchanged)
scope: F1 ONLY (handler edit + 8 tests). F3 = AH1-App-EXECUTED (12/12 keys live as of dep-d7tefirtll9c73bvdovg).
trigger_class: TIER_A_AUTH_TOUCHING
dispatched_at: 2026-05-06T07:2XZ
dispatched_by: ai-head-a (lead)
target_branch: b2/brisen-lab-auth-completion-1
target_repo: vallen300-bit/brisen-lab (NOT baker-master)
review_chain_mandatory:
  - feature-dev:code-architect (post-WRITE design review)
  - feature-dev:code-reviewer (standard pass)
  - feature-dev:code-reviewer SECOND PASS (auth-touching trigger)
  - /security-review (auth-touching → mandatory; AH2 lane)
  - B1 SITUATIONAL REVIEW (auth-touching trigger fires per ai_head_b1_review_triggers.md)
ship_gate: ACs A1+A3+A4+A5+A6+A12+A13 all GREEN per V0.4 brief
---

# CODE_2_PENDING — BRIEF_BRISEN_LAB_AUTH_COMPLETION_1 — F1 (V0.4 architect+reviewer-folded, V0.5 doc-prose; 2026-05-06)

## Mailbox

- **Brief:** `briefs/BRIEF_BRISEN_LAB_AUTH_COMPLETION_1.md` on baker-master `main` (latest commit on that file).
- **Read top-to-bottom — including ALL amendments**. V0.4 amendment text is AUTHORITATIVE over V0.1 body wherever they conflict.
- **Scope for B2:** F1 ONLY. F3 (12-key provisioning) is COMPLETE — AH1-App shipped 2026-05-06. Do NOT touch Render env, 1Password, or zshrc.

## What you're building (F1)

**Repo:** `~/bm-b4-brisen-lab` (or your preferred clone of `vallen300-bit/brisen-lab`). NOT `baker-master`.

**Branch:** `b2/brisen-lab-auth-completion-1` (do NOT clobber existing b2/* branches).

**Files modified (per V0.2 §A + V0.3 §K):**

1. `bus.py` — ONE handler edit on `GET /msg/{terminal}` (lines 298-349). Add IMMEDIATELY after `reader_slug = _require_worker_slug(x_terminal_key)`:

   ```python
   if reader_slug != terminal:
       raise HTTPException(status_code=403, detail="reader_slug_mismatch")
   ```

   **PLUS — V0.3 §K broadcast OR-branch verification gate (MANDATORY EXPLORE step):**
   - Read `bus.py:330-340` (SQL clause-builder section).
   - Determine: does the `to_terminals` filter clause include `OR '*' = ANY(to_terminals)` already?
     - **Variant A (present):** no SQL change needed — single recipient-bind check above is the whole edit.
     - **Variant B (absent):** Edit 1 expands — extend the SQL clause to add the OR-branch:
       ```python
       clauses = ["(%s = ANY(to_terminals) OR '*' = ANY(to_terminals))"]
       params: list[Any] = [terminal]
       ```
   - Surface the variant determination in the PR body before merge (AC A14).
   - Do NOT touch the ack handler at line 442-463 — V0.2 §A struck Edit 2; ack already enforces with `_is_director` exemption.

2. `tests/test_inbox_read_authz.py` (NEW) — **8 tests per V0.4 §L+§M (AUTHORITATIVE — overrides V0.1 6-test list which is SUPERSEDED in the brief):**

   | # | Test name | Setup | Caller | Expect |
   |---|---|---|---|---|
   | 1 | `test_get_msg_self_succeeds` | post msg `to=['lead']` from director | lead's key, GET `/msg/lead` | 200 + msg in list |
   | 2 | `test_get_msg_cross_terminal_403` | post msg `to=['cowork-ah1']` from lead | lead's key, GET `/msg/cowork-ah1` | 403 `detail="reader_slug_mismatch"` |
   | 3 | `test_get_msg_no_key_401` | (no setup) | no `X-Terminal-Key` header, GET `/msg/lead` | 401 (regression) |
   | 4 | `test_get_msg_self_broadcast_succeeds` | DB-seed msg `to=['*']` from director | lead's key, GET `/msg/lead` | 200 + broadcast msg in list |
   | 5 | `test_ack_self_addressed_succeeds` | post msg `to=['cowork-ah1']` from lead | cowork-ah1's key, POST `/msg/<id>/ack` | 200 (regression) |
   | 6 | `test_ack_not_in_recipients_403` | post msg `to=['cowork-ah1']` from lead | lead's key, POST `/msg/<id>/ack` | 403 (regression) |
   | 7 | `test_get_msg_cross_slug_attack_403` | post msg `to=['lead']` from director; **third-slug key created INLINE** (`secrets.token_urlsafe(32)` + insert into test DB worker registry) | inline-created third-slug key, GET `/msg/lead` | 403 `detail="reader_slug_mismatch"` |
   | 8 | `test_ack_director_exemption_succeeds` | post msg `to=['cowork-ah1']` from lead | director's key, POST `/msg/<id>/ack` | 200 (`_is_director` exemption regression) |

   **Test 7 conftest discipline (V0.4 medium-fold):** third-slug key MUST be created INLINE; do NOT read from env. Reading from env will fail with 401 (key absent in test DB worker registry) instead of 403 — wrong signal.

## Trigger class + review chain (MANDATORY)

This is auth-touching → triggers full chain per `feedback_ai_head_b1_review_triggers.md`:

1. After your write: `feature-dev:code-architect` post-WRITE pass (you invoke).
2. After local pytest GREEN (8 tests against `TEST_DATABASE_URL_BRISEN_LAB`): `feature-dev:code-reviewer` standard pass.
3. **Second-pass `code-reviewer` on the diff** (auth-touching trigger; not optional).
4. **`/security-review`** — AH2 lane runs this on the PR; do NOT merge until verdict PASS.
5. **B1 SITUATIONAL REVIEW** — B1 picks up the PR per ai_head_b1_review_triggers.md.

## Pre-work

- Run `git pull && git status` in your brisen-lab clone (verify clean main).
- `git checkout -b b2/brisen-lab-auth-completion-1`.
- **Read the WHOLE brief — V0.1 body + V0.2 + V0.3 + V0.4 + V0.5 amendments.** V0.4 IN-PLACE edits (Sequencing §2, AC table, V0.1 test-list SUPERSEDED notice, etc.) make later amendments authoritative wherever they conflict with body.
- Re-read `bus.py:298-349` AND `bus.py:442-463` AND `bus.py:330-340` (broadcast SQL clause).

## Definition of done

- Variant A or B determination surfaced in PR body (AC A14).
- ACs A1, A2, A3 (8 tests pass), A4, A5, A6 from the V0.4 brief all GREEN.
- A12 (`feature-dev:code-reviewer` standard pass) verdict pasted in PR.
- A13 (`/security-review`) verdict pasted in PR.
- Ship-report at `briefs/_reports/B2_brisen_lab_auth_completion_1_F1_<date>.md` per SKILL.md.
- Mailbox flipped to COMPLETE on merge (§3 hygiene).

## Notes

- F3 is DONE (AH1-App execute, 2026-05-06 — 12/12 keys live, dep-d7tefirtll9c73bvdovg LIVE). DO NOT touch Render env, 1Password, or zshrc launchers.
- Tier-A → ratification path runs through `/security-review` PASS + B1 review verdict. Director nod on terminal merge typical for Tier-A.
- If you discover a fact-error in V0.2/V0.3/V0.4 amendments during pre-work — STOP, surface to AH1 (lead) before any code change.
