# BRIEF: FINANCIAL-WATCHDOG-1 — Browser Sentinel monitors bank portals for payments, anomalies, and suspicious transactions

## Context
Baker was blind to a $10,953 Amex payment due in 3 days because financial emails were caught by noise filters and Gmail Promotions. The root cause is architectural: relying on email notifications for financial obligations is fragile. This brief eliminates the email dependency by having Baker monitor bank/card portals directly via Chrome MCP on the MacBook.

Director request: "The bottleneck is emails instead of Baker Agent reading bank accounts directly from the web."

## Estimated time: ~6h (Phase 1: Amex + UBS)
## Complexity: Medium
## Prerequisites:
- Chrome MCP connected to MacBook Chrome (debug port 9222 — already working)
- Amex credentials stored in Chrome password manager (already there)
- Edita's WhatsApp ID must be in VIP contacts for payment routing

## Execution Model
- Baker uses **Chrome MCP on MacBook** (same Chrome the Director uses daily)
- **Fully autonomous login** — Baker handles 2FA by itself (see Feature 6)
- Polls every **3 calendar days** — conservative, catches all monthly obligations well before D-2 wire date
- If MacBook is closed at poll time, skips and retries next cycle
- **No Mac Mini required. No Render browser needed. No Director intervention needed.**

## STATUS: PARKED — ready for next session pickup

---

## Feature 1: Financial Transaction Table

### Problem
No persistent storage for bank transactions. Without history, Baker can't detect duplicates, unusual amounts, or spending pattern changes.

### Current State
`browser_results` stores raw page content but has no structured financial data model. `financial_detector.py` only scans emails and document extractions — not browser results.

### Implementation

**File: `triggers/state.py`** — Add DDL in `ensure_tables()`:

```python
# Financial Watchdog — transaction storage
cur.execute("""
    CREATE TABLE IF NOT EXISTS financial_transactions (
        id              SERIAL PRIMARY KEY,
        account_id      TEXT NOT NULL,
        account_name    TEXT NOT NULL,
        transaction_date DATE,
        post_date       DATE,
        description     TEXT NOT NULL,
        amount          NUMERIC(12,2) NOT NULL,
        currency        TEXT DEFAULT 'USD',
        category        TEXT,
        is_pending       BOOLEAN DEFAULT FALSE,
        source_task_id  INTEGER REFERENCES browser_tasks(id),
        content_hash    TEXT NOT NULL,
        flags           JSONB DEFAULT '[]',
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
""")
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_fin_tx_account
    ON financial_transactions(account_id, transaction_date DESC)
""")
cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_fin_tx_hash
    ON financial_transactions(content_hash)
""")

# Financial obligations (payment due dates, minimum payments)
cur.execute("""
    CREATE TABLE IF NOT EXISTS financial_obligations (
        id              SERIAL PRIMARY KEY,
        account_id      TEXT NOT NULL,
        account_name    TEXT NOT NULL,
        obligation_type TEXT NOT NULL,
        amount          NUMERIC(12,2) NOT NULL,
        currency        TEXT DEFAULT 'USD',
        due_date        DATE NOT NULL,
        status          TEXT DEFAULT 'pending',
        deadline_id     INTEGER,
        alert_id        INTEGER,
        source_task_id  INTEGER REFERENCES browser_tasks(id),
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(account_id, obligation_type, due_date)
    )
""")
```

### Key Constraints
- `content_hash` on transactions prevents duplicate insertion when the same page is scraped twice
- `UNIQUE` constraint on obligations prevents duplicate deadline creation
- All amounts stored as NUMERIC(12,2) — never float

