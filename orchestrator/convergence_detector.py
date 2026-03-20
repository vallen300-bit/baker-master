"""
CROSS-MATTER-CONVERGENCE-1 — Cross-Matter Convergence Detection (Session 29)

Weekly job: extract key entities from recent activity across ALL matters,
detect when the same entity appears in multiple unrelated matters,
and generate convergence alerts.

This is the "connecting dots" capability — the insight that makes a CoS
indispensable.

Examples:
- "Contractor X appears in 3 disputes — possible pattern"
- "Thomas Leitner appeared in 3 meetings across 2 matters"
- "EUR 215K + EUR 180K = EUR 395K outflow this month across 2 matters"

Runs weekly (Wednesdays 06:00 UTC). Uses Haiku for entity extraction
and Haiku for convergence analysis. ~EUR 0.50/run.
"""
import json
import logging
from datetime import datetime, timezone, date

import anthropic

from config.settings import config

logger = logging.getLogger("baker.convergence_detector")


# ─────────────────────────────────────────────────
# Entity extraction via Haiku
# ─────────────────────────────────────────────────

_ENTITY_EXTRACT_PROMPT = """Extract key entities from these alerts/messages for a specific matter.
Return ONLY a JSON object with these keys:
{
  "people": ["Name1", "Name2"],
  "companies": ["Company1", "Company2"],
  "amounts": [{"value": 50000, "currency": "EUR", "context": "what it's for"}],
  "dates": [{"date": "2026-04-15", "context": "what's happening"}],
  "locations": ["City1", "City2"]
}

Rules:
- Only extract SPECIFIC entities — no generic terms.
- Normalize names: "Dr. Schmidt" and "Schmidt" → "Schmidt".
- Amounts must be numeric (no strings like "significant").
- Dates must be ISO format.
- Skip boilerplate entities (e.g., "Brisen Group", "Dimitry Vallen").
- If no entities of a type, use empty array."""


def _extract_entities_for_matter(matter_name: str, texts: list) -> dict:
    """Use Haiku to extract entities from a matter's recent activity."""
    if not texts:
        return {"people": [], "companies": [], "amounts": [], "dates": [], "locations": []}

    combined = f"Matter: {matter_name}\n\n"
    for i, t in enumerate(texts[:15], 1):
        combined += f"{i}. {t[:300]}\n"

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": f"{_ENTITY_EXTRACT_PROMPT}\n\nTexts:\n{combined}",
            }],
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "claude-haiku-4-5-20251001", resp.usage.input_tokens,
                resp.usage.output_tokens, source="convergence_extract",
            )
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        return json.loads(raw)

    except Exception as e:
        logger.warning(f"Entity extraction failed for {matter_name}: {e}")
        return {"people": [], "companies": [], "amounts": [], "dates": [], "locations": []}


# ─────────────────────────────────────────────────
# Convergence detection
# ─────────────────────────────────────────────────

def _find_convergences(matter_entities: dict) -> list:
    """
    Find entities that appear in 2+ matters.
    matter_entities: {matter_name: {people: [...], companies: [...], ...}}
    Returns list of convergence dicts.
    """
    # Skip these common entities that would create noise
    _SKIP_PEOPLE = {
        "dimitry vallen", "vallen", "dimitry", "baker", "brisen",
    }
    _SKIP_COMPANIES = {
        "brisen group", "brisen", "brisen development", "baker",
    }

    convergences = []

    # People convergences
    people_matters = {}  # person → [matters]
    for matter, entities in matter_entities.items():
        for person in entities.get("people", []):
            normalized = person.strip().lower()
            if normalized in _SKIP_PEOPLE or len(normalized) < 3:
                continue
            if normalized not in people_matters:
                people_matters[normalized] = []
            people_matters[normalized].append(matter)

    for person, matters in people_matters.items():
        if len(set(matters)) >= 2:
            convergences.append({
                "type": "person",
                "entity": person.title(),
                "matters": list(set(matters)),
                "count": len(set(matters)),
            })

    # Company convergences
    company_matters = {}
    for matter, entities in matter_entities.items():
        for company in entities.get("companies", []):
            normalized = company.strip().lower()
            if normalized in _SKIP_COMPANIES or len(normalized) < 3:
                continue
            if normalized not in company_matters:
                company_matters[normalized] = []
            company_matters[normalized].append(matter)

    for company, matters in company_matters.items():
        if len(set(matters)) >= 2:
            convergences.append({
                "type": "company",
                "entity": company.title(),
                "matters": list(set(matters)),
                "count": len(set(matters)),
            })

    # Amount convergences (cumulative exposure within 30 days)
    total_amounts = {}  # currency → total
    matter_amounts = {}  # currency → [(matter, amount, context)]
    for matter, entities in matter_entities.items():
        for amt in entities.get("amounts", []):
            currency = amt.get("currency", "EUR")
            value = amt.get("value", 0)
            context = amt.get("context", "")
            if not value or value < 1000:
                continue
            if currency not in total_amounts:
                total_amounts[currency] = 0
                matter_amounts[currency] = []
            total_amounts[currency] += value
            matter_amounts[currency].append((matter, value, context))

    for currency, total in total_amounts.items():
        items = matter_amounts[currency]
        unique_matters = set(m for m, _, _ in items)
        if len(unique_matters) >= 2 and total >= 50000:
            convergences.append({
                "type": "financial_exposure",
                "entity": f"{currency} {total:,.0f}",
                "matters": list(unique_matters),
                "count": len(unique_matters),
                "details": [
                    {"matter": m, "amount": v, "context": c}
                    for m, v, c in items
                ],
            })

    # Sort by significance (more matters = more significant)
    convergences.sort(key=lambda c: c["count"], reverse=True)
    return convergences


