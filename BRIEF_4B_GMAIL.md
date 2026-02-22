# Brief 4B — Gmail Extraction (Run Pipeline)

**From:** Cowork (Architect)
**To:** Claude Code (Builder)
**Date:** 2026-02-19
**Status:** READY TO EXECUTE

---

## Context

Google Cloud OAuth2 setup is **complete**:
- ✅ Project `baker-gmail` created
- ✅ Gmail API enabled
- ✅ OAuth consent screen configured (External, Testing mode)
- ✅ Test user added: `vallen300@gmail.com`
- ✅ OAuth client "Baker Gmail Client" created (Desktop app)
- ✅ Credentials saved: `config/gmail_credentials.json`

The script `scripts/extract_gmail.py` is already built and ready to run.

---

## Task 1 — First Run (OAuth + Dry Run)

**IMPORTANT:** The first run will open a browser window for OAuth consent.
The user (Dimitry) must click through the consent screen to authorize.

```bash
cd /path/to/15_Baker_Master/01_build
python3 scripts/extract_gmail.py --mode historical --since 2025-08-19 --dry-run
```

**What will happen:**
1. Script reads `config/gmail_credentials.json`
2. No token exists yet → opens browser for OAuth consent
3. User signs in with `vallen300@gmail.com` and clicks "Allow"
4. Token saved to `config/gmail_token.json`
5. Dry-run fetches thread count + 3 sample previews
6. No files written in dry-run mode

**Expected output:** Thread count, 3 sample previews with subjects/dates/participants.

**If OAuth fails with "redirect_uri_mismatch":** The Desktop app flow uses `http://localhost` — this should work. If it doesn't, try adding `http://localhost` to the authorized redirect URIs in Google Cloud Console.

---

## Task 2 — Full Historical Extraction

After dry-run confirms things look good:

```bash
python3 scripts/extract_gmail.py --mode historical --since 2025-08-19
```

**Expected output:** `03_data/gmail/gmail_threads.json` containing all substantive email threads since Aug 2025 (noise-filtered).

---

## Task 3 — Ingest into Qdrant

```bash
python3 scripts/bulk_ingest.py \
  --source "../03_data/gmail/gmail_threads.json" \
  --collection baker-conversations
```

This uses the same `bulk_ingest.py` pipeline that ingested Fireflies data.

---

## Task 4 — Add Live Polling Mode (New Code)

After historical extraction works, add `--mode poll` to `extract_gmail.py`:

**Requirements:**
- Reads last-seen timestamp from `config/gmail_poll_state.json`
- Queries Gmail for threads newer than last-seen
- Processes new threads through the same noise filter + format pipeline
- Appends to or creates `03_data/gmail/gmail_incremental.json`
- Updates `gmail_poll_state.json` with new high-water mark
- CLI: `python3 scripts/extract_gmail.py --mode poll`

**Design notes:**
- Use `after:YYYY/MM/DD` in Gmail query based on last-seen date
- If no state file exists, default to 24h ago
- Output format identical to historical (same `{text, metadata}` structure)
- This will be called by the trigger system (Brief 4D) every 5 minutes

---

## Dependencies Already Installed

Check these are available (should be from Punch 3):
- `google-auth`, `google-auth-oauthlib`, `google-auth-httplib2`
- `google-api-python-client`
- `python-dotenv`

If missing:
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv
```

---

## Success Criteria

1. ✅ OAuth flow completes, `gmail_token.json` created
2. ✅ Dry-run shows thread count and sample previews
3. ✅ Full extraction produces `gmail_threads.json` with 50+ threads
4. ✅ Qdrant ingestion adds vectors to `baker-conversations`
5. ✅ Poll mode added with state tracking
