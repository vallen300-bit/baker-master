# BRIEF: BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 — surface linkedin_url + source_of_introduction on baker_vip_contacts MCP tool

## Context

Phase 3 live researcher test (2026-05-23) surfaced a real defect on the `baker_vip_contacts` MCP tool surface. The `vip_contacts` PostgreSQL table has `linkedin_url` (TEXT) and `source_of_introduction` (TEXT) columns (verified `memory/store_back.py:2376` + `:2383`). The MCP tool's underlying SQL is `SELECT *` so the values ARE returned in the response — but:

1. **The tool description lies by omission.** `baker_mcp/baker_mcp_server.py:259` says "List Baker's VIP contacts — key people tracked by the system." with no mention of provenance fields. Researcher (and any other agent reading the tool description before deciding to use it) doesn't know `linkedin_url` is available.
2. **Search doesn't match provenance columns.** `baker_mcp/baker_mcp_server.py:1397` SQL: `WHERE name ILIKE %s OR role ILIKE %s OR email ILIKE %s` — `linkedin_url` and `source_of_introduction` aren't in the WHERE. So `search="linkedin.com/in/jane-doe"` matches nothing even when that URL is the canonical row.
3. **The input schema description repeats the lie.** `baker_mcp/baker_mcp_server.py:263` `search` param: "Search by name, role, or email" — agents who read schemas (most LLM clients do) infer those are the only searchable fields.

Result during Phase 3: researcher had to **inline-encode `linkedin_url` into `role_context`** because there was no other way to surface the URL through `baker_upsert_vip` and have it be visible to a downstream agent reading `baker_vip_contacts`. That's a workaround, not a fix.

**§X-26 ratification anchor:** Director ratified 2026-05-23 chat ("§X-26 ratified"). Surfaced by cowork-ah1 on bus #732 (researcher-verify-citations arc closure). Brief authored 2026-05-23 ~13:30Z by lead.

### Surface contract: N/A — pure MCP backend (tool description text + SQL WHERE clause). No new clickable surface, no dashboard panel, no anchor links.

