# BRIEF: WhatsApp Inline Send Fix

**Priority:** High — Director can't send WhatsApp to people not in VIP contacts
**Ticket:** WHATSAPP-INLINE-SEND-1

## Problem

When the Director says "Send a WhatsApp to Marisol" and Marisol isn't in `vip_contacts`, Baker refuses with "I don't have their number." Even after the Director adds the contact in the same conversation, Baker still can't send on the next message.

**Root causes:**
1. `_resolve_names_to_whatsapp_ids()` in `orchestrator/action_handler.py` (~line 872) ONLY checks `vip_contacts` table. The "Add to contacts" action writes to the `contacts` table (different table). So even after adding, the lookup still fails.
2. The inline phone regex (~line 1426) only checks the CURRENT message (`_original_question`). When the Director says "Can you send her a message now?" there's no phone number in that message, so the fallback doesn't trigger.
3. No conversation history awareness for recently provided phone numbers.

## Fix — Three Changes

### Change 1: Expand `_resolve_names_to_whatsapp_ids()` to also check `contacts` table

**File:** `orchestrator/action_handler.py`, function `_resolve_names_to_whatsapp_ids()` (~line 872)

After the existing VIP contacts lookup, add a fallback that queries the `contacts` table:

```python
# If no VIP match, try the general contacts table
if not resolved:
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        for part in name_parts:
            part_clean = part.strip()
            if not part_clean:
                continue
            cur.execute("""
                SELECT name, phone, whatsapp_id
                FROM contacts
                WHERE (LOWER(name) LIKE %s OR LOWER(name) LIKE %s)
                  AND (phone IS NOT NULL OR whatsapp_id IS NOT NULL)
                LIMIT 1
            """, (f"%{part_clean.lower()}%", f"{part_clean.lower()}%"))
            row = cur.fetchone()
            if row:
                c_name, c_phone, c_wa = row
                wa_id = c_wa or (re.sub(r'[\s\-()]', '', c_phone).lstrip('+') + '@c.us' if c_phone else None)
                if wa_id:
                    resolved.append((c_name, wa_id))
                    break
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Contacts table WhatsApp lookup failed: {e}")
```

**Important:** Verify the `contacts` table schema first:
```sql
SELECT column_name FROM information_schema.columns WHERE table_name = 'contacts';
```
Check which columns hold phone/WhatsApp data. Adapt the query accordingly.

### Change 2: Check conversation history for phone numbers

**File:** `orchestrator/action_handler.py`, function `handle_whatsapp_action()` (~line 1442, the `if not resolved and _inline_phone:` block)

Before the final "I don't have their number" error (line ~1457), add a fallback that scans conversation history for phone numbers:

```python
# Fallback: scan conversation history for phone numbers
if not resolved and not _inline_phone and conversation_history:
    _hist_phone_match = _re.search(r'\+?[\d\s\-()]{10,}', conversation_history)
    if _hist_phone_match:
        _hist_phone = _re.sub(r'[\s\-()]', '', _hist_phone_match.group().strip())
        if not _hist_phone.endswith('@c.us'):
            _hist_phone = _hist_phone.lstrip('+') + '@c.us'
        # Use the recipient name from intent, clean of digits
        _clean_name = _re.sub(r'\+?[\d\s\-()]+', '', raw_recipient).strip()
        if not _clean_name:
            _clean_name = raw_recipient
        resolved = [(_clean_name, _hist_phone)]
```

Place this AFTER the `if not resolved and _inline_phone:` block and BEFORE the `if not resolved: return error` block.

### Change 3: Update intent system prompt to extract phone numbers

**File:** `orchestrator/action_handler.py`, the `_INTENT_SYSTEM` prompt (~line 232)

In the whatsapp_action section of the intent classifier prompt, add a new field:

```
For "whatsapp_action", also extract:
- "whatsapp_phone": the phone number if explicitly provided (e.g., "+41 78 871 57 64"). Set to null if no phone number in the message.
```

Then in `handle_whatsapp_action()`, check `intent.get("whatsapp_phone")` as an additional source before falling back to regex.

## Testing

1. **New contact with inline number:** "Send a WhatsApp to +41 78 871 57 64 saying hello" → should send and auto-add to VIP
2. **Known VIP:** "Send a WhatsApp to Edita about dinner" → should work as before (VIP lookup)
3. **Contact in contacts table:** "Send a WhatsApp to Marisol" (after she was added via "Add Marisol to contacts with WhatsApp +41...") → should find her in contacts table and send
4. **Conversation history fallback:** User provides number in one message, then says "send her a message" in the next → should find number in history
5. **No number anywhere:** "Send a WhatsApp to some random person" → should still return the error message

## Files to Modify

| File | Change |
|------|--------|
| `orchestrator/action_handler.py` | All 3 changes above |

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/action_handler.py', doraise=True)"
```

Test via dashboard Ask Baker:
1. "Send a WhatsApp to +41 78 871 57 64 saying test" — should send
2. Add a contact, then ask to message them — should work

## Rules

- Do NOT change the VIP contacts flow — it must continue to work as-is
- Do NOT auto-send to external contacts without the existing safeguards
- Verify `contacts` table schema before writing SQL (lesson #2 & #3)
- `conn.rollback()` in all except blocks (PostgreSQL rule)
