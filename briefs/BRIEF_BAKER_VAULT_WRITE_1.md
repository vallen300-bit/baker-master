# BRIEF: BAKER_VAULT_WRITE_1 — New MCP tool `baker_vault_write`

**Revision:** v2 (post-review). v1 returned REQUEST_CHANGES; 11 findings addressed inline.
**Estimated time:** ~3-4h (incl. tests)
**Complexity:** Medium
**Trigger class:** **TIER A** — new external write surface (GitHub Contents API) + new audit row class. Requires:
1. AI Head B cross-lane review pre-merge per `_ops/processes/b-code-dispatch-coordination.md` §HIGH-class.
2. **`/security-review` skill invocation pre-merge** per Lesson #52 (Tier-A merges with new external API surface MUST run security review).
**Prerequisites:** `GITHUB_TOKEN` env var on Render (currently used for vault read mirror — verify scope includes `contents:write` for `vallen300-bit/baker-vault`).

---

## Context

Director ratified 2026-04-30 the Manus filesystem-as-memory pattern for Cowork-side scoped **Desk** agents (AO Desk / MOVIE Desk / Hagenauer Desk / Origination Desk / Brisen Desk — "Desk" naming approved 2026-04-30, replaces the per-matter PM/AM/Cortex earlier proposals). Each Desk produces durable curated knowledge after deliberation; without write access, deliberations evaporate at session end.

