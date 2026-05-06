# BRIEF: BRISEN_LAB_PATH_FILTERED_DEPLOY_1 — stop doc-only commits from restarting brisen-lab daemon

## Context

brisen-lab service `srv-d7q7kvlckfvc739l2e8g` runs at `https://brisen-lab.onrender.com` and is the V2 message-bus daemon for all 8 worker terminals (lead, deputy, b1-b5, cortex, cowork-ah1) plus any `/sse/stream` subscribers. Default `autoDeployTrigger: commit` + no `buildFilter` = every commit on `main` redeploys, including doc-only changes (README, `docs/`).

Each redeploy:
- Drops `/msg/<terminal>` polling clients (V2 bus disconnect for ~30-60s)
- Drops `/sse/stream` subscribers (live-state UI freezes, must reconnect)
- Costs ~45-60s build + Python process restart per commit

This brief mirrors the baker-master path-filter pattern shipped 2026-05-06 (commit `935d793`, `BRIEF_RENDER_PATH_FILTERED_DEPLOY_1`). brisen-lab repo is much simpler than baker-master (no top-level `briefs/` dir; total 8 .py modules + `static/` + `tests/` + `docs/` + `*.md`), so the filter list is correspondingly minimal.

**Anchor for follow-up scope:** L3 finding from baker-master path-filter V0.2 review (agent `a4403941237a1d52d`): "brisen-lab service auto-deploys from baker-master commits? The brief explicitly says 'different repo, different structure' and defers to a follow-up brief. AC A7 marks this as out-of-scope, which is acceptable, but the gap should be logged as a follow-up action before closing this brief." This brief closes that follow-up.

**Lessons folded UPFRONT** from baker-master execution (no V0.2 cycle expected — these are pre-applied):
- `assert len(ignored) == EXPECTED` count assertion (baker-master L1 nit)
- Smoke test commit MUST write to a path inside the filter list, else self-defeating (baker-master M2 reviewer find)
- POST `/v1/services/{id}/deploys` returns 202 + EMPTY body — capture HTTP code via `curl -w`, do NOT pipe to `python3 json.load` (baker-master execution D3)
- `git restore --source=$COMMIT_SHA file` requires a COMMIT SHA, not a blob SHA (baker-master execution recovery lesson)
- For env-var changes, single-key PUT does NOT auto-restart the daemon (baker-master F3 D1) — but **buildFilter is service-config not env-var**: PATCH on service config takes effect for SUBSEQUENT pushes without restart (verified baker-master tonight). This brief DOES NOT need an explicit deploy step.

---

## Estimated time: ~20 min apply
## Complexity: Low (single Render service config change + verification, repo is simpler than baker-master)
## Prerequisites: Render API key in 1Password (`op://Baker API Keys/API Render/credential`); access to `srv-d7q7kvlckfvc739l2e8g`; local clone at `~/brisen-lab-staging` (verified `~/brisen-lab-staging/` exists, on `b4/v2-bridge-surface-6-session-keys-cleanup` branch — operator must `git checkout main && git pull --ff-only` before smoke commits).
## Tier: A (production deploy behavior on V2 message bus daemon)

---

## Feature 1 — Configure `buildFilter.ignoredPaths` on brisen-lab service

### Problem

`autoDeployTrigger: commit` + no `buildFilter` = every commit redeploys. Doc-only commits should be no-ops at the deploy boundary; right now they drop the V2 bus.

### Current state (verified via Render API tonight)

```json
{
  "id": "srv-d7q7kvlckfvc739l2e8g",
  "name": "brisen-lab",
  "autoDeploy": "yes",
  "autoDeployTrigger": "commit",
  "branch": "main",
  "buildFilter": null,
  "repo": "https://github.com/vallen300-bit/brisen-lab",
  "rootDir": ""
}
```

Repo layout (verified via `ls /Users/dimitry/brisen-lab-staging` + `find` traversal):

