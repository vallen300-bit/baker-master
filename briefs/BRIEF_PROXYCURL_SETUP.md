# Brief: LinkedIn Enrichment API Setup (C1) — REVISED

**For:** AI Head (Code 300)
**From:** AI Head (Session 27) + Director feedback
**Priority:** High — unblocks 5 backlog items (C3, C7, C8, F7, H2)
**Status:** BLOCKED — needs API evaluation

---

## What Happened

Proxycurl is dead. LinkedIn filed a federal lawsuit (Jan 24, 2026) for unauthorized scraping. The site (nubela.co/proxycurl) now redirects to **NinjaPear**, which is a different product — a "Customer Listing API" built on LLMs, NOT LinkedIn profile enrichment.

The original brief assumed Proxycurl was active. It's not.

---

## What Baker Needs

For pre-meeting dossiers, conference intelligence, and contact enrichment:
- **Person lookup** by name or email → professional profile (title, company, history)
- **Company lookup** → org structure, employee count
- **Reasonable pricing** — ~EUR 40/month budget (~500 lookups/month)
- **API access** — REST API with JSON responses, not a SaaS platform

---

## Candidates to Evaluate

### 1. Netrows (netrows.com) — RECOMMENDED TO EVALUATE FIRST
- **Price:** EUR 0.005/request (~EUR 2.50 for 500 lookups)
- **Coverage:** 48+ LinkedIn endpoints (profiles, companies, jobs, posts)
- **Also covers:** X/Twitter, Crunchbase, Glassdoor, Reddit
- **Approach:** Real-time data retrieval
- **Compliance:** Transparent about data sourcing

### 2. People Data Labs (peopledatalabs.com)
- **Price:** ~$0.01/request, free tier available (100 records/month)
- **Coverage:** 1.5B person records, 200M+ company records
- **Approach:** Pre-compiled dataset (not real-time LinkedIn)
- **Good for:** Batch enrichment of existing contacts
- **Limitation:** Data may be months old

### 3. Scrapin.io
- **Price:** ~$0.01/request
- **Coverage:** LinkedIn profile enrichment
- **Approach:** Similar to old Proxycurl

### 4. Apollo.io
- **Price:** Freemium (50 credits/month free, $49/month for 500)
- **Coverage:** Large B2B database
- **Limitation:** Sales platform — may be overkill for Baker's use case

---

## Next Steps

1. **AI Head evaluates** Netrows API docs + pricing — does it cover Baker's use cases?
2. **If yes:** Sign up for Netrows, get API key, add to Render as `LINKEDIN_API_KEY`
3. **If no:** Evaluate PDL or Scrapin.io
4. **Update code brief** — client wrapper will be `tools/linkedin_client.py` (not `proxycurl_client.py`)
5. **Unblock C3/C7/C8/F7/H2** once API is live

---

## Impact on Backlog

All 5 blocked items remain blocked until an API is selected and integrated:
- **C3:** Conference attendee intelligence
- **C7:** Org chart awareness
- **C8:** Outreach draft generation
- **F7:** Pre-meeting "what don't I know" check (enhanced)
- **H2:** LinkedIn monitoring
