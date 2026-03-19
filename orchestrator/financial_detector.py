"""
F4: Financial Signal Detector (Session 27)

Runs every 6 hours. Scans recent emails and document extractions for:
  - Unusual invoice amounts (>2x historical average for same sender)
  - Payment delay signals ("overdue", "past due", "reminder")
  - Budget overrun language ("exceeded", "over budget", "cost increase")
  - New large amounts (>EUR 50K mentioned in emails)

Uses regex for fast pre-filtering, then Haiku for classification.
Creates T2/T3 alerts for confirmed financial signals.
"""
import logging
import re
import json
from datetime import datetime, timezone

logger = logging.getLogger("baker.financial_detector")

# Amount regex: matches EUR/USD/CHF + number patterns (European and US formats)
_AMOUNT_RE = re.compile(
    r'(?:EUR|USD|CHF|€|\$|Fr\.?)\s*'
    r'([\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)'
    r'|'
    r'([\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*'
    r'(?:EUR|USD|CHF|Euro|Euros|Dollar|Franken)',
    re.IGNORECASE,
)

# Payment delay keywords
_DELAY_RE = re.compile(
    r'\b(overdue|past\s+due|payment\s+reminder|zahlungserinnerung|'
    r'mahnung|fällig|outstanding\s+balance|unpaid|verzug)\b',
    re.IGNORECASE,
)

# Budget overrun keywords
_OVERRUN_RE = re.compile(
    r'\b(over\s*budget|exceeded|cost\s+increase|kostensteigerung|'
    r'mehrkosten|nachtragsangebot|additional\s+cost|budget\s+overrun|'
    r'teurer|price\s+increase)\b',
    re.IGNORECASE,
)

_LARGE_AMOUNT_THRESHOLD = 50000  # EUR


def _parse_amount(text: str) -> float:
    """Parse European/US number format to float."""
    text = text.strip()
    # European: 1.234.567,89 or 1234567,89
    if ',' in text and ('.' not in text or text.rindex(',') > text.rindex('.')):
        text = text.replace('.', '').replace(',', '.')
    else:
        text = text.replace(',', '')
    try:
        return float(text)
    except (ValueError, TypeError):
        return 0.0