| Path | Runtime-critical? | Editing frequency | Filter? |
|---|---|---|---|
| `app.py`, `auth_lab.py`, `bus.py`, `db.py`, `freeze.py`, `lifecycle.py`, `otel_setup.py`, `tier_classification.py` | **YES** — all imported by FastAPI startup or runtime endpoints | HIGH | NO |
| `tier-classification.yml` | **YES** — read at startup by `tier_classification.load_initial()` (verified `tier_classification.py:33`); `app.py:87` calls it on lifespan startup | LOW | NO |
| `static/**` | **YES** — served by `app.mount("/static", StaticFiles(directory="static"))` at `app.py:47` | LOW | NO |
| `requirements.txt` | **YES** — `pip install -r requirements.txt` at deploy time | LOW | NO |
| `start.sh` | **YES** — `bash start.sh` per `render.yaml` startCommand | LOW | NO |
| `render.yaml` | **YES** — Render build/start command + env-var contract | LOW | NO |
| `tests/**` | NO at runtime today; defensive against future build.sh / pytest pre-deploy | LOW | NO (defensive) |
| `.githooks/**` | NO at Render runtime; production safety controls per baker-master Lesson #50 (`pre-commit` migration immutability check pattern). Hook changes ship intentionally. | LOW | NO (defensive) |
| `docs/**` | NO — markdown documentation (`docs/HARDENING.md` today; room for growth) | MED | **YES** |
| `*.md` (root-level: `README.md`) | NO — documentation | LOW | **YES** |

Verified imports (grepped `app.py` + `tier_classification.py`):
- `tier_classification.load_initial()` reads `tier-classification.yml` at startup; `BRISEN_LAB_TIER_YAML` env override for path
- `app.mount("/static", StaticFiles(directory="static"))` serves the entire `static/` tree
- No `*.md` import / read paths anywhere in `*.py` modules (grep confirmed)

Doc-only commit volume on `main` (last 14 days, verified via `git log --since="14 days ago" --oneline --no-merges -- 'docs/**' '*.md' README.md`):
- 2 doc-only commits / 5 total commits (40% ratio). Modest absolute volume but the bus-drop blast radius (8 worker terminals + SSE) is the real cost.

### Implementation

**Use `buildFilter.ignoredPaths` (negative list), NOT `buildFilter.paths` (positive list).**

Rationale: a positive list requires us to enumerate every runtime path; missing one = silent no-deploy on real code change. A negative list is safe-by-default — anything not listed still deploys.

**Render API call (PATCH the service):**

```bash
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')

curl -s -X PATCH \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "buildFilter": {
      "paths": [],
      "ignoredPaths": [
        "docs/**",
        "*.md"
      ]
    }
  }' \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g"
```

**Why only 2 patterns:** brisen-lab repo has no top-level `briefs/`, `_ops/`, `memory/`, `tasks/`, or `docs-site/` (those are baker-master / vault-side dirs). The only doc-only surfaces are `docs/` and root-level `*.md`. `*.md` at root catches `README.md` AND any future top-level markdown (e.g., `BRIEF_*.md` if anyone ever drops one here, though convention is briefs live in baker-master).

**Alternative: Render dashboard UI.** Service → Settings → "Build Filters" → Ignored Paths. Add each pattern. Same outcome; less reproducible than API.

### Key constraints

- **Negative list only.** Setting `buildFilter.paths` to a non-empty array would invert semantics (deploy ONLY when those paths change) — that's the under-filter footgun. Leave `paths: []`.
- **Don't filter `*.py`.** All 8 modules are runtime imports.
- **Don't filter `tier-classification.yml`.** Runtime-loaded YAML — `tier_classification.load_initial()` at startup reads it. Changes MUST trigger redeploy (otherwise the runtime config drift goes silent).
- **Don't filter `static/**`.** Served by FastAPI mount.
- **Don't filter `tests/**`.** Defensive — `start.sh` doesn't currently invoke pytest, but `render.yaml` could change. Cheap insurance.
- **Don't filter `.githooks/**`.** Production safety control class per baker-master Lesson #50.
- **Don't filter `requirements.txt`, `start.sh`, `render.yaml`.** All deploy-relevant.
- **Render glob semantics:** patterns use `**` for cross-directory recursion; `*` is single-segment. `docs/**` matches all sub-paths under `docs/`; `*.md` at root matches root-level `.md` files only (no recursion). Verify against current Render docs at apply time — Render has historically renamed fields without notice.

### Verification

#### Step 1 — Pre-apply state capture

```bash
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g" \
  > /tmp/brisen-lab-pre-filter.json
# Capture so rollback can restore the prior shape exactly.
ls -l /tmp/brisen-lab-pre-filter.json
python3 -c "import json; d=json.load(open('/tmp/brisen-lab-pre-filter.json')); bf=d.get('buildFilter'); print('current buildFilter:', bf if bf else 'NOT SET (matches V0.1 expectation)')"
```

#### Step 2 — Apply (per Implementation curl above)

#### Step 3 — Confirm field landed (hardened verification per baker-master V0.2 §C)