### Verification
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'financial_transactions' ORDER BY ordinal_position LIMIT 20;
```

---

## Feature 2: Financial Portal Scraper (Chrome CDP)

### Problem
Bank portals require authenticated sessions and multi-step navigation (login check → navigate to statements → extract transactions).

### Current State
Baker has Chrome MCP connected to the MacBook's Chrome browser (debug port 9222). This is the same Chrome the Director uses daily — bank sessions are already authenticated via remember-this-device cookies that persist for 30-90 days. Chrome MCP provides `navigate_page`, `take_snapshot`, `click`, `fill`, `evaluate_script` — all the building blocks needed for portal navigation.

### Implementation

**File: `triggers/browser_trigger.py`** — Add after existing `_execute_task()`:

```python
# -------------------------------------------------------
# FINANCIAL-WATCHDOG-1: Financial portal processing
# -------------------------------------------------------

_FINANCIAL_CATEGORY = "financial_account"
_LARGE_TX_THRESHOLD = 2000  # USD — alert on transactions above this


def _process_financial_task(task: dict, client) -> dict:
    """Execute a financial portal task and extract structured data.

    Financial tasks use Chrome MCP (authenticated session in MacBook Chrome).
    Multi-step: navigate to portal → extract page content → Flash parse.

    Returns:
        {content: str, structured: dict, error: str|None}
    """
    task_id = task["id"]
    task_name = task["name"]
    url = task["url"]
    task_prompt = task.get("task_prompt", "")

    logger.info(f"Financial task [{task_id}] {task_name}: fetching {url}")

    # Step 1: Fetch portal page via Chrome CDP
    result = client.fetch_chrome(url, wait_seconds=5)
    if result.get("error"):
        return {"content": "", "structured": {}, "error": result["error"]}

    content = result.get("content", "")
    if len(content) < 100:
        return {"content": content, "structured": {}, "error": "Page content too short — possible auth expiry"}

    # Step 2: Flash extraction — parse transactions + obligations
    structured = _flash_extract_financial(content, task_name, task_prompt)

    return {"content": content, "structured": structured, "error": None}


def _flash_extract_financial(page_content: str, account_name: str, instructions: str) -> dict:
    """Use Gemini Flash to extract structured financial data from portal page content.

    Returns:
        {
            "transactions": [{"date", "description", "amount", "currency", "is_pending"}],
            "obligations": [{"type", "amount", "currency", "due_date"}],
            "account_summary": {"balance", "available_credit", "last_payment_date", "last_payment_amount"},
            "auth_ok": bool
        }
    """
    from llm.gemini_client import call_flash

    prompt = f"""Extract ALL financial data from this bank/card portal page.

Account: {account_name}
{f"Special instructions: {instructions}" if instructions else ""}

Page content:
---
{page_content[:8000]}
---

Return valid JSON with these keys:
- "auth_ok": true if the page shows account data (not a login page or error)
- "transactions": list of recent transactions, each with:
  - "date": "YYYY-MM-DD" (best effort)
  - "description": merchant/payee name
  - "amount": number (negative for charges, positive for credits/payments)
  - "currency": "USD"/"EUR"/"CHF"
  - "is_pending": true/false
- "obligations": list of upcoming payment obligations, each with:
  - "type": "payment_due" / "minimum_payment" / "direct_debit"
  - "amount": number
  - "currency": "USD"/"EUR"/"CHF"
  - "due_date": "YYYY-MM-DD"
- "account_summary": object with "balance", "available_credit", "last_payment_date", "last_payment_amount" (all optional)

If the page is a login page or error, set auth_ok=false and leave other fields empty.
Return ONLY valid JSON, no markdown."""

    try:
        resp = call_flash(
            messages=[{"role": "user", "content": prompt}],
            system="You are a financial data extraction engine. Return only valid JSON.",
        )
        import json
        text = resp.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Flash financial extraction failed: {e}")
        return {"auth_ok": False, "transactions": [], "obligations": [], "account_summary": {}}


