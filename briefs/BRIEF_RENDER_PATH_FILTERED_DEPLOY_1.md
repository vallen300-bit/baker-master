# BRIEF: RENDER-PATH-FILTERED-DEPLOY-1 — stop doc-only commits from restarting the baker-master service

## Context

Tonight (2026-05-05T22:52Z) my brief-only commit `370c9ba` (852 lines of pure markdown) triggered a full baker-master Python service restart on Render. The restart killed AH1-App's MCP-over-HTTP connection mid-session (~22:55Z). Director and AH1-App both flagged this as preventable noise.

Render's default behavior is `autoDeployTrigger: commit` on the `main` branch — every commit re-deploys, regardless of what changed. This is wasteful and operationally hostile:

- **Per-commit cost:** ~45–60 seconds of build + restart per commit; concurrent restarts during a flurry of brief commits can compound (Lesson #earlier: "concurrent startup tasks" anti-pattern).
- **Connection blast radius:** every active MCP-over-HTTP client (Cowork-AH1, Cowork-AH2, Slack interactivity, dashboard SSE) drops on restart; clients usually auto-reconnect but UX cliff is real.
- **Latency for legitimate code changes:** real code commits queue behind doc-only commits in the build pipeline.

This brief configures `buildFilter.ignoredPaths` on baker-master so doc-only path changes do NOT trigger redeploys. Everything else continues to redeploy as today (no opt-in deploys regress).

**Director ratification:** 2026-05-05 via AH1-App relay ("APPROVED — author the brief … explicitly enumerate (a) safe-to-filter and (b) never-filter"). Tier-A per AH1-App scope statement.

## Estimated time: ~30 min
## Complexity: Low (single Render service config change + verification)
## Prerequisites: Render API key in 1Password (`op://Baker API Keys/API Render/credential`); access to `srv-d6dgsbctgctc73f55730` (Render auto-selected workspace `tea-d6dgif24d50c73apjilg`).
## Tier: A (touches deploy behavior on production-critical service; misconfigure risk = stale prod after real code change)

---

## Feature 1 — Configure `buildFilter.ignoredPaths` on baker-master service

### Problem

`autoDeployTrigger: commit` + no `buildFilter` = every commit redeploys. Doc-only commits should be no-ops at the deploy boundary.

### Current state (verified via Render API tonight)

```json
{
  "id": "srv-d6dgsbctgctc73f55730",
  "name": "baker-master",
  "autoDeploy": "yes",
  "autoDeployTrigger": "commit",
  "branch": "main",
  // no buildFilter field — every commit on main triggers a deploy
}
```

Repo layout (verified at `~/Desktop/baker-code`):

| Path | Runtime-critical? | Editing frequency | Filter? |
|---|---|---|---|
| `briefs/**` | NO — markdown only, never imported | HIGH (every dispatch + every brief authoring) | YES |
| `briefs/_tasks/CODE_<N>_PENDING.md` | NO — workflow mailbox, not Python-imported | VERY HIGH | YES |
| `briefs/_reports/**` | NO — completion reports, not imported | HIGH | YES |
| `_ops/**` (vault-side ops md) | NO — never imported by dashboard | MED | YES |
| `tasks/lessons.md` | NO — append-only audit, not imported | MED | YES |
| `memory/**` (if present in repo) | NO — runtime-irrelevant docs | LOW | YES |
| `*.md` at repo root (`CLAUDE.md`, `BRIEF_*.md`, `00_WORKTREES.md`, `BUILD_GUIDE.md`, `CHANDA*.md`, `SESSION_LOG.md`, `CODE_SESSION_LOG.md`, `CLAUDE_REFERENCE.md`, `BRIEF_OWNERS_LENS.md`) | NO | LOW–MED | YES |
| `docs-site/**` | NO — static HTML; served by separate `brisen-docs` Render service, not by baker-master | LOW | YES |
| `outputs/dashboard.py` | YES — FastAPI app entry | MED | NO |
| `start.sh`, `build.sh`, `requirements.txt`, `cli.py`, `baker_rag.py`, `clickup_client.py`, `document_generator.py`, `vault_mirror.py`, `__init__.py` | YES — runtime | LOW–MED | NO |
| `config/**`, `kbl/**`, `orchestrator/**`, `tools/**`, `triggers/**`, `models/**`, `pm/**`, `projects/**`, `strategy/**`, `baker/**`, `baker_mcp/**`, `baker-wealth-mcp/**`, `invariant_checks/**`, `migrations/**`, `outputs/**` | YES — runtime imports | MED | NO |
| `scripts/**` | MIXED — some runtime (`check_applied_migrations.sh`, `validate_eval_labels.py`); most one-shot tools | LOW | NO (safer) |
| `tests/**` | NO at runtime, but Render `build.sh` may run them | LOW | NO (defensive) |
| `migrations/**` | YES — runtime schema | LOW | NO |
| `.githooks/**`, `.claude/**` | NO at Render runtime | LOW | NO (defensive — unclear what `.claude/` could trigger downstream) |

Verified imports in `outputs/dashboard.py`:
```
from config.settings import config
from orchestrator.gemini_client import ...
from orchestrator import action_handler ...
from orchestrator.cortex_runner import ...
from kbl.cache_telemetry import ...
from tools.ingest.pipeline import ...
from tools.ingest.extractors import ...
from tools.ingest.classifier import ...
from triggers.embedded_scheduler import ...
from kbl.citations import ...
from triggers.waha_webhook import ...
from triggers.slack_events import ...
from triggers.slack_interactivity import ...
from outputs.email_router import ...
```

None of these touch `briefs/`, `docs-site/`, `_ops/`, `memory/`, `tasks/`, or root-level `*.md` files.

### Implementation

**Use `buildFilter.ignoredPaths` (negative list), NOT `buildFilter.paths` (positive list).**

Rationale: a positive list requires us to enumerate every runtime path; missing one = silent no-deploy on real code change. A negative list is safe-by-default — anything not listed still deploys.

**Render API call (PATCH the service):**

```bash
PATH=/usr/bin:/usr/local/bin:/opt/homebrew/bin
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')

curl -X PATCH \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "buildFilter": {
      "paths": [],
      "ignoredPaths": [
        "briefs/**",
        "_ops/**",
        "memory/**",
        "tasks/**",
        "docs-site/**",
        "*.md",
        "BRIEF_*.md",
        "00_WORKTREES.md",
        "BUILD_GUIDE.md",
        "CLAUDE.md",
        "CLAUDE_REFERENCE.md",
        "CHANDA.md",
        "CHANDA_enforcement.md",
        "SESSION_LOG.md",
        "CODE_SESSION_LOG.md"
      ]
    }
  }' \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730"
```

**Why also list root-level `*.md` explicitly:** Render's glob semantics (per Render docs) match `**` cross-directory but the leading-`*.md` glob is needed to catch root-level markdown without recursion. The redundant explicit names (`CLAUDE.md`, `BUILD_GUIDE.md`, etc.) are belt-and-suspenders in case Render's glob engine has edge-case behavior at root level.

**Alternative: Render dashboard UI.** Service → Settings → "Build Filters" → Ignored Paths. Add each pattern. Same outcome; less reproducible than API.

### Key constraints

- **Negative list only.** Setting `buildFilter.paths` to a non-empty array would invert semantics (deploy ONLY when those paths change) — that's the under-filter footgun. Leave `paths: []`.
- **Don't filter `scripts/**`.** Mixed-purpose dir; some scripts are runtime hooks (`check_applied_migrations.sh`). Safer to redeploy on script changes (cost: a few extra deploys per quarter when a new backfill script lands; benefit: zero risk of a scripts/ change going un-deployed).
- **Don't filter `tests/**`.** Defensive — if a future Render `build.sh` adds `pytest` invocations during build, test changes need to redeploy.
- **Don't filter `.claude/**` or `.githooks/**`.** These are tool-config paths consumed by local Claude Code / git, not by Render directly. But they sometimes ship with intent (e.g., `.githooks/pre-commit` was a real ratified change). Keep deploys honest.
- **Migration files (`migrations/**`) MUST trigger redeploy.** Schema changes need the runtime restart to apply. Excluded from the ignored list.
- **Don't filter `requirements.txt` or `requirements-*.txt`.** Pip-install diffs change the running env; need redeploy.
- **Render path-filter docs:** patterns use double-asterisk globbing (`briefs/**` matches all sub-paths). Verify against current Render documentation at apply time — the API field name `ignoredPaths` was stable as of Q1 2026 but Render has historically renamed fields without notice.

### Verification

#### Step 1 — Pre-apply state capture

```bash
PATH=/usr/bin:/usr/local/bin:/opt/homebrew/bin
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730" \
  > /tmp/baker-master-pre-filter.json
# Capture so rollback can restore the prior shape exactly.
```

#### Step 2 — Apply (per Implementation curl above)

#### Step 3 — Confirm field landed

```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730" \
  | python3 -c "import sys,json; data=json.load(sys.stdin); bf=data.get('buildFilter', None); print('buildFilter:', json.dumps(bf, indent=2) if bf else 'NOT SET')"
# Expect: full buildFilter object echoed back with ignoredPaths matching Step 2.
```

#### Step 4 — Filter behavior smoke test (the proof)

```bash
# Make a doc-only commit. Push. Confirm NO deploy fires.
cd ~/Desktop/baker-code
echo "" >> briefs/_test/path_filter_smoke_$(date +%s).md
git add briefs/_test/path_filter_smoke_*.md
git commit -m "test: path-filter smoke (doc-only — should NOT trigger redeploy)"
git push

# Wait 30s. Then list deploys.
sleep 30
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys?limit=2" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for d in data[:2]:
    dep = d.get('deploy', d)
    print(f\"  {dep['id']} status={dep['status']} created={dep['createdAt']} commit={dep.get('commit', {}).get('id', '?')[:8]}\")"
# Expect: top deploy ID is unchanged from before the smoke commit.
# If a NEW deploy was triggered → filter not working → roll back per Step 6.
```

#### Step 5 — Real-code smoke test (positive control)

```bash
# Make a Python comment-only edit (semantic no-op but in a runtime file).
echo "# path-filter positive control $(date +%s)" >> outputs/dashboard.py
git add outputs/dashboard.py
git commit -m "test: path-filter positive control (runtime file — SHOULD trigger redeploy)"
git push

# Wait 30s. Confirm a NEW deploy started.
sleep 30
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys?limit=2" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
dep = (data[0] if data else {}).get('deploy', data[0] if data else {})
print(f\"latest: {dep.get('id')} status={dep.get('status')} commit={dep.get('commit', {}).get('id', '?')[:8]}\")"
# Expect: a NEW deploy ID, status build_in_progress or live, commit matches the smoke push.
```

#### Step 6 — Rollback (if Step 4 or 5 fails)

```bash
# Restore prior buildFilter (or absence thereof).
PRIOR_BF=$(python3 -c "import json; d=json.load(open('/tmp/baker-master-pre-filter.json')); print(json.dumps(d.get('buildFilter') or {'paths': [], 'ignoredPaths': []}))")
curl -X PATCH \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  --data "{\"buildFilter\": $PRIOR_BF}" \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730"
# OR if pre-filter had no buildFilter at all, set both arrays to empty
# (which is functionally the same as no filter — Render falls back to "deploy
# every commit").
```

#### Step 7 — Cleanup

```bash
# Remove the smoke-test files (they're in `briefs/_test/` and root `outputs/dashboard.py` got a comment).
git checkout outputs/dashboard.py
rm briefs/_test/path_filter_smoke_*.md
rm -d briefs/_test/ 2>/dev/null  # only if empty
git add -A && git commit -m "test: clean up path-filter smoke artifacts" && git push
# This commit is doc-only on briefs/_test cleanup + outputs/dashboard.py revert.
# Will trigger ONE redeploy (because dashboard.py reverted), then quiet.
```

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | `buildFilter.ignoredPaths` set on `srv-d6dgsbctgctc73f55730` with the 14 patterns enumerated | API GET (Step 3) — exact array match |
| **A2** | `buildFilter.paths` is `[]` (or absent) so the filter is negative-only | API GET (Step 3) |
| **A3** | Doc-only smoke commit (`briefs/_test/path_filter_smoke_*.md`) does NOT trigger a new deploy | API list-deploys before/after (Step 4) — top deploy ID unchanged |
| **A4** | Runtime smoke commit (`outputs/dashboard.py` comment-only) DOES trigger a new deploy | API list-deploys before/after (Step 5) — new deploy ID with matching commit SHA |
| **A5** | Rollback path tested in advance — `/tmp/baker-master-pre-filter.json` captured + the rollback curl shape verified | inspect file existence + dry-run rollback |
| **A6** | Cleanup commit lands clean; smoke test artifacts removed | `git status` post-cleanup |
| **A7** | Brief migration of pattern: brisen-lab service (`srv-d7q7kvlckfvc739l2e8g`) candidate for the same treatment NOT included in this brief — separate scope | NOT verified in this brief; documented as follow-up |

**Ship gate:** A1–A6 all green. Rollback path tested but not used = success.

---

## Files Modified

- Render service config (`srv-d6dgsbctgctc73f55730`) — `buildFilter` field added.
- Repo: ephemeral smoke-test files (deleted in Step 7) — no permanent repo changes.

## Do NOT Touch

- `start.sh`, `build.sh`, `requirements.txt`, `cli.py`, `outputs/dashboard.py` (except the smoke-test comment that gets reverted).
- The `srv-d7q7kvlckfvc739l2e8g` brisen-lab service — separate scope; brisen-lab repo has different doc structure (no top-level `briefs/` dir).
- `auto-deploy: yes` — keep auto-deploy on; we're filtering WHICH commits redeploy, not disabling autodeploy.
- `autoDeployTrigger: commit` — keep at `commit` (not `lastModifiedAt` or other modes).

---

## Quality Checkpoints

1. After A2 confirmed, manually verify the next 2–3 doc-only commits to baker-master's `main` branch result in zero new deploys (let real workflow exercise the filter).
2. Monitor Render alerts inbox for any "build skipped" or "filter applied" notifications. Render historically logs filter decisions to the deploy audit trail; verify by inspecting deploys-list with no new entries during the doc-only smoke window.
3. After 1 week of operation, count how many redeploys were skipped vs the prior week's commit volume to confirm the filter is doing useful work. Capture metric in actions_log.

---

## Open questions for AH1 (resolved-or-surfaced)

**Q1.** Should brisen-lab service (`srv-d7q7kvlckfvc739l2e8g`) get the same treatment? **Resolution:** out of scope — different repo, different structure. Spin a separate follow-up brief if/when brisen-lab repo accumulates doc-only commit volume worth filtering.

**Q2.** Should the filter cover `tests/**`? **Resolution:** NO. Defensive against future Render `build.sh` changes that might run pytest.

**Q3.** What if AH1-App or another worker introduces a NEW top-level doc file (e.g. `BRIEF_NEW_INITIATIVE.md` at root)? **Resolution:** the `BRIEF_*.md` glob covers it. New `*.md` files at root are also covered by `*.md`. New top-level non-doc files (e.g., a Python script at root) will trigger a deploy — correct behavior; doc files won't.

**Q4.** What if a doc commit lands ALONGSIDE a code commit in the same push? **Resolution:** Render evaluates per-commit, not per-push. Each commit is checked individually; mixed pushes deploy ONLY for commits that touch non-ignored paths. This is correct behavior.

**Q5.** Will the path-filter cover edits to `briefs/_tasks/CODE_<N>_PENDING.md` (B-code mailbox flips)? **Resolution:** YES — `briefs/**` matches `briefs/_tasks/...`. Mailbox-flip commits will no longer trigger redeploys. This is a significant win (mailbox commits happen 5–10× per session during active dispatch).

---

## Sequencing

1. EXPLORE: read `outputs/dashboard.py` imports + `start.sh` + `build.sh` to confirm runtime path inventory (already done in this brief; B-code or AH1 should re-verify if elapsed > 1 week before apply).
2. PLAN: confirm `ignoredPaths` set against current repo state (no new top-level dirs introduced since 2026-05-05 EOD).
3. CAPTURE pre-state via Step 1.
4. APPLY via Step 2 curl.
5. VERIFY via Steps 3–5.
6. CLEANUP via Step 7.
7. REPORT closure to AH1-App + ship-report paste-block.
8. CAPTURE LESSON if anything surprised — append to `tasks/lessons.md`.

---

## Reference

- Render service config (current): `srv-d6dgsbctgctc73f55730` — `autoDeploy: yes`, `autoDeployTrigger: commit`, `branch: main`, no `buildFilter`.
- Render API endpoint: `PATCH /v1/services/{serviceId}` — supports `buildFilter` field.
- Render glob semantics docs: render.com/docs/build-filters (verify URL at apply time).
- Tonight's incident timeline: brief commit `370c9ba` → deploy `dep-d7t79g67r5hc73duoj30` → MCP disconnect ~22:55Z → AH1-App diagnostic ping.
- Lesson #earlier: Render env-var verification must round-trip via Render API (this brief follows the same discipline for `buildFilter`).

---

# V0.2 Amendment — Architect-reviewer fold (2026-05-05)

> **Trigger:** post-WRITE architect-reviewer pass (verdict PASS-WITH-NITS) surfaced one design-correctness issue + four hardening items. Folding before AH1-App apply.

## Amendment §A — MED: `briefs/_inputs/**` IS runtime-loaded; narrow filter

**Reviewer finding (MED, confidence high after grep verification):** `briefs/_inputs/bootstrap_*.yml` (17 files at last count) are READ AT RUNTIME by `scripts/bootstrap_matter.py` and `scripts/bootstrap_entities.py`. V0.1 `briefs/**` filter would silently skip redeploys on bootstrap YAML changes — exactly the under-filter footgun.

**Action — REPLACE `briefs/**` with explicit doc-only sub-paths:**

```json
"ignoredPaths": [
  "briefs/*.md",
  "briefs/_drafts/**",
  "briefs/_future_optimization/**",
  "briefs/_handovers/**",
  "briefs/_plans/**",
  "briefs/_reports/**",
  "briefs/_runbooks/**",
  "briefs/_skills_drafts/**",
  "briefs/_staging/**",
  "briefs/_tasks/**",
  "briefs/_templates/**",
  "briefs/archive/**",

  "_ops/**",
  "memory/**",
  "tasks/**",
  "docs-site/**",

  "*.md",
  "BRIEF_*.md",
  "00_WORKTREES.md",
  "BUILD_GUIDE.md",
  "CLAUDE.md",
  "CLAUDE_REFERENCE.md",
  "CHANDA.md",
  "CHANDA_enforcement.md",
  "SESSION_LOG.md",
  "CODE_SESSION_LOG.md"
]
```

The 12 `briefs/...` entries cover all current briefs/ subdirs EXCEPT `briefs/_inputs/`, which intentionally remains deploy-triggering (runtime YAML).

**Verification additions to AC A1:** the curl assertion script must `assert 'briefs/_inputs/**' NOT in ignoredPaths` to catch a future drift where someone adds the input-path back to the list.

## Amendment §B — MED: explicit `config/**` in never-filter constraints

**Reviewer finding (MED, confidence high):** Director's explicit ask was "yaml/json configs read at runtime" must NEVER be filtered. V0.1 covered this implicitly via the table but not in the Key Constraints list. `config/gmail_credentials.json`, `config/gmail_token.json`, `config/gmail_poll_state.json`, and `config/settings.py` are all runtime-loaded.

**Action — append to Key Constraints:**

> - **Do not filter `config/**`.** Includes `gmail_credentials.json`, `gmail_token.json`, `gmail_poll_state.json` (runtime-loaded by `triggers/gmail_*` modules and dashboard startup), `env.mac-mini.yml.example` (template, but kept honest in deploy stream), and `settings.py` (imported by every module). `config/__pycache__/` is `.gitignore`'d so not at risk.

> - **Do not filter `vault_scaffolding/**`.** Contains `entities.yml` and `people.yml` that may be read by future cortex bootstrap pipelines. Safe-by-default (not in ignoredPaths) but enumerated for audit clarity.

## Amendment §C — MED: API field-name verification step

**Reviewer finding (MED, confidence high):** Render historically renames API fields without notice; `ignoredPaths` is camelCase per current published examples but the brief offered no defense if Render silently drops a field.

**Action — strengthen Step 3 verification:**

```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730" \
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
print(f'sample: {ignored[:3]}')
# Double-check briefs/_inputs/** is NOT in the filter
if 'briefs/_inputs/**' in ignored or 'briefs/_inputs' in ignored:
    print('FAIL: briefs/_inputs/** is filtered — runtime under-filter regression')
    sys.exit(1)
print('PASS: briefs/_inputs is NOT in ignoredPaths (runtime-safe)')
"
```

## Amendment §D — LOW: Step 4 smoke test 30s → 90s + poll loop

**Reviewer finding (LOW, confidence high):** Render queues builds during busy periods; 30s wait can false-pass if the deploy hasn't been queued yet.

**Action — replace 30s sleep with 90s polling loop:**

```bash
PUSH_TS=$(date -u +%s)
git push  # the doc-only commit
PATH=/usr/bin:/usr/local/bin:/opt/homebrew/bin
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')

# Poll up to 90s; expect NO new deploy with createdAt >= PUSH_TS
for i in 1 2 3 4 5 6; do
  sleep 15
  NEW=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/deploys?limit=1" \
    | python3 -c "
import sys, json, datetime
data = json.load(sys.stdin)
if not data: print(0); sys.exit()
dep = data[0].get('deploy', data[0])
created = datetime.datetime.fromisoformat(dep['createdAt'].replace('Z','+00:00'))
print(int(created.timestamp()))
")
  echo "  poll $i: latest deploy createdAt epoch=$NEW (push at $PUSH_TS)"
  if [ "$NEW" -ge "$PUSH_TS" ]; then
    echo "FAIL: filter broken — new deploy fired after doc-only commit"
    exit 1
  fi
done
echo "PASS: 90s window with NO new deploy after doc-only commit"
```

## Amendment §E — LOW: Step 7 `git checkout` → `git restore`

**Reviewer finding (LOW, confidence high):** `git checkout outputs/dashboard.py` silently discards uncommitted working-tree changes. Use `git restore` for explicit intent.

**Action — Step 7 cleanup:**

```bash
# Capture dashboard.py SHA pre-smoke (added to Step 5 BEFORE the comment is appended)
DASHBOARD_PRE_SMOKE_SHA=$(git rev-parse HEAD:outputs/dashboard.py)
# ... smoke-test commit/push ...
# In cleanup:
git restore --source="$DASHBOARD_PRE_SMOKE_SHA" outputs/dashboard.py
# OR if the smoke commit is already pushed and merged:
git checkout HEAD~1 -- outputs/dashboard.py  # explicit ref, not bare 'checkout'
```

## Amendment §F — LOW: `.githooks/**` reasoning anchored to Lesson #50

**Reviewer finding (LOW, confidence high):** the V0.1 "keep deploys honest" rationale for `.githooks/**` is correct but disconnected from the canonical lesson. The migration immutability guard's `.githooks/pre-commit` was a ratified production safety control (Lesson #50 / PR #146).

**Action — extend Key Constraints:**

> - **Don't filter `.githooks/**`.** This dir houses production safety controls (e.g., `pre-commit` migration immutability check per `tasks/lessons.md` Lesson #50, PR #146 merged 6ba7534). Hook changes ship intentionally; filtering them is a foot-gun.

## Amendment §G — Updated AC deltas

**New / strengthened:**
| **A1** (UPDATED) | `buildFilter.ignoredPaths` set with the 28-pattern V0.2 list (12 briefs/ sub-paths + 4 cross-cutting + 12 root files). `briefs/_inputs/**` MUST NOT be in the list | Step 3 script (V0.2 above) |
| **A8** (NEW) | Step 5 positive control wait increased to 90s polling | shell script in Amendment §D |
| **A9** (NEW) | Step 7 cleanup uses `git restore` (or explicit ref `git checkout HEAD~1 --`), not bare `git checkout` | grep cleanup script |

**Unchanged:** A2, A3 (now via 90s loop), A4, A5, A6, A7.

## Amendment §H — Net effect summary

- **Filter list precision:** 14 → 28 patterns; under-filter risk on `briefs/_inputs/**` eliminated.
- **Verification hardened:** explicit field-presence + `briefs/_inputs/` exclusion check.
- **Smoke test resilience:** 90s polling vs 30s blocking sleep.
- **Cleanup safety:** `git restore` over bare `git checkout`.
- **Constraints expanded:** explicit `config/**` + `.githooks/**` + `vault_scaffolding/**` never-filter clauses.
- **Brief intent (stop doc-only commits from restarting baker-master) preserved.**

**End V0.2 amendment.**