# ─────────────────────────────────────────────────
# Convergence analysis via Haiku
# ─────────────────────────────────────────────────

_ANALYSIS_PROMPT = """You are Baker, AI Chief of Staff. Analyze these cross-matter convergences.

For each convergence, explain:
1. WHY this connection matters (strategic implication)
2. WHAT the Director should do about it (specific action)
3. RISK LEVEL (high/medium/low)

Be specific and actionable. If a convergence is trivial (e.g., same lawyer appearing in related matters), say so.
Only flag convergences that are genuinely surprising or require action.

Return ONLY valid JSON:
{
  "insights": [
    {
      "title": "Short descriptive title",
      "body": "2-3 sentences: what this means and what to do",
      "risk_level": "high|medium|low",
      "matters_involved": ["Matter1", "Matter2"]
    }
  ]
}"""


def _analyze_convergences(convergences: list) -> list:
    """Use Haiku to analyze convergences and generate insights."""
    if not convergences:
        return []

    conv_text = json.dumps(convergences[:10], indent=2)

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": f"{_ANALYSIS_PROMPT}\n\nConvergences:\n{conv_text}",
            }],
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "claude-haiku-4-5-20251001", resp.usage.input_tokens,
                resp.usage.output_tokens, source="convergence_analysis",
            )
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)
        return result.get("insights", [])

    except Exception as e:
        logger.warning(f"Convergence analysis failed: {e}")
        return []


# ─────────────────────────────────────────────────
# Data gathering
# ─────────────────────────────────────────────────

def _gather_matter_texts() -> dict:
    """
    Gather recent alert + email texts per matter (last 14 days).
    Returns {matter_name: [text1, text2, ...]}.
    """
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return {}

    matter_texts = {}
    _INTERNAL_MATTERS = {"Baker", "Brisen-AI", "Owner's Lens"}

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get active matters
        cur.execute("SELECT matter_name FROM matter_registry WHERE status = 'active'")
        matters = [r["matter_name"] for r in cur.fetchall() if r["matter_name"] not in _INTERNAL_MATTERS]

        for matter in matters:
            texts = []

            # Alerts from last 14 days
            cur.execute("""
                SELECT title, body FROM alerts
                WHERE created_at > NOW() - INTERVAL '14 days'
                  AND (matter_slug = %s OR title ILIKE %s)
                ORDER BY created_at DESC
                LIMIT 10
            """, (matter, f"%{matter}%"))
            for r in cur.fetchall():
                texts.append(f"[Alert] {r['title']}: {(r.get('body') or '')[:200]}")

            # Emails from last 14 days
            cur.execute("""
                SELECT subject, sender_name, body_preview FROM email_messages
                WHERE received_date > NOW() - INTERVAL '14 days'
                  AND (subject ILIKE %s OR sender_name ILIKE %s)
                ORDER BY received_date DESC
                LIMIT 10
            """, (f"%{matter}%", f"%{matter}%"))
            for r in cur.fetchall():
                texts.append(f"[Email from {r.get('sender_name', '?')}] {r['subject']}: {(r.get('body_preview') or '')[:200]}")

            if texts:
                matter_texts[matter] = texts

        cur.close()
    except Exception as e:
        logger.error(f"Matter text gathering failed: {e}")
    finally:
        store._put_conn(conn)

    return matter_texts


# ─────────────────────────────────────────────────
# Delivery
# ─────────────────────────────────────────────────

