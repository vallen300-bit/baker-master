# KBL-A Brief v2 — R2 Narrow-Scope Review

**From:** Code Brisen #1
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_1_PENDING.md`](../_tasks/CODE_1_PENDING.md) @ commit `011a55f`
**Date:** 2026-04-17
**Target:** `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md` @ commit `4efca68` (1722 lines)
**Related commits:** `8782813` (schema v3), `52e2653` (B2 schema report)
**Time spent:** ~25 min

---

## TL;DR

**1 new BLOCKER / 3 new SHOULD-FIX / 0 blockers regressed.** All 6 R1 blockers genuinely resolved. Sampled R1 should-fixes (S3/S4/S7/S8/S9/S10) all applied cleanly. Verdict: **fast v3 revision** (1-2 band). The single new blocker is a one-line spec fix in §2 Deliverables (kbl/db.py points to a `.conn` attribute that doesn't exist on `SentinelStoreBack`). Not architectural; 10-min fix.

---

## (a) R1 Blocker Verification

| # | Expected Fix | Verified at | Status |
|---|---|---|---|
| **B1** `started_at` column | §5 line 247: `ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ` | line 247 | ✅ |
| **B2** "NOW()" literal | §12 line 1481: `datetime.now(timezone.utc).isoformat()`; §10 line 1086 same for `qwen_active_since`; `pipeline_tick.main()` removes the heartbeat write entirely (S7) | lines 1481, 1086, 672-674 | ✅ |
| **B3** `__main__` dispatchers | §9 line 908: `gold_drain.py` has `if __name__ == "__main__": drain_queue()`. §12 line 1446: `logging.py` has argv dispatcher with `level_map` + usage message | lines 908, 1446-1470 | ✅ |
| **B4** Gold push failure rollback | §9 line 756-822: `drain_queue` reordered: (1) claim rows, (2) apply filesystem, (3) commit+push with retry, (4) mark PG done ONLY after push success. Push failure → `git reset --hard HEAD~1` + `git checkout HEAD -- <paths>` → rows stay pending → next drain retries | lines 756-822 + 859-904 | ✅ |
| **B5** FileHandler import safety | §12 line 1378-1390: try/except around `FileHandler` creation; falls back to `StreamHandler(sys.stderr)` + stderr warning message | lines 1378-1390 | ✅ |
| **B6** Model-key normalizer | §11 line 1223: `_model_key()` defined, called at estimate_cost (line 1264) AND log_cost_actual (line 1288). Raises `ValueError` on unknown model (better than silent $0) | lines 1223-1235, 1264, 1288 | ✅ |

**All 6 R1 blockers resolved. Implementations match the spec in the R1 Review Response Log table.**

**Notable bonus:** `_model_key` raises on unknown model rather than returning silent zeros — stricter than requested and more resilient.

---

## (b) Should-Fix Spot-Checks

Sampled 6 (random-ish, including the two I was most skeptical would land cleanly):

| # | Spot-check result |
|---|---|
| **S3** `git add` specific paths | §9 line 865-866: `for path in promoted_paths: git add path`, never `-A`. ✅ |
| **S4** Commit message audit trail | §9 line 869-873: `msg_lines` includes `path + queue_id + wa_msg_id` per row. ✅ |
| **S7** Heartbeat single owner | §8 line 672-674: explicit NOTE that pipeline_tick does NOT write `mac_mini_heartbeat`. §12 line 1473-1484: `kbl/heartbeat.py` is the sole owner. ✅ at the code level, ❌ at the acceptance-test level (see NEW-S2 below). |
| **S8** Qwen recovery hours trigger | §10 line 1141-1151: either-condition logic `count_trigger OR hours_trigger`, computes `elapsed_hours` from ISO-parsed `qwen_active_since`, ValueError → count-based only. ✅ |
| **S9** Ollama timeout bumped | §10 line 1114: `timeout=180` in `_call_ollama`. ✅ |
| **S10** purge.log rotated | §6 line 401: `/var/log/kbl/purge.log 644 7 1024 * J` in newsyslog-kbl.conf. ✅ |

**Sample passes clean. No drift between the Response Log claims and the code.**

---

## (c) New-Blocker Scan (v2 delta ~400 lines)

### NEW BLOCKER — `kbl/db.py` spec references non-existent attribute

**§2 Deliverables, line 125:**
```python
def get_conn(): return SentinelStoreBack().conn
```

`memory/store_back.py` has no `.conn` attribute. Verified via direct read:
- `__init__` initializes `self._pool = None` (line 60), then `self._pool = psycopg2.pool.SimpleConnectionPool(...)` (line 193)
- The conn getter is the private method `_get_conn()` (line 203) which returns a pool-owned connection requiring `putconn()` to release (line 224)
- All 20+ call sites inside `store_back.py` use `conn = self._get_conn()` + explicit `self._pool.putconn(conn)` pairs

**Impact:** every `from kbl.db import get_conn; with get_conn() as conn:` in the brief (pipeline_tick, gold_drain, retry, cost, logging, runtime_state) raises `AttributeError` on first call. The fallback path in the spec only catches `ImportError`, not `AttributeError`, so it never fires.

**Additionally problematic**, even if `.conn` existed: the brief uses `with get_conn() as conn:` throughout. psycopg2 connection's `__exit__` commits/rollbacks but does NOT return to pool. Using `_get_conn()` directly would leak pool connections.

**Fix (suggested, ~10 min):** sidestep `SentinelStoreBack` for kbl code. `kbl/db.py`:

```python
import os
import psycopg2
from contextlib import contextmanager

