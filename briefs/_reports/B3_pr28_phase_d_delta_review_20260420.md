---
title: B3 baker-master PR #28 SOT Phase D delta — APPROVE
voice: report
author: code-brisen-3
created: 2026-04-20
---

# SOT_OBSIDIAN_1_PHASE_D_VAULT_READ Delta Review — baker-master PR #28 (B3, post-recall)

**From:** Code Brisen #3
**To:** AI Head
**Re:** baker-master `briefs/_tasks/CODE_3_PENDING.md` @ `9bae2ae`
**Prior review:** `briefs/_reports/B3_pr28_phase_d_master_review_20260420.md` @ `237d8c7` (REQUEST_CHANGES)
**Fix commit:** `a563054` on `sot-obsidian-1-phase-d-vault-read` (fast-forward; no force-push)
**Delta shape:** `237d8c7..a563054` = 3 files, +147/-13 (`outputs/dashboard.py`, `vault_mirror.py`, `tests/test_mcp_vault_tools.py`)
**Coupled PR:** baker-vault [#6](https://github.com/vallen300-bit/baker-vault/pull/6) — APPROVE-HOLD from my prior review still stands; this delta review unblocks the hold.
**Date:** 2026-04-20
**Time:** ~15 min

---

## Verdict

**APPROVE.** S1a and S1b both closed with minimal, surgical deltas; 5 new tests added (4 I requested + 1 extra baseline for symmetry + the symlink test closing my N2 nit); `_redact()` bonus helper prevents the token from leaking into Render logs along any log or error-propagation path I can find. Ready to merge together with baker-vault #6.

**Reviewer-separation intact:** I still haven't implemented; B1 still the implementer; B2 is on Phase C. Clean.

---

## S1a — first-clone fatal path propagates — ✅ CLOSED

**Delta** (`outputs/dashboard.py:438-448`):

```python
-    try:
-        from vault_mirror import ensure_mirror
-        ensure_mirror()
-    except Exception as e:
-        logger.error("vault_mirror: ensure_mirror failed on startup: %s", e)
+    from vault_mirror import ensure_mirror
+    ensure_mirror()
```

- Blanket `except Exception` removed. `RuntimeError` from `ensure_mirror()`'s first-clone path now propagates up through FastAPI's `@app.on_event("startup")` lifespan. Service aborts boot rather than registering MCP tools against a missing mirror. Matches brief §1 "fatal on first-clone" contract + B1 ship-report claim.
- Docstring rewritten — now states the actual contract clearly and attributes the change to B3 review S1a (2026-04-20). ✅
- `ensure_mirror()` internal semantics still correctly distinguish pull (WARN-log, non-fatal) from clone (raise `RuntimeError`, fatal) — confirmed at `vault_mirror.py:165-181`.

**New test** (`test_ensure_vault_mirror_reraises_first_clone_failure`): sets `VAULT_MIRROR_PATH` to a fresh temp dir + `VAULT_MIRROR_REMOTE` to an invalid URL + unsets `GITHUB_TOKEN`, reloads `vault_mirror`, asserts `pytest.raises(RuntimeError, match="initial clone failed")`. Covers the fatal contract end-to-end — from git's non-zero exit up through the dashboard wrapper.

*(This test fails in my py3.9 env because importing `outputs.dashboard` transitively hits `tools/ingest/extractors.py:275`'s PEP-604 `str | None` landmine — lesson #41, pre-existing on main. B1's ship report confirms 26/26 green on py3.12. Env gap, not a regression.)*

---

## S1b — `GITHUB_TOKEN` injection for private baker-vault clone — ✅ CLOSED

**Delta** (`vault_mirror.py:79-100`):

```python
def _remote_url() -> str:
    override = os.environ.get("VAULT_MIRROR_REMOTE")
    if override:
        return override                           # test/ops override wins
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return (                                  # private-repo path (prod)
            f"https://x-access-token:{token}"
            f"@github.com/vallen300-bit/baker-vault.git"
        )
    return DEFAULT_REMOTE                         # local dev / public fallback
```

- Resolution order matches my recommendation: override → token → plain default.
- `x-access-token:…@` form is the GitHub-blessed HTTPS auth shape; works for both PATs and Render's auto-injected token.
- Private-repo clone on Render's first deploy will now succeed — was the direct blocker in my prior review (`gh repo view vallen300-bit/baker-vault --json visibility` → PRIVATE).
- Docstring attributes to B3 review S1b (2026-04-20). ✅

### Bonus: `_redact()` helper — token never reaches Render logs

**New helper** (`vault_mirror.py:64-75`):

```python
_TOKEN_URL_RE = re.compile(r"https://x-access-token:[^@\s]+@")

def _redact(text) -> str:
    if text is None:
        return ""
    return _TOKEN_URL_RE.sub("https://x-access-token:REDACTED@", str(text))
```

**Coverage audit — every log/raise path that could carry the token:**

| Site | Line | Status |
|------|------|--------|
| `ensure_mirror` pull-failure WARN log | 167-170 | `_redact(e.stderr or e)` ✅ |
| `ensure_mirror` clone-failure `RuntimeError` message | 179-181 | `_redact(e.stderr or e)` — **and** the RuntimeError propagates; FastAPI logs the already-redacted message ✅ |
| `sync_tick` re-clone failure WARN log | 205-207 | `_redact(e.stderr or e)` ✅ |
| `sync_tick` pull failure WARN log | 213-214 | `_redact(e.stderr or e)` ✅ |

Note: `_redact` runs `str(text)` on its input. When `e.stderr` is None, `_redact(e)` stringifies the `CalledProcessError`, which includes the full argv (CPython's default `__str__` shows `"Command '{cmd!r}' returned non-zero exit status {retcode}"`). The argv would include the tokenized URL — but the regex folds it out before logging. Audited; safe. ✅

Other log paths (`logger.info` for successful pulls, path-only WARN at `sync_interval_seconds` line 112, success message at line 166/178/204) don't carry URLs. ✅ `_head_commit_sha` / `_last_commit_for_path` swallow `CalledProcessError` silently and return None — no URL exposure. ✅

### 3 new tests for S1b

- `test_remote_url_injects_github_token_when_set` — asserts the tokenized URL shape when `GITHUB_TOKEN` is set + `VAULT_MIRROR_REMOTE` is unset. ✅ PASS on py3.9.
- `test_remote_url_override_wins_over_token` — `VAULT_MIRROR_REMOTE=file:///tmp/fake` + `GITHUB_TOKEN=should_be_ignored` → override wins. ✅ PASS.
- `test_remote_url_plain_when_no_token_and_no_override` — the baseline-symmetry test B1 added beyond my request; protects against future regression where the default path could accidentally pick up a stale env leak. ✅ PASS.

### N2 symlink escape test — ✅ CLOSED

`test_read_rejects_symlink_escape_outside_ops`: creates `_ops/skills/it-manager/EVIL.md` as a symlink pointing at a file outside the mirror root, asserts both (a) `read_ops_file` raises `VaultPathError` AND (b) `list_ops_files` skips the symlink in its output. Proves the `realpath`-based containment check at `_normalize_and_resolve` + the re-resolve inside `list_ops_files:L293-301` work end-to-end against an attacker who drops a malicious symlink into the cloned tree.

Path-safety coverage now **6/6** (traversal, absolute, out-of-scope prefix, binary ext, oversize, symlink). ✅ PASS on py3.9.

---

## What did NOT change (unchanged from prior review, still accepted)

- Design call D1 (single `vault_mirror.py` module) — still accepted; structure is unchanged by the delta.
- Design call D2 (module-level `_git_lock`) — still accepted. Note the N1 nit (reads don't take the lock, rare freshness glitch) remains an optional nit; not raised again here.
- Design call D3 (lazy imports) — still accepted.
- Secret audit — 14 hits, concept-only; unchanged.
- `/health` shape — unchanged.
- `VAULT_SYNC_INTERVAL_SECONDS` floor + clamp — unchanged.
- Mirror read-only invariant — unchanged (`grep -nE "git.*push" vault_mirror.py` still 0 hits).

---

## Test run — py3.9 partial

```
$ pytest tests/test_mcp_vault_tools.py -q
20 passed, 6 failed (5 × MCP ModuleNotFoundError + 1 × py3.9 str|None landmine) in 4.76s
```

4 of 5 new tests I could run on py3.9 **all green** — the 5th (`test_ensure_vault_mirror_reraises_first_clone_failure`) fails only because `from outputs.dashboard import _ensure_vault_mirror` triggers the pre-existing lesson-#41 parse error at `tools/ingest/extractors.py:275`. B1 reports 26/26 green on py3.12 (`bm-b2-venv`). Accept.

---

## CHANDA pre-merge

- **Q1 Loop Test:** still passes — `_ops/` carve-out, no `wiki/` writes, Legs 1/2/3 untouched. Bonus: `_redact()` plus the now-fatal first-clone path mean a broken mirror fails loud instead of silently feeding wrong context to Leg 1 reads in the future.
- **Q2 Wish Test:** now actually serves the wish — the post-fix deploy will clone successfully (S1b), and if it ever fails the service will abort boot loudly (S1a) instead of booting with a broken tool surface. Wish served after merge.
- **Inv audit:** unchanged from prior review — Inv 4/9/10 all respected. `_redact()` specifically protects the token from ending up in Render's log stream, which would otherwise be a secrets-in-logs anti-pattern.

---

## Dispatch back

> **B3 PR #28 delta re-review — APPROVE.** S1a closed (`_ensure_vault_mirror` wrapper removed; `RuntimeError` propagates through FastAPI lifespan). S1b closed (`_remote_url` injects `GITHUB_TOKEN` as `https://x-access-token:…@`; override > token > plain fallback). Bonus `_redact()` helper strips the token from all 4 log/error sites where git stderr could echo the URL — audited end-to-end. 5 new tests added (S1a fatal propagation, token injection, override precedence, no-token baseline, symlink escape — closes my N2 nit). Design calls (D1/D2/D3) unchanged. 4/5 new tests pass on py3.9 (5th fails only due to pre-existing lesson-#41 landmine in `tools/ingest/extractors.py`; B1 confirms 26/26 green on py3.12). Report at `briefs/_reports/B3_pr28_phase_d_delta_review_20260420.md` @ (this commit). **Baker-vault #6 hold now lifted** — AI Head may auto-merge both per Tier A. Day 1 verification: `curl $RENDER/health | jq .vault_mirror_commit_sha` + a Cowork `mcp__baker__baker_vault_read` call.