def _deliver_convergences(insights: list, convergences: list):
    """Create alerts for high-value convergences."""
    if not insights:
        return

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()

    alerts_created = 0
    for insight in insights[:3]:  # Max 3 convergence alerts
        risk = insight.get("risk_level", "medium")
        tier = 1 if risk == "high" else 2

        matters = insight.get("matters_involved", [])
        matter_str = " + ".join(matters[:3])

        alert_id = store.create_alert(
            tier=tier,
            title=f"Convergence: {insight.get('title', 'Cross-matter connection')}"[:120],
            body=f"**Matters:** {matter_str}\n\n{insight.get('body', '')}",
            action_required=(risk in ("high", "medium")),
            tags=["convergence", "cross-matter"],
            source="convergence_detector",
            source_id=f"convergence-{date.today().isoformat()}-{alerts_created}",
        )
        if alert_id:
            alerts_created += 1

    # WhatsApp summary if any high-risk convergences
    high_risk = [i for i in insights if i.get("risk_level") == "high"]
    if high_risk:
        try:
            from outputs.whatsapp_sender import send_whatsapp
            wa_lines = ["[Convergence] Cross-matter connections detected:"]
            for i, insight in enumerate(high_risk[:2], 1):
                wa_lines.append(f"\n{i}. {insight.get('title', '')}")
                wa_lines.append(f"   {insight.get('body', '')[:120]}")
            send_whatsapp("\n".join(wa_lines)[:1500])
        except Exception as e:
            logger.warning(f"Convergence WA delivery failed: {e}")

    logger.info(f"Convergence delivery: {alerts_created} alerts created")


# ─────────────────────────────────────────────────
# API helper
# ─────────────────────────────────────────────────

def get_convergence_report(days: int = 14) -> dict:
    """Run convergence detection on-demand for API. Returns raw results."""
    matter_texts = _gather_matter_texts()
    if not matter_texts:
        return {"status": "no_data", "matters_analyzed": 0}

    # Extract entities per matter
    matter_entities = {}
    for matter, texts in matter_texts.items():
        entities = _extract_entities_for_matter(matter, texts)
        matter_entities[matter] = entities

    # Find convergences
    convergences = _find_convergences(matter_entities)

    # Analyze
    insights = _analyze_convergences(convergences) if convergences else []

    return {
        "status": "ok",
        "matters_analyzed": len(matter_entities),
        "convergences_found": len(convergences),
        "insights": insights,
        "raw_convergences": convergences[:10],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def run_convergence_detection():
    """
    Main entry point — called by scheduler weekly (Wednesdays 06:00 UTC).
    1. Gather recent texts per matter
    2. Extract entities via Haiku
    3. Detect convergences
    4. Analyze significance via Haiku
    5. Deliver as alerts
    """
    from triggers.sentinel_health import report_success, report_failure

    try:
        # Advisory lock
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(900500)")
            if not cur.fetchone()[0]:
                logger.info("Convergence detection: another instance running — skipping")
                return
            cur.close()
        finally:
            store._put_conn(conn)

        logger.info("Convergence detection: starting...")

        # 1. Gather
        matter_texts = _gather_matter_texts()
        if not matter_texts:
            logger.info("Convergence detection: no matter activity found")
            return

        logger.info(f"Convergence detection: analyzing {len(matter_texts)} matters")

        # 2. Extract entities
        matter_entities = {}
        for matter, texts in matter_texts.items():
            entities = _extract_entities_for_matter(matter, texts)
            matter_entities[matter] = entities

        # 3. Detect convergences
        convergences = _find_convergences(matter_entities)
        logger.info(f"Convergence detection: {len(convergences)} convergences found")

        if not convergences:
            logger.info("Convergence detection: no cross-matter convergences — clean")
            return

        # 4. Analyze
        insights = _analyze_convergences(convergences)
        logger.info(f"Convergence detection: {len(insights)} insights generated")

        # 5. Deliver
        _deliver_convergences(insights, convergences)

        # 6. Store analysis for reference
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.log_deep_analysis(
                topic="Cross-matter convergence analysis",
                prompt="Weekly convergence detection",
                analysis_text=json.dumps({
                    "matters_analyzed": len(matter_entities),
                    "convergences": convergences[:10],
                    "insights": insights,
                }, indent=2),
                source_documents=", ".join(matter_texts.keys()),
            )
        except Exception:
            pass

        report_success("convergence_detector")
        logger.info(
            f"Convergence detection complete: {len(matter_texts)} matters, "
            f"{len(convergences)} convergences, {len(insights)} insights"
        )

    except Exception as e:
        report_failure("convergence_detector", str(e))
        logger.error(f"Convergence detection failed: {e}")
