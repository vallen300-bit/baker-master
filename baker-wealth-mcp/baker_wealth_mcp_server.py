"""
Baker Wealth MCP Server — Edita's interface to Baker.

Exposes wealth-relevant tools only. Filters by owner IN ('edita', 'shared').
Connects to the same PostgreSQL database as Baker.

Usage:
  python3 baker_wealth_mcp_server.py

MCP Configuration (Claude Code .mcp.json):
  {
    "mcpServers": {
      "baker-wealth": {
        "command": "python3",
        "args": ["/path/to/baker-wealth-mcp/baker_wealth_mcp_server.py"],
        "env": {
          "POSTGRES_HOST": "...",
          "POSTGRES_DB": "...",
          "POSTGRES_USER": "...",
          "POSTGRES_PASSWORD": "...",
          "BAKER_API_URL": "https://baker-master.onrender.com",
          "BAKER_API_KEY": "..."
        }
      }
    }
  }
"""
import json
import os
import sys
from datetime import datetime, timezone

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Install psycopg2: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Install MCP SDK: pip install mcp", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("Baker Wealth Manager")

# ─────────────────────────────────────────────
# Database connection
# ─────────────────────────────────────────────

_conn = None

def _get_conn():
    global _conn
    if _conn and not _conn.closed:
        return _conn
    try:
        _conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            sslmode=os.getenv("POSTGRES_SSLMODE", "require"),
            connect_timeout=10,
        )
        _conn.autocommit = True
        return _conn
    except Exception as e:
        print(f"DB connection failed: {e}", file=sys.stderr)
        return None


# Owner filter for all queries
_OWNER_FILTER = "owner IN ('edita', 'shared')"


# ─────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────

@mcp.tool()
def wealth_portfolio(category: str = "") -> str:
    """Get portfolio overview or filter by category (real_estate, equity, financial, cash, liability, insurance)."""
    conn = _get_conn()
    if not conn:
        return "Database unavailable"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if category:
        cur.execute(f"""
            SELECT name, category, current_value, currency, valuation_date, valuation_source, notes
            FROM wealth_positions
            WHERE {_OWNER_FILTER} AND category = %s
            ORDER BY current_value DESC NULLS LAST
        """, (category,))
    else:
        cur.execute(f"""
            SELECT name, category, current_value, currency, valuation_date, valuation_source, notes
            FROM wealth_positions
            WHERE {_OWNER_FILTER}
            ORDER BY category, current_value DESC NULLS LAST
        """)
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return "No portfolio positions found."

    # Format as table
    lines = ["# Portfolio Positions\n"]
    current_cat = None
    total = 0
    for r in rows:
        if r["category"] != current_cat:
            current_cat = r["category"]
            lines.append(f"\n## {(current_cat or 'Other').replace('_', ' ').title()}\n")
        val = r["current_value"]
        val_str = f"{r['currency']} {val:,.0f}" if val else "No valuation"
        stale = ""
        if r["valuation_date"]:
            days_old = (datetime.now(timezone.utc).date() - r["valuation_date"]).days
            if days_old > 30:
                stale = f" ⚠️ ({days_old}d old)"
        lines.append(f"- **{r['name']}**: {val_str}{stale}")
        if r["valuation_source"]:
            lines.append(f"  Source: {r['valuation_source']}")
        if val:
            total += float(val)

    lines.append(f"\n**Total: EUR {total:,.0f}**")
    return "\n".join(lines)


@mcp.tool()
def wealth_properties() -> str:
    """Get real estate portfolio with current valuations."""
    return wealth_portfolio(category="real_estate")