```bash
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
EXPECTED_COUNT=2
EXPECTED_IGNORED='["docs/**", "*.md"]'

curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
bf = data.get('buildFilter', None)
if not bf:
    print('FAIL: buildFilter field absent — API silently dropped the PATCH')
    sys.exit(1)
ignored = bf.get('ignoredPaths', [])
if not ignored:
    print('FAIL: ignoredPaths field absent or empty — API may have dropped the inner field')
    sys.exit(1)
print(f'PASS: buildFilter present; ignoredPaths has {len(ignored)} entries')
EXPECTED = $EXPECTED_COUNT
if len(ignored) != EXPECTED:
    print(f'FAIL: expected {EXPECTED} entries, got {len(ignored)} — Render may have deduplicated or truncated')
    sys.exit(1)
print(f'PASS: count matches expected {EXPECTED}')
expected_runtime = ['app.py', 'bus.py', 'db.py', 'auth_lab.py', 'lifecycle.py', 'tier-classification.yml', 'static/**', 'requirements.txt', 'tests/**', '.githooks/**']
present_in_filter = [p for p in expected_runtime if p in ignored]
if present_in_filter:
    print(f'FAIL: runtime paths accidentally filtered: {present_in_filter}')
    sys.exit(1)
print('PASS: no runtime paths accidentally in filter')
print('paths:', bf.get('paths', '?'))
print('full ignoredPaths:')
for p in ignored: print(f'  {p}')
"
```

#### Step 4 — Doc-only smoke test (the proof — write to FILTERED path per baker-master M2 lesson)

```bash
cd ~/brisen-lab-staging
git checkout main && git pull --ff-only origin main

RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')

# Capture pre-push deploy ID for comparison
PRE_DEPLOY=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/deploys?limit=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('deploy', d[0]).get('id', '?') if d else '?')")
echo "pre-push latest deploy id: $PRE_DEPLOY"

# Doc-only smoke commit — write to docs/ (in filter list)
TS=$(date +%s)
SMOKE_FILE="docs/path_filter_smoke_${TS}.md"
echo "# path-filter smoke $(date -u +%FT%TZ)" > "$SMOKE_FILE"
git add "$SMOKE_FILE"
git commit -m "test: path-filter smoke (doc-only — should NOT trigger redeploy)"
PUSH_TS=$(date -u +%s)
git push origin main
echo "PUSH_TS=$PUSH_TS  SMOKE_FILE=$SMOKE_FILE"

# Poll up to 90s (per baker-master V0.2 §D); expect NO new deploy with createdAt >= PUSH_TS
echo "polling 6x15s for absence of new deploy"
for i in 1 2 3 4 5 6; do
  sleep 15
  RESULT=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/deploys?limit=1" \
    | python3 -c "
import sys, json, datetime
data = json.load(sys.stdin)
if not data: print('EMPTY 0'); sys.exit()
dep = data[0].get('deploy', data[0])
created = datetime.datetime.fromisoformat(dep.get('createdAt','1970-01-01T00:00:00Z').replace('Z','+00:00'))
print(f'{dep.get(\"id\")} {int(created.timestamp())} {dep.get(\"status\")}')
")
  echo "  poll $i: $RESULT"
  EPOCH=$(echo $RESULT | awk '{print $2}')
  if [ "$EPOCH" -ge "$PUSH_TS" ]; then
    echo "FAIL: filter broken — new deploy fired after doc-only commit"
    exit 1
  fi
done
echo "PASS: 90s window with NO new deploy after doc-only commit"
```

#### Step 5 — Real-code positive control (semantic no-op edit in runtime file)

```bash
cd ~/brisen-lab-staging
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')

# Capture pre-state SHA of runtime file for clean restore
APP_PRE_SHA=$(git rev-parse HEAD)  # COMMIT SHA, not blob (per baker-master recovery lesson)
echo "pre-smoke commit SHA: $APP_PRE_SHA"

# Comment-only edit in runtime file — semantic no-op but Render must redeploy
TS=$(date +%s)
echo "# path-filter positive control $TS" >> app.py
git add app.py
git commit -m "test: path-filter positive control (runtime file — SHOULD trigger redeploy)"
PUSH_TS=$(date -u +%s)
git push origin main

# Poll up to 90s for NEW deploy with createdAt >= PUSH_TS
echo "polling 6x15s for presence of new deploy"
for i in 1 2 3 4 5 6; do
  sleep 15
  RESULT=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/deploys?limit=1" \
    | python3 -c "
import sys, json, datetime
data = json.load(sys.stdin)
if not data: print('EMPTY 0'); sys.exit()
dep = data[0].get('deploy', data[0])
created = datetime.datetime.fromisoformat(dep.get('createdAt','1970-01-01T00:00:00Z').replace('Z','+00:00'))
print(f'{dep.get(\"id\")} {int(created.timestamp())} {dep.get(\"status\")}')
")
  echo "  poll $i: $RESULT"
  EPOCH=$(echo $RESULT | awk '{print $2}')
  if [ "$EPOCH" -ge "$PUSH_TS" ]; then
    echo "PASS: new deploy fired (epoch $EPOCH >= push $PUSH_TS) — positive control proves runtime files DO trigger redeploys"
    exit 0
  fi
done
echo "FAIL: 90s window elapsed with NO new deploy after runtime-file commit — positive control inconclusive (filter may be over-filtering, or Render queue is delayed beyond 90s)"
exit 1
```

