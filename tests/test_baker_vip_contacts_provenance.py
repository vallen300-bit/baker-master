"""BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 — tests for provenance search match.

Verifies the baker_vip_contacts MCP tool's surface (description + input schema
+ SQL WHERE clause + parameter tuple) includes linkedin_url +
source_of_introduction. Static-source assertions — no live DB, no MCP server
boot, no live env required.
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
    m = re.search(
        r'elif name == "baker_vip_contacts":(.*?)(elif name ==|\Z)',
        src,
        flags=re.DOTALL,
    )
    assert m, "baker_vip_contacts handler branch not found"
    handler = m.group(1)
    assert "linkedin_url ILIKE" in handler, "WHERE clause must match linkedin_url"
    assert "source_of_introduction ILIKE" in handler, "WHERE clause must match source_of_introduction"
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
    call = re.search(r"_query\(sql,\s*\((.*?)\),\s*limit\)", handler, flags=re.DOTALL)
    assert call, "_query call with tuple parameter not found"
    pats = [p.strip() for p in call.group(1).split(",") if p.strip()]
    assert len(pats) == 5, f"Expected 5 pat params; got {len(pats)}: {pats}"
    assert all(p == "pat" for p in pats), f"All params should be 'pat'; got {pats}"
