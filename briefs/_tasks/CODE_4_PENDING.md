# CODE_4_PENDING — dispatch (supersedes prior)

dispatch: BOX5_OUTBOUND_CORRELATION_FIX_1
brief: briefs/BRIEF_BOX5_OUTBOUND_CORRELATION_FIX_1.md
to: b4
from: lead
dispatched_by: lead
ship_to: lead (ship report + gate verdicts to lead)
branch: box5-outbound-correlation-fix-1
class: production bug fix, additive/corrective (connector stays DARK, flag rolled back to false)
effort: high

summary: Fix the live defect your canary #4881 caught. correlate() step 4 (_correlate_dispatcher_flight) queries dispatcher_bus_threads.thread_key (does not exist; real col = bus_thread_id) with status IN ('open','waiting_reply') (wrong; prod status incl. 'replied'). to_regclass guard passes -> UndefinedColumn -> the except returns None WITHOUT conn.rollback() -> under the shared no-commit txn the txn aborts -> next _update_event raises InFailedSqlTransaction uncaught -> every ratifying AND routine outbound errors in prod. Two fixes: (A) column bus_thread_id + real status vocabulary (grep dispatcher writer); (B) SAVEPOINT-guard every defensive correlation read so a read error can't abort the shared txn (bare conn.rollback would discard prior good writes). Fixture fidelity is part of the fix: the unit fixture masked the schema mismatch — make dispatcher_bus_threads fixture schema-accurate to prod + add repro/regression tests. Full envelope + AC in the brief.

status: lead rolled AIRPORT_OUTBOUND_INGEST_ENABLED back to false (verified) — connector dark. This fix does NOT flip it; lead re-activates + re-canaries after gate+merge.

gate: G1 self-check -> codex G3 on BUS (topic gate/box5-outbound-correlation-fix-g3, effort HIGH) -> lead G4 /security-review -> lead squash-merge.