## Estimated time: ~1-2h
## Complexity: Low
## Prerequisites:
- `vip_contacts` table has `linkedin_url` + `source_of_introduction` columns (confirmed via `memory/store_back.py:2376/2383` `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- Baker MCP server is live (`baker_mcp/baker_mcp_server.py`); deploy path via Render auto-deploy on push to main.

---

## Fix/Feature 1: Expose provenance fields on baker_vip_contacts

### Problem

See Context. Three concrete defects in the tool surface:
1. Tool description doesn't mention `linkedin_url` / `source_of_introduction` are returned.
2. Tool input schema `search` param description doesn't mention provenance fields are searchable.
3. The underlying SQL `WHERE` clause doesn't match against `linkedin_url` or `source_of_introduction`.

### Current State

- **Tool definition:** `baker_mcp/baker_mcp_server.py:257-267`:
  ```python
  Tool(
      name="baker_vip_contacts",
      description="List Baker's VIP contacts — key people tracked by the system.",
      inputSchema={
          "type": "object",
          "properties": {
              "search": {"type": "string", "description": "Search by name, role, or email"},
              "limit": {"type": "integer", "default": 50},
          },
      },
  ),
  ```

- **Tool handler:** `baker_mcp/baker_mcp_server.py:1393-1402`:
  ```python
  elif name == "baker_vip_contacts":
      search = args.get("search")
      limit = args.get("limit", 50)
      if search:
          sql = "SELECT * FROM vip_contacts WHERE name ILIKE %s OR role ILIKE %s OR email ILIKE %s ORDER BY name"
          pat = f"%{search}%"
          rows = _query(sql, (pat, pat, pat), limit)
      else:
          rows = _query("SELECT * FROM vip_contacts ORDER BY name", limit=limit)
      return _format_results(rows, "VIP Contacts")
  ```

- **Output formatter:** `baker_mcp/baker_mcp_server.py:140-152` `_format_results()` iterates ALL key/value pairs from each row (no column filtering). So when `linkedin_url` and `source_of_introduction` are non-NULL, they DO appear in the response text. The defect is purely on the **declared surface** + **searchable** dimensions, not on the output dimension.

- **Schema source-of-truth:** `memory/store_back.py:2376` (`source_of_introduction TEXT`) + `:2383` (`linkedin_url TEXT`). Both added via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` at SentinelStoreBack `_ensure_*_base` bootstrap path. No migration file (bootstrap-only).

- **Migration-vs-bootstrap check (Brief Standard #4):** These columns are bootstrap-DDL only, no migration files. No migration drift trap here; no DDL changes in this brief either (read-only surface change + SQL WHERE expansion).

### Implementation

#### Step 1 — Update tool description + input schema at `baker_mcp/baker_mcp_server.py:257-267`

Replace the existing block with:

```python
    Tool(
        name="baker_vip_contacts",
        description=(
            "List Baker's VIP contacts — key people tracked by the system. "
            "Returns full provenance fields including linkedin_url + source_of_introduction "
            "(both stored on vip_contacts table). Search matches name / role / email / "
            "linkedin_url / source_of_introduction."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": (
                        "Search by name, role, email, linkedin_url, or "
                        "source_of_introduction (case-insensitive substring match)"
                    ),
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
```

#### Step 2 — Update SQL WHERE clause at `baker_mcp/baker_mcp_server.py:1393-1402`

Replace the handler body with:

```python
    elif name == "baker_vip_contacts":
        search = args.get("search")
        limit = args.get("limit", 50)
        if search:
            # Match name / role / email + provenance fields (linkedin_url,
            # source_of_introduction). Surface refinement
            # BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 (2026-05-23).
            sql = (
                "SELECT * FROM vip_contacts "
                "WHERE name ILIKE %s "
                "   OR role ILIKE %s "
                "   OR email ILIKE %s "
                "   OR linkedin_url ILIKE %s "
                "   OR source_of_introduction ILIKE %s "
                "ORDER BY name"
            )
            pat = f"%{search}%"
            rows = _query(sql, (pat, pat, pat, pat, pat), limit)
        else:
            rows = _query("SELECT * FROM vip_contacts ORDER BY name", limit=limit)
        return _format_results(rows, "VIP Contacts")
```

Five `%s` placeholders, five `pat` parameters in the tuple. Verify exact count before commit — mismatched count is a runtime psycopg error.

#### Step 3 — Verify NULL handling

The `ILIKE` operator on a NULL column returns NULL, not TRUE. PostgreSQL's `OR` short-circuits on TRUE so a NULL `linkedin_url` will not cause a row to mistakenly match. But it also won't cause any row to be **excluded** that previously matched. Behavior is additive and safe: rows with NULL `linkedin_url` still match if their `name` / `role` / `email` match.

No code change needed for NULL handling; this is a documentation point for the reviewer.

#### Step 4 — Tests `tests/test_baker_vip_contacts_provenance.py`

```python
"""BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 — tests for provenance search match.

Verifies the baker_vip_contacts MCP tool's SQL WHERE clause includes
linkedin_url + source_of_introduction.
"""
from __future__ import annotations

import re
from pathlib import Path


_SERVER_FILE = Path(__file__).resolve().parent.parent / "baker_mcp" / "baker_mcp_server.py"


def _read_server_source() -> str:
    return _SERVER_FILE.read_text(encoding="utf-8")


def test_tool_description_mentions_provenance_fields():
    """Tool description must mention linkedin_url + source_of_introduction."""
    src = _read_server_source()
    # Locate Tool(name="baker_vip_contacts", ...) block (~lines 257-267).
    m = re.search(
        r'name="baker_vip_contacts".*?description=\((.*?)\)',
        src,
        flags=re.DOTALL,
    )
    assert m, "Tool definition for baker_vip_contacts not found"
    desc = m.group(1)
    assert "linkedin_url" in desc, "description should mention linkedin_url"
    assert "source_of_introduction" in desc, "description should mention source_of_introduction"


def test_search_input_schema_mentions_provenance_fields():
    """search input-schema description must mention linkedin_url + source_of_introduction."""
    src = _read_server_source()
    # Heuristic: find "search" property near baker_vip_contacts.
    m = re.search(
        r'name="baker_vip_contacts".*?"search":\s*\{(.*?)\}',
        src,
        flags=re.DOTALL,
    )
    assert m, "baker_vip_contacts search property not found"
    block = m.group(1)
    assert "linkedin_url" in block, "search description should mention linkedin_url"
    assert "source_of_introduction" in block, "search description should mention source_of_introduction"


def test_sql_where_clause_includes_provenance_columns():
    """The vip_contacts WHERE clause must reference linkedin_url AND source_of_introduction."""
    src = _read_server_source()
    # Locate the baker_vip_contacts elif branch.
    m = re.search(
        r'elif name == "baker_vip_contacts":(.*?)(elif name ==|\Z)',
        src,
        flags=re.DOTALL,
    )
    assert m, "baker_vip_contacts handler branch not found"
    handler = m.group(1)
    assert "linkedin_url ILIKE" in handler, "WHERE clause must match linkedin_url"
    assert "source_of_introduction ILIKE" in handler, "WHERE clause must match source_of_introduction"
    # Five-placeholder check — guard against tuple/placeholder count drift.
    placeholders = re.findall(r"ILIKE %s", handler)
    assert len(placeholders) == 5, (
        f"Expected exactly 5 ILIKE %s placeholders in WHERE; got {len(placeholders)}"
    )


def test_sql_parameter_tuple_has_five_pat_entries():
    """The handler's psycopg parameter tuple must pass exactly 5 pat values."""
    src = _read_server_source()
    m = re.search(
        r'elif name == "baker_vip_contacts":(.*?)(elif name ==|\Z)',
        src,
        flags=re.DOTALL,
    )
    assert m, "baker_vip_contacts handler branch not found"
    handler = m.group(1)
    # Find _query(sql, (pat, pat, ...), limit) call.
    call = re.search(r"_query\(sql,\s*\((.*?)\),\s*limit\)", handler, flags=re.DOTALL)
    assert call, "_query call with tuple parameter not found"
    pats = [p.strip() for p in call.group(1).split(",") if p.strip()]
    assert len(pats) == 5, f"Expected 5 pat params; got {len(pats)}: {pats}"
    assert all(p == "pat" for p in pats), f"All params should be 'pat'; got {pats}"
```

These are **static-source tests** — they read the file and assert on its content. No live DB required, no MCP server boot needed. Fast (~ms), deterministic, runs in any CI environment.

### Key Constraints

- **DO NOT change the underlying SQL behavior for the `else` (no-search) branch.** It already does `SELECT *` which returns all columns. Only the WHERE-clause expansion is in scope when `search` is provided.
- **DO NOT modify `_format_results`** — output formatter already iterates all columns. Changing it could affect every other MCP tool.
- **DO NOT modify `vip_contacts` table schema** — columns already exist. No `ALTER TABLE`, no migration file.
- **DO NOT modify `baker_upsert_vip`** — separate tool, separate concern. Brief is `baker_vip_contacts` (read) only.
- **DO NOT touch `outputs/dashboard.py` `list_vip_contacts`** — different surface (HTTP API for delegate picker), out of scope.
- **DO NOT touch `models/deadlines.py` `get_vip_contacts()`** — that's the Python-side helper used by dashboard, not the MCP path.
- **Five `%s` placeholders ↔ five `pat` tuple entries.** Verify count before commit. Mismatched count → psycopg runtime error.
- **`ILIKE` on NULL is safe.** No `COALESCE` needed; OR short-circuit handles it.

### Verification

#### Literal `pytest` output (ship gate):

```bash
cd ~/bm-aihead1 && pytest tests/test_baker_vip_contacts_provenance.py -v
# Expected: 4 passed
```

Paste literal output in ship report. No "by inspection."

#### Syntax check:

```bash
python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"
```

#### Post-merge spot-check (manual, AI Head):

```bash
# Render auto-deploys on push to main.
# Then exercise the live MCP tool:
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | python3 -m json.tool | grep -A6 baker_vip_contacts
# Expected: description includes "linkedin_url" + "source_of_introduction"
```

#### Live search verification (Director-runnable):

```bash
# A search by linkedin URL substring now matches:
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_vip_contacts","arguments":{"search":"linkedin.com/in","limit":5}}}' \
  | python3 -m json.tool
# Expected: rows where linkedin_url contains "linkedin.com/in" are returned.
# Pre-fix: zero rows. Post-fix: all VIPs with a populated linkedin_url.
```

---

## Files Modified

- `baker_mcp/baker_mcp_server.py` — tool description + input schema description (~line 257-267) + SQL WHERE clause + parameter tuple (~line 1393-1402)

## Files Created

- `tests/test_baker_vip_contacts_provenance.py` — 4 static-source tests

## Do NOT Touch

- `_format_results()` (`baker_mcp/baker_mcp_server.py:140-152`) — shared output formatter
- `baker_upsert_vip` (write tool) — separate concern; provenance is already write-supported
- `vip_contacts` table schema — columns exist, no DDL change
- `outputs/dashboard.py /api/contacts/vips` endpoint — different surface, out of scope
- `models/deadlines.py get_vip_contacts()` — non-MCP helper, out of scope
- Other MCP tools' descriptions / WHERE clauses — single-tool surgical brief

## Quality Checkpoints

1. `baker_vip_contacts` tool description string mentions both `linkedin_url` AND `source_of_introduction`.
2. `search` input-schema description mentions both `linkedin_url` AND `source_of_introduction`.
3. SQL WHERE clause references `linkedin_url ILIKE %s` AND `source_of_introduction ILIKE %s`.
4. Exactly 5 `%s` placeholders in the WHERE clause.
5. Exactly 5 `pat` entries in the `_query()` parameter tuple.
6. Tests pass via literal `pytest -v` — paste output in ship report.
7. Syntax check clean on `baker_mcp/baker_mcp_server.py`.
8. No DDL changes; no migration files added.
9. `_format_results` untouched.
10. No other MCP tool's behavior changed.

## Verification SQL

```sql
-- Confirm linkedin_url + source_of_introduction columns are populated for at least
-- some VIP rows post-deploy. (Sanity that the search target is non-empty.)
SELECT
    COUNT(*) FILTER (WHERE linkedin_url IS NOT NULL AND linkedin_url <> '') AS rows_with_linkedin,
    COUNT(*) FILTER (WHERE source_of_introduction IS NOT NULL AND source_of_introduction <> '') AS rows_with_source,
    COUNT(*) AS total_rows
  FROM vip_contacts
  LIMIT 1;
```

---

## Risks + lessons applied

| Anti-pattern (from `tasks/lessons.md`) | Mitigation in this brief |
|---|---|
| Function name guessing | Tool name `baker_vip_contacts` + handler branch `elif name == "baker_vip_contacts"` verified against `baker_mcp/baker_mcp_server.py:258 + 1393` |
| Column name guessing | `linkedin_url` + `source_of_introduction` verified in `memory/store_back.py:2376 + 2383` ADD COLUMN IF NOT EXISTS bootstraps |
| Migration-vs-bootstrap drift | Both columns are bootstrap-only (no migration files); brief adds zero DDL — safe |
| Brief snippet wrong signature | Five `%s` placeholders ↔ five `pat` tuple entries explicit + asserted by test #4 |
| Unbounded SQL queries | `LIMIT` preserved (default 50; `args.get("limit", 50)`); verification SQL has `LIMIT 1` |
| Already-implemented brief | Git log searched for "VIP_MCP" / "PROVENANCE" — no prior commits; brief is genuinely new |
| Editing applied migration | No migration changes — column DDL stays in store_back.py bootstrap path |
| Secrets in brief | No credential values; only env-var-NAME reference (`bakerbhavanga` key is a public anchor in `.claude/docs/baker-mcp-api.md` already) |
| `ILIKE` on NULL | Documented as safe (PostgreSQL `OR` short-circuit) — no behavior change for existing rows |

## Estimated cost

- B-code time: ~1-2h (tool description + WHERE clause + 4 static tests + sanity grep)
- AI Head time post-merge: ~5 min (curl spot-check + live search verification)
- LLM cost: $0 — no LLM calls in this brief
- Infrastructure cost: $0 — no new services, no new DB tables, no Render config change
- Storage cost: $0

---

## Reporting

- Ship PR against baker-master `main` from branch `b<N>/baker-vip-mcp-expose-provenance-fields-1` (B-code claiming the brief).
- **Bus-post `lead` on PR open** with topic `ship/baker-vip-mcp-expose-provenance-fields-1` (`dispatched_by: lead` ⇒ ship-report to `lead`).
- Gate chain on PR open: AH1 static + `/security-review` (FIRES — touches MCP tool surface per §Security Review Protocol invariant S2 audit boundary) + `feature-dev:code-reviewer` 2nd-pass (FIRES per §Code-reviewer 2nd-pass Protocol trigger 4 — external-surface endpoint / MCP tool surface).

`dispatched_by:` and reply-target slug set by the AH1 instance claiming the dispatch.