@contextmanager
def get_conn():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    try:
        yield conn
    finally:
        conn.close()
```

Simple, short-lived connection per use, context-managed cleanly. Matches Mac Mini's use case (~one connection per tick) and Render's (many concurrent — Neon pool handles it). No coupling to `SentinelStoreBack`'s bootstrap side-effects (which include Qdrant, Voyage, and ~30 `_ensure_*` calls not needed in KBL Python paths).

Alternatively, if you want pool reuse on Render: expose `SentinelStoreBack._get_conn`/`_put_conn` as a contextmanager pair. More work; not worth it for Phase 1.

### Other structural scans (no new blockers)

- **Wrapper bash (§8 line 568-571):** M3 guard for missing `env.mac-mini.yml` — ✅ present, logs INFO and exits cleanly.
- **Dev-reset note (§15 line 1641-1647):** `TRUNCATE ... CASCADE` guidance — ✅ addresses B2 schema report concern #3.
- **`_ensure_*` ordering invariant (§5 line 275-286):** explicit numbered order, FK target tables first — ✅.
- **Inline FK form (§5 line 234-236):** matches `KBL_A_SCHEMA.sql` v3 @ `8782813` — ✅.
- **§2 Deliverables lists new `kbl/db.py` and `kbl/whatsapp.py`** — ✅ both spec'd, though kbl/db.py's spec is the new blocker above. `kbl/whatsapp.py` points to `triggers/waha_client.py` which exists — ✅.

---

## (d) B2 Schema Reconciliation Adoption

| Requirement | Verified at | Status |
|---|---|---|
| Adopt B2's inline FK form (auto-named) | §5 line 234-236 — `signal_id INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL` | ✅ |
| Match `KBL_A_SCHEMA.sql` v3 @ `8782813` | references `8782813` at line 232 | ✅ |
| `_ensure_*` ordering invariant documented | §5 line 275-286 — numbered list + rationale | ✅ |
| `TRUNCATE ... CASCADE` dev-reset note | §15 line 1639-1649 | ✅ |

**All four points land cleanly.**

---

## NEW FINDINGS SUMMARY

### BLOCKERS (must fix before ratification)

**NEW-B1 — `kbl/db.py` spec attribute error.** §2 line 125: `SentinelStoreBack().conn` — `.conn` doesn't exist on that class; all kbl modules' `get_conn()` calls would AttributeError. Fallback chain only handles ImportError. **Fix:** rewrite §2 line 125 spec to use a direct `psycopg2.connect(DATABASE_URL)` contextmanager (see snippet above). No architectural change; 1 paragraph edit in deliverables.

### SHOULD-FIX

**NEW-S1 — Duplicate `if __name__ == "__main__":` block in `pipeline_tick.py`.** §8 lines 708-712 shows the block twice back-to-back. First `sys.exit(main())` terminates so the second is dead code, but Code Brisen implementing verbatim would carry this forward. 2-line delete.

**NEW-S2 — Acceptance tests contradict S7 (heartbeat single-owner fix).**
- §8 line 720: "Heartbeat: after 1 tick, `mac_mini_heartbeat` is within last 2 min" — but pipeline_tick no longer writes heartbeat (S7). Only the 30-min dedicated agent does.
- §14 line 1591: "Heartbeat updates `mac_mini_heartbeat` every tick" — same contradiction.

**Fix:** replace with "after ≥35 min (first heartbeat-agent firing), `mac_mini_heartbeat` is within last 30 min" in both places. Tester running the original acceptance would false-positive a regression.

**NEW-S3 — Dead ternary in `gold_drain.py` log level.** §9 line 815:
```python
"WARN" if result.startswith("error") else "WARN",
```
Both branches identical. Two problems:
1. Intent was probably `"ERROR"` for error results.
2. Every Gold success emits WARN → PG `kbl_log`. Silver-matter has many successful promotions over time → `kbl_log` gets noise. Intended behaviour per S2 was "local-only for success; WARN+ only goes to PG."

**Fix:** `"ERROR" if result.startswith("error") else "WARN"` OR bypass `emit_log` for success path and log locally only.

---

## Verdict

**Per pass criteria table (from task file):**

| Result | Next step |
|---|---|
| 0 blockers | ratify → dispatch |
| **1-2 blockers** | **fast v3 revision** ← we are here |
| ≥3 blockers | stop, diagnose |

**Recommendation: fast v3 revision, narrow scope.** AI Head fixes:
1. NEW-B1: rewrite `kbl/db.py` spec paragraph in §2 line 125 (~10 min)
2. NEW-S1: delete duplicate `__main__` block in §8 (~1 min)
3. NEW-S2: reword acceptance tests lines 720 + 1591 (~5 min)
4. NEW-S3: fix the ternary + reconsider Gold-success log level (~5 min)

Total: ~20-30 min turnaround.

**R3 scope:** verify only these 4 items plus no regression. 10-min review max.

Architecture is solid. V2 delta is overwhelmingly clean — the 6 R1 blockers landed with no side-effects, and several pedantic should-fixes (S3/S4/S8) were implemented with care. The new blocker is a surface-level spec slip (one attribute name wrong); nothing about it reopens the underlying design.

**Not a "stop and diagnose" situation.** V2 is 85% of the way there.

---

*Filed by Code Brisen #1 via the `briefs/_reports/` mailbox pattern, 2026-04-17. Next task or ratification awaited.*