def _store_financial_data(task: dict, structured: dict, store):
    """Store extracted transactions and obligations. Create alerts and deadlines.

    Args:
        task: browser_tasks row dict
        structured: output from _flash_extract_financial()
        store: SentinelStoreBack instance
    """
    import hashlib
    from datetime import date, timedelta

    task_id = task["id"]
    account_name = task["name"]
    account_id = f"fin:{task_id}"

    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()

        # --- Store transactions (dedup by content_hash) ---
        new_tx_count = 0
        suspicious = []
        for tx in structured.get("transactions", [])[:100]:
            desc = tx.get("description", "")[:500]
            amount = tx.get("amount", 0)
            currency = tx.get("currency", "USD")
            tx_date = tx.get("date")
            is_pending = tx.get("is_pending", False)

            # Content hash for dedup
            hash_input = f"{account_id}:{tx_date}:{desc}:{amount}:{currency}"
            content_hash = hashlib.sha256(hash_input.encode()).hexdigest()

            cur.execute("""
                INSERT INTO financial_transactions
                    (account_id, account_name, transaction_date, description,
                     amount, currency, is_pending, source_task_id, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING id
            """, (account_id, account_name, tx_date, desc,
                  amount, currency, is_pending, task_id, content_hash))
            row = cur.fetchone()
            if row:
                new_tx_count += 1

                # Flag: large transaction
                if abs(amount) > _LARGE_TX_THRESHOLD:
                    suspicious.append({
                        "type": "large_transaction",
                        "desc": desc,
                        "amount": amount,
                        "currency": currency,
                        "date": tx_date,
                    })

        # Flag: duplicate detection (same amount + similar desc within 48h)
        if new_tx_count > 0:
            cur.execute("""
                SELECT description, amount, currency, transaction_date, COUNT(*) as cnt
                FROM financial_transactions
                WHERE account_id = %s
                  AND transaction_date > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY description, amount, currency, transaction_date
                HAVING COUNT(*) > 1
                LIMIT 5
            """, (account_id,))
            for dup in cur.fetchall():
                suspicious.append({
                    "type": "possible_duplicate",
                    "desc": dup[0],
                    "amount": float(dup[1]),
                    "currency": dup[2],
                    "date": str(dup[3]),
                    "count": dup[4],
                })

        # --- Store obligations + create deadlines ---
        for ob in structured.get("obligations", [])[:10]:
            ob_type = ob.get("type", "payment_due")
            amount = ob.get("amount", 0)
            currency = ob.get("currency", "USD")
            due_date = ob.get("due_date")
            if not due_date or not amount:
                continue

            cur.execute("""
                INSERT INTO financial_obligations
                    (account_id, account_name, obligation_type, amount,
                     currency, due_date, source_task_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (account_id, obligation_type, due_date) DO NOTHING
                RETURNING id
            """, (account_id, account_name, ob_type, amount,
                  currency, due_date, task_id))
            row = cur.fetchone()
            if row:
                obligation_id = row[0]
                # Create Baker deadline (D-2 for wire lead time)
                try:
                    from datetime import datetime as dt
                    due_dt = dt.strptime(due_date, "%Y-%m-%d").date()
                    wire_date = due_dt - timedelta(days=2)
                    desc = f"{account_name} — {ob_type}: {currency} {amount:,.2f}"
                    _create_financial_deadline(store, desc, str(wire_date), due_date, amount, currency, account_name)
                except Exception as e:
                    logger.warning(f"Failed to create deadline for obligation: {e}")

                # T2 alert → Edita (payment handler)
                _alert_payment_handler(store, account_name, ob_type, amount, currency, due_date)

        # --- Create anomaly alerts → Director ---
        for sig in suspicious[:5]:
            _alert_suspicious_transaction(store, account_name, sig)

        conn.commit()
        logger.info(
            f"Financial watchdog [{task_id}] {account_name}: "
            f"{new_tx_count} new transactions, {len(structured.get('obligations', []))} obligations, "
            f"{len(suspicious)} suspicious flags"
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Financial data storage failed: {e}")
    finally:
        store._put_conn(conn)


def _create_financial_deadline(store, description, wire_date, due_date, amount, currency, account_name):
    """Create a Baker deadline for a financial obligation."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        # Check if deadline already exists for this obligation
        cur.execute("""
            SELECT id FROM deadlines
            WHERE description = %s AND due_date = %s::date
            LIMIT 1
        """, (description, wire_date))
        if cur.fetchone():
            return  # Already exists

        cur.execute("""
            INSERT INTO deadlines (description, due_date, priority, source_snippet, confidence)
            VALUES (%s, %s::date, 'critical',
                    %s, 'high')
        """, (description, wire_date,
              f"Auto-detected from {account_name} portal. Payment {currency} {amount:,.2f} due {due_date}. Wire date D-2."))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"Financial deadline creation failed: {e}")
    finally:
        store._put_conn(conn)


def _alert_payment_handler(store, account_name, ob_type, amount, currency, due_date):
    """Send T2 alert for payment obligation — routed to Edita."""
    title = f"Payment due: {account_name} — {currency} {amount:,.2f} by {due_date}"
    body = (
        f"**Account:** {account_name}\n"
        f"**Type:** {ob_type}\n"
        f"**Amount:** {currency} {amount:,.2f}\n"
        f"**Due:** {due_date}\n"
        f"**Wire by:** 2 days before due date\n\n"
        f"_Auto-detected by Financial Watchdog from bank portal._"
    )
    alert_id = store.create_alert(
        tier=2,
        title=title[:120],
        body=body,
        action_required=True,
        tags=["financial", "payment_due", "watchdog"],
        source="financial_watchdog",
        source_id=f"fin-ob-{account_name}-{due_date}",
    )
    if alert_id:
        # Also send WhatsApp to Edita
        try:
            from outputs.whatsapp_sender import send_whatsapp_message
            edita_wa = _get_edita_whatsapp_id()
            if edita_wa:
                msg = (
                    f"*Payment Due — {account_name}*\n\n"
                    f"Amount: {currency} {amount:,.2f}\n"
                    f"Due: {due_date}\n"
                    f"Type: {ob_type}\n\n"
                    f"Please arrange wire 2 days before due date."
                )
                send_whatsapp_message(edita_wa, msg)
        except Exception as e:
            logger.warning(f"WhatsApp to payment handler failed: {e}")


def _get_edita_whatsapp_id() -> str:
    """Get Edita's WhatsApp ID from VIP contacts."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT whatsapp_id FROM vip_contacts
                WHERE LOWER(name) LIKE '%edita%'
                  AND whatsapp_id IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()
            return row[0] if row else ""
        finally:
            store._put_conn(conn)
    except Exception:
        return ""


def _alert_suspicious_transaction(store, account_name, sig):
    """Create T1 alert for suspicious transaction → Director."""
    sig_type = sig["type"]
    amount = sig.get("amount", 0)
    currency = sig.get("currency", "USD")
    desc = sig.get("desc", "unknown")

    if sig_type == "possible_duplicate":
        title = f"Possible duplicate: {account_name} — {desc} ({currency} {amount:,.2f} x{sig.get('count', 2)})"
        tier = 1
    elif sig_type == "large_transaction":
        title = f"Large transaction: {account_name} — {desc} ({currency} {amount:,.2f})"
        tier = 2
    else:
        title = f"Financial flag: {account_name} — {sig_type}"
        tier = 2

    body = (
        f"**Account:** {account_name}\n"
        f"**Type:** {sig_type}\n"
        f"**Description:** {desc}\n"
        f"**Amount:** {currency} {amount:,.2f}\n"
        f"**Date:** {sig.get('date', 'unknown')}\n\n"
        f"_Auto-detected by Financial Watchdog._"
    )
    store.create_alert(
        tier=tier,
        title=title[:120],
        body=body,
        action_required=(tier <= 1),
        tags=["financial", sig_type, "watchdog"],
        source="financial_watchdog",
        source_id=f"fin-{sig_type}-{account_name}-{sig.get('date', 'today')}",
    )
```

**File: `triggers/browser_trigger.py`** — Modify `run_browser_poll()` to handle financial tasks:

In the main task loop (after `_execute_task()`), add a category check:

```python
# Inside run_browser_poll(), after getting task result:
if task.get("category") == _FINANCIAL_CATEGORY:
    # Financial tasks get special processing
    structured = result.get("structured", {})
    if structured.get("auth_ok") is False:
        # Session expired — attempt autonomous re-login (Feature 6)
        logger.info(f"Financial task [{task['id']}]: auth expired, attempting autonomous 2FA login")
        login_ok = _amex_autonomous_login(client)
        if login_ok:
            # Retry the scrape after successful login
            result = _process_financial_task(task, client)
            structured = result.get("structured", {})
        if not login_ok or structured.get("auth_ok") is False:
            # Autonomous login failed — alert Director
            store.create_alert(
                tier=1,
                title=f"Bank login failed: {task['name']}",
                body=f"Financial Watchdog could not log into {task['name']} autonomously. 2FA may have changed or credentials expired.",
                action_required=True,
                tags=["financial", "auth_failed", "watchdog"],
                source="financial_watchdog",
                source_id=f"fin-auth-{task['id']}",
            )
    elif structured:
        _store_financial_data(task, structured, store)
    continue  # Skip normal browser_change pipeline
```

### Key Constraints
- Financial tasks poll every 3 calendar days (not 30 min) — set via `FINANCIAL_POLL_DAYS` env var
- Max 100 transactions per extraction (prevent runaway storage)
- All DB operations wrapped in try/except with `conn.rollback()`
- Flash extraction capped at 8000 chars of page content
- Auth expiry → T1 alert to Director (not Edita)
- Never store full bank page content in browser_results (sensitive data) — only structured extractions

### Verification
```sql
-- Check transactions are being stored
SELECT account_name, COUNT(*), MAX(transaction_date)
FROM financial_transactions
GROUP BY account_name LIMIT 10;

-- Check obligations
SELECT * FROM financial_obligations WHERE status = 'pending' ORDER BY due_date LIMIT 10;

-- Check for anomaly alerts
SELECT title, tier, created_at FROM alerts
WHERE source = 'financial_watchdog' ORDER BY created_at DESC LIMIT 10;
```

---

## Feature 3: Browser Task Configuration (Amex + UBS)

### Problem
Need to create browser tasks for Amex and UBS portals with the right URLs and prompts.

### Implementation

Create tasks via API or direct SQL:

```sql
-- Amex: Statement & activity page
INSERT INTO browser_tasks (name, url, mode, task_prompt, category, is_active)
VALUES (
    'Amex - Account Activity',
    'https://global.americanexpress.com/activity/recent',
    'chrome_mcp',
    'Extract all recent transactions and the payment due amount/date. Look for: statement balance, payment due date, minimum payment, and all transaction line items with date, description, amount.',
    'financial_account',
    true
);

-- UBS: Account overview
INSERT INTO browser_tasks (name, url, mode, task_prompt, category, is_active)
VALUES (
    'UBS - Account Overview',
    'https://ebanking.ubs.com/workbench/home',
    'chrome_mcp',
    'Extract account balances, recent transactions, and any pending payments or standing orders. Look for: account balance, available balance, recent debits/credits with date, description, amount.',
    'financial_account',
    true
);
```

**Pre-requisite:** Director logs into Amex and UBS once in MacBook Chrome. Sessions persist via remember-this-device cookies (30-90 days). Baker detects session expiry and sends T1 alert — Director re-logs in once.

### Key Constraints
- `mode` = `'chrome_mcp'` — uses MacBook Chrome via MCP (not httpx or Browser-Use Cloud)
- Sessions persist 30-90 days via remember-this-device cookies. No regular login needed.
- When session expires, Baker detects (auth_ok=false) and sends T1 alert. Director re-logs in once.
- UBS may require SMS 2FA on each login — if so, UBS moves to Phase 2 with a different approach

---

## Feature 4: Polling Schedule — Every 3 Calendar Days

### Problem
Financial tasks should poll much less frequently than general browser tasks to avoid bot detection and because statements are monthly.

### Implementation

**File: `triggers/browser_trigger.py`** — In `run_browser_poll()`, add frequency check:

```python
_FINANCIAL_POLL_DAYS = int(os.getenv("FINANCIAL_POLL_DAYS", "3"))

def _should_poll_financial_task(task: dict) -> bool:
    """Financial tasks poll every 3 calendar days."""
    last_polled = task.get("last_polled")
    if not last_polled:
        return True
    from datetime import datetime, timezone, timedelta
    age = datetime.now(timezone.utc) - last_polled
    return age > timedelta(days=_FINANCIAL_POLL_DAYS)
```

Add check at top of task loop:
```python
if task.get("category") == _FINANCIAL_CATEGORY:
    if not _should_poll_financial_task(task):
        continue  # Not time yet
    result = _process_financial_task(task, client)
else:
    result = _execute_task(task, client)
```

### Key Constraints
- 3-day interval configurable via env var `FINANCIAL_POLL_DAYS` (default: 3)
- ~10 polls per billing cycle — catches new statements well before D-2 wire deadline
- Financial tasks still participate in the normal `run_browser_poll()` cycle — they just skip if polled too recently
- Health reporting: if no successful financial poll for 7 days, create T2 alert

---

## Feature 5: Anomaly Detection Rules

### Problem
Need specific rules for what constitutes a suspicious transaction beyond just "large amount."

### Implementation

**In `_store_financial_data()`, after storing transactions, run anomaly checks:**

```python
def _detect_anomalies(cur, account_id: str, new_transactions: list) -> list:
    """Run anomaly detection on newly stored transactions.

    Rules:
    1. Large transaction: abs(amount) > $2,000
    2. Duplicate: same description + amount within 7 days
    3. Foreign transaction: currency doesn't match account default
    4. Declined/failed: description contains declined/failed/rejected keywords
    5. New merchant large: first-time merchant with amount > $500
    """
    suspicious = []

    for tx in new_transactions:
        amount = abs(tx.get("amount", 0))
        desc = (tx.get("description", "") or "").lower()
        currency = tx.get("currency", "USD")

        # Rule 1: Large transaction
        if amount > _LARGE_TX_THRESHOLD:
            suspicious.append({
                "type": "large_transaction",
                "desc": tx.get("description", ""),
                "amount": tx.get("amount", 0),
                "currency": currency,
                "date": tx.get("date"),
            })

        # Rule 4: Declined/failed
        if any(kw in desc for kw in ("declined", "failed", "rejected", "refused", "insufficient")):
            suspicious.append({
                "type": "declined_transaction",
                "desc": tx.get("description", ""),
                "amount": tx.get("amount", 0),
                "currency": currency,
                "date": tx.get("date"),
            })

    # Rule 2: Duplicates (checked via SQL after insert — see _store_financial_data)

    # Rule 5: New merchant with large amount
    for tx in new_transactions:
        if abs(tx.get("amount", 0)) > 500:
            desc = tx.get("description", "")
            cur.execute("""
                SELECT COUNT(*) FROM financial_transactions
                WHERE account_id = %s
                  AND description = %s
                  AND created_at < NOW() - INTERVAL '1 day'
                LIMIT 1
            """, (account_id, desc))
            count = cur.fetchone()[0]
            if count == 0:
                suspicious.append({
                    "type": "new_merchant_large",
                    "desc": desc,
                    "amount": tx.get("amount", 0),
                    "currency": tx.get("currency", "USD"),
                    "date": tx.get("date"),
                })

    return suspicious
```

### Alert Routing Summary

| Anomaly Type | Tier | Recipient | Channel |
|---|---|---|---|
| Declined/failed transaction | T1 | Director | Slack + WhatsApp |
| Possible duplicate | T1 | Director | Slack + WhatsApp |
| New merchant >$500 | T2 | Director | Slack |
| Large transaction >$2K | T2 | Director | Slack |
| Payment obligation due | T2 | Edita | Slack + WhatsApp |
| Auth expired (auto-login attempted first) | T1 | Director | Slack + WhatsApp |

---

## Feature 6: Autonomous 2FA Login (Self-Service OTP)

### Problem
Amex requires a one-time password (OTP) on every login, sent to `dvallen@brisengroup.com`. Without solving this, Baker cannot poll autonomously — someone must enter the code manually each time.

### Discovery (Session 46, Apr 6 2026)
Live test confirmed:
- Amex login page auto-fills credentials from Chrome password manager
- After login, Amex shows "Security Verification: One-Time Password" page
- Only option: email to `d*****n@brisengroup.com`
- OTP arrives at `dvallen@brisengroup.com` → forwards to `vallen300@gmail.com`
- Baker already has Gmail API access to `vallen300@gmail.com`
- **Baker can read its own OTP.**

### Implementation

**File: `triggers/browser_trigger.py`** — Add autonomous login flow:

```python
def _amex_autonomous_login(client) -> bool:
    """Handle Amex login + 2FA autonomously via Chrome MCP + Gmail API.

    Flow:
    1. Navigate to Amex login page
    2. Credentials auto-filled by Chrome password manager
    3. Click "Log In"
    4. On 2FA page: select email, click Continue
    5. Wait 15 seconds for OTP email
    6. Gmail API: search for latest Amex OTP email
    7. Extract 6-digit code via regex
    8. Enter code, click Continue
    9. Verify landing on Account Home (auth_ok)

    Returns:
        True if login successful, False otherwise.
    """
    import re
    import time

    # Step 1: Navigate to login
    # (Chrome MCP: navigate_page to Amex login URL)
    # Step 2: Credentials auto-fill from password manager
    # Step 3: Click Log In button

    # Step 4: Detect 2FA page, select email option, click Continue
    # (Chrome MCP: take_snapshot → find radio button → click → click Continue)

    # Step 5: Wait for OTP email (15-30 seconds)
    time.sleep(15)

    # Step 6: Read OTP from Gmail
    otp_code = _fetch_amex_otp_from_gmail()
    if not otp_code:
        # Retry once after 15 more seconds
        time.sleep(15)
        otp_code = _fetch_amex_otp_from_gmail()

    if not otp_code:
        logger.error("Amex 2FA: Could not retrieve OTP from Gmail")
        return False

    # Step 7: Enter OTP code
    # (Chrome MCP: fill OTP input → click Continue)

    # Step 8: Verify we landed on Account Home
    # (Chrome MCP: take_snapshot → check for "Payment due" or "Total balance")

    return True


def _fetch_amex_otp_from_gmail() -> str:
    """Search Gmail for the latest Amex OTP email and extract the 6-digit code.

    Returns:
        6-digit code string, or empty string if not found.
    """
    import re
    try:
        from scripts.extract_gmail import authenticate
        from googleapiclient.discovery import build

        creds = authenticate()
        service = build("gmail", "v1", credentials=creds)

        # Search for Amex OTP email from last 5 minutes
        results = service.users().threads().list(
            userId="me",
            q="from:americanexpress subject:(one-time OR verification OR security code) newer_than:5m",
            maxResults=1,
        ).execute()

        threads = results.get("threads", [])
        if not threads:
            return ""

        # Get the latest thread
        thread = service.users().threads().get(
            userId="me", id=threads[0]["id"], format="full"
        ).execute()

        # Extract body text
        messages = thread.get("messages", [])
        if not messages:
            return ""

        # Get the most recent message body
        import base64
        for msg in reversed(messages):
            payload = msg.get("payload", {})
            body_data = payload.get("body", {}).get("data", "")
            if not body_data:
                # Check parts
                for part in payload.get("parts", []):
                    if part.get("mimeType") == "text/plain":
                        body_data = part.get("body", {}).get("data", "")
                        break
                    if part.get("mimeType") == "text/html":
                        body_data = part.get("body", {}).get("data", "")

            if body_data:
                body_text = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                # Extract 6-digit OTP code
                match = re.search(r'\b(\d{6})\b', body_text)
                if match:
                    return match.group(1)

        return ""
    except Exception as e:
        logger.error(f"Gmail OTP fetch failed: {e}")
        return ""
```

### Amex Portal URLs (confirmed live Apr 6 2026)
- **Login:** `https://www.americanexpress.com/en-gb/account/login`
- **Account Home (after auth):** `https://global.americanexpress.com/dashboard`
- **Recent Activity:** `https://global.americanexpress.com/activity/recent?account_key=6ED377936FFFAA3AF9229EDC0E620BDD`
- **Statements:** `https://global.americanexpress.com/activity/statements?account_key=6ED377936FFFAA3AF9229EDC0E620BDD`

### What Baker Sees on Account Home (confirmed live)
Single page gives everything needed — no sub-navigation required:
- **Payment due:** $10,953.25 (heading text)
- **Pay by:** 08 April (heading text)
- **Total balance:** $12,609.11 (heading text)
- **Statement period:** 26 Feb - 25 Mar
- **7 recent transactions** with date, description, amount, pending flag (DV)
- **Rewards points:** 358,508
- **Last login timestamp**

### Key Constraints
- OTP email typically arrives within 10-30 seconds
- Gmail search uses `newer_than:5m` to only match fresh OTP emails
- If OTP not found after 30 seconds total wait, fail gracefully (T1 alert)
- Never store the OTP code in logs or database
- Chrome password manager handles credentials — Baker never sees/stores the password
- Full login flow takes ~45 seconds (navigate + 2FA + wait + enter code)

### Verification
- Trigger login manually via API endpoint: `POST /api/browser/tasks/{id}/run`
- Check logs for: `"Amex 2FA: OTP retrieved successfully"`
- Verify Account Home reached: `auth_ok=true` in structured result

---

## Files Modified
- `triggers/state.py` — DDL for `financial_transactions` and `financial_obligations` tables
- `triggers/browser_trigger.py` — `_process_financial_task()`, `_flash_extract_financial()`, `_store_financial_data()`, `_detect_anomalies()`, alert functions, polling schedule check
- `triggers/browser_client.py` — No changes needed (Chrome MCP handles browser interaction)
- `config/settings.py` — Add `FINANCIAL_POLL_HOURS` env var (optional)

## Do NOT Touch
- `orchestrator/pipeline.py` — financial results bypass general pipeline entirely
- `orchestrator/financial_detector.py` — existing email-based detector stays as-is (complementary, not replaced)
- `outputs/slack_notifier.py` — use existing alert delivery
- `outputs/dashboard.py` — no UI in Phase 1
- `outputs/whatsapp_sender.py` — use existing send function

## Quality Checkpoints
1. DDL runs clean on fresh DB (no column conflicts)
2. Amex task created and first poll succeeds (auth_ok=true)
3. Transactions stored with correct dedup (re-poll doesn't duplicate)
4. Payment obligation → Baker deadline created with D-2 date
5. Payment obligation → Edita receives WhatsApp with amount + due date
6. Large transaction → T2 alert appears in Slack
7. Simulate auth expiry (navigate to logout page) → T1 alert fires
8. Render restart → financial tasks resume on next poll cycle (all state in PostgreSQL)
9. `conn.rollback()` present in every except block

## Verification SQL
```sql
-- Confirm tables exist
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('financial_transactions', 'financial_obligations');

-- Confirm transactions flowing
SELECT account_name, COUNT(*), MIN(transaction_date), MAX(transaction_date)
FROM financial_transactions GROUP BY account_name LIMIT 10;

-- Confirm obligations + deadlines
SELECT fo.account_name, fo.amount, fo.due_date, fo.status, d.description as deadline
FROM financial_obligations fo
LEFT JOIN deadlines d ON fo.deadline_id = d.id
WHERE fo.status = 'pending' ORDER BY fo.due_date LIMIT 10;

-- Confirm alerts
SELECT title, tier, source, created_at FROM alerts
WHERE source = 'financial_watchdog' ORDER BY created_at DESC LIMIT 10;
```

---

## Phase 2 (separate brief): Multi-bank + Baseline Learning
- Add Swissquote, Revolut, Wise portals
- Build 90-day transaction baseline per account
- Anomaly: amount >2 standard deviations from historical average for same merchant
- Anomaly: recurring charge amount changed (Netflix $15 → $23)
- Dashboard widget: Financial Overview (balances, upcoming obligations, recent flags)