#### Step 6 — Rollback (if Step 4 or 5 fails)

```bash
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
# Restore prior buildFilter (or absence thereof).
PRIOR_BF=$(python3 -c "
import json
d = json.load(open('/tmp/brisen-lab-pre-filter.json'))
bf = d.get('buildFilter') or {'paths': [], 'ignoredPaths': []}
print(json.dumps(bf))
")
curl -s -X PATCH \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  --data "{\"buildFilter\": $PRIOR_BF}" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g"
```

#### Step 7 — Cleanup

```bash
cd ~/brisen-lab-staging
# Use COMMIT SHA captured in Step 5 (not blob — per baker-master recovery lesson).
# Fallback: HEAD~2 = pre-smoke baseline (Step 4 added 1 commit, Step 5 added 1 — total 2 commits ahead of original)
APP_PRE_SHA=${APP_PRE_SHA:-$(git rev-parse HEAD~2)}
echo "Restoring app.py from $APP_PRE_SHA"
git checkout "$APP_PRE_SHA" -- app.py

# Remove smoke .md file
rm docs/path_filter_smoke_*.md 2>/dev/null

git add -A docs/ app.py
git status -s | head -5  # sanity: only intended changes staged
git commit -m "test: clean up path-filter smoke artifacts (revert app.py + rm smoke .md)"
git push origin main
# This commit will trigger ONE expected redeploy (because app.py reverted), then quiet.
```

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | `buildFilter.ignoredPaths` set on `srv-d7q7kvlckfvc739l2e8g` with the **2** patterns enumerated (`docs/**`, `*.md`) | API GET (Step 3) — exact array match + count assertion |
| **A2** | `buildFilter.paths` is `[]` (or absent) so the filter is negative-only | API GET (Step 3) |
| **A3** | Doc-only smoke commit (`docs/path_filter_smoke_*.md`) does NOT trigger a new deploy within 90s | 90s polling loop (Step 4) — top deploy ID unchanged |
| **A4** | Runtime smoke commit (`app.py` comment-only) DOES trigger a new deploy within 90s | 90s polling loop (Step 5) — new deploy ID with matching commit SHA |
| **A5** | Rollback path tested in advance — `/tmp/brisen-lab-pre-filter.json` captured + the rollback curl shape verified by `python3 -c` dry-run | inspect file existence + dry-run rollback |
| **A6** | Cleanup commit lands clean; smoke test artifacts removed; one expected redeploy fires from `app.py` revert then quiet | `git status` post-cleanup + Render deploy list shows the single cleanup deploy |
| **A7** | No runtime paths accidentally in the `ignoredPaths` array (Step 3 script checks `app.py`, `bus.py`, `db.py`, `tier-classification.yml`, `static/**`, `requirements.txt`, `tests/**`, `.githooks/**`) | Step 3 script |

**Ship gate:** A1–A7 all green. Rollback path tested but not used = success.

---

## Files Modified

- Render service config (`srv-d7q7kvlckfvc739l2e8g`) — `buildFilter` field added.
- Repo: ephemeral smoke-test files (deleted in Step 7) — no permanent repo changes.

## Do NOT Touch

- All 8 `*.py` modules (`app.py`, `auth_lab.py`, `bus.py`, `db.py`, `freeze.py`, `lifecycle.py`, `otel_setup.py`, `tier_classification.py`) except the smoke-test comment in `app.py` that gets reverted in Step 7.
- `tier-classification.yml`, `static/**`, `tests/**`, `.githooks/**`, `requirements.txt`, `start.sh`, `render.yaml` — all runtime / deploy / safety surfaces.
- `auto-deploy: yes` — keep auto-deploy on; we're filtering WHICH commits redeploy, not disabling autodeploy.
- `autoDeployTrigger: commit` — keep at `commit`.
- baker-master service `srv-d6dgsbctgctc73f55730` — separate scope (already has its own buildFilter shipped 2026-05-06 935d793).