@mcp.tool()
def wealth_deadlines(days: int = 90) -> str:
    """Get upcoming tax, insurance, loan payment deadlines."""
    conn = _get_conn()
    if not conn:
        return "Database unavailable"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Tax calendar
    cur.execute(f"""
        SELECT jurisdiction, obligation, due_date, status, advisor, notes
        FROM wealth_tax_calendar
        WHERE {_OWNER_FILTER}
          AND due_date >= CURRENT_DATE
          AND due_date <= CURRENT_DATE + %s * INTERVAL '1 day'
        ORDER BY due_date
    """, (days,))
    tax_items = cur.fetchall()

    # General deadlines
    cur.execute("""
        SELECT description, due_date, severity, priority
        FROM deadlines
        WHERE status = 'active'
          AND due_date >= CURRENT_DATE
          AND due_date <= CURRENT_DATE + %s * INTERVAL '1 day'
        ORDER BY due_date
        LIMIT 20
    """, (days,))
    deadlines = cur.fetchall()
    cur.close()

    lines = [f"# Upcoming Deadlines (next {days} days)\n"]

    if tax_items:
        lines.append("## Tax Calendar\n")
        for t in tax_items:
            due = t["due_date"].strftime("%d %b %Y") if t["due_date"] else "?"
            lines.append(f"- **{due}** [{t['jurisdiction']}] {t['obligation']} ({t['status']})")
            if t["advisor"]:
                lines.append(f"  Advisor: {t['advisor']}")

    if deadlines:
        lines.append("\n## General Deadlines\n")
        for d in deadlines:
            due = d["due_date"].strftime("%d %b %Y") if d["due_date"] else "?"
            sev = f" ({d['severity']})" if d.get("severity") else ""
            lines.append(f"- **{due}**{sev} {d['description']}")

    if not tax_items and not deadlines:
        lines.append("No upcoming deadlines found.")

    return "\n".join(lines)


@mcp.tool()
def wealth_documents(search: str = "", doc_type: str = "") -> str:
    """Search Edita's documents — bank statements, tax filings, policies."""
    conn = _get_conn()
    if not conn:
        return "Database unavailable"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    conditions = [_OWNER_FILTER, "full_text IS NOT NULL"]
    params = []

    if search:
        conditions.append("(filename ILIKE %s OR full_text ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if doc_type:
        conditions.append("document_type = %s")
        params.append(doc_type)

    where = " AND ".join(conditions)
    cur.execute(f"""
        SELECT id, filename, document_type, matter_slug, source_path,
               ingested_at, LEFT(full_text, 500) as preview
        FROM documents
        WHERE {where}
        ORDER BY ingested_at DESC
        LIMIT 10
    """, params)
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return f"No documents found" + (f" matching '{search}'" if search else "") + "."

    lines = [f"# Documents ({len(rows)} results)\n"]
    for r in rows:
        date = r["ingested_at"].strftime("%d %b %Y") if r.get("ingested_at") else "?"
        dtype = r.get("document_type") or "?"
        lines.append(f"### {r['filename']} [{dtype}]")
        lines.append(f"Date: {date} | Path: {r.get('source_path', '?')}")
        if r.get("preview"):
            lines.append(f"Preview: {r['preview'][:200]}...")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def wealth_ask(question: str) -> str:
    """Ask the wealth specialist a question. Routes to Baker's wealth capability."""
    import urllib.request

    api_url = os.getenv("BAKER_API_URL", "https://baker-master.onrender.com")
    api_key = os.getenv("BAKER_API_KEY", "")

    payload = json.dumps({
        "question": question,
        "capability_slug": "wealth",
    }).encode()

    req = urllib.request.Request(
        f"{api_url}/api/scan/specialist",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Baker-Key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            # SSE stream — collect text chunks
            answer_parts = []
            for line in resp:
                line = line.decode("utf-8", errors="replace").strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if chunk.get("type") == "text":
                            answer_parts.append(chunk.get("content", ""))
                    except json.JSONDecodeError:
                        answer_parts.append(data)
            return "".join(answer_parts) if answer_parts else "No response from specialist."
    except Exception as e:
        return f"Error contacting Baker: {e}"


if __name__ == "__main__":
    mcp.run()