**Foundational research:** [`wiki/research/2026-04-30-context-engineering-scoped-agents.md`](https://github.com/vallen300-bit/baker-vault) — surveys Anthropic / Manus / LangGraph / Letta / 12 sources. Filesystem-as-memory is HIGH-confidence canonical (Manus production lessons + Anthropic 3-tier).

**Architecture alignment:** Identical to Cortex Stage 2 V1 Phase 6 archive paths (`_ops/ideas/2026-04-27-cortex-architecture-final-locked.md`, RA-23 ratified). When Stage 2 V1 backend ships, the same write paths are reused — no migration.

**Read-scope split (intentional):** Cowork's vault read scope is currently `_ops/` only (`vault_mirror.py:283`). This brief delivers **write only**; companion brief `BAKER_VAULT_READ_WIKI_SCOPE_1` (separate, follow-on) will extend read scope to `wiki/`. Splitting prevents monolith anti-pattern (lessons.md). Both must ship before Desk skills are end-to-end useful, but they ship independently.

---

## Problem

| Use case | Today | Blocked because |
|---|---|---|
| AO Desk writes session pickup state at session end | Cowork has no MCP write | No write tool |
| Hagenauer Desk archives a curated dossier post-deliberation | Cowork has no MCP write | No write tool |
| AO Desk hands off to MOVIE Desk via `_inbox/handoff-*.md` | Cowork has no MCP write | No write tool |
| AI Dennis emits an IT decision into vault for AI Head A consumption | Cowork has no MCP write | No write tool |

Without persistence, every Desk deliberation is single-session-only. The bootstrap loop that feeds the eventual Cortex Stage 2 V1 corpus does not start.

---

## Solution

Add MCP tool `baker_vault_write` that commits to the vault GitHub repo via REST Contents API (`PUT /repos/{owner}/{repo}/contents/{path}`). **Bypasses the local read-only mirror entirely.** Mirror picks up new commits on its next sync tick (~5 min); writes return commit URL so the caller can prove the write without waiting for sync.

Strict guardrails enforced server-side:
1. **Path whitelist** — only the 6 Desk-output path classes accepted.
2. **Append-only** — only `_session-state.md` accepts overwrite; all other paths reject overwrite mode.
3. **Hard-block** — protected paths (`gold.md`, `slugs.yml`, `_priorities.yml`, `_ops/`, `_install/`) raise on every attempt.
4. **Frontmatter requirement** — `curated/` and `proposed-gold.md` writes require `source` + `confidence` + `provenance` keys in YAML frontmatter; rejected without them.
5. **Audit log** — every write (success or rejection) emits a row to `baker_actions` table.
6. **Authorization tiers** (Tier A standing auth vs Tier B Director-consult per path class) are enforced at the **agent layer** (Cowork SKILL.md prose rules), NOT at this tool layer. This tool enforces only the structural guardrails above. Per-path tier metadata is documented in the BAKER_VAULT_WRITE_1 spec and in each Desk SKILL.md, not returned in tool output. (v1 had this as "metadata returned to caller" — dropped in v2 since the response dict didn't actually carry the tier and the contract was unimplemented.)

### Implementation pattern: GitHub Contents API directly

Reuse existing `GITHUB_TOKEN` env var (already wired for `vault_mirror.py` line 94) — the **same token** authenticates the write provided its scope includes `contents:write` on the vault repo.

**API call shape:**
```
PUT https://api.github.com/repos/vallen300-bit/baker-vault/contents/{path}
Authorization: Bearer {GITHUB_TOKEN}
Accept: application/vnd.github+json
Body: {"message": "{commit_message}", "content": base64(content), "sha": "{existing_sha_if_overwrite}"}
```

**Append flow:** read existing file via Contents API → decode base64 → append new content → encode → PUT with the existing `sha` for conflict detection. If file doesn't exist (404), create fresh.

**Overwrite flow:** PUT with existing sha if file exists, or omit sha if new.

**Sync vs async httpx:** use **sync `httpx.Client` calls** from `_dispatch()`. This matches the existing MCP pattern — every other tool in `baker_mcp_server.py` (`baker_scan`, `baker_search`, all DB tools) calls sync I/O from the dispatch handler. Async migration is a separate refactor across the whole MCP layer, out of scope for this brief. Acknowledged trade-off: a vault write blocks the event loop for ~200-700ms (one or two GitHub round-trips). At expected volume (~handful of writes per Desk session, < 100/day), aggregate impact is negligible.

`httpx` is already in `requirements.txt:27`.

---

## Files to modify

1. **`baker_mcp/baker_mcp_server.py`** — register `baker_vault_write` Tool entry (insert after `baker_vault_read` at line 511); add dispatch case in `_dispatch()` (after `baker_vault_read` handler at line 1379).
2. **NEW `baker_mcp/vault_write.py`** — write logic module (path whitelist, GitHub API client, frontmatter validation, audit emit). Mirrors structure of `vault_mirror.py` for read.
3. **NEW `tests/test_baker_vault_write.py`** — 6 happy paths + 4 rejection paths (see Verification).
4. **`outputs/dashboard.py`** — verify the MCP route at line 632 exposes the new tool automatically (it should, since the route iterates the TOOLS list — but verify with `grep -n "TOOLS" outputs/dashboard.py`).

## Files NOT to touch

- `vault_mirror.py` — read-only mirror, separate concern. Path scope (`_ops/`) stays as-is for read; write uses different path whitelist.
- vault repo paths: **NEVER** write to `gold.md`, `slugs.yml`, `_priorities.yml`, `_ops/`, `_install/` — these are Director-only / separate-process. Hard-block in path validator.
- `baker_actions` schema — use existing columns. Verify with `SELECT column_name FROM information_schema.columns WHERE table_name='baker_actions'` before INSERT (DO NOT guess column names — lessons.md §Database top recurring bug).

---

## Implementation

### Fix/Feature 1: Path whitelist + validation (`baker_mcp/vault_write.py`)

```python
"""Vault write — GitHub Contents API direct commit.

Bypasses the read-only Render mirror entirely. Strict path whitelist + append-only
enforcement. Every write audited to baker_actions.

Scope invariants (BAKER_VAULT_WRITE_1):
  * Whitelist enforced at path-validation layer
  * Append-only except wiki/matters/<slug>/_session-state.md
  * Hard-block on gold.md, slugs.yml, _priorities.yml, _ops/, _install/
  * curated/ and proposed-gold.md require source/confidence/provenance frontmatter
"""
import base64
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

GITHUB_API = "https://api.github.com"
VAULT_REPO = "vallen300-bit/baker-vault"

# ALLOWED path patterns — caller-supplied path must match one of these regexes.
# Slugs validated against alphanumeric+hyphen ([a-z0-9-]+).
_ALLOWED_PATTERNS = [
    # _session-state.md — overwrite OK
    (r"^wiki/matters/[a-z0-9-]+/_session-state\.md$", "session_state", True),
    # curated/<YYYY-MM-DD>-<slug-topic>.md — append-only, frontmatter required
    (r"^wiki/matters/[a-z0-9-]+/curated/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$", "curated", False),
    # _inbox/handoff-<date>-<src>-to-<tgt>.md — append-only
    (r"^wiki/_inbox/handoff-\d{4}-\d{2}-\d{2}-[a-z0-9-]+-to-[a-z0-9-]+\.md$", "handoff", False),
    # proposed-gold.md — append-only, frontmatter required
    (r"^wiki/matters/[a-z0-9-]+/proposed-gold\.md$", "proposed_gold", False),
    # decisions/<date>-<topic>.md — append-only
    (r"^wiki/matters/[a-z0-9-]+/decisions/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$", "decision", False),
    # red-flags.md — append-only
    (r"^wiki/matters/[a-z0-9-]+/red-flags\.md$", "red_flags", False),
]

# HARD-BLOCK paths — never writable, even by accident.
# Defense-in-depth: catch alternate placements anywhere in the tree, not just the
# canonical path. Reviewer flag: alternate `gold.md` placements would otherwise
# slip through the allowed-pattern fall-through.
_BLOCKED_PATTERNS = [
    r"^wiki/.*gold\.md$",            # any gold.md anywhere under wiki/
    r"^wiki/_cortex/.*\.md$",        # cortex meta-knowledge — Director-only
    r"^slugs\.yml$",
    r"^wiki/.*_priorities\.yml$",    # any _priorities.yml anywhere under wiki/
    r"^_ops/.*$",
    r"^_install/.*$",
]

class VaultWriteError(ValueError):
    pass

def validate_path(path: str, mode: str) -> tuple[str, bool]:
    """Return (path_class, overwrite_allowed). Raises VaultWriteError on rejection."""
    if not isinstance(path, str) or not path:
        raise VaultWriteError("path must be a non-empty string")
    if path.startswith("/") or "\\" in path or ".." in path:
        raise VaultWriteError(f"path must be relative without traversal: {path!r}")
    for blocked in _BLOCKED_PATTERNS:
        if re.match(blocked, path):
            raise VaultWriteError(f"path is hard-blocked: {path}")
    for pattern, klass, overwrite_ok in _ALLOWED_PATTERNS:
        if re.match(pattern, path):
            if mode == "overwrite" and not overwrite_ok:
                raise VaultWriteError(
                    f"path '{path}' (class={klass}) is append-only; "
                    "overwrite mode rejected"
                )
            return klass, overwrite_ok
    raise VaultWriteError(
        f"path '{path}' does not match any allowed pattern. See vault_write._ALLOWED_PATTERNS."
    )
```

### Fix/Feature 2: Frontmatter validation

```python
_FRONTMATTER_REQUIRED_KLASSES = {"curated", "proposed_gold"}
_FRONTMATTER_REQUIRED_KEYS = {"source", "confidence", "provenance"}

def validate_frontmatter(content: str, klass: str) -> None:
    """For curated/ and proposed-gold writes, require frontmatter keys with non-empty values.

    Frontmatter format: leading `---\\n...\\n---\\n` block of YAML-style
    `key: value` lines. We DO NOT parse YAML strictly — just substring-check
    for required keys at line-start AND that the value is non-empty.

    Reviewer fix: re.escape() the key (defense against future metachar keys),
    plus require non-empty value (\\S after the colon) — empty `source: ` was
    passing v1 validator.
    """
    if klass not in _FRONTMATTER_REQUIRED_KLASSES:
        return  # other classes have no frontmatter requirement
    if not content.startswith("---\n"):
        raise VaultWriteError(
            f"path class '{klass}' requires YAML frontmatter starting with '---'"
        )
    end = content.find("\n---\n", 4)
    if end == -1:
        raise VaultWriteError(
            f"path class '{klass}' frontmatter missing closing '---'"
        )
    frontmatter = content[4:end]
    missing = []
    empty = []
    for required_key in _FRONTMATTER_REQUIRED_KEYS:
        # Escape key (today static, but cheap defense for future)
        # AND require at least one non-whitespace character after the colon.
        key_re = re.escape(required_key)
        if not re.search(rf"^{key_re}\s*:", frontmatter, re.MULTILINE):
            missing.append(required_key)
        elif not re.search(rf"^{key_re}\s*:\s*\S", frontmatter, re.MULTILINE):
            empty.append(required_key)
    if missing:
        raise VaultWriteError(
            f"path class '{klass}' frontmatter missing required keys: {missing}. "
            f"Required: {sorted(_FRONTMATTER_REQUIRED_KEYS)}"
        )
    if empty:
        raise VaultWriteError(
            f"path class '{klass}' frontmatter keys present but empty: {empty}. "
            "Each required key must have a non-empty value."
        )
```

### Fix/Feature 3: GitHub Contents API client + 409 retry + token redaction

**Token redaction discipline** — reuse `vault_mirror._redact()` regex pattern.
Every error string surfaced to logs OR audit MUST be redacted:

```python
# Token redaction — same regex as vault_mirror._redact()
_TOKEN_URL_RE = re.compile(r"https://x-access-token:[^@\s]+@")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+")

def _redact(text) -> str:
    """Strip tokenized URLs and Bearer tokens from text before logging/auditing.

    Mirrors vault_mirror._redact() and extends with Bearer redaction since
    REST API uses Authorization: Bearer (not the URL-embedded form).
    """
    if text is None:
        return ""
    s = _TOKEN_URL_RE.sub("https://x-access-token:REDACTED@", str(text))
    s = _BEARER_RE.sub("Bearer REDACTED", s)
    return s
```

**HTTP client + retry-once on 409** (sync httpx — matches existing MCP dispatch
pattern, all other tools call sync DB/HTTP from `_dispatch()`. Async is a
future refactor across the whole MCP layer, not this brief's scope):

```python
def _gh_get(path: str, token: str) -> Optional[dict]:
    """Fetch existing file metadata. Returns None on 404."""
    r = httpx.get(
        f"{GITHUB_API}/repos/{VAULT_REPO}/contents/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15.0,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def _gh_put(path: str, content_b64: str, message: str, sha: Optional[str], token: str) -> httpx.Response:
    """Single PUT attempt. Returns the raw Response so caller can inspect 409 vs raise."""
    body = {"message": message, "content": content_b64}
    if sha:
        body["sha"] = sha
    return httpx.put(
        f"{GITHUB_API}/repos/{VAULT_REPO}/contents/{path}",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=20.0,
    )

def write_vault_file(
    path: str,
    content: str,
    mode: str,
    commit_message: str,
    token: str,
) -> dict:
    """Validate + commit. Returns {commit_sha, content_sha, html_url, klass, mode_used, bytes_written}.

    For 'append' mode: fetches existing file, decodes, concatenates new content
    after a separating newline if existing didn't end with one, re-encodes, PUTs
    with existing sha for conflict detection. On 409 Conflict (concurrent write),
    refresh sha and retry ONCE; on second 409, raise.
    For 'overwrite' mode (only allowed on _session-state.md): replaces entire content.
    """
    klass, _ = validate_path(path, mode)
    validate_frontmatter(content, klass)

    if mode not in {"append", "overwrite"}:
        raise VaultWriteError(f"mode must be 'append' or 'overwrite', got: {mode!r}")

    def _build_payload(existing: Optional[dict]) -> tuple[str, Optional[str], str]:
        """Returns (content_b64, sha_for_request, new_content_str).

        Three values: caller needs the decoded new_content to compute
        bytes_written for the audit payload.
        """
        if mode == "overwrite":
            new_content = content
            sha = existing.get("sha") if existing else None
        else:  # append
            if existing:
                existing_decoded = base64.b64decode(existing["content"]).decode("utf-8")
                sep = "" if existing_decoded.endswith("\n") else "\n"
                new_content = existing_decoded + sep + content
                sha = existing["sha"]
            else:
                new_content = content
                sha = None
        return base64.b64encode(new_content.encode("utf-8")).decode("ascii"), sha, new_content

    # First attempt
    existing = _gh_get(path, token)
    content_b64, sha, new_content = _build_payload(existing)
    response = _gh_put(path, content_b64, commit_message, sha, token)

    # 409 retry-once with refreshed sha
    if response.status_code == 409:
        existing = _gh_get(path, token)  # refresh sha
        content_b64, sha, new_content = _build_payload(existing)
        response = _gh_put(path, content_b64, commit_message, sha, token)
        if response.status_code == 409:
            raise VaultWriteError(
                f"persistent 409 Conflict on {path} after retry — "
                "concurrent writers detected; caller should retry from session"
            )

    response.raise_for_status()
    result = response.json()

    return {
        "path": path,
        "klass": klass,
        "mode_used": mode,
        "commit_sha": result["commit"]["sha"],
        "content_sha": result["content"]["sha"],
        "html_url": result["content"]["html_url"],
        "bytes_written": len(new_content.encode("utf-8")),
    }
```

### Fix/Feature 4: MCP Tool registration + dispatch

**Tool entry** (insert in `baker_mcp/baker_mcp_server.py:TOOLS` list immediately after `baker_vault_read` entry at line 511):

```python
Tool(
    name="baker_vault_write",
    description=(
        "Write a curated knowledge file to the baker-vault via GitHub Contents API. "
        "STRICT path whitelist (6 path classes), append-only except _session-state.md, "
        "frontmatter required for curated/ and proposed-gold.md. "
        "Allowed path classes: "
        "wiki/matters/<slug>/_session-state.md (overwrite OK), "
        "wiki/matters/<slug>/curated/<YYYY-MM-DD>-<topic>.md (append-only, frontmatter req'd), "
        "wiki/_inbox/handoff-<date>-<src>-to-<tgt>.md (append-only), "
        "wiki/matters/<slug>/proposed-gold.md (append-only, frontmatter req'd), "
        "wiki/matters/<slug>/decisions/<YYYY-MM-DD>-<topic>.md (append-only), "
        "wiki/matters/<slug>/red-flags.md (append-only). "
        "Returns commit SHA + content SHA + GitHub URL."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative vault path. Must match one of the 6 allowed patterns.",
                "minLength": 1,
                "maxLength": 500,
            },
            "content": {
                "type": "string",
                "description": "UTF-8 file content. For append mode, the segment to append.",
                "minLength": 1,
                "maxLength": 100000,  # 100 KB cap per write
            },
            "mode": {
                "type": "string",
                "enum": ["append", "overwrite"],
                "description": "append (default for all paths) or overwrite (only allowed for _session-state.md).",
                "default": "append",
            },
            "commit_message": {
                "type": "string",
                "description": "Git commit message. Required. Format: '<Desk> — <topic>'.",
                "minLength": 1,
                "maxLength": 200,
            },
        },
        "required": ["path", "content", "commit_message"],
    },
),
```

**Dispatch case** (insert in `_dispatch()` after `baker_vault_read` handler at line 1379, before `baker_scan` at line 1381). All error strings written to audit MUST go through `_redact()`:

```python
elif name == "baker_vault_write":
    from baker_mcp.vault_write import write_vault_file, VaultWriteError, _redact
    import os

    path = args.get("path")
    content = args.get("content")
    mode = args.get("mode", "append")
    commit_message = args.get("commit_message")

    if not path or not content or not commit_message:
        return "Error: 'path', 'content', and 'commit_message' are required"

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return "Error: GITHUB_TOKEN env var not set on Render"

    # Audit BEFORE attempt (record intent even if write fails). Audit row
    # captures the attempt so post-mortem can correlate even on hard crashes.
    audit_id = _emit_vault_write_audit(path, mode, commit_message, success=None)

    try:
        result = write_vault_file(path, content, mode, commit_message, token)
        _update_vault_write_audit(audit_id, success=True, payload_extra=result)
        return json.dumps(result, indent=2)
    except VaultWriteError as e:
        # Validation rejection — never contains tokens, but redact anyway
        _update_vault_write_audit(audit_id, success=False, error_message=_redact(str(e)))
        return f"Error: {_redact(str(e))}"
    except httpx.HTTPStatusError as e:
        # GitHub error response body could echo headers — MUST redact before
        # writing to audit / returning to caller. Lesson #18 + vault_mirror._redact discipline.
        body = _redact(f"{e.response.status_code}: {e.response.text[:200]}")
        _update_vault_write_audit(audit_id, success=False, error_message=body)
        return f"Error: GitHub API rejected write — {e.response.status_code}"
    except Exception as e:
        _update_vault_write_audit(audit_id, success=False, error_message=_redact(str(e)))
        return f"Error: {_redact(str(e))}"
```

**Audit helpers — verified schema + verified helper (queried 2026-04-30):**

`_write()` helper at `baker_mcp/baker_mcp_server.py:115` is verified to:
- accept `(sql: str, params: tuple = None)`,
- execute with `RealDictCursor`,
- `commit()` automatically,
- `fetchone()` then return the row as a dict if `RETURNING` was used, else None.

So `row["id"]` after `INSERT … RETURNING id` is correct. **Code Brisen MUST NOT** replace `_write` with a hand-rolled cursor pattern unless `_write` has changed at implementation time — re-grep `def _write` in `baker_mcp_server.py` to confirm signature and RETURNING propagation before relying on it.

`baker_actions` table columns (live, verified):

| Column | Type | Use for vault_write |
|--------|------|--------------------|
| `id` | integer | auto-increment, used as audit_id |
| `action_type` | text | `'vault_write'` |
| `target_task_id` | text | use for `path` (vault path being written) |
| `target_space_id` | text | use for `klass` once known (post-validation) — null pre-validation |
| `payload` | jsonb | full request + result JSON (mode, commit_message, commit_sha, html_url, bytes_written) |
| `trigger_source` | text | `'mcp'` |
| `created_at` | timestamptz | NOW() |
| `success` | boolean | TRUE/FALSE/NULL — NULL = attempt-in-flight, set on completion |
| `error_message` | text | `_redact()`-ed error string on failure; null on success |

```python
import json as _json
from typing import Optional

def _emit_vault_write_audit(path: str, mode: str, message: str, success: Optional[bool]) -> Optional[int]:
    """INSERT initial audit row in attempt state. Returns id or None on failure.

    Schema verified against information_schema 2026-04-30: columns are
    action_type/target_task_id/target_space_id/payload/trigger_source/
    created_at/success/error_message. NOT 'summary' or 'status'.
    """
    try:
        payload = {"mode": mode, "commit_message": message[:200]}
        row = _write(
            """INSERT INTO baker_actions
               (action_type, target_task_id, payload, trigger_source, created_at, success)
               VALUES (%s, %s, %s::jsonb, %s, NOW(), %s)
               RETURNING id""",
            ("vault_write", path, _json.dumps(payload), "mcp", success),
        )
        return row["id"] if row else None
    except Exception as e:
        logger.warning("vault_write audit emit failed: %s", e)
        return None

def _update_vault_write_audit(
    audit_id: Optional[int],
    success: bool,
    payload_extra: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> None:
    """UPDATE the audit row with terminal state.

    payload_extra (success path): merges into existing payload — adds klass,
    commit_sha, content_sha, html_url, bytes_written.
    error_message (failure path): MUST already be _redact()-ed by caller.
    """
    if not audit_id:
        return
    try:
        if payload_extra:
            extra_json = _json.dumps(payload_extra, default=str)[:8000]
            _write(
                """UPDATE baker_actions
                   SET success = %s,
                       payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                       target_space_id = %s,
                       error_message = %s
                   WHERE id = %s""",
                (
                    success,
                    extra_json,
                    payload_extra.get("klass"),
                    error_message,  # null on success
                    audit_id,
                ),
            )
        else:
            _write(
                """UPDATE baker_actions
                   SET success = %s,
                       error_message = %s
                   WHERE id = %s""",
                (success, error_message, audit_id),
            )
    except Exception as e:
        logger.warning("vault_write audit update failed: %s", e)
```

**Schema-verification footnote:** if Code Brisen finds the schema has drifted between this brief and implementation time, **do not guess**. Re-run `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='baker_actions' ORDER BY ordinal_position` and update SQL. Lessons.md §3 / §3b: column-name guessing is the #1 recurring bug.

**Stuck-NULL audit defense:** initial INSERT sets `success=NULL` to mark "attempt in flight." A daily sweeper SELECT (in Verification SQL block) detects rows older than 5 minutes still NULL — those represent crashes between INSERT and UPDATE, and should alert. The Verification SQL block includes the detection query.

---

## Key Constraints

- **DO NOT** modify `vault_mirror.py`. Read scope is a separate brief.
- **DO NOT** weaken the path whitelist regexes "for flexibility." Director ratified the strict pattern.
- **DO NOT** allow `overwrite` mode on any path other than `_session-state.md`. Append-only is load-bearing for the Manus restorability invariant.
- **DO NOT** put GITHUB_TOKEN into log output. Lessons.md §3 (vault_mirror.py:_redact pattern) — the same redaction discipline applies.
- **All DB calls** in try/except + `conn.rollback()` (python-backend.md rule).
- **Verify `baker_actions` schema** before INSERT (don't guess columns).
- **Verify GITHUB_TOKEN write scope** — current token is used for vault read clone; if it lacks `contents:write` on `vallen300-bit/baker-vault`, GitHub returns 403 on every write. Code Brisen should test with one happy-path write before declaring done; if 403, flag for Director to issue a write-scoped token (likely the same PAT just needs scope expansion).
- **Concurrency:** GitHub Contents API uses `sha` for conflict detection. If two Cortex sessions append to the same `red-flags.md` simultaneously, the second loses with 409 Conflict. Code Brisen: catch 409 and retry once with refreshed sha. If still conflicting, return error — caller can retry from session.

---

## Verification (acceptance test matrix)

### 6 happy paths

| # | Path | Mode | Frontmatter | Expected |
|---|------|------|-------------|----------|
| H1 | `wiki/matters/oskolkov/_session-state.md` | overwrite | none | 201, commit_sha returned |
| H2 | `wiki/matters/oskolkov/curated/2026-04-30-aukera-call.md` | append | source+confidence+provenance present | 201, commit_sha returned |
| H3 | `wiki/_inbox/handoff-2026-04-30-ao-to-movie.md` | append | none | 201, commit_sha returned |
| H4 | `wiki/matters/oskolkov/proposed-gold.md` | append | source+confidence+provenance present | 201, append-detected |
| H5 | `wiki/matters/hagenauer-rg7/decisions/2026-04-30-gc-takeover.md` | append | none | 201, commit_sha returned |
| H6 | `wiki/matters/oskolkov/red-flags.md` | append | none | 201, append-detected |

### 6 rejection paths (R1-R6)

| # | Path | Mode | Reason | Expected |
|---|------|------|--------|----------|
| R1 | `wiki/matters/oskolkov/curated/2026-04-30-x.md` | overwrite | append-only path | VaultWriteError "append-only" |
| R2 | `wiki/matters/oskolkov/gold.md` | append | hard-blocked | VaultWriteError "hard-blocked" |
| R3 | `_ops/skills/foo.md` | append | hard-blocked (Director-only) | VaultWriteError "hard-blocked" |
| R4 | `wiki/matters/oskolkov/curated/2026-04-30-x.md` | append | missing frontmatter (no `---` block) | VaultWriteError "frontmatter missing" |
| **R5** | `wiki/matters/oskolkov/curated/2026-04-30-x.md` | append | **frontmatter present but `source: ` empty value** | VaultWriteError "keys present but empty" |
| **R6** | `wiki/_cortex/director-gold-global.md` | append | **alternate gold placement — defense-in-depth hard-block** | VaultWriteError "hard-blocked" |

### Plus 3 behaviour tests

| # | Scenario | Expected |
|---|----------|----------|
| B1 | First PUT returns 409, second PUT (after sha refresh) succeeds | result returned, both _gh_get calls observed |
| B2 | Both PUTs return 409 | VaultWriteError "persistent 409 Conflict" |
| B3 | GitHub returns 403 with body containing `Bearer ghp_xxx...` | error returned to caller, **`_redact()` strips Bearer**, audit row has `error_message` with `Bearer REDACTED` (assert via SQL or in-memory captor) |

### Tests file structure (`tests/test_baker_vault_write.py`)

```python
import pytest
import re
from unittest.mock import patch, MagicMock
from baker_mcp.vault_write import (
    validate_path, validate_frontmatter, write_vault_file,
    _redact, VaultWriteError
)

# H1-H6: happy paths (mock _gh_get / _gh_put with Response objects)
# R1-R6: rejection paths (test validators directly OR with mocked _gh_get for R6)
# B1-B3: behaviour tests (mock _gh_put to return 409, then 200)

# AUDIT-SQL TEST (per reviewer Lesson #42):
# Capture the cursor.execute() args via MagicMock and assert:
#   - INSERT statement contains "INTO baker_actions"
#   - column tuple matches verified schema:
#     (action_type, target_task_id, payload, trigger_source, created_at, success)
#   - on UPDATE: SET clause uses success/payload/target_space_id/error_message
# Catches schema-drift regression even without a live DB.

def test_audit_insert_uses_verified_columns(monkeypatch):
    captured = []
    class FakeCur:
        def execute(self, sql, params=None):
            captured.append((sql, params))
        def fetchone(self): return {"id": 999}
        def __enter__(self): return self
        def __exit__(self, *a): pass
    class FakeConn:
        def cursor(self, cursor_factory=None): return FakeCur()
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr("psycopg2.connect", lambda **kw: FakeConn())

    from baker_mcp.baker_mcp_server import _emit_vault_write_audit
    audit_id = _emit_vault_write_audit("wiki/matters/x/red-flags.md", "append", "test", success=None)
    assert audit_id == 999
    sql, params = captured[0]
    assert "INSERT INTO baker_actions" in sql
    # Column list assertion — fail loud on schema drift
    for col in ("action_type", "target_task_id", "payload", "trigger_source", "success"):
        assert col in sql, f"missing column {col} in audit INSERT — schema drift?"

def test_redact_strips_bearer_token():
    s = "GitHub 403: bad credentials. Authorization: Bearer ghp_AAAA1234567890BBBB"
    out = _redact(s)
    assert "ghp_" not in out
    assert "Bearer REDACTED" in out
```

### Live verification (Code Brisen runs after deploy)

```bash
# 1. List tool is exposed
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep baker_vault_write

# 2. Happy path H1 — session state overwrite
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_vault_write","arguments":{
    "path":"wiki/matters/oskolkov/_session-state.md",
    "content":"# AO Desk session state\n\nLast deliberation: 2026-04-30 vault_write smoke test.\n",
    "mode":"overwrite",
    "commit_message":"AO Desk — vault_write smoke test"
  }}}'

# Expected: result with commit_sha and html_url to vault repo

# 3. Verify commit landed in vault repo
gh api repos/vallen300-bit/baker-vault/commits/main | grep '"sha"' | head -1
```

### Verification SQL (uses verified `baker_actions` columns — NOT v1 guessed `summary`/`status`)

```sql
-- Audit row landed for the smoke-test write
SELECT id, action_type, target_task_id, target_space_id, success,
       error_message, payload, created_at
FROM baker_actions
WHERE action_type = 'vault_write'
ORDER BY created_at DESC
LIMIT 5;

-- Should show:
--   * Initial INSERT: success=NULL, payload contains {mode, commit_message}
--   * After completion: success=TRUE (or FALSE), payload merged with
--     {commit_sha, content_sha, html_url, bytes_written, klass}, target_space_id=klass
--   * On failure: error_message contains the redacted error string

-- Detect stuck-NULL audit rows (defensive — should be empty)
SELECT id, target_task_id, created_at
FROM baker_actions
WHERE action_type = 'vault_write'
  AND success IS NULL
  AND created_at < NOW() - INTERVAL '5 minutes'
LIMIT 10;
```

---

## Quality Checkpoints

1. ✅ `pytest tests/test_baker_vault_write.py -v` — all H1-H6 + R1-R6 + B1-B3 + audit-SQL test + redact test pass (15 tests min)
2. ✅ `python3 -c "import py_compile; py_compile.compile('baker_mcp/vault_write.py', doraise=True)"` clean
3. ✅ `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"` clean
4. ✅ Render deploy succeeds (post-merge auto-deploy)
5. ✅ Live H1 smoke (session-state overwrite) returns commit_sha + html_url
6. ✅ Live R2 rejection (gold.md write attempt) returns clear error
7. ✅ Live R6 rejection (`wiki/_cortex/director-gold-global.md` write attempt) returns hard-blocked error
8. ✅ Audit row visible in `baker_actions` for both H1 and R2 — verify with verified-column SELECT
9. ✅ Smoke commit visible in vault repo via `gh api repos/vallen300-bit/baker-vault/commits/main`
10. ✅ NO GITHUB_TOKEN / Bearer value in any log line (grep Render logs after deploy + grep audit `error_message` column)
11. ✅ **`/security-review` skill PASS** — required pre-merge per Lesson #52 (Tier-A trigger: new external API surface + new write surface to vault repo + new audit row class)
12. ✅ Concurrent write test (fire 2 appends to same red-flags.md back-to-back) — second succeeds after sha refresh OR returns clear "persistent 409 Conflict"

---

## Out of scope (separate follow-on briefs)

1. **`BAKER_VAULT_READ_WIKI_SCOPE_1`** — extend `vault_mirror.py:_normalize_and_resolve` to accept `wiki/` prefix in addition to `_ops/`. ~30 LOC change. Required for Cortex/Desk skills to **read** what they wrote. Independent of this brief.
2. **`DESK_SKILL_AO_1`** (and 4 sibling skills) — Cowork-side SKILL.md files for AO Desk / MOVIE Desk / Hagenauer Desk / Origination Desk / Brisen Desk. These USE `baker_vault_write` and the wiki-read scope. Not blocking this brief.
3. **Cortex Stage 2 V1 backend Phase 6 archive** — server-side write path. Will reuse the same vault_write module. Not blocking this brief.

---

## Working branch

```
b{N}/baker-vault-write-1
```

(N = chosen builder; AI Head A picks at dispatch — likely B2 per current mailbox state 2026-04-30)

## Pre-flight

```bash
cd ~/bm-b{N}
git fetch origin && git checkout main && git pull --ff-only origin main
git checkout -b b{N}/baker-vault-write-1
# Read DB schema BEFORE writing audit helpers:
psql "$DATABASE_URL" -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='baker_actions' ORDER BY ordinal_position;"
# Verify GITHUB_TOKEN scope:
curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/repos/vallen300-bit/baker-vault | grep '"permissions"'
```

If `permissions.push` is `false` — **stop**, flag for Director to expand token scope. Don't proceed without write scope.

## Co-Authored-By

```
Co-authored-by: Code Brisen #{N} <b{N}@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Director-visible after merge

- Cowork-side AI Head Biz / future Desks can write durable curated knowledge to the vault via MCP.
- First Desk skill (post-`BAKER_VAULT_READ_WIKI_SCOPE_1` ship) becomes useful end-to-end.
- All writes audited; every commit visible in `gh api repos/vallen300-bit/baker-vault/commits/main`.
- Manus filesystem-as-memory pattern operationalised for Brisen.

## Dispatch trigger class: HIGH (cross-lane review required)

Per `_ops/processes/b-code-dispatch-coordination.md`: AI Head B reviews before merge. Reasons:
1. New external API call (GitHub Contents API)
2. New write surface to vault repo
3. New token-scope requirement (write permission)
4. New audit row class

AI Head B review focus areas: path-whitelist regex correctness, append vs overwrite enforcement, frontmatter validation completeness, token-redaction in error paths, baker_actions schema match, 409 retry logic.
