# B4 ship report — ARM alarm semantic consumer (micro-lane lead #10630)

- **Brief:** micro-lane off ARM_OUT_OF_BAND_ALARM_1, opened by lead #10630 (from my follow-on flag #10621).
- **PR:** #556 (b4/arm-alarm-semantic-consumer → main). Commit e654ef1f.
- **Dispatcher / reply target:** lead. Gate: codex (effort medium) → lead merge.

## Done rubric
- `semantic` wired as a real 3rd kind in `arm_alarm_check.sh`: freshness field `evaluated_at`, FIRE on `semantic_ok=false` (mirrors canary `ok=false`), stale past max-age. SOURCES row added for `semantic.json`.
- **Rider (a)** — absent `semantic.json` = TRUE silent skip (no verdict, no AMBER, no log) until `ARM_ALARM_SEMANTIC_ENFORCE=1`; present marker always evaluated. Enforce-flip to coordinate with b2 on evaluator cadence.
- **Rider (b)** — additive only; report/canary byte-identical (field map defaults non-report/canary → `checked_at`). Regression 2–16 unchanged + green.
- Marker-version guard: unknown `schema` major → skipped, not paged; missing `schema` tolerated.

## Test evidence
`bash scripts/tests/test_arm_alarm.sh` →
```
arm_alarm tests: 66 passed, 0 failed
```
52 prior + 14 new (silent-skip, semantic_ok=false, stale, healthy, unknown-schema, enforce=1 MISSING policy). `bash -n` clean on worker + suite. Non-bus invariant test still green.

## Coordination
- Told b2 (#10619) to hold the consumer-row edit — consumer lives in my file. b2's marker-writer side unblocked (my reader uses explicit filenames, no glob).
- Consumer is inert until b2's writer lands + `ARM_ALARM_SEMANTIC_ENFORCE=1`; POST_DEPLOY_AC deferred to enforce-flip time.

## Marker contract consumed (v1)
`{"schema":"semantic_delivery_verdict_v1","evaluated_at":"<iso8601>","semantic_ok":bool, ...}` — only `schema`/`evaluated_at`/`semantic_ok` are load-bearing for this consumer; other b2 fields (checks/failures/receipt_epoch/canary_epoch) are ignored. No SPEC-delta needed beyond `semantic_ok`+`evaluated_at`.
