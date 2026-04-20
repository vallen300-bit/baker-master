---
title: B3 baker-master PR #28 SOT Phase D — REQUEST_CHANGES
voice: report
author: code-brisen-3
created: 2026-04-20
---

# SOT_OBSIDIAN_1_PHASE_D_VAULT_READ Review — baker-master PR #28 (B3, reroute from B2)

**From:** Code Brisen #3
**To:** AI Head
**Re:** `briefs/_tasks/CODE_3_PENDING.md` @ `2912d31`
**Brief:** `briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md` @ `d6a50ef`
**PR:** https://github.com/vallen300-bit/baker-master/pull/28
**Branch:** `sot-obsidian-1-phase-d-vault-read`
**Head commit:** `237d8c7`
**Base:** `main` at `c70d4a3`
**Ship report (B1):** `briefs/_reports/B1_sot_phase_d_ship_20260420.md` @ `592b07d`
**Coupled PR:** baker-vault [#6](https://github.com/vallen300-bit/baker-vault/pull/6) (separate report: `_reports/B3_pr6_phase_d_vault_review_20260420.md`)
**Date:** 2026-04-20
**Time:** ~55 min

---

## Verdict

**REQUEST_CHANGES.** Two stacking critical defects on the production path — together they make the mirror silently unreachable on the first Render deploy. Neither is caught by the current test suite. Design calls (3) are all accepted; path-safety tests are strong; `/health` shape is correct. Once S1a + S1b are fixed (~20 min combined), this ships.

**Both PRs must approve together per brief coupling.** PR #6 (vault doc append) is clean on its own and ready to merge — see sibling report — but pointing Cowork at tools that don't work on Render is worse than not pointing at them. Hold PR #6 until PR #28 re-approves.

---

## S1a — CRITICAL — `_ensure_vault_mirror` wrapper swallows first-clone RuntimeError

**File:** `outputs/dashboard.py:438-449`

```python
def _ensure_vault_mirror() -> None:
    """SOT_OBSIDIAN_1_PHASE_D: clone/pull baker-vault mirror on startup.

    Non-fatal on pull failure (transient — next ``vault_sync_tick``
    retries) but fatal on initial-clone failure so a missing mirror
    can't go unnoticed. See ``vault_mirror.py`` for scope invariants.
    """
    try:
        from vault_mirror import ensure_mirror
        ensure_mirror()
    except Exception as e:
        logger.error("vault_mirror: ensure_mirror failed on startup: %s", e)
```

**Bug:** docstring says "fatal on initial-clone failure" but the implementation blanket-catches `Exception`, logs ERROR, returns. `ensure_mirror()` DOES correctly raise `RuntimeError` on first-clone failure (vault_mirror.py:144-146) — the wrapper defeats it.

**Impact (compounded by S1b):** on first Render deploy, clone fails (see S1b) → `ensure_mirror()` raises `RuntimeError` → wrapper logs + returns → `_start_scheduler()` runs → MCP tools register → Cowork calls `baker_vault_read` → tool returns errors or empty listings. `/health` reports `vault_mirror_commit_sha: None`. Failure is visible only to an operator tailing logs in the first minutes.

B1's ship report (§Render-side vault mirror) explicitly claims **"Fatal on initial clone failure; non-fatal on pull failure"**. The implementation contradicts the claim.

**Fix (minimal — 1 line delta):**

```python
def _ensure_vault_mirror() -> None:
    """SOT_OBSIDIAN_1_PHASE_D: clone/pull baker-vault mirror on startup.

    ``ensure_mirror()`` already distinguishes the two cases internally —
    WARN-logs pull failures, raises RuntimeError only on initial-clone
    failure. Propagate so FastAPI's lifespan aborts startup per brief.
    """
    from vault_mirror import ensure_mirror
    ensure_mirror()
```

**Plus test** — add to `tests/test_mcp_vault_tools.py`:

```python
def test_ensure_vault_mirror_reraises_first_clone_failure(tmp_path, monkeypatch):
    """First-clone failure must abort startup (brief contract)."""
    monkeypatch.setenv("VAULT_MIRROR_PATH", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("VAULT_MIRROR_REMOTE", "https://invalid.example/nope.git")
    import importlib, vault_mirror
    importlib.reload(vault_mirror)
    from outputs.dashboard import _ensure_vault_mirror
    with pytest.raises(RuntimeError):
        _ensure_vault_mirror()
```

---

## S1b — CRITICAL — missing `GITHUB_TOKEN` auth for private baker-vault clone

**File:** `vault_mirror.py:63-64, 140`

```python
DEFAULT_REMOTE = "https://github.com/vallen300-bit/baker-vault.git"

def _remote_url() -> str:
    return os.environ.get("VAULT_MIRROR_REMOTE", DEFAULT_REMOTE)
```

Clone call (line 140):

```python
_run_git(["clone", "--depth", "1", _remote_url(), str(path)])
```

**Bug:** `git clone https://github.com/vallen300-bit/baker-vault.git` against a **private repo** without credentials fails with:

```
fatal: Authentication failed for 'https://github.com/vallen300-bit/baker-vault.git/'
```

Verified: `gh repo view vallen300-bit/baker-vault --json visibility` → `{"visibility":"PRIVATE"}`. Brief §1 explicitly called for token auth:

> Use existing ``GITHUB_TOKEN`` env var for auth (already present — reused from auto-deploy).

B1 did not wire `GITHUB_TOKEN` into `_remote_url()`. On production first deploy: clone fails → RuntimeError → (swallowed by S1a) → service boots with broken mirror.

**Fix (minimal):**

```python
def _remote_url() -> str:
    override = os.environ.get("VAULT_MIRROR_REMOTE")
    if override:
        # Test/ops override wins — local path or pre-authed URL.
        return override
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        # x-access-token works for both PATs and Render's auto-injected token.
        return (
            f"https://x-access-token:{token}"
            f"@github.com/vallen300-bit/baker-vault.git"
        )
    return DEFAULT_REMOTE
```

**Plus test** — no live GitHub call, just the URL builder:

```python
def test_remote_url_injects_github_token_when_set(monkeypatch):
    monkeypatch.delenv("VAULT_MIRROR_REMOTE", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    import importlib, vault_mirror
    importlib.reload(vault_mirror)
    assert "x-access-token:ghp_test@" in vault_mirror._remote_url()

def test_remote_url_override_wins(monkeypatch):
    monkeypatch.setenv("VAULT_MIRROR_REMOTE", "file:///tmp/fake")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_unused")
    import importlib, vault_mirror
    importlib.reload(vault_mirror)
    assert vault_mirror._remote_url() == "file:///tmp/fake"
```

**Brief-lesson consequence (lesson #40):** the brief's §1 referenced Render-side env (`GITHUB_TOKEN`) without a §Pre-merge verification block. That's the pattern lesson #40 was coined to prevent. Recommend future Phase-* briefs include an explicit ssh/curl check, e.g.: *"post-deploy, `curl $RENDER_URL/health | jq .vault_mirror_commit_sha` returns a full SHA, not null."*

---

## Deviations (B1's 3 flagged) — all accepted

### D1 — single `vault_mirror.py` module (not a package) — ACCEPT

356 LOC with clear section headers (Config accessors / Mirror management / Path safety) + minimal module-level state (`_last_pull_at`, `_git_lock`). Public surface (`ensure_mirror`, `sync_tick`, `list_ops_files`, `read_ops_file`, `VaultPathError`, `mirror_status`, `sync_interval_seconds`) reads cleanly. A future `baker_vault_write` brief could either extend in place (add `write_ops_file` next to `read_ops_file` under a new section) or extract a package — current cohesion doesn't force the split. Not tangled.

### D2 — module-level `_git_lock` (not filesystem flock) — ACCEPT

- Serializes `ensure_mirror` ↔ `sync_tick` within a single Render process. ✓
- Both paths use `with _git_lock:` around full git op; no lock release between clone/pull and status read. ✓
- Cross-process: Render web service is single-instance Starter tier. No cross-process contention possible. Filesystem flock would survive process restart but the mirror is re-cloned at restart anyway, so the survival buys nothing. ✓
- One minor consideration: **`read_ops_file` / `list_ops_files` don't take the lock.** A rare freshness glitch exists — if `sync_tick` is mid `git pull` and Cowork calls `baker_vault_read`, the read may see a partially-updated tree. Git's `pull --ff-only` updates files non-atomically. Worst case: one file shows old content, the next call shows new — no corruption, just a moment of inconsistent freshness. Accept as-is (read-only, no state mutation). Nit N1 below if desired.

### D3 — lazy imports in dispatch/wrapper branches — ACCEPT

Matches the `_kbl_bridge_tick_job` + `_run_migrations` pattern. Keeps module-load from requiring git subprocess availability (test hermeticity) and sidesteps any potential circular-import risk. Python's module cache amortizes per-call cost to near-zero. Idiom consistency > micro-optimisation.

---

## Verdict focus (mailbox §Verdict focus, 1-for-1)

| Check | Result |
|-------|--------|
| Path traversal test | ✅ `test_read_path_traversal_is_rejected` (`_ops/../CHANDA.md`) |
| Absolute path test | ✅ `test_read_absolute_path_is_rejected` (`/etc/passwd`) |
| Symlink escape test | ⚠️ **not present** — `list_ops_files:L293-301` re-resolves every hit, so defense exists, but no test proves it. Nit N2. |
| Binary file test | ✅ `test_read_binary_extension_is_rejected` (.png) |
| Oversize test | ✅ `test_read_oversize_returns_metadata_only` (MAX_FILE_BYTES + 10) |
| Nonexistent (404 dict, not exception) | ✅ `test_read_nonexistent_returns_not_found` |
| Mirror read-only — no `git push` | ✅ `grep -nE "git.*push" vault_mirror.py` → 0 hits (only docstring mention) |
| Scheduler floor ≥60s | ✅ `SYNC_INTERVAL_FLOOR_SECONDS = 60` + `test_sync_interval_clamps_to_floor` |
| **First-clone fatal** | ❌ **S1a bug above** — wrapper swallows RuntimeError; no test covers the fatal path |
| Post-first-clone pull non-fatal | ✅ `ensure_mirror:131-135` WARN-logs, returns |
| Tool shape `{path, content_utf8, sha256, bytes, last_commit_sha, truncated}` | ✅ per brief + `error: 'not_found'` for 404 (documented in B1 ship report) |
| Secret audit (14 hits concept-only) | ✅ spot-check 4 of 14: `git-mailbox.md:51-53` (rules, no values), `write-brief.md:130,217,235` (advice + anti-patterns), `SKILL.md:213-216` (policy) — zero values |
| `/health` — `vault_mirror_last_pull` + `vault_mirror_commit_sha` | ✅ `outputs/dashboard.py:1279-1297` — keys added; Null-defaults on exception path; non-blocking. |

---

## Test run — 16/21 green on py3.9 (env gap, not PR regression)

```
$ pytest tests/test_mcp_vault_tools.py -q
16 passed, 5 failed (ModuleNotFoundError: mcp) in 3.24s
```

5 failures are all `baker_mcp.baker_mcp_server` import cascading to `mcp` package not being in my py3.9 env. B1 ran on `bm-b2-venv` (py3.12 with `mcp` installed) where "21 new tests ... all green" per ship report. My 16-green covers the load-bearing vault_mirror logic (path safety, oversize, sync_tick, interval clamp, list/read semantics) — those pass. Acceptable.

`test_migration_runner.py::test_startup_call_order` **fails on py3.9** with the PEP-604 `str | None` landmine (lesson #41 — pre-existing on main at `tools/ingest/extractors.py:275`, not a regression from this PR).

---

## Nits (non-blocking — flag for follow-up)

- **N1 — reads don't take `_git_lock`.** Consider `with _git_lock:` for `read_ops_file` / `list_ops_files` to eliminate the rare "mid-pull inconsistent tree" window. Cost: extra lock acquisition on every read. Accept as-is if read concurrency matters more than freshness atomicity; this is read-only, so no correctness issue — just a ~100ms window ~once per 5 min tick.
- **N2 — symlink escape test.** `list_ops_files` defends via `realpath` re-resolution on every hit but no test proves it. Add a fixture that `os.symlink(outside_root, _ops/evil)` and assert the listing skips it. 6-line addition.
- **N3 — Brief §Pre-merge verification.** Brief didn't include a post-deploy `curl /health` check (lesson #40 pattern). Had it been there, S1b would have been caught before merge. Suggest AI Head add this to the Phase-* brief template.

---

## Coupled PR status

**baker-vault #6** (branch `sot-obsidian-1-phase-d-operating-append`, head `707555e`): reviewed in sibling report `_reports/B3_pr6_phase_d_vault_review_20260420.md`. Verdict **APPROVE (hold until #28 re-approves)**. The 17-line OPERATING.md append matches brief §4 and references baker-vault-read tools correctly. Cannot merge before #28 is fixed — merging would point AI Dennis at broken tools.

(Note: `git diff main..HEAD` on the baker-vault branch initially looked like it deleted B2's Phase C review report at `_reports/B2_pr5_phase_c_review_20260420.md`. That's a two-dot-diff display artifact — three-dot `git diff main...HEAD` correctly shows only +17 OPERATING.md. Merge-squash or merge-commit preserves main-side additions made after the branch point. False alarm on initial scan; no rebase required.)

---

## CHANDA pre-merge

- **Q1 Loop Test:** `_ops/` is exempt from Inv 9 per Phase A writer-contract. No `wiki/` writes. Tools are read-only on `_ops/**`. Legs 1/2/3 untouched. ✅
- **Q2 Wish Test:** serves the SoT wish (Cowork reads her canonical files from the single source). S1a+S1b defeat that wish *as-shipped* — once fixed, the wish is served. Clean after fix.
- **Inv audit:**
  - Inv 4 (author-director files untouched) — none modified. ✅
  - Inv 9 (Mac Mini single agent writer to vault) — mirror is **READ-ONLY**, no push. Render reads, never writes. Verified by `grep push vault_mirror.py` → 0 hits. ✅
  - Inv 10 (prompts don't self-modify) — no prompt files. ✅

---

## Dispatch back

> **B3 PR #28 SOT Phase D — REQUEST_CHANGES.** Two stacking critical defects: (S1a) `outputs/dashboard.py:_ensure_vault_mirror` swallows the `RuntimeError` that `ensure_mirror` raises on initial-clone failure — violates brief's "fatal on first-clone" contract and B1 ship-report's identical claim; (S1b) `vault_mirror.py:_remote_url` does not inject `GITHUB_TOKEN`, but baker-vault is PRIVATE — production clone will fail with auth error. Combined: first Render deploy → clone fails → wrapper silences → service boots with broken mirror → Cowork tools return errors. Fixes ~20 min total; 4 new tests (first-clone-fatal, token-injection, override-wins, symlink-escape). Design calls (D1/D2/D3) all accepted; path-safety tests strong; `/health` shape correct; secret-audit spot-check clean. Report at `briefs/_reports/B3_pr28_phase_d_master_review_20260420.md`. Coupled PR #6 (baker-vault) is clean — hold its merge until #28 re-approves.