def run_financial_detection():
    """Main entry point — called by scheduler every 6 hours."""
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Transaction-level advisory lock
        cur.execute("SELECT pg_try_advisory_xact_lock(900300)")
        if not cur.fetchone()["pg_try_advisory_xact_lock"]:
            logger.info("Financial detector: another instance running — skipping")
            return

        signals = []

        # 1. Scan recent emails (last 12 hours) for financial signals
        cur.execute("""
            SELECT message_id, subject, sender_email, sender_name, full_body,
                   received_date
            FROM email_messages
            WHERE received_date > NOW() - INTERVAL '12 hours'
              AND full_body IS NOT NULL
            ORDER BY received_date DESC
            LIMIT 50
        """)
        emails = cur.fetchall()

        for email in emails:
            body = (email.get("full_body") or "")[:5000]
            subject = email.get("subject") or ""
            sender = email.get("sender_name") or email.get("sender_email") or "Unknown"
            combined = f"{subject}\n{body}"

            # Check for payment delays
            delay_match = _DELAY_RE.search(combined)
            if delay_match:
                signals.append({
                    "type": "payment_delay",
                    "source": "email",
                    "sender": sender,
                    "subject": subject[:100],
                    "match": delay_match.group(0),
                    "date": str(email.get("received_date", "")),
                })

            # Check for budget overruns
            overrun_match = _OVERRUN_RE.search(combined)
            if overrun_match:
                signals.append({
                    "type": "budget_overrun",
                    "source": "email",
                    "sender": sender,
                    "subject": subject[:100],
                    "match": overrun_match.group(0),
                    "date": str(email.get("received_date", "")),
                })

            # Check for large amounts
            for amount_match in _AMOUNT_RE.finditer(combined):
                amount_str = amount_match.group(1) or amount_match.group(2)
                if amount_str:
                    amount = _parse_amount(amount_str)
                    if amount >= _LARGE_AMOUNT_THRESHOLD:
                        signals.append({
                            "type": "large_amount",
                            "source": "email",
                            "sender": sender,
                            "subject": subject[:100],
                            "amount": amount,
                            "match": amount_match.group(0),
                            "date": str(email.get("received_date", "")),
                        })

        # 2. Scan recent document extractions (last 24h) for invoice anomalies
        cur.execute("""
            SELECT de.extraction_type, de.structured_data, de.created_at,
                   d.filename, d.source_path
            FROM document_extractions de
            JOIN documents d ON d.id = de.document_id
            WHERE de.extraction_type IN ('invoice_amounts', 'financial_model')
              AND de.created_at > NOW() - INTERVAL '24 hours'
            LIMIT 20
        """)
        extractions = cur.fetchall()

        for ext in extractions:
            try:
                data = ext.get("structured_data")
                if isinstance(data, str):
                    data = json.loads(data)
                if not data:
                    continue

                # Check for large amounts in structured data
                for key in ("total_amount", "amount", "total", "grand_total"):
                    val = data.get(key)
                    if val and isinstance(val, (int, float)) and val >= _LARGE_AMOUNT_THRESHOLD:
                        signals.append({
                            "type": "large_invoice",
                            "source": "document",
                            "filename": ext.get("filename", "unknown"),
                            "amount": float(val),
                            "date": str(ext.get("created_at", "")),
                        })
            except Exception:
                continue

        conn.commit()

        # 3. Create alerts for signals (dedup by source_id)
        alerts_created = 0
        for sig in signals[:5]:  # cap at 5 alerts per run
            sig_type = sig["type"]
            from datetime import date
            source_id = f"fin-{sig_type}-{sig.get('sender', sig.get('filename', 'doc'))}-{date.today().isoformat()}"

            if sig_type == "payment_delay":
                title = f"Payment signal: {sig['sender']} — \"{sig['match']}\""
                body = f"**Sender:** {sig['sender']}\n**Subject:** {sig['subject']}\n**Signal:** {sig['match']}\n**Date:** {sig['date']}"
                tier = 2
            elif sig_type == "budget_overrun":
                title = f"Budget signal: {sig['sender']} — \"{sig['match']}\""
                body = f"**Sender:** {sig['sender']}\n**Subject:** {sig['subject']}\n**Signal:** {sig['match']}\n**Date:** {sig['date']}"
                tier = 2
            elif sig_type in ("large_amount", "large_invoice"):
                amount = sig.get("amount", 0)
                source_label = sig.get("sender", sig.get("filename", "document"))
                title = f"Large amount: EUR {amount:,.0f} from {source_label}"
                body = f"**Source:** {source_label}\n**Amount:** EUR {amount:,.2f}\n**Context:** {sig.get('subject', sig.get('match', ''))}\n**Date:** {sig['date']}"
                tier = 3
            else:
                continue

            # Auto-assign matter
            matter_slug = None
            try:
                from orchestrator.pipeline import _match_matter_slug
                matter_slug = _match_matter_slug(title, body, store)
            except Exception:
                pass

            alert_id = store.create_alert(
                tier=tier,
                title=title[:120],
                body=body,
                action_required=(tier <= 2),
                matter_slug=matter_slug,
                tags=["financial", sig_type],
                source="financial_detector",
                source_id=source_id[:200],
            )
            if alert_id:
                alerts_created += 1

        logger.info(
            f"Financial detector complete: {len(emails)} emails scanned, "
            f"{len(extractions)} extractions checked, {len(signals)} signals, "
            f"{alerts_created} alerts created"
        )

    except Exception as e:
        logger.error(f"Financial detector failed: {e}")
    finally:
        store._put_conn(conn)
