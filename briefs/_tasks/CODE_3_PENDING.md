# CODE_3_PENDING — B3 REVIEW: PR #61 PROMPT_CACHE_AUDIT_1 — 2026-04-24

**Dispatcher:** AI Head (Team 1 — Meta/Persistence)
**Working dir:** `~/bm-b3`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/61
**Branch:** `prompt-cache-audit-1`
**Brief:** `briefs/BRIEF_PROMPT_CACHE_AUDIT_1.md` (dispatched in commit `566e843`, restored `d1096fd`)
**Status:** OPEN — peer review on B1's ship

**§2 pre-dispatch busy-check** (per 2026-04-24 coordination rule): B3 mailbox was `COMPLETE`, last branch `citations-api-scan-1` merged `bb2d709`. Idle — safe to dispatch.

**Supersedes:** prior mailbox state `COMPLETE — PR #59 merged bb2d709`.

---

## What this PR does

Ships M0 quintet row 4 — prompt-cache audit + top-3 cache_control + 24h hit-rate telemetry. 7 files.

**NEW:**
- `scripts/audit_prompt_cache.py` — AST-based static analysis. Audited 78 Claude call sites.
- `scripts/prompt_cache_hit_rate.py` — 24h aggregation, Slack alert <60%.
- `kbl/cache_telemetry.py` — fire-and-forget `log_cache_usage()` helper.
- `tests/test_prompt_cache_audit.py` — 8 scenarios.

**MODIFIED:**
- `outputs/dashboard.py` — `/api/scan` stable prefix → `cache_control: {"type": "ephemeral"}` + `log_cache_usage` wiring.
- `orchestrator/capability_runner.py` — same pattern.
- `baker_rag.py` — **skip-equivalent**: `BAKER_SYSTEM_PROMPT` at ~265 tokens is below Anthropic's 1024-token minimum cacheable prefix. Instrumented with telemetry only; no `cache_control` applied. Documented in B1 ship report.

B1 reported: 9/9 ship gate PASS. Regression delta 870→878 (+8 passes, 0 regressions).

---

## Your review job (charter §3 — B3 routes; Tier A auto-merge on B3 APPROVE + /security-review PASS)

### 1. Scope lock — exactly 7 files

```bash
cd ~/bm-b3 && git fetch && git checkout prompt-cache-audit-1 && git pull -q
git diff --name-only main...HEAD
```

Expect exactly these 7 paths (+ ship report under `briefs/_reports/` which is fine):

```
baker_rag.py
kbl/cache_telemetry.py
orchestrator/capability_runner.py
outputs/dashboard.py
scripts/audit_prompt_cache.py
scripts/prompt_cache_hit_rate.py
tests/test_prompt_cache_audit.py
```

**Reject if:** `kbl/anthropic_client.py` touched (brief: unchanged), `kbl/cost.py` touched, `memory/store_back.py` touched, or any model ID change anywhere.

### 2. Python syntax on all 7 files

```bash
for f in baker_rag.py kbl/cache_telemetry.py orchestrator/capability_runner.py outputs/dashboard.py scripts/audit_prompt_cache.py scripts/prompt_cache_hit_rate.py tests/test_prompt_cache_audit.py; do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo "FAIL: $f"; exit 1; }
done && echo "All 7 files clean."
```

Expect: `All 7 files clean.`

### 3. Imports smoke

```bash
python3 -c "from kbl.cache_telemetry import log_cache_usage; from scripts.audit_prompt_cache import CallSite; print('OK')"
```

Expect: `OK`.

### 4. Audit script runs end-to-end

```bash
python3 scripts/audit_prompt_cache.py --out /tmp/audit.md
grep -c "^| " /tmp/audit.md
head -15 /tmp/audit.md
```

Script exits 0, writes report, tiers table present.

### 5. 3 hot sites carry cache_control (OR documented skip for baker_rag)

```bash
grep -l "cache_control" outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py
```

Expect: `outputs/dashboard.py` + `orchestrator/capability_runner.py` in the output. `baker_rag.py` may or may not — B1 reported skip-equivalent (~265 tok < 1024). Verify via:

```bash
grep -nB2 -A3 "BAKER_SYSTEM_PROMPT\|cache_control" baker_rag.py | head -20
```

Expect: if `cache_control` NOT applied, a comment/docstring notes the below-threshold skip. If `cache_control` IS applied despite <1024 tokens, that's a mistake — flag.

### 6. cache_control block shape matches kbl/anthropic_client.py precedent

For each site that applies `cache_control`, `system=` kwarg should be a list of `{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}` blocks. Stable prefix → cached block; dynamic content (retrieval) → user message OR separate non-cached system block.

```bash
grep -B3 -A5 'cache_control.*ephemeral' outputs/dashboard.py | head -30
grep -B3 -A5 'cache_control.*ephemeral' orchestrator/capability_runner.py | head -30
```

Both should show the `{"type": "text", "text": <STABLE PREFIX>, "cache_control": {"type": "ephemeral"}}` pattern. Reject if cache_control is on retrieval/question content (would break caching — content changes per call).

### 7. `log_cache_usage()` is fire-and-forget

Open `kbl/cache_telemetry.py`:
- Wrapped in try/except (two levels per brief: usage parse + store.log_baker_action call).
- Returns None on failure, never raises.
- Does NOT block the Claude call flow — called AFTER `response = client.messages.create(...)`.

```bash
grep -c "try:\|except" kbl/cache_telemetry.py
```

Expect ≥2. Also confirm call-site integration in dashboard.py / capability_runner.py — `log_cache_usage` called AFTER the `client.messages.create()` return, NOT inside the try/except guarding the call itself.

### 8. 8 tests pass in isolation

```bash
pytest tests/test_prompt_cache_audit.py -v 2>&1 | tail -15
```

Expect `8 passed`. Test names cover: audit script exit-zero + report shape, audit identifies cached site, cache_control shape preserved, cache_control present in 3 hot sites (or skip on baker_rag), log_cache_usage fires baker_action, silent on missing store, silent on malformed usage, below_threshold classification.

### 9. Regression delta — 870 → 878

```bash
pytest tests/ 2>&1 | tail -3
```

Expect `<N> failed, 878 passed, <M> errors`. Delta = +8 passes, 0 new failures/errors vs main.

### 10. No baker-vault writes

```bash
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
```

Expect: `OK: no baker-vault writes.`

### 11. No new env vars / no schema changes

```bash
grep -n "os.environ\[\|getenv\(" kbl/cache_telemetry.py scripts/audit_prompt_cache.py scripts/prompt_cache_hit_rate.py | grep -v "ANTHROPIC_API_KEY\|BAKER_\|PRICE_OPUS"
```

Expect: zero brand-new env vars. Pre-existing ones (`ANTHROPIC_API_KEY`, `BAKER_VAULT_PATH`, `PRICE_OPUS*`) fine.

No DDL:
```bash
grep -E "CREATE TABLE|ALTER TABLE|ADD COLUMN" scripts/prompt_cache_hit_rate.py kbl/cache_telemetry.py
```

Expect: zero matches. `baker_actions` is reused as-is.

### 12. Singleton hook

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.`

---

## If 12/12 green

Post APPROVE on PR #61. AI Head (me) runs `/security-review` next + auto-merges on PASS.

Write ship report to `briefs/_reports/B3_pr61_prompt_cache_audit_1_review_20260424.md`. Include all 12 check outputs literal.

**§3 mailbox hygiene** runs post-merge: I mark `CODE_1_PENDING.md` COMPLETE for B1 after squash lands.

## If any check fails

`gh pr review --request-changes` with specific list. Route back to B1. Do NOT merge.

---

## Timebox

**~30–40 min.** 12 checks, mix of mechanical + spot inspection.

**Working dir:** `~/bm-b3`.

---

**Dispatch timestamp:** 2026-04-24 post-PR-61-ship (Team 1, M0 quintet row 4 B3 review)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → MAC_MINI_WRITER_AUDIT_1 (#53) → KBL_INGEST_ENDPOINT_1 (#55) → CITATIONS_API_SCAN_1 (#59) → **PROMPT_CACHE_AUDIT_1 (#61, this review)** — closes M0 row 4. **M0 quintet fully closed on this merge.**