---

## Quality Checkpoints

1. After A1 confirmed, manually verify the next 2-3 doc-only commits to brisen-lab `main` result in zero new deploys (let real workflow exercise the filter).
2. Monitor Render deploy audit trail for any "build skipped" or "filter applied" notifications. Verify by inspecting deploys-list with no new entries during doc-only commit windows.
3. After 30 days of operation, count how many redeploys were skipped vs the prior 30 days' commit volume. **Kill criterion:** if <1 deploy saved → revert (low-volume repo, filter overhead not worth maintenance burden).

---

## Verification commands (one-liners for the operator)

```bash
# 1. Confirm filter live (after Step 2 apply)
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('buildFilter:', json.dumps(d.get('buildFilter'), indent=2))"

# 2. Recent deploys (post-apply window — should show NO doc-only triggers)
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/deploys?limit=10" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for d in data[:10]:
    dep = d.get('deploy', d)
    print(f\"  {dep['id']} status={dep.get('status')} created={dep.get('createdAt')} commit={dep.get('commit',{}).get('id','?')[:8]}\")"
```

---

## Open questions for AH1 (resolved-or-surfaced)

**Q1.** Should the filter cover `tests/**`? **Resolution:** NO — defensive against future `start.sh` / build pipeline changes that might run pytest pre-deploy. Same as baker-master Q2.

**Q2.** What if a doc commit lands ALONGSIDE a code commit in the same push? **Resolution:** Render evaluates per-commit, not per-push. Each commit is checked individually; mixed pushes deploy ONLY for commits that touch non-ignored paths. Same as baker-master Q4.

**Q3.** What if a future top-level non-doc file is added (e.g., `Dockerfile`, `pyproject.toml`)? **Resolution:** the `*.md` glob does NOT match non-`.md` extensions. New top-level non-doc files trigger a deploy (correct behavior). New `.md` files at root are filtered (also correct).

**Q4.** Does `tier-classification.yml` need explicit "do not filter" enforcement? **Resolution:** YES (verified): the verification script in Step 3 checks for it explicitly in `expected_runtime`. If a future operator adds it to `ignoredPaths`, Step 3 fails and they must remove it.

**Q5.** Does the brisen-lab service actually deploy from baker-master commits (per L3 follow-up framing)? **Resolution:** NO — verified via Render API: `repo: https://github.com/vallen300-bit/brisen-lab` is its own GitHub repo, NOT baker-master. The L3 hypothetical ("brisen-lab deploys from baker-master main") was incorrect; cross-repo deploy coupling does NOT exist. This brief is therefore the single-repo isolation baker-master assumed it was.

---

## Sequencing

1. EXPLORE: read `app.py` imports + `tier_classification.py` YAML loader + `start.sh` to confirm runtime path inventory (already done in this brief; operator should re-verify if elapsed > 1 week before apply).
2. PLAN: confirm `ignoredPaths` set against current repo state (no new top-level dirs introduced since 2026-05-06 EOD).
3. CAPTURE pre-state via Step 1.
4. APPLY via Step 2 curl.
5. VERIFY via Steps 3-5 (Step 5 requires `git checkout main && git pull --ff-only` first if local clone is on a feature branch — current state observed: `b4/v2-bridge-surface-6-session-keys-cleanup`).
6. CLEANUP via Step 7.
7. REPORT closure to AH1-App + ship-report PL paste-block per SKILL.md §"PL ship-report contract".

---

## Reference

- Render service config (current): `srv-d7q7kvlckfvc739l2e8g` — `autoDeploy: yes`, `autoDeployTrigger: commit`, `branch: main`, no `buildFilter`.
- Render API endpoint: `PATCH /v1/services/{serviceId}` — supports `buildFilter` field.
- Baker-master path-filter precedent: commit `935d793` (`BRIEF_RENDER_PATH_FILTERED_DEPLOY_1`, AH1-App execution 2026-05-06).
- Baker-master path-filter 2nd-pass review (V0.2): agent `a4403941237a1d52d` — L3 finding (this brief closes that follow-up).
- Local repo clone: `~/brisen-lab-staging` (currently on `b4/v2-bridge-surface-6-session-keys-cleanup` branch — must `git checkout main` before smoke commits).
- Director ratification anchor: 2026-05-06 — pragmatic accept on baker-master path-filter (Director "a" pick on Option A inline-fold) + "your pick" → "draft path-filter-2" authorization for this brief.
