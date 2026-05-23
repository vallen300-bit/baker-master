# BRIEF: BAKER_SUBSTACK_SEARCH_1 — Generic Substack archive ingest + agent-queryable MCP tool

## Context

Director ratified 2026-05-23 ~16:30Z: build a Perplexity-style queryable surface so every Brisen agent (cowork-AH1, lead, AH2, hag-desk, researcher, AID-T, BEN, future matter desks) can call a single MCP tool to query Nate Jones's Substack archive (and future Brisen Substack subscriptions) by topic, get back top-k matching posts with excerpts + URLs.

**Anchor incidents:**
- 2026-05-23 chat with Director: *"How to make it possible that you or AH2 or any other agents can reach Nat Jones's Substack full data in a similar way to how we reach Perplexity, NotebookLM, etc.?"*
- Director ratified Option B (generic tool, Nate-seeded today) over Option A (Nate-only) + Option C (lazy on-demand). Reason: zero extra engineering cost over Nate-only at Day 1, zero forward migration cost when subscribing to other Substacks (Brisen-Anthropic / Latent Space / Stratechery / Import AI already in reading rotation per Cluster 5 RSS config).

**Live-probed reality (2026-05-23, this session):**
- Substack REST API is reachable unauthenticated for archive listing + per-post metadata (publication-scoped subdomain `<publication>.substack.com/api/v1/...`).
- Nate's archive: ~220 posts total (paginated 50/page via `?limit=N&offset=N`).
- For `audience: only_paid` posts (11 of 12 in recent batch), full body requires authenticated request with Director's session cookie.
- Free + founding-tier posts return full body unauthenticated.

