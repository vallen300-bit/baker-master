---
title: B2 PR #7 Phone Fix Delta — APPROVE
voice: report
author: code-brisen-2
created: 2026-04-18
---

# PR #7 Phone Fix Delta Re-verify (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task C-delta-phone
**Commit:** `4780a40` on branch `layer0-impl` ("fix(LAYER0-IMPL S1): strip 00 international-dial prefix in `_normalize_phone`")
**Diff:** `7342617..4780a40` on `baker/director_identity.py` + `tests/test_director_identity.py`
**Prior review:** [`B2_pr7_review_20260418.md`](B2_pr7_review_20260418.md) — S1 filed
**Date:** 2026-04-18
**Time:** ~5 min (focused delta check)

---

## Verdict

**APPROVE.** S1 closed exactly as my original recommended option (a) — strip leading `00` after digit extraction. Fix is 3 lines; docstring rewritten with correct reasoning (`00` is the international-dial prefix, E.164 alternate to `+`, used across Europe/Africa/Asia) replacing the original "Swiss trunk-prefix" framing which was factually incorrect. +4 parametrized tests split across both `test_normalize_phone_strips_non_digits` and `test_director_whatsapp_recognized_all_formats`. Local pytest run: **88 passed, 1 skipped in 0.24s** — matches B1's claim verbatim.

| Item | Status |
|---|---|
| `_normalize_phone` strips leading `00` after digit extraction | ✓ 3-line implementation (`if digits.startswith("00"): digits = digits[2:]`) |
| Docstring corrected from "Swiss trunk-prefix" to "international-dial prefix (E.164 alternate to `+`)" | ✓ Accurate; also notes GSM-client / calendaring-app emission |
| `0041 79 960 50 92` → `41799605092` | ✓ matches canonical `DIRECTOR_PHONES` |
| `0041799605092` → `41799605092` | ✓ same |
| Tests added at both normalization layer and integration layer (WhatsApp recognition) | ✓ Both `test_normalize_phone_strips_non_digits` (+2 params) and `test_director_whatsapp_recognized_all_formats` (+2 params) |
| 88/88 new + 1 live-PG skip locally | ✓ Verified: `88 passed, 1 skipped in 0.24s` |
| No regressions on existing 84 tests | ✓ (subset of the 88) |

**C2 author-authority gap closed.** The `0041`-serialization edge case I flagged in my original PR #7 review (S1) — "a Director handset or client using `00` international dialing would bypass `is_director_sender`, proceed to rule walk, and potentially drop Director's own message" — is now mechanically impossible. This was the single structural concern on PR #7; with it resolved, the PR is ship-ready.

**Nice-to-haves N1-N5 from the original review remain open** — they're independent of S1 and can land in a future touch (or bundled into the `pipeline_tick` wiring ticket per my pre-flag: pin N1/N2 side-effect-failure contract + N5 `_kbl_conn` payload-key reservation + `Signal(payload=None)` defensive default).

PR #7 is now mergeable. The fix docstring frames `00` correctly as an international-call prefix, which also makes this change generalize beyond Switzerland — any country's E.164 number reached via `00` routing (most of the world outside North America's `011`) now canonicalizes correctly in `_normalize_phone`.

---

*Delta-reviewed 2026-04-18 by Code Brisen #2. Diff `7342617..4780a40`. Tests run locally in `/tmp/bm-b2/.venv` on branch `layer0-impl` @ `4780a40`: 88 passed, 1 skipped (live-PG). 5-min focused check per task brief.*
