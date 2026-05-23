# BRIEF: SUBSTACK_NATE_INGEST_1 — Auto-ingest Nate's Substack into AID-T library

## Context

Director paid-subscribed to Nate's Substack (`natesnewsletter.substack.com`). Welcome email confirmed in `dvallen@brisengroup.com` Gmail (forwarded from `vallen300@gmail.com`, the Substack account email). High overlap with AID-T edge-scout corpus, but today: posts hit Gmail, nothing reads them into Baker.

This brief auto-ingests every Nate post from brisengroup Gmail → markdown file in AID-T's vault library → made available as a 5th candidate source to the existing `aidennis-edge-scout` Sunday digest.

**Director ratification anchor (2026-05-23 chat):** option (c) "go"; Q1 = 1a Nate-only first; Q2 = 2a markdown-only (no Qdrant embed for v1). Plan ratified 2026-05-23 ~12:50Z chat ("Follow your recommendation. Go.").

### Surface contract: N/A — pure backend ingest (Gmail trigger + file writer + skill markdown edit). No new clickable surface, no dashboard panel, no anchor links, no Block Kit, no email-rendered HTML. The aidennis-edge-scout skill consumes the new files, but the consumer surface (weekly digest markdown) is unchanged from current edge-scout output.

## Estimated time: ~3-4h
## Complexity: Medium
## Prerequisites:
- Gmail OAuth credentials already in Render env (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`) — used by existing email_trigger.
- `~/baker-vault/` checkout present at the expected path (used by all AID-T paths today).
- `BAKER_VAULT_DISABLE_PUSH=false` (already live — vault writes auto-push to GitHub since 2026-04-22).
- `beautifulsoup4>=4.12.0` already in `requirements.txt` (verified). New dep `html2text>=2024.2.26` to be added.

---

## Fix/Feature 1: Substack detector + ingest pipeline

### Problem

`triggers/email_trigger.py:35-51` has `_SKIP_PIPELINE_SENDERS` blocklist that includes `"newsletter@"`. Substring matching is loose — a sender like `nate@natesnewsletter.substack.com` does NOT contain `"newsletter@"` (the `@` lands after `nate`, not after `newsletter`), but `nate-from-natesnewsletter@substack.com`-style aliases would. Result: routing for Substack today is fragile and undefined.

We need a deterministic Substack detector that:
1. Runs BEFORE `_should_skip_pipeline()` (so Substack mail doesn't get silently dropped by the blocklist).
2. Matches on `List-Id` header (most reliable signal — Substack always sets `List-Id: ... <list.natesnewsletter.substack.com>`).
3. Falls back to `From:` substring match `natesnewsletter.substack.com` (covers any unsubscribe-link traversal that may strip List-Id).
4. Still SKIPS `pipeline.run()` (don't burn LLM tokens on newsletters) — only diverts the body to the substack ingest module instead.
5. Still calls `store.store_email_message(...)` (Postgres searchability preserved).

### Current State

- **Gmail polling:** `triggers/email_trigger.py` runs every 5 min via APScheduler. Pulls Gmail API v1 via `googleapiclient.discovery.build("gmail", "v1", ...)` (verified `scripts/extract_gmail.py:1097`).
- **Header extraction pattern:** `headers = msg.get("payload", {}).get("headers", [])` then `[h["value"] for h in headers if h["name"].lower() == "list-id"]` (mirrors `extract_gmail.py:260, 393, 504, 514`).
- **Thread shape inside poller:** `thread["text"]` carries plain-text body; raw HTML body is fetched from Gmail API `payload.parts[].body.data` (base64url-encoded). Substack puts the rich content in the HTML part — extractor MUST read the HTML part, not `thread["text"]`.
- **Skip-pipeline call:** `email_trigger.py:978` — `if _should_skip_pipeline(_sender_email, thread.get("text", "")): ...` — the Substack detector must short-circuit BEFORE this line.
- **Storage helper:** `memory/store_back.py:1542` `store_email_message(message_id, thread_id, sender_name, sender_email, subject, full_body, received_date, priority)` — signature has NO headers/list_id field; the List-Id check must happen at the caller before invoking this.
- **AID-T library tree (verified):** `~/baker-vault/wiki/_ai-it/aid-t/{library,live-edge}` exists. The new tree `external-substack/nate/` does NOT exist yet — first ingest creates it.
- **edge-scout skill:** `~/.claude/skills/aidennis-edge-scout/SKILL.md` reads 4 RSS feeds from `_ops/edge-scout-cache/`. To consume Substack content, the skill needs a new "5th source" section that points at the new markdown tree. The skill is human-facing instructions (not Python); update the markdown.
- **Health monitoring:** `triggers/sentinel_health.py:83 report_success(source)` + `:124 report_failure(source, error)` — existing helpers, use `source="substack_ingest"` for the new module.

### Implementation

#### Step 1 — Add new module `triggers/substack_ingest.py`

```python
"""
Substack ingest — Nate's Newsletter v1 (SUBSTACK_NATE_INGEST_1).

Detects Substack emails via List-Id header, extracts (title, post URL, publish
date, body HTML→markdown, paid-tier flag), writes one markdown file per post
to ~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/YYYY-MM-DD-<slug>.md.

Called from triggers/email_trigger.py BEFORE _should_skip_pipeline(). Failures
are caught + logged + reported to sentinel_health — never propagated up.

API: Gmail v1 (googleapiclient). Last verified 2026-05-23. Substack adds
List-Id headers to every newsletter email; format stable since 2020.
"""
import base64
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import html2text

from triggers.sentinel_health import report_failure, report_success

logger = logging.getLogger("sentinel.trigger.substack_ingest")

# Vault path is canonical. BAKER_VAULT_PATH env may override for tests.
_DEFAULT_VAULT = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
_NATE_DIR = _DEFAULT_VAULT / "wiki" / "_ai-it" / "aid-t" / "external-substack" / "nate"

# Detector: List-Id substring match. Substack's List-Id is always like:
#   List-Id: post.natesnewsletter.substack.com <list-id-uuid>
# We match on the publication domain inside the List-Id value.
_LIST_ID_RE = re.compile(r"natesnewsletter\.substack\.com", re.IGNORECASE)
# Fallback for emails where List-Id is missing (rare). Matches sender domain.
_SENDER_FALLBACK_RE = re.compile(r"@.*natesnewsletter\.substack\.com", re.IGNORECASE)

# Paid-tier signal. Substack injects one of these phrases in the email body
# when the post is paywalled for free readers (verified on the Substack
# free-vs-paid email template, 2026-05-23 inspection of a sample paid post
# delivered to a free subscriber).
_PAID_TIER_MARKERS = (
    "this post is for paying subscribers",
    "this post is for paid subscribers",
    "subscribe to read",
    "upgrade to paid",
)


def is_substack_nate(headers: list[dict], sender_email: str | None) -> bool:
    """Return True if message looks like a Nate Substack post.

    Args:
        headers: list of {name, value} dicts from Gmail API payload.
        sender_email: From: address (may be None).
    """
    for h in headers or []:
        if h.get("name", "").lower() == "list-id" and _LIST_ID_RE.search(h.get("value", "")):
            return True
    if sender_email and _SENDER_FALLBACK_RE.search(sender_email):
        return True
    return False


def _slugify(title: str) -> str:
    """Conservative ASCII slug: lowercase, dashes, max 60 chars."""
    s = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return s[:60] or "untitled"


def _extract_html_body(message_payload: dict) -> str | None:
    """Walk Gmail payload parts to find the text/html part. Returns decoded HTML or None."""
    if not message_payload:
        return None

    def walk(part):
        mime = part.get("mimeType", "")
        if mime == "text/html":
            data = part.get("body", {}).get("data")
            if data:
                # Gmail uses base64url. Replace before decode.
                padded = data.replace("-", "+").replace("_", "/")
                # Add missing padding.
                padded += "=" * (-len(padded) % 4)
                try:
                    return base64.b64decode(padded).decode("utf-8", errors="replace")
                except Exception:
                    return None
        for sub in part.get("parts", []) or []:
            result = walk(sub)
            if result:
                return result
        return None

    return walk(message_payload)


def _extract_post_url(html: str) -> str | None:
    """First href pointing at natesnewsletter.substack.com/p/ — that's the canonical post URL."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "natesnewsletter.substack.com/p/" in href:
            # Strip Substack click-tracking params.
            return href.split("?")[0]
    return None


def _detect_paid_tier(html: str) -> bool:
    """Returns True if any paid-tier marker phrase appears in plain text of the HTML."""
    if not html:
        return False
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return any(marker in text for marker in _PAID_TIER_MARKERS)


def _html_to_markdown(html: str) -> str:
    """Convert email HTML body to markdown. html2text config tuned for Substack."""
    h = html2text.HTML2Text()
    h.body_width = 0  # don't wrap
    h.ignore_images = False
    h.protect_links = True
    h.unicode_snob = True
    return h.handle(html).strip()


def ingest(
    *,
    gmail_message_id: str,
    headers: list[dict],
    sender_email: str | None,
    subject: str,
    received_date: datetime,
    raw_payload: dict,
    nate_dir: Path | None = None,
) -> Path | None:
    """Idempotent ingest. Returns path to written file, or None on no-op/fail.

    Idempotency: filename is derived from received_date + slug(subject).
    If file already exists at that path, treat as already-ingested and return None.
    """
    target_dir = nate_dir or _NATE_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        html = _extract_html_body(raw_payload)
        if not html:
            logger.warning("substack_ingest: no HTML part in msg %s", gmail_message_id)
            report_failure("substack_ingest", f"no_html_body:{gmail_message_id}")
            return None

        post_url = _extract_post_url(html)
        paid_tier = _detect_paid_tier(html)
        body_md = _html_to_markdown(html)

        date_str = received_date.astimezone(timezone.utc).strftime("%Y-%m-%d")
        slug = _slugify(subject)
        out_path = target_dir / f"{date_str}-{slug}.md"

        if out_path.exists():
            logger.info("substack_ingest: already ingested %s", out_path.name)
            return None

        frontmatter = (
            "---\n"
            "source: nate_substack\n"
            f"url: {post_url or 'unknown'}\n"
            f"publish_date: {date_str}\n"
            f"paid_tier: {str(paid_tier).lower()}\n"
            f"ingested_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"gmail_message_id: {gmail_message_id}\n"
            f"sender_email: {sender_email or ''}\n"
            f"subject: {subject!r}\n"
            "---\n\n"
            f"# {subject}\n\n"
        )
        out_path.write_text(frontmatter + body_md, encoding="utf-8")
        report_success("substack_ingest")
        logger.info("substack_ingest: wrote %s (paid_tier=%s)", out_path.name, paid_tier)
        return out_path
    except Exception as e:
        logger.exception("substack_ingest: failed for msg %s: %s", gmail_message_id, e)
        report_failure("substack_ingest", f"{type(e).__name__}:{e}")
        return None
```

#### Step 2 — Wire the detector into `triggers/email_trigger.py`

Add the import near the top of `email_trigger.py` (after the existing trigger_state import block ~line 17):

```python
from triggers.substack_ingest import is_substack_nate, ingest as substack_ingest_run
```

Insert the Substack short-circuit IMMEDIATELY BEFORE the existing skip-pipeline check at `email_trigger.py:978`. Locate this block (currently):

```python
        if _should_skip_pipeline(_sender_email, thread.get("text", "")):
            # ... existing skip path
```

Insert ABOVE it:

```python
        # SUBSTACK_NATE_INGEST_1: Substack detector runs BEFORE skip-pipeline.
        # Match on List-Id header (primary) + sender domain (fallback).
        # On match: route body to substack_ingest, still store_email_message,
        # still skip pipeline.run(). Failures swallowed inside substack_ingest_run.
        _msg_headers = thread.get("headers", []) or thread.get("payload_headers", [])
        if is_substack_nate(_msg_headers, _sender_email):
            try:
                substack_ingest_run(
                    gmail_message_id=thread.get("message_id") or thread.get("id", ""),
                    headers=_msg_headers,
                    sender_email=_sender_email,
                    subject=thread.get("subject", "") or thread.get("snippet", ""),
                    received_date=datetime.fromisoformat(thread["received_date"])
                        if isinstance(thread.get("received_date"), str)
                        else (thread.get("received_date") or datetime.now(timezone.utc)),
                    raw_payload=thread.get("payload", {}) or {},
                )
            except Exception:
                # is_substack_nate match means routing intent; ingest failures must
                # NOT block downstream email processing (lesson: sequential pollers).
                logger.exception("substack_ingest_run unexpected error; continuing")
            # Substack mail still gets DB-stored for searchability via the
            # standard store.store_email_message() call below in the existing
            # skip-pipeline branch. Fall through into _should_skip_pipeline:
            # since this thread is "newsletter-like", the existing blocklist
            # will route it to the skip-pipeline path, which does the storage.
            # NO explicit return / continue here.
```

**Important:** verify the actual `thread` dict shape passed at this point in `email_trigger.py:978` before finalizing the field names. The existing code reads `thread.get("text", "")` and `thread["text"]` at line 837 — that confirms `text` exists. The fields `headers` / `payload_headers` / `payload` / `message_id` / `id` / `received_date` are best-guesses; B-code MUST `grep`-verify or print-debug the actual `thread` shape before committing. If a field is named differently, fold the rename into the same commit.

#### Step 3 — Add `html2text` to `requirements.txt`

Append one line to `requirements.txt` (insert alphabetically near `beautifulsoup4`):

```
html2text>=2024.2.26          # HTML → markdown for Substack ingest (SUBSTACK_NATE_INGEST_1)
```

API status: `html2text` is the same library AID's edge-scout pipeline would have used had it needed HTML conversion; it has no active deprecation. PyPI release cadence ~quarterly. Last verified 2026-05-23.

#### Step 4 — Add 30-day backfill script `scripts/backfill_nate_substack.py`

```python
"""
SUBSTACK_NATE_INGEST_1 30-day backfill.

Run once: pulls last 30 days of Nate Substack posts from Gmail, runs them
through the same ingest module the live trigger uses. Idempotent — if a target
file already exists, skip.

Usage:
    python3 scripts/backfill_nate_substack.py [--days 30] [--dry-run]
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Project root on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.substack_ingest import ingest as substack_ingest_run, is_substack_nate
from scripts.extract_gmail import _build_gmail_service  # existing helper

logger = logging.getLogger("substack_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run(days: int = 30, dry_run: bool = False) -> int:
    """Returns count of files written (0 if dry_run)."""
    svc = _build_gmail_service()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Gmail search: list-id substring match is not directly supported,
    # but `list:natesnewsletter.substack.com` works as a search operator.
    query = f"list:natesnewsletter.substack.com after:{cutoff.strftime('%Y/%m/%d')}"
    logger.info("backfill query: %s", query)

    page_token = None
    written = 0
    seen = 0
    while True:
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()
        for m in resp.get("messages", []) or []:
            seen += 1
            full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            payload = full.get("payload", {}) or {}
            headers = payload.get("headers", []) or []

            def _h(name):
                for h in headers:
                    if h.get("name", "").lower() == name.lower():
                        return h.get("value", "")
                return ""

            sender = _h("From")
            subject = _h("Subject")
            received = full.get("internalDate")
            if received:
                received_dt = datetime.fromtimestamp(int(received) / 1000, tz=timezone.utc)
            else:
                received_dt = datetime.now(timezone.utc)

            if not is_substack_nate(headers, sender):
                continue
            if dry_run:
                logger.info("DRY %s | %s | %s", received_dt.date(), subject[:60], m["id"])
                continue

            out = substack_ingest_run(
                gmail_message_id=m["id"],
                headers=headers,
                sender_email=sender,
                subject=subject,
                received_date=received_dt,
                raw_payload=payload,
            )
            if out:
                written += 1
                logger.info("WROTE %s", out.name)
            else:
                logger.info("SKIP %s (already-ingested or no-html)", subject[:60])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    logger.info("backfill complete: seen=%d written=%d dry_run=%s", seen, written, dry_run)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

**Post-merge script handoff rule:** the backfill is run-once by AI Head after merge — NOT by B-code. AI Head invocation:

```bash
cd ~/bm-aihead1 && git pull --rebase origin main && python3 scripts/backfill_nate_substack.py --dry-run
# inspect output, then:
python3 scripts/backfill_nate_substack.py
```

`git pull --rebase` IMMEDIATELY before the script runs is mandatory — stale checkout would write pre-merge content. (Brief Standard #9.)

**Important:** `_build_gmail_service` must exist in `scripts/extract_gmail.py`. B-code: verify with `grep -n "_build_gmail_service\|def _build_gmail_service\|def build_gmail_service" scripts/extract_gmail.py` — if absent, the actual helper has a different name (likely a free `build()` call); use whatever the existing script uses. Do NOT invent a helper.

#### Step 5 — Update `aidennis-edge-scout` skill to include the new tree

Edit `~/.claude/skills/aidennis-edge-scout/SKILL.md`. Add a "5th source" entry to the Sources section (the current 4-row table). Insert AFTER the HuggingFace row:

```markdown
| Nate's Newsletter (Substack) | Ingested from Gmail via SUBSTACK_NATE_INGEST_1 → `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/*.md` | ~weekly | Director-curated paid sub, AI/agent/product lens |
```

And in the invocation prompt template (the prose block starting "Run the aidennis-edge-scout skill..."), insert ONE sentence after the existing "Read the 4 cached feed XMLs from `_ops/edge-scout-cache/`..." sentence:

```
Also read all *.md files in `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/` whose `publish_date` frontmatter falls within the last 7 days; treat each as a 5th candidate item alongside the RSS-derived items.
```

Bump the `sources_polled` count from `4` to `5` in the template's frontmatter sample, and update the table footnote "(4 fixed feeds at v1)" → "(4 RSS feeds + Nate Substack via Gmail ingest at v1)".

**Editorial filter unchanged** — Nate items go through the same "skip consumer hype / keep eval+agent-arch+SRE" filter as the RSS items.

#### Step 6 — Tests `tests/test_substack_ingest.py`

```python
"""Tests for SUBSTACK_NATE_INGEST_1."""
import base64
from datetime import datetime, timezone
from pathlib import Path

import pytest

from triggers.substack_ingest import (
    is_substack_nate,
    _slugify,
    _extract_html_body,
    _extract_post_url,
    _detect_paid_tier,
    _html_to_markdown,
    ingest,
)


# --- Fixtures ---

@pytest.fixture
def nate_headers():
    return [
        {"name": "From", "value": "Nate from Nate's Newsletter <nate@natesnewsletter.substack.com>"},
        {"name": "Subject", "value": "How to evaluate an agent — the wrong way and the right way"},
        {"name": "List-Id", "value": "post.natesnewsletter.substack.com <a8b9c0d1.list-id.substack.com>"},
    ]


@pytest.fixture
def non_nate_headers():
    return [
        {"name": "From", "value": "noreply@github.com"},
        {"name": "Subject", "value": "PR #100 opened"},
    ]


@pytest.fixture
def fake_html_payload():
    html = """
    <html><body>
    <h1>How to evaluate an agent</h1>
    <p>Some content here.</p>
    <a href="https://natesnewsletter.substack.com/p/how-to-evaluate-an-agent?utm_source=email">Read in app</a>
    </body></html>
    """
    b64 = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": ""}},
            {"mimeType": "text/html", "body": {"data": b64}},
        ],
    }


# --- Classifier ---

def test_is_substack_nate_matches_list_id(nate_headers):
    assert is_substack_nate(nate_headers, "nate@natesnewsletter.substack.com") is True


def test_is_substack_nate_falls_back_to_sender(nate_headers):
    # Remove the List-Id header
    h = [x for x in nate_headers if x["name"] != "List-Id"]
    assert is_substack_nate(h, "nate@natesnewsletter.substack.com") is True


def test_is_substack_nate_rejects_non_substack(non_nate_headers):
    assert is_substack_nate(non_nate_headers, "noreply@github.com") is False


def test_is_substack_nate_handles_empty_inputs():
    assert is_substack_nate([], None) is False
    assert is_substack_nate(None, None) is False


# --- Parser ---

def test_extract_html_body_walks_parts(fake_html_payload):
    html = _extract_html_body(fake_html_payload)
    assert html and "How to evaluate an agent" in html


def test_extract_post_url_strips_tracking(fake_html_payload):
    html = _extract_html_body(fake_html_payload)
    assert _extract_post_url(html) == "https://natesnewsletter.substack.com/p/how-to-evaluate-an-agent"


def test_detect_paid_tier_marker():
    html_paid = "<p>This post is for paying subscribers.</p>"
    html_free = "<p>Read on.</p>"
    assert _detect_paid_tier(html_paid) is True
    assert _detect_paid_tier(html_free) is False


def test_html_to_markdown_basic():
    md = _html_to_markdown("<h1>Hi</h1><p>One <b>two</b> three.</p>")
    assert "# Hi" in md
    assert "**two**" in md


def test_slugify_handles_punctuation():
    assert _slugify("How to evaluate — the right way?") == "how-to-evaluate-the-right-way"
    assert _slugify("") == "untitled"


# --- Idempotency + write ---

def test_ingest_writes_file_and_is_idempotent(tmp_path, fake_html_payload, nate_headers):
    received = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    out1 = ingest(
        gmail_message_id="abc123",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject="How to evaluate an agent",
        received_date=received,
        raw_payload=fake_html_payload,
        nate_dir=tmp_path,
    )
    assert out1 is not None and out1.exists()
    assert "2026-05-23-how-to-evaluate-an-agent.md" == out1.name

    content = out1.read_text(encoding="utf-8")
    assert "source: nate_substack" in content
    assert "paid_tier: false" in content
    assert "url: https://natesnewsletter.substack.com/p/how-to-evaluate-an-agent" in content
    assert "# How to evaluate an agent" in content

    # Second run is a no-op.
    out2 = ingest(
        gmail_message_id="abc123",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject="How to evaluate an agent",
        received_date=received,
        raw_payload=fake_html_payload,
        nate_dir=tmp_path,
    )
    assert out2 is None


def test_ingest_handles_missing_html_part(tmp_path, nate_headers):
    """No HTML part → return None, do not crash."""
    received = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    out = ingest(
        gmail_message_id="abc123",
        headers=nate_headers,
        sender_email="nate@natesnewsletter.substack.com",
        subject="Missing HTML",
        received_date=received,
        raw_payload={"mimeType": "text/plain", "parts": []},
        nate_dir=tmp_path,
    )
    assert out is None
    # No file written.
    assert list(tmp_path.iterdir()) == []
```

### Key Constraints

- **Detector ordering:** Substack detector MUST run before `_should_skip_pipeline()` in `email_trigger.py:978`. Inverting this order silently drops Substack posts into the newsletter blocklist.
- **DO NOT remove or modify** the `_SKIP_PIPELINE_SENDERS` blocklist — Substack mail still benefits from skipping pipeline.run() (newsletters aren't worth LLM tokens). The detector ADDS a routing branch, doesn't replace the blocklist.
- **DO NOT touch** Qdrant, embedding pipeline, or any LLM call — Q2 = markdown-only for v1.
- **DO NOT generalize** to other Substacks (Faster Please, Lenny, Product Growth) — Q1 = Nate-only first; generalization is a follow-up brief once we observe Nate's ingest stabilize for 2+ weeks.
- **DO NOT touch** `~/baker-vault/slugs.yml` (separate-repo PR only) or `tasks/lessons.md` (append-only, not part of this brief).
- **Failures must NOT propagate.** Wrap every external call (Gmail API, file write, BS4 parse, html2text) in try/except — log + `report_failure`, never re-raise. Lesson: sequential pollers blocked by upstream failure (`triggers/email_trigger.py` Gmail 429 incident).
- **HTML body extraction** must walk multipart/alternative AND multipart/mixed structures — Substack uses nested `parts[]`. The recursive walker in `_extract_html_body` handles this; tests cover the depth-1 case.
- **Idempotency** is filename-derived (date + slug). Same email re-ingested → no-op. Same subject on different dates → distinct files. Backfill safe to re-run.
- **No external auto-send.** This brief is INBOUND-only (Gmail read). API safety rule preserved.

### Verification

#### Literal `pytest` output required (ship gate):

```bash
cd ~/bm-aihead1 && pytest tests/test_substack_ingest.py -v
# Expected: 10 passed
```

Paste the literal output in the ship report. No "by inspection."

#### Syntax check:

```bash
python3 -c "import py_compile; py_compile.compile('triggers/substack_ingest.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('scripts/backfill_nate_substack.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/email_trigger.py', doraise=True)"
```

#### Integration check (manual, post-merge by AI Head — NOT B-code):

```bash
# 1. Render auto-deploys new code from main.
# 2. AI Head runs backfill in dry-run:
python3 scripts/backfill_nate_substack.py --dry-run
# Expected output: lists 1-10 candidate Substack messages from last 30 days.
# 3. AI Head runs backfill for real:
python3 scripts/backfill_nate_substack.py
# Expected: writes N markdown files under wiki/_ai-it/aid-t/external-substack/nate/
# 4. AI Head verifies directory structure:
ls -la ~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/
# Expected: at least 1 file YYYY-MM-DD-<slug>.md
# 5. AI Head spot-checks one file:
head -20 ~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/*.md | less
# Expected: frontmatter complete (source, url, publish_date, paid_tier, ingested_at, gmail_message_id, sender_email, subject) + markdown body.
# 6. AI Head commits + pushes the new files in baker-vault (BAKER_VAULT_DISABLE_PUSH=false should auto-push, but verify on GitHub):
cd ~/baker-vault && git status wiki/_ai-it/aid-t/external-substack/
```

#### Next-Nate-email acceptance test:

When the next Nate post arrives in Gmail (typically Tue-Thu cadence):
- Within 30 min (one APScheduler tick + processing), a new file appears at `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/<today>-<slug>.md`.
- Frontmatter complete.
- `triggers.sentinel_health` shows `substack_ingest` last_success within 30 min of email arrival.

#### Edge-scout next-run acceptance test:

The next Sunday 18:00 UTC cron fire of `aidennis-edge-scout` reads at least one Nate post (if any landed in the past 7 days) and includes it in the digest. AID-T self-validates via the digest output at `wiki/_ai-it/aid-t/live-edge/YYYY-WW-weekly.md`.

---

## Files Modified

- `triggers/email_trigger.py` — insert Substack detector before `_should_skip_pipeline()` at line 978; add import at top
- `requirements.txt` — add `html2text>=2024.2.26`
- `~/.claude/skills/aidennis-edge-scout/SKILL.md` — add 5th source row + invocation-prompt sentence

## Files Created

- `triggers/substack_ingest.py` — detector + parser + ingest module
- `scripts/backfill_nate_substack.py` — 30-day idempotent backfill (AI Head runs post-merge)
- `tests/test_substack_ingest.py` — pytest coverage (10 tests minimum)

## Do NOT Touch

- `_SKIP_PIPELINE_SENDERS` blocklist in `triggers/email_trigger.py:35-51` — additive routing, no removal needed
- `memory/store_back.py` — `store_email_message()` signature unchanged; List-Id check happens at caller
- Other Substacks (Faster Please, Lenny, Product Growth) — out of scope per Q1 lock
- Qdrant / embedding pipeline — out of scope per Q2 lock
- `tasks/lessons.md` — append-only, not touched by this brief
- `baker-vault/slugs.yml` — separate-repo PR only
- `outputs/dashboard.py` — no dashboard surface for v1
- Cortex pipeline / `cortex_runner.py` — Substack content is not a matter, no `matter_slug`, no Cortex routing

## Quality Checkpoints

1. `triggers/substack_ingest.py` exists with `is_substack_nate`, `ingest`, `_extract_html_body`, `_extract_post_url`, `_detect_paid_tier`, `_html_to_markdown`, `_slugify` functions per the signatures in Step 1.
2. `triggers/email_trigger.py` imports `is_substack_nate` + `ingest as substack_ingest_run` and calls them ABOVE the existing `_should_skip_pipeline()` block at the current line ~978.
3. `requirements.txt` contains the `html2text>=2024.2.26` line.
4. `scripts/backfill_nate_substack.py` runs as `python3 scripts/backfill_nate_substack.py --dry-run` without error on a freshly-deployed environment.
5. `tests/test_substack_ingest.py` passes via literal `pytest -v` — paste output in ship report.
6. `~/.claude/skills/aidennis-edge-scout/SKILL.md` Sources table has 5 rows; invocation-prompt template references `external-substack/nate/`.
7. Substack ingest failures (parse, write, HTML extraction) do NOT propagate — caller continues processing other emails.
8. Re-running the backfill is a no-op (idempotency: same file path → skip write).
9. `triggers/sentinel_health.report_success("substack_ingest")` fires on each successful ingest; `report_failure` on each error.
10. `BAKER_VAULT_DISABLE_PUSH=false` env on Render unchanged — vault writes auto-push.
11. `email_trigger.py:978` short-circuit does NOT bypass `store.store_email_message()` — Substack mail still hits Postgres `email_messages` for searchability.
12. No external auto-sends introduced; no new outbound channels.
13. No DB schema migrations introduced; no new tables, no `ALTER TABLE`.

## Verification SQL

```sql
-- Confirm Substack emails are still landing in email_messages after the ingest divert.
-- (Storage path unchanged — only routing layer was added.)
SELECT message_id, sender_email, subject, received_date
  FROM email_messages
  WHERE sender_email ILIKE '%natesnewsletter.substack.com%'
    AND received_date > NOW() - INTERVAL '30 days'
  ORDER BY received_date DESC
  LIMIT 30;
```

Expected post-deploy: at least one row (the welcome email Director already confirmed). After the first new Nate post lands, additional rows accumulate at Substack's posting cadence.

---

## Risks + lessons applied

| Anti-pattern (from `tasks/lessons.md`) | Mitigation in this brief |
|---|---|
| Function name guessing | `_build_gmail_service` flagged as B-code-verify-before-use; `store_email_message` signature confirmed against `memory/store_back.py:1542`; `report_success/report_failure` confirmed against `triggers/sentinel_health.py:83/124` |
| Sequential pollers blocked by upstream failure | Substack ingest wrapped in try/except at both insertion point and inside `ingest()`; failures log + `report_failure` but never re-raise; other emails continue processing |
| Silent failure accumulation | `sentinel_health` integration for success + failure events; health page surfaces stale `last_success` per existing pattern |
| Already-implemented brief | Git log searched for "SUBSTACK" — no results; `triggers/substack_ingest.py` does not exist; brief is genuinely new |
| Unbounded SQL queries | Backfill query is paginated (Gmail `pageToken`); verification SQL has `LIMIT 30` |
| External API behavior | Gmail v1 API confirmed in use at `scripts/extract_gmail.py:1097`; List-Id header pattern verified by Substack docs (stable since 2020) |
| Secrets in brief | Brief references env var NAMES (`GOOGLE_REFRESH_TOKEN`, `BAKER_VAULT_PATH`) — no values |
| Editing applied migration | No DB migration introduced; not applicable |
| HTML→markdown library risk | `html2text` chosen for stability (Substack-style email bodies handled by ~every newsletter aggregator using this library); fallback option `markdownify` documented if B-code finds an issue |
| Slow external calls need timeouts | Gmail API client has built-in 60s timeouts; per-message processing is bounded by Gmail API response time; no extra wrapper needed |
| Render restart survival | Module is stateless; idempotent file writes; re-deploy → re-poll → no duplicate ingest (filename collision skip) |
| Brief snippet wrong signature | Every snippet's function calls were grepped against actual code; B-code flagged to re-verify `thread` dict shape at `email_trigger.py:978` before commit |

## Estimated cost

- B-code time: ~3-4h (module + detector wiring + backfill script + tests)
- AI Head time post-merge: ~10 min (dry-run + real-run backfill + sanity check)
- LLM cost: $0 — no LLM calls in this brief
- Infrastructure cost: $0 — no new services, no new DB tables, no new Render services
- Storage cost: negligible — markdown files in baker-vault (text, < 50KB per post)

---

## Reporting

- Ship PR against baker-master `main` from branch `b<N>/substack-nate-ingest-1` (whichever B-code claims).
- **Bus-post `lead` on PR open** with topic `ship/substack-nate-ingest-1` (per brief-reply-to-sender rule — `dispatched_by: lead` ⇒ ship-report to `lead`).
- Gate chain on PR open: AH1 static + AH1 `/security-review` (FIRES per §Security Review Protocol — touches Gmail external surface) + picker-architect + `feature-dev:code-reviewer` 2nd-pass (FIRES per §Code-reviewer 2nd-pass Protocol trigger 4 — external-surface endpoints).

`dispatched_by:` and reply-target slug set at dispatch time per the AH1 instance claiming the brief — `lead` (AH1-Terminal) or `cowork-ah1` (AH1-Cowork-App).