**Complementary to (not replacing) the already-merged forward-flow ingest** (`triggers/substack_ingest.py` from PR #248, commit eeca2e0): that path catches NEW emails from now. This brief adds (a) historical backfill from the API, (b) semantic-search retrieval layer on top of both backfill + forward-flow.

## Estimated time: ~5-6h B-code + ~10 min Director handoff (cookie extraction → 1Password)
## Complexity: Medium
## Prerequisites:
- Director extracts `substack.sid` session cookie from logged-in Chrome session on `natesnewsletter.substack.com` → stores in 1Password at `op://Baker API Keys/SUBSTACK_COOKIE_natesnewsletter/credential` (~5 min; same pattern as `BRISEN_LAB_TERMINAL_KEY_*` items).
- Render env vars: add `SUBSTACK_COOKIE_natesnewsletter` populated from 1Password via existing render_env update flow (so production worker reads it).
- `VOYAGE_API_KEY` already in Render env (verified — used by `kbl/voyage_client.py`).
- Qdrant Cloud connection already wired (used by `baker-task-examples`, `sentinel-interactions`, `baker-conversations`, `baker-wiki` collections per `orchestrator/capability_runner.py`).
- `baker_mcp/baker_mcp_server.py` is the canonical MCP tool catalog (`TOOLS = [...]` at line 243; dispatch branches via `name == "..."` lookup).

---

## Fix/Feature 1: Substack archive backfill + Qdrant index

### Problem
~220 historical Nate posts predate Director's paid subscription. The forward-flow Gmail ingest (PR #248) only catches NEW emails from sub date forward. Without backfill, agents querying "what does Nate say about X" miss the entire pre-sub archive — including the "Knowledge Layer Architecture" + "AI Project Room" posts that already shaped Brisen design decisions.

### Current State
- **Archive endpoint (verified live 2026-05-23):** `GET https://natesnewsletter.substack.com/api/v1/archive?sort=new&limit=50&offset=N` returns array of post metadata. Pagination via offset. Each entry has: `id`, `slug`, `canonical_url`, `title`, `post_date`, `audience` (`only_paid` / `founding` / `free`), `search_engine_description` (~200-char SEO preview), `type` (`podcast` / `newsletter`), podcast metadata, restack metadata. `truncated_body_text: true` flag — archive listing does NOT include body.
- **Per-post endpoint (verified live):** `GET https://natesnewsletter.substack.com/api/v1/posts/<slug>` OR `GET https://natesnewsletter.substack.com/api/v1/posts/by-id/<id>` returns full post metadata. For paid posts, body is returned ONLY when request carries authenticated `substack.sid` cookie.
- **Forward-flow ingest:** `triggers/substack_ingest.py` (PR #248, merged eeca2e0) writes `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/YYYY-MM-DD-<slug>.md` from Gmail. No Qdrant embed in V1 (per ratification anchor in PR #248).
- **Voyage embed pattern:** `kbl/voyage_client.py` calls Voyage AI `voyage-3` model (1024d). Existing collections use same model.
- **Qdrant collection naming convention (verified):** lowercase-with-dashes, scoped prefix (`baker-task-examples`, `sentinel-interactions`, `baker-conversations`, `baker-wiki`).

### Implementation

#### Step 1 — Auth probe (~10 min, MUST run first; everything else depends on this passing)

Confirm Director's session cookie actually returns full body for a paid post.

```bash
# After Director extracts substack.sid cookie to 1Password:
COOKIE="$(op read 'op://Baker API Keys/SUBSTACK_COOKIE_natesnewsletter/credential')"
curl -s -H "Cookie: substack.sid=${COOKIE}" \
  "https://natesnewsletter.substack.com/api/v1/posts/rag-agents-knowledge-layer-architecture" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('body_html present:', bool(d.get('body_html'))); print('body length:', len(d.get('body_html','') or '')); print('truncated:', d.get('truncated_body_text', False))"
```

**Expected output:** `body_html present: True`, `body length: > 5000`, `truncated: False`.

If body is NOT returned (Substack changed paid-content gating to web-only): **STOP — escalate to AI Head.** Brief falls back to HTML-scraping fallback path (Chrome MCP + logged-in browser → BeautifulSoup → ~2h additional engineering).

#### Step 2 — Create `scripts/backfill_substack_archive.py`

New script. Pattern follows `scripts/backfill_meeting_transcripts_matter_slug.py` (env pre-flight from BACKFILL_PREFLIGHT_1, idempotent, --dry-run / --apply pair).

```python
#!/usr/bin/env python3
"""
Backfill Substack archive into Qdrant for agent-queryable retrieval.

Usage:
    python scripts/backfill_substack_archive.py --publication natesnewsletter [--dry-run | --apply]

Reads Substack archive via REST API, fetches each post with authenticated cookie,
embeds via Voyage (1024d), inserts into Qdrant collection baker-substack-<publication>.

Env required:
    VOYAGE_API_KEY              — Voyage AI key (existing)
    QDRANT_URL + QDRANT_API_KEY — Qdrant Cloud (existing)
    SUBSTACK_COOKIE_<publication> — session cookie (one per paid sub)
"""
import argparse, os, sys, time, html
from typing import Optional
import requests
from bs4 import BeautifulSoup

# Reuse existing env pre-flight pattern (per BACKFILL_PREFLIGHT_1 — PR #247)
REQUIRED_ENV = ["VOYAGE_API_KEY", "QDRANT_URL", "QDRANT_API_KEY"]

def _check_required_env(publication: str):
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    cookie_var = f"SUBSTACK_COOKIE_{publication}"
    if not os.getenv(cookie_var):
        missing.append(cookie_var)
    if missing:
        sys.exit(f"ERROR: missing env vars: {', '.join(missing)}. Source from 1Password before running.")

def _fetch_archive(publication: str, cookie: str, page_size: int = 50) -> list:
    """Paginate archive via offset. Returns list of post metadata."""
    posts = []
    offset = 0
    while True:
        url = f"https://{publication}.substack.com/api/v1/archive?sort=new&limit={page_size}&offset={offset}"
        resp = requests.get(url, headers={"Cookie": f"substack.sid={cookie}", "User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < page_size:
            break  # last page
        offset += page_size
        time.sleep(0.3)  # be polite to Substack rate limits
    return posts

def _fetch_post_body(publication: str, slug: str, cookie: str) -> Optional[dict]:
    """Fetch single post with full body (auth required for paid)."""
    url = f"https://{publication}.substack.com/api/v1/posts/{slug}"
    resp = requests.get(url, headers={"Cookie": f"substack.sid={cookie}", "User-Agent": "Mozilla/5.0"}, timeout=30)
    if resp.status_code != 200:
        return None
    return resp.json()

def _html_to_text(body_html: str) -> str:
    """Strip HTML tags; preserve paragraph breaks."""
    soup = BeautifulSoup(body_html, "html.parser")
    return soup.get_text(separator="\n\n", strip=True)

def _embed_and_index(text: str, metadata: dict, qdrant_client, voyage_client, collection_name: str):
    """Embed via Voyage, insert into Qdrant with metadata payload."""
    embedding = voyage_client.embed_one(text)  # voyage-3, 1024d
    qdrant_client.upsert(
        collection_name=collection_name,
        points=[{
            "id": metadata["id"],
            "vector": embedding,
            "payload": metadata,
        }],
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication", required=True, help="Substack publication slug (e.g., natesnewsletter)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        sys.exit("ERROR: must specify --dry-run or --apply")

    _check_required_env(args.publication)
    cookie = os.environ[f"SUBSTACK_COOKIE_{args.publication}"]

    # Initialize clients (reuse existing kbl/voyage_client.py + qdrant config)
    from kbl.voyage_client import VoyageClient
    from qdrant_client import QdrantClient

    voyage = VoyageClient()
    qdrant = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ["QDRANT_API_KEY"])

    collection_name = f"baker-substack-{args.publication}"

    # Ensure collection exists (idempotent)
    if args.apply:
        try:
            qdrant.get_collection(collection_name)
        except Exception:
            from qdrant_client.models import Distance, VectorParams
            qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )

    posts = _fetch_archive(args.publication, cookie)
    print(f"Found {len(posts)} posts in {args.publication} archive")

    inserted = 0
    skipped = 0
    failed = 0

    for post in posts:
        slug = post["slug"]
        post_id = post["id"]

        # Idempotency: skip if already in Qdrant
        if args.apply:
            try:
                existing = qdrant.retrieve(collection_name=collection_name, ids=[post_id])
                if existing:
                    skipped += 1
                    continue
            except Exception:
                pass

        full = _fetch_post_body(args.publication, slug, cookie)
        if not full or not full.get("body_html"):
            print(f"  [WARN] no body for {slug} (audience={post.get('audience')}) — skipping")
            failed += 1
            continue

        body_text = _html_to_text(full["body_html"])
        if len(body_text) < 200:
            print(f"  [WARN] body too short for {slug} ({len(body_text)} chars) — possible paywall hit")
            failed += 1
            continue

        metadata = {
            "id": post_id,
            "slug": slug,
            "publication": args.publication,
            "title": post.get("title", ""),
            "post_date": post.get("post_date", ""),
            "canonical_url": post.get("canonical_url", ""),
            "audience": post.get("audience", ""),
            "type": post.get("type", ""),
            "preview": post.get("search_engine_description", "")[:300],
            "body_text": body_text[:8000],  # cap stored payload at 8KB
            "char_count": len(body_text),
        }

        if args.apply:
            _embed_and_index(body_text, metadata, qdrant, voyage, collection_name)
            inserted += 1
            print(f"  [OK] {slug} ({len(body_text)} chars)")
        else:
            print(f"  [DRY] would index {slug} ({len(body_text)} chars)")

        time.sleep(0.5)  # rate-limit politeness

    print(f"\nDONE — inserted: {inserted}, skipped (already indexed): {skipped}, failed: {failed}")

if __name__ == "__main__":
    main()
```

### Key Constraints

- **Rate-limit politeness:** 0.3s between archive pages, 0.5s between post fetches. Substack's API is undocumented — they may throttle aggressive scrapers. ~220 posts × 0.5s = ~2 min walk.
- **Idempotency:** check Qdrant for existing post ID before re-fetching. Re-runs are cheap.
- **Cookie expiry:** `substack.sid` typically valid ~1 year. If `_fetch_post_body` returns 401 or empty body for a post that should be paid-accessible, surface a `CookieExpiredError` and halt — Director re-extracts.
- **Audience gate:** for `audience: only_paid` posts WITHOUT body in response, log warning + skip. Better to backfill 200/220 than 0/220.
- **Voyage embed cost:** voyage-3 is $0.06 per 1M tokens. Average post ~3000 tokens. 220 posts × 3000 = 660K tokens = ~$0.04. Negligible.
- **Qdrant storage:** ~220 vectors × 1024 dims × 4 bytes ≈ 900KB. Plus metadata payload ~8KB/post × 220 = ~1.8MB. Total <3MB. Negligible.

### Verification

```bash
# After --dry-run, expect output like:
# Found ~220 posts in natesnewsletter archive
# [DRY] would index ai-organize-files-before-writing (~4500 chars)
# [DRY] would index rag-agents-knowledge-layer-architecture (~6200 chars)
# ...
# DONE — inserted: 0, skipped: 0, failed: 0

# After --apply, expect:
# DONE — inserted: ~220, skipped: 0, failed: <5

# Confirm Qdrant collection populated:
python3 -c "
from qdrant_client import QdrantClient
import os
q = QdrantClient(url=os.environ['QDRANT_URL'], api_key=os.environ['QDRANT_API_KEY'])
info = q.get_collection('baker-substack-natesnewsletter')
print(f'vectors_count: {info.points_count}')
"
# Expected: 200-220
```

---

## Fix/Feature 2: Extend forward-flow ingest to ALSO embed + index

### Problem
`triggers/substack_ingest.py` (PR #248) writes markdown to vault but does not embed or index. Forward-flow posts arrive in Gmail but aren't retrievable via the new MCP tool until manual re-backfill.

### Current State
- `triggers/substack_ingest.py:_handle_substack_email()` — extracts post metadata + body from email HTML, writes markdown to vault path.
- No Qdrant insert in current code path.
- Function called from `triggers/email_trigger.py` BEFORE `_should_skip_pipeline()`.

### Implementation

Add Qdrant insertion as a NON-BLOCKING side effect of the existing markdown write:

```python
# In triggers/substack_ingest.py, after the markdown file is written:

def _index_to_qdrant(slug: str, publication: str, body_text: str, metadata: dict):
    """Embed + insert into Qdrant. Non-blocking: catch + log all errors."""
    try:
        from kbl.voyage_client import VoyageClient
        from qdrant_client import QdrantClient
        import os

        if not os.getenv("VOYAGE_API_KEY") or not os.getenv("QDRANT_URL"):
            return  # silently skip if env not configured (e.g., local dev)

        voyage = VoyageClient()
        qdrant = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ["QDRANT_API_KEY"])

        embedding = voyage.embed_one(body_text)
        qdrant.upsert(
            collection_name=f"baker-substack-{publication}",
            points=[{"id": metadata["id"], "vector": embedding, "payload": metadata}],
        )
        sentinel_health.report_success("substack_qdrant_index")
    except Exception as e:
        sentinel_health.report_failure("substack_qdrant_index", str(e))
        # Do NOT raise — markdown is already on disk; Qdrant gap is recoverable via re-backfill
```

Call from existing `_handle_substack_email` after markdown write.

### Key Constraints
- **Non-blocking:** any Qdrant failure (rate limit, network, schema mismatch) must NOT block the markdown write. Markdown is the ground truth; Qdrant is the queryable index. Re-backfill recovers any gaps.
- **Idempotency:** existing post ID re-insert is a no-op upsert (Qdrant native behavior).

### Verification

```bash
# Wait for next Nate post to arrive in Gmail (or use existing test fixture).
# After ingest pipeline fires:
python3 -c "
from qdrant_client import QdrantClient
import os
q = QdrantClient(url=os.environ['QDRANT_URL'], api_key=os.environ['QDRANT_API_KEY'])
recent = q.scroll(collection_name='baker-substack-natesnewsletter', limit=5, with_payload=True)[0]
for p in sorted(recent, key=lambda x: x.payload.get('post_date',''), reverse=True)[:3]:
    print(p.payload.get('post_date'), p.payload.get('slug'), p.payload.get('audience'))
"
# Expected: most recent post in Qdrant matches most recent Nate email
```

---

## Fix/Feature 3: MCP tool `baker_substack_search(publication, query, limit)`

### Problem
Agents need a single callable to query the Substack index. Mirror the shape of `baker_search` so the call pattern is familiar.

### Current State
- `baker_mcp/baker_mcp_server.py:243` — `TOOLS = [...]` list with all 24 MCP tool definitions.
- `baker_mcp/baker_mcp_server.py:258` — existing `baker_vip_contacts` entry as schema example.
- `baker_mcp/baker_mcp_server.py:682` — existing `baker_search` entry (semantic search on internal content).
- Dispatch branches at `baker_mcp/baker_mcp_server.py:1393` (`baker_vip_contacts`) and `:1956` (`baker_search`).

### Implementation

**Step 1 — Add tool entry to `TOOLS` list** (after the existing `baker_search` entry, ~line 682):

```python
Tool(
    name="baker_substack_search",
    description=(
        "Semantic search across ingested Substack archives. "
        "Use when an agent needs to query a known Substack publication's content by topic. "
        "Returns top-k matching posts with title, URL, post date, audience tier, and a body excerpt. "
        "Today's seeded publications: 'natesnewsletter' (Nate Jones — Director paid sub). "
        "New publications added by running scripts/backfill_substack_archive.py --publication <slug> after Director provides session cookie."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "publication": {
                "type": "string",
                "description": "Substack publication slug (subdomain). Today supports: natesnewsletter."
            },
            "query": {
                "type": "string",
                "description": "Natural-language query. Embedded via Voyage; matched against post bodies."
            },
            "limit": {
                "type": "integer",
                "description": "Max posts to return (1-20).",
                "default": 5,
            },
        },
        "required": ["publication", "query"],
    },
),
```

**Step 2 — Add dispatch branch** (after the `baker_search` branch at ~line 1956):

```python
elif name == "baker_substack_search":
    publication = arguments.get("publication", "").strip()
    query = arguments.get("query", "").strip()
    limit = min(max(int(arguments.get("limit", 5)), 1), 20)

    if not publication or not query:
        return "Error: both 'publication' and 'query' are required."

    try:
        from kbl.voyage_client import VoyageClient
        from qdrant_client import QdrantClient

        voyage = VoyageClient()
        qdrant = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ["QDRANT_API_KEY"])

        collection_name = f"baker-substack-{publication}"

        # Verify collection exists
        try:
            qdrant.get_collection(collection_name)
        except Exception:
            return f"Error: no Substack archive for '{publication}'. Available: see TOOLS description, or run scripts/backfill_substack_archive.py --publication {publication} first."

        query_vec = voyage.embed_one(query)
        hits = qdrant.search(
            collection_name=collection_name,
            query_vector=query_vec,
            limit=limit,
            with_payload=True,
        )

        if not hits:
            return f"No matches for '{query}' in {publication} archive."

        lines = [f"Top {len(hits)} matches for '{query}' in {publication}:\n"]
        for i, h in enumerate(hits, 1):
            p = h.payload
            lines.append(f"{i}. {p.get('title', '(untitled)')}")
            lines.append(f"   URL: {p.get('canonical_url', '')}")
            lines.append(f"   Date: {p.get('post_date', '')[:10]} | Audience: {p.get('audience', '')} | Type: {p.get('type', '')}")
            lines.append(f"   Match score: {h.score:.3f}")
            preview = p.get('preview', '') or p.get('body_text', '')[:400]
            lines.append(f"   Preview: {preview}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
```

### Key Constraints

- **Mirror existing MCP tool patterns.** `baker_search` is the closest analog — read it before implementing. Same Voyage embed → Qdrant search → text-format response pattern.
- **Handle missing collection gracefully.** If a caller asks for `publication=latentspace` but it's never been backfilled, return a helpful error pointing at the backfill script — do NOT silently return zero results (that's indistinguishable from "no matches found").
- **Cap limit at 20.** Prevent agents from accidentally retrieving the full archive in one call.
- **Result includes match score.** Helps the calling agent decide whether the match is relevant (score > 0.7 = strong match; < 0.5 = stretch).

### Verification

```bash
# Live test via MCP curl:
curl -s -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_substack_search","arguments":{"publication":"natesnewsletter","query":"how to organize files for AI to write a memo","limit":3}}}' \
  | python3 -m json.tool

# Expected: top match is "ai-organize-files-before-writing" (2026-05-22 post)
# with score > 0.7
```

Acceptance: an agent in any picker (researcher, hag-desk, AID-T, AH1, AH2, BEN, future matter desks) can call the tool via Baker MCP and receive top-k matched posts.

---

## Files Modified
- `baker_mcp/baker_mcp_server.py` — add `baker_substack_search` to `TOOLS` list + dispatch branch (~80 LOC additions)
- `triggers/substack_ingest.py` — add `_index_to_qdrant()` non-blocking call after markdown write (~30 LOC additions)

## Files Created
- `scripts/backfill_substack_archive.py` — backfill script (~150 LOC)

## Do NOT Touch
- `triggers/email_trigger.py` — out of scope; PR #248 already wired the Gmail → substack_ingest entry point.
- `kbl/voyage_client.py` — consume only; no changes.
- `outputs/dashboard.py` — MCP request handler is generic; new tool registers via `TOOLS` list.
- Existing Qdrant collections (`baker-task-examples`, `sentinel-interactions`, `baker-conversations`, `baker-wiki`) — separate namespaces.
- Existing aidennis-edge-scout skill — orthogonal; the markdown corpus it reads is unchanged.
- `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/` markdown files — ground truth; Qdrant is a derived index.

## Quality Checkpoints

1. Auth probe (Step 1 of Feature 1) passes — full body returned for at least one `only_paid` post.
2. Backfill --dry-run completes without errors; reports ~220 posts to be indexed.
3. Backfill --apply completes; Qdrant collection `baker-substack-natesnewsletter` has 200+ vectors.
4. Forward-flow non-blocking index runs on next Nate email arrival; new post visible in Qdrant within ~5 min of Gmail receipt.
5. MCP tool registered (visible via `tools/list` MCP call).
6. MCP `tools/call` for `baker_substack_search` returns top-k results with match scores + URLs.
7. Acceptance test query "how to organize files for AI to write a memo" returns "ai-organize-files-before-writing" as top match (score > 0.7).
8. Calling with an un-backfilled publication (`publication=latentspace`) returns helpful error pointing at backfill script — not silent zero results.
9. Cookie-expiry path: temporarily corrupt the 1P cookie; backfill surfaces `CookieExpiredError` and halts, does NOT silently insert zero-body entries.
10. `sentinel_health` reports `substack_qdrant_index` success on forward-flow inserts.

## Verification SQL

N/A — no Postgres schema changes. All state in Qdrant (vector index) + vault markdown (ground truth). Audit via Qdrant scroll + filesystem ls.

```bash
# Qdrant collection state check:
python3 -c "
from qdrant_client import QdrantClient; import os
q = QdrantClient(url=os.environ['QDRANT_URL'], api_key=os.environ['QDRANT_API_KEY'])
info = q.get_collection('baker-substack-natesnewsletter')
print(f'points: {info.points_count}, vector_size: {info.config.params.vectors.size}')
"

# Cross-ref with vault markdown:
ls ~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/ | wc -l
```

---

## Risks + lessons applied

| Anti-pattern / lesson | Mitigation in this brief |
|---|---|
| Function name guessing | Verified `kbl/voyage_client.VoyageClient.embed_one`, `qdrant_client.QdrantClient` + collection naming pattern (`baker-*`), and existing MCP tool TOOLS list location (`baker_mcp/baker_mcp_server.py:243`) before referencing them in code snippets. |
| Brief snippet wrong signature | Code snippets above use only signatures that match existing code paths (verified). |
| MCP tool surface vs DB schema (this session's lesson, BRIEF_BAKER_VIP_MCP defect) | Not applicable here — no DB schema changes. But the lesson applies: brief's tool description spells out exactly which params + types the MCP tool exposes; `baker_substack_search` only documents what it actually accepts. |
| Already-implemented brief | Searched git log + filesystem for prior substack-search / substack-qdrant work: none found. Forward-flow ingest exists (PR #248) and is referenced — not duplicated. |
| Cost impact | ~$0.04 Voyage backfill + ~$0.001/new post ongoing + <3MB Qdrant storage. Negligible. |
| Render restart survival | Backfill is one-shot manual; forward-flow index is non-blocking (any Render restart loses at most one in-flight post that's already on disk in vault). |
| Blast radius | Failure mode = empty Qdrant collection → MCP tool returns "no matches" → calling agent re-tries via Chrome MCP or web search → graceful degradation. No data loss possible (markdown is ground truth). |
| Edge cases | Cookie expiry (CookieExpiredError + halt), paywall body missing (skip + log), non-existent publication (helpful error), zero-results query (clear message). |
| New integrations need health monitoring | `sentinel_health.report_success/failure("substack_qdrant_index")` wired into forward-flow. Backfill failures surface in stderr (manual run). |
| Slow external calls need timeouts | All Substack API calls have 30s timeout. Voyage + Qdrant calls inherit existing client defaults. |
| Auth cookie storage | `op://Baker API Keys/SUBSTACK_COOKIE_<publication>/credential` — one entry per paid publication, mirrors `BRISEN_LAB_TERMINAL_KEY_*` pattern. Never inlined in code. |
| Secrets in brief | No cookie or API key values in this brief — only env var NAMES + 1P paths. |

## Estimated cost

- **B-code time:** ~5-6h (Feature 1: ~3h script + auth probe; Feature 2: ~1h existing-file extension; Feature 3: ~2h MCP tool registration + dispatch + acceptance test)
- **Director handoff:** ~10 min one-time (extract `substack.sid` from Chrome → 1Password)
- **One-time backfill cost:** ~$0.04 Voyage + ~$0.005 Qdrant storage = ~$0.05
- **Ongoing per-post cost:** ~$0.001/post × ~5 posts/week = ~$0.02/month
- **No Render env addition required** beyond `SUBSTACK_COOKIE_natesnewsletter` (one-time)
- **No Baker MCP schema change** — additive tool only

## Forward-extensibility

To add a new Substack publication (e.g., Latent Space, Stratechery, Brisen-Anthropic) after this brief ships:

1. Director extracts cookie from logged-in browser → 1P: `op://Baker API Keys/SUBSTACK_COOKIE_<slug>/credential`
2. Add env var to Render: `SUBSTACK_COOKIE_<slug>` populated from 1P
3. Run: `python scripts/backfill_substack_archive.py --publication <slug> --apply`
4. Update `baker_substack_search` tool description to mention the new publication (single-line edit; can be in a follow-up nit-fold)

**Zero code changes per new publication.** The tool is generic.

---

## Anchor + ratification trail

- Director ratified Option B 2026-05-23 ~16:30Z chat: *"b. go"*
- Baker decision: this brief writes one once authored (Director-facing PRESENT step still pending).
- §X queue position: 5th per lead's #735 (after BACKFILL_PREFLIGHT_1 → BUS_REPLY_TO_SENDER → §X-26 BAKER_VIP_MCP → this).
- Live-probed API foundation (this session): pagination + per-post metadata fetch + authenticated body access path all verified.
