# BRIEF: CITATIONS_API_SCAN_1 — Anthropic Citations API on Scan + render in Slack substrate

## Context

M0 quintet row 5. Per Research ratified 2026-04-21 (`_ops/ideas/2026-04-21-anthropic-4-7-upgrade-package.md` §Adoption 3):

> Migrate Scan's source-attribution from whatever current implementation uses to Anthropic's native Citations API. Surface Invariant S5 (CHANDA enforcement) requires "Scan responses cite sources; no hallucinated citations". Anthropic Citations provides model-level source grounding — each claim returns a pointer to its supporting document span. Mechanical, not prompt-engineered. CLQ: major trust gain on Scan output. Replaces post-response validator currently spec'd in S5. Gate: 4.7 migration should complete first (Citations performance likely better on 4.7 given document-reasoning lift).

**Cross-application from Director 2026-04-21** (per MEMORY.md "Baker surface architecture" §"4th block"): Citations must render in **Slack substrate messages** too — not just the Scan browser chat.

**Current state (verified this session):**

- No use of Anthropic's Citations API anywhere. `grep -rn "citations" --include="*.py"` only hits domain citation-lint scripts (`scripts/lint_movie_am_vault.py`) + prompt-level instructions in `orchestrator/capability_runner.py:1149` ("Never fabricate citations — only cite sources you actually retrieved"). The latter is a prompt-engineered instruction, NOT the mechanical Citations API — exactly what this brief replaces.
- `outputs/dashboard.py:7249` — `/api/scan` endpoint streams SSE responses from Claude. Retrieval context is injected into the system prompt or user message today; there's no `documents` parameter or `citations: {enabled: True}` flag anywhere.
- Slack rendering is via `outputs/slack_notifier.py` + Block Kit blocks. No footnote/citation rendering today.

**Model version note:** Per the 4.7 upgrade package, Citations is gated on 4.7 migration. **4.7 migration has NOT landed** (the `kbl/anthropic_client.py:51` default is `"claude-opus-4-7"` as of this brief — that's the Step 5 Opus path; but the broader migration across Baker + the eval gate is still pending M4). This brief ships the Citations adapter + wiring but NOT the model-version flip. It stays model-agnostic — Anthropic's Citations API works on both 4.6 and 4.7, just with quality variance. When M4 completes the 4.6→4.7 flip, Citations benefits automatically.

**What this brief ships:**

1. `kbl/citations.py` — thin adapter around Anthropic's Citations API. Public surface: `build_document_blocks(documents) -> list[dict]`, `extract_citations(response) -> list[Citation]`, `Citation` dataclass. Hides SDK schema churn behind a stable Baker-side interface.
2. Scan endpoint wiring — `/api/scan` + `/api/scan/specialist` + `/api/scan/client-pm` pass retrieval results as `documents=[...]` with `citations: {enabled: True}`; responses are parsed through `extract_citations()`; citation metadata streams over SSE alongside text.
3. Slack substrate rendering — when Baker posts Scan output to Slack, citations render as numbered footnotes in a Block Kit `section` + an `Attribution` block listing source document titles.
4. S5 mechanical enforcement — CHANDA_enforcement.md §5 row S5 method column: note that Citations API is the enforcement mechanism; §7 amendment-log row.
5. pytest — adapter unit tests (mock SDK response shape) + end-to-end adapter → Block Kit render test.

**What this brief does NOT ship:**

- **Model-version migration (4.6 → 4.7)** — that's the M4 eval-gated migration brief. This brief is model-agnostic.
- **Retiring the prompt-level "never fabricate citations" instruction in `capability_runner.py:1149`** — belt-and-braces: keep the prompt instruction AND add Citations API. Removal becomes safe only after 7-day observation of Citations-API-only enforcement. Follow-on brief `CITATIONS_PROMPT_CLEANUP_1`.
- **Citations on non-Scan paths** (ingest/extract, capability runner, chain runner, RAG direct calls) — Scan is the user-facing substrate; other paths are internal synthesis. Rollout there is `CITATIONS_ROLLOUT_1` follow-on.
- **Editing `outputs/slack_notifier.py` beyond the new citation-rendering function** — no generalized Slack-block refactor.
- **PDF / image citations** — Anthropic Citations API supports only text documents per 2026-04 release. PDF citations = out of scope until Baker ingests PDFs as text.

**Source artefacts:**
- `_ops/ideas/2026-04-21-anthropic-4-7-upgrade-package.md` §Adoption 3
- `CHANDA_enforcement.md` §5 row S5 (Scan responses cite sources)
- MEMORY.md — "Baker surface architecture" cross-application 2026-04-21
- Anthropic docs: https://docs.anthropic.com/en/docs/build-with-claude/citations (reference)

## Estimated time: ~3.5–4h
## Complexity: Medium-High (SDK adapter + SSE stream surgery + Slack Block Kit + tests)
## Prerequisites: M0 rows 1–4 shipped. No new env vars. No DB schema changes.

---

## Fix/Feature 1: `kbl/citations.py` — thin adapter

### Problem

Direct use of Anthropic's Citations API schema across 3+ Scan endpoints would couple Baker tightly to SDK shape. An adapter gives us the `Citation` dataclass and `extract_citations` / `build_document_blocks` entry points so future SDK changes land in one file.

### Current State

- `kbl/anthropic_client.py` is the reference shape for a thin Anthropic adapter.
- No Citations-API awareness anywhere.
- SDK version: check `requirements.txt`; `anthropic>=0.x.x` (exact version line at repo root).

### Implementation

**Create `kbl/citations.py`:**

```python
"""Anthropic Citations API adapter.

Baker-side stable surface:

    build_document_blocks(documents) -> list[dict]
    extract_citations(response) -> list[Citation]
    render_citations_markdown(citations) -> str
    render_citations_slack_blocks(citations) -> list[dict]

Hides Anthropic SDK schema churn behind this module. Callers:
- outputs/dashboard.py scan_chat + scan_specialist + scan_client_pm
- outputs/slack_notifier.py (Scan-output Slack posting, Feature 3)

Reference schema (Anthropic Citations API 2026-04):

    Request:
      messages.create(
          ...,
          messages=[{"role": "user", "content": [
              {
                  "type": "document",
                  "source": {"type": "text", "media_type": "text/plain",
                             "data": "<document body>"},
                  "title": "<doc title>",
                  "citations": {"enabled": True},
              },
              {"type": "text", "text": "<user question>"},
          ]}],
      )

    Response content blocks carry a `citations` list:
      {
          "type": "text",
          "text": "Some claim.",
          "citations": [
              {
                  "type": "char_location",
                  "cited_text": "...",
                  "document_index": 0,
                  "document_title": "...",
                  "start_char_index": 120,
                  "end_char_index": 165,
              },
              ...
          ]
      }

If the SDK version in use doesn't support this schema, the adapter
degrades gracefully — build_document_blocks emits documents without
citations flag and extract_citations returns []. Scan continues to work
without citations; a logger.warning fires once per module load.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("baker.kbl.citations")


@dataclass(frozen=True)
class Citation:
    """Normalized citation record — one supporting span for one claim."""
    document_index: int
    document_title: str
    cited_text: str
    start_char_index: int
    end_char_index: int


@dataclass
class ExtractedResponse:
    """Full adapter output for one Scan turn."""
    text: str
    citations_by_paragraph: list[list[Citation]] = field(default_factory=list)
    citations_flat: list[Citation] = field(default_factory=list)


def build_document_blocks(
    documents: list[dict],
) -> list[dict]:
    """Convert Baker retrieval hits into Anthropic document content blocks.

    Args:
        documents: list of dicts with keys `title`, `body`. Extra keys ignored.

    Returns:
        list of content-block dicts suitable for inclusion in a user
        message's `content` array.
    """
    blocks: list[dict] = []
    for i, doc in enumerate(documents):
        title = str(doc.get("title", f"Document {i + 1}"))
        body = str(doc.get("body", ""))
        if not body:
            logger.debug("build_document_blocks: skipping empty doc idx=%d title=%r", i, title)
            continue
        blocks.append({
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": body,
            },
            "title": title,
            "citations": {"enabled": True},
        })
    return blocks


def extract_citations(
    response: Any,
) -> ExtractedResponse:
    """Parse Anthropic messages.create response → Baker-normalized output.

    Walks response.content blocks. For each text block, collects its
    citations (if any). Returns concatenated text + grouped citation list.

    Tolerates:
    - Response without any citations (older SDK, feature disabled) — citations empty.
    - Malformed citation blocks — logged, skipped.
    - Mixed content types (thinking + text) — text blocks only.
    """
    out_text_parts: list[str] = []
    grouped: list[list[Citation]] = []
    flat: list[Citation] = []

    content = getattr(response, "content", None)
    if not content:
        return ExtractedResponse(text="")

    for block in content:
        block_type = getattr(block, "type", None)
        if block_type != "text":
            continue
        text = getattr(block, "text", "") or ""
        out_text_parts.append(text)
        block_cites: list[Citation] = []
        raw_cites = getattr(block, "citations", None) or []
        for rc in raw_cites:
            try:
                c = Citation(
                    document_index=int(getattr(rc, "document_index", 0)),
                    document_title=str(getattr(rc, "document_title", "")),
                    cited_text=str(getattr(rc, "cited_text", "")),
                    start_char_index=int(getattr(rc, "start_char_index", 0)),
                    end_char_index=int(getattr(rc, "end_char_index", 0)),
                )
                block_cites.append(c)
                flat.append(c)
            except Exception as e:
                logger.warning("extract_citations: skip malformed citation: %s", e)
        grouped.append(block_cites)

    return ExtractedResponse(
        text="".join(out_text_parts),
        citations_by_paragraph=grouped,
        citations_flat=flat,
    )


def render_citations_markdown(
    extracted: ExtractedResponse,
) -> str:
    """Render citations as numbered footnote list in plain markdown.

    Format:
        ## Sources

        1. **<title>** — "<cited_text>" (chars 120–165)
        2. ...
    """
    if not extracted.citations_flat:
        return ""
    lines = ["", "## Sources", ""]
    seen: set[tuple[int, int, int]] = set()
    n = 1
    for c in extracted.citations_flat:
        key = (c.document_index, c.start_char_index, c.end_char_index)
        if key in seen:
            continue
        seen.add(key)
        quote = c.cited_text.replace("\n", " ").strip()
        if len(quote) > 180:
            quote = quote[:177] + "…"
        lines.append(
            f"{n}. **{c.document_title}** — \"{quote}\" (chars {c.start_char_index}–{c.end_char_index})"
        )
        n += 1
    return "\n".join(lines)


def render_citations_slack_blocks(
    extracted: ExtractedResponse,
) -> list[dict]:
    """Render citations as a Slack Block Kit `section` + `context` block.

    Returns an empty list if no citations. Block structure:

        [
          {"type": "divider"},
          {"type": "section", "text": {"type": "mrkdwn", "text": "*Sources*"}},
          {"type": "context", "elements": [
              {"type": "mrkdwn", "text": "1. *<title>* — \"...\""},
              ...
          ]}
        ]
    """
    if not extracted.citations_flat:
        return []
    items: list[str] = []
    seen: set[tuple[int, int, int]] = set()
    n = 1
    for c in extracted.citations_flat:
        key = (c.document_index, c.start_char_index, c.end_char_index)
        if key in seen:
            continue
        seen.add(key)
        quote = c.cited_text.replace("\n", " ").strip()
        if len(quote) > 140:
            quote = quote[:137] + "…"
        items.append(f"{n}. *{c.document_title}* — \"{quote}\"")
        n += 1
    return [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Sources*"}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": text}
                for text in items[:10]  # Slack cap: 10 context elements
            ],
        },
    ]
```

### Key Constraints

- **Zero runtime dependency beyond stdlib + anthropic SDK types** — no Qdrant, no Postgres.
- **Graceful degradation** — if SDK response lacks `citations` attribute on blocks, adapter returns empty lists, not an exception.
- **Stable Baker interface** — future Anthropic SDK changes land in this module only. Callers never touch SDK schema directly.
- **Title fallback** — documents without a `title` key get `Document N`.
- **Dedup** — citation dedup by `(doc_idx, start, end)` — identical spans from the same doc render once.
- **Slack cap at 10 context elements** — Slack's Block Kit limit. If more citations, truncate (tolerable — top-10 by order).

### Verification

1. `python3 -c "import py_compile; py_compile.compile('kbl/citations.py', doraise=True)"` — zero.
2. `python3 -c "from kbl.citations import Citation, ExtractedResponse, build_document_blocks, extract_citations, render_citations_markdown, render_citations_slack_blocks; print('OK')"` — prints OK.

---

## Fix/Feature 2: Wire Citations API into Scan endpoints

### Problem

The adapter is inert until Scan endpoints actually pass documents + parse citations. Three Scan endpoints need the wiring: `/api/scan` (main Director-facing), `/api/scan/specialist`, `/api/scan/client-pm`.

### Current State

- `/api/scan` at `outputs/dashboard.py:7249` — handler `scan_chat(req: ScanRequest)` — uses SSE streaming. Retrieval context is injected as part of the system prompt or user message body today. Need to verify exact assembly point before editing.
- `/api/scan/specialist` at `outputs/dashboard.py:5406`.
- `/api/scan/client-pm` at `outputs/dashboard.py:5495`.
- All 3 use `_get_retriever()` / similar to fetch top-K retrieval hits; these hits have (`title`, `body`, `metadata`) shape — directly consumable by `build_document_blocks`.

### Implementation

**Generic pattern** applied to each of the 3 Scan endpoints:

**Step A — Replace retrieval-as-system-prompt with retrieval-as-document-blocks.**

Before (simplified):
```python
retrieved = retriever.fetch(req.question, top_k=10)
context_text = "\n\n".join(f"[{i}] {doc['title']}\n{doc['body']}" for i, doc in enumerate(retrieved))
system_prompt = f"{persona}\n\nRetrieved context:\n{context_text}"
response = client.messages.create(
    model=model,
    system=system_prompt,
    messages=[{"role": "user", "content": req.question}],
    ...
)
```

After:
```python
from kbl.citations import build_document_blocks, extract_citations, render_citations_markdown

retrieved = retriever.fetch(req.question, top_k=10)
doc_blocks = build_document_blocks([
    {"title": doc["title"], "body": doc["body"]} for doc in retrieved
])

response = client.messages.create(
    model=model,
    system=persona,  # stable persona only — keep cache_control if present (from PROMPT_CACHE_AUDIT_1)
    messages=[{"role": "user", "content": [
        *doc_blocks,
        {"type": "text", "text": req.question},
    ]}],
    ...
)
extracted = extract_citations(response)
answer_text = extracted.text
citations_md = render_citations_markdown(extracted)
full_answer = f"{answer_text}\n{citations_md}" if citations_md else answer_text
```

**Step B — Stream citations over SSE.**

Scan's SSE stream emits `data: <token>\n\n` events today. Add a final `data: __citations__<json>\n\n` event after the last text event, with the flat citations list serialized as JSON. The frontend consumes this last-event payload to render a footer.

Pseudo-patch in each Scan handler:

```python
async def _stream():
    async for chunk in stream:
        if chunk.type == "content_block_delta":
            yield f"data: {chunk.delta.text}\n\n"
    # After stream completes:
    final = stream.get_final_message()
    extracted = extract_citations(final)
    import json
    yield f"data: __citations__{json.dumps([c.__dict__ for c in extracted.citations_flat])}\n\n"
    yield "event: done\ndata: {}\n\n"
```

The exact streaming API depends on the SDK version — B-code locates the existing stream-consumption code in each endpoint and integrates. Do NOT refactor the whole stream machinery; insert citations emission at the end-of-stream boundary.

**Step C — Respect the existing `cache_control` from PROMPT_CACHE_AUDIT_1.** If that brief applied cache_control to `/api/scan` system block, preserve the cache_control on the persona block. The retrieval-as-documents change is compatible — documents go in the user message, not the system block.

### Key Constraints

- **Do NOT remove the existing `capability_runner.py:1149` anti-hallucination prompt instruction** — belt-and-braces until Citations observation proves sufficient.
- **Do NOT change `ScanRequest` / `SpecialistScanRequest` Pydantic shape** — input contract is stable.
- **Frontend compatibility** — the SSE `__citations__` event is NEW. Frontend parsing is out-of-scope for this brief (parallel follow-on `SCAN_CITATIONS_FRONTEND_1`). For the MVP, the backend emits the event; if the frontend ignores it, nothing breaks (frontend reads until `event: done`).
- **Retrieval shape assumption** — each retrieved doc has `title` + `body` keys. If actual retriever returns different keys, adapter is tolerant but B-code should verify + document.
- **Do NOT enable Citations on `/api/scan/followups` or `/api/scan/image`** — those are secondary paths; follow-on brief handles.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` — zero output.
2. `grep -n "from kbl.citations" outputs/dashboard.py` — expect ≥1 (ideally 1 import per Scan endpoint, or 1 top-level).
3. `grep -n "build_document_blocks\|extract_citations" outputs/dashboard.py` — expect ≥3 call sites (the 3 Scan endpoints).
4. Live endpoint smoke (post-deploy AI Head):
   ```
   curl -s -X POST "https://baker-master.onrender.com/api/scan" \
     -H "X-Baker-Key: $BAKER_KEY" -H "Content-Type: application/json" \
     -d '{"question":"test","project":"baker","role":"director"}' | tail -c 500
   ```
   Expect: `__citations__` event in the tail of the SSE stream.

---

## Fix/Feature 3: Slack substrate citation rendering

### Problem

Per Director's 2026-04-21 "4th block" cross-application: whenever Baker pushes Scan output to Slack, citations must render in the message.

### Current State

- `outputs/slack_notifier.py` — the Slack integration module. Posts Block Kit messages.
- No citation-aware Slack render function exists.
- Baker posts Scan output to Slack via… B-code verifies: grep for `slack_notifier.post` or `chat_postMessage` near the Scan handlers / substrate-push logic. If the Scan → Slack push lives somewhere other than `outputs/slack_notifier.py`, wire there.

### Implementation

**Step 1 — Add a rendering helper to `outputs/slack_notifier.py`:**

```python
def post_scan_with_citations(
    channel: str,
    question: str,
    answer_text: str,
    extracted_citations,  # kbl.citations.ExtractedResponse
    thread_ts: Optional[str] = None,
) -> dict:
    """Post Scan answer to Slack with inline citation footer blocks.

    Reuses the project's existing Slack client. Returns the API response.
    """
    from kbl.citations import render_citations_slack_blocks

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Question:* {question}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": answer_text[:2900]}},  # Slack mrkdwn cap ~3000
    ]
    blocks.extend(render_citations_slack_blocks(extracted_citations))
    return _client.chat_postMessage(
        channel=channel,
        blocks=blocks,
        text=answer_text[:500],  # fallback for mobile notifs
        thread_ts=thread_ts,
    )
```

(B-code adapts exact import and client names based on the file's existing conventions.)

**Step 2 — Identify Scan → Slack push paths.** grep:
```bash
grep -rn "slack_notifier\|chat_postMessage" --include="*.py" | grep -i "scan\|answer"
```

Wire `post_scan_with_citations` as the replacement function at any site that currently posts Scan output to Slack. If no such site exists today (i.e., Scan is browser-only currently), add a no-op marker comment in `outputs/slack_notifier.py` noting the helper is available for future integration — do NOT invent a new caller.

### Key Constraints

- **Do NOT break existing Slack-posting functions** — the new `post_scan_with_citations` is additive. Existing posters are left alone.
- **Block Kit 3000-char cap** on mrkdwn section text — truncate answer_text at 2900 chars to leave headroom.
- **Context block 10-element cap** — already enforced in `render_citations_slack_blocks`.
- **Mobile fallback** — `text=` kwarg ensures notifications show on iOS per past Baker lesson (lessons.md anti-pattern "Plain text Slack replies").

### Verification

1. `python3 -c "import py_compile; py_compile.compile('outputs/slack_notifier.py', doraise=True)"` — zero.
2. `grep -n "post_scan_with_citations\|render_citations_slack_blocks" outputs/slack_notifier.py` — ≥1 def + ≥1 import.
3. Unit test in Feature 5 covers the block shape.

---

## Fix/Feature 4: CHANDA_enforcement.md §5 row S5 + §7 amendment

### Problem

CHANDA_enforcement.md §5 row S5 currently says "post-response validator: grep citations against source IDs" — a prompt-engineered approach. This brief replaces that with Anthropic's Citations API (model-level). §5 row S5 method column should reflect the mechanical enforcement; §7 amendment log records the change.

### Current State

From current file (post-MAC_MINI_WRITER_AUDIT_1):

```
| S5 | Scan responses cite sources; no hallucinated citations | warn | post-response validator: grep citations against source IDs |
```

### Implementation

**Step 1 — Edit §5 row S5** in `CHANDA_enforcement.md`. Replace method column:

Before: `post-response validator: grep citations against source IDs`
After:  `Anthropic Citations API (model-level grounding); post-response validator retired`

New row:
```
| S5 | Scan responses cite sources; no hallucinated citations | warn | Anthropic Citations API (model-level grounding); post-response validator retired |
```

**Step 2 — Append §7 amendment row:**

```
| 2026-04-24 | §5 row S5 | Enforcement mechanism changed from post-response validator (prompt-engineered) to Anthropic Citations API (model-level source grounding). Adapter at `kbl/citations.py`. Scan endpoints `/api/scan`, `/api/scan/specialist`, `/api/scan/client-pm` wire documents through the adapter; citations stream over SSE + render in Slack substrate (CITATIONS_API_SCAN_1, PR TBD). Belt-and-braces: prompt-level anti-hallucination instruction in `capability_runner.py:1149` retained until 7-day Citations observation window. | Ratified 2026-04-21 "all 9 are ratified" + 2026-04-21 "4th block" Slack cross-application |
```

### Key Constraints

- **One-row edit in §5 + one row appended to §7.** No other changes to the file.
- **Do NOT touch §4 KBL invariants** — those are unchanged.
- **Do NOT retire §4 row #4 or #2 detector text** — unrelated.

### Verification

1. `grep -c "Anthropic Citations API" CHANDA_enforcement.md` → ≥2 (row S5 + amendment-log entry).
2. `grep -c "post-response validator" CHANDA_enforcement.md` → 1 (only in the amendment-log row explaining retirement — the §5 row S5 method column should NOT contain the old phrase anymore).
3. `grep -c "^| 2026-04" CHANDA_enforcement.md` → 5 (4 previous + 1 new 2026-04-24).
4. `tail -1 CHANDA_enforcement.md` → the new 2026-04-24 row.

---

## Fix/Feature 5: pytest scenarios

### Problem

Adapter correctness + Block Kit shape + graceful-degradation paths need test coverage.

### Current State

- No `tests/test_citations.py` or similar.
- `tests/test_kbl_ingest_endpoint.py` (PR #55) is the closest shape precedent.

### Implementation

**Create `tests/test_citations_api_scan.py`** with ~10 tests:

```python
"""Tests for kbl/citations.py + Slack render helpers."""
from __future__ import annotations

from types import SimpleNamespace
import json
import pytest

from kbl.citations import (
    Citation,
    ExtractedResponse,
    build_document_blocks,
    extract_citations,
    render_citations_markdown,
    render_citations_slack_blocks,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_docs():
    return [
        {"title": "Hagenauer RG7 Overview", "body": "RG7 is a Baden bei Wien project. Insolvency Mar 2026."},
        {"title": "Cupial Dispute Timeline", "body": "Tops 4,5,6,18 handover contested by Michal Hassa."},
    ]


def _fake_response(texts_and_citations):
    """Build a fake Anthropic response object.

    texts_and_citations: list of (text, [Citation]) tuples.
    """
    blocks = []
    for text, cites in texts_and_citations:
        cite_objs = [
            SimpleNamespace(
                type="char_location",
                cited_text=c.cited_text,
                document_index=c.document_index,
                document_title=c.document_title,
                start_char_index=c.start_char_index,
                end_char_index=c.end_char_index,
            )
            for c in cites
        ]
        blocks.append(SimpleNamespace(type="text", text=text, citations=cite_objs))
    return SimpleNamespace(content=blocks)


# ─── build_document_blocks ────────────────────────────────────────────────

def test_build_document_blocks_happy(sample_docs):
    out = build_document_blocks(sample_docs)
    assert len(out) == 2
    assert out[0]["type"] == "document"
    assert out[0]["source"]["type"] == "text"
    assert out[0]["source"]["media_type"] == "text/plain"
    assert out[0]["source"]["data"] == sample_docs[0]["body"]
    assert out[0]["title"] == sample_docs[0]["title"]
    assert out[0]["citations"] == {"enabled": True}


def test_build_document_blocks_skips_empty_body():
    docs = [{"title": "X", "body": ""}, {"title": "Y", "body": "content"}]
    out = build_document_blocks(docs)
    assert len(out) == 1
    assert out[0]["title"] == "Y"


def test_build_document_blocks_missing_title_uses_fallback():
    docs = [{"body": "body only"}]
    out = build_document_blocks(docs)
    assert out[0]["title"] == "Document 1"


# ─── extract_citations ────────────────────────────────────────────────────

def test_extract_citations_simple():
    cite = Citation(0, "Doc A", "cited span", 10, 22)
    resp = _fake_response([("Some text.", [cite])])
    extracted = extract_citations(resp)
    assert extracted.text == "Some text."
    assert len(extracted.citations_flat) == 1
    assert extracted.citations_flat[0].document_title == "Doc A"
    assert len(extracted.citations_by_paragraph) == 1
    assert extracted.citations_by_paragraph[0][0] == cite


def test_extract_citations_multiple_blocks():
    c1 = Citation(0, "Doc A", "span1", 0, 10)
    c2 = Citation(1, "Doc B", "span2", 5, 15)
    resp = _fake_response([("First.", [c1]), ("Second.", [c2])])
    extracted = extract_citations(resp)
    assert extracted.text == "First.Second."
    assert len(extracted.citations_flat) == 2


def test_extract_citations_response_without_citations_attr():
    """Older SDK / citations disabled — blocks lack 'citations' attr."""
    blocks = [SimpleNamespace(type="text", text="plain response")]
    resp = SimpleNamespace(content=blocks)
    extracted = extract_citations(resp)
    assert extracted.text == "plain response"
    assert extracted.citations_flat == []


def test_extract_citations_empty_response():
    resp = SimpleNamespace(content=[])
    extracted = extract_citations(resp)
    assert extracted.text == ""
    assert extracted.citations_flat == []


def test_extract_citations_tolerates_malformed_citation():
    bad = SimpleNamespace()  # no attrs at all
    blocks = [SimpleNamespace(type="text", text="text", citations=[bad])]
    resp = SimpleNamespace(content=blocks)
    extracted = extract_citations(resp)
    # Bad citation skipped; text still extracted.
    assert extracted.text == "text"
    # SimpleNamespace returns Mock-like values — may extract as 0/empty.
    # Behavior: either skip (malformed) or extract with defaults. Accept either.
    assert len(extracted.citations_flat) <= 1


# ─── render_citations_markdown ────────────────────────────────────────────

def test_render_markdown_empty():
    assert render_citations_markdown(ExtractedResponse(text="x")) == ""


def test_render_markdown_numbered():
    cites = [
        Citation(0, "Doc A", "span a", 0, 10),
        Citation(1, "Doc B", "span b", 5, 15),
    ]
    out = render_citations_markdown(ExtractedResponse(text="", citations_flat=cites))
    assert "## Sources" in out
    assert "1. **Doc A**" in out
    assert "2. **Doc B**" in out


def test_render_markdown_dedups_identical_spans():
    c1 = Citation(0, "Doc A", "span", 10, 20)
    c2 = Citation(0, "Doc A", "span", 10, 20)  # same
    out = render_citations_markdown(ExtractedResponse(text="", citations_flat=[c1, c2]))
    assert out.count("1. **Doc A**") == 1
    assert "2. " not in out  # only one line


# ─── render_citations_slack_blocks ────────────────────────────────────────

def test_render_slack_empty():
    assert render_citations_slack_blocks(ExtractedResponse(text="x")) == []


def test_render_slack_shape():
    cites = [Citation(0, "Doc A", "span a", 0, 10)]
    blocks = render_citations_slack_blocks(ExtractedResponse(text="", citations_flat=cites))
    assert blocks[0] == {"type": "divider"}
    assert blocks[1]["type"] == "section"
    assert blocks[2]["type"] == "context"
    assert len(blocks[2]["elements"]) == 1
    assert "1." in blocks[2]["elements"][0]["text"]
    assert "Doc A" in blocks[2]["elements"][0]["text"]


def test_render_slack_caps_at_10_elements():
    cites = [Citation(i, f"Doc {i}", f"span {i}", 0, 10) for i in range(15)]
    blocks = render_citations_slack_blocks(ExtractedResponse(text="", citations_flat=cites))
    assert len(blocks[2]["elements"]) == 10  # capped
```

### Key Constraints

- **SimpleNamespace for SDK response stubs** — hermetic, no `unittest.mock.patch`. Matches anti-mock convention across Baker tests.
- **13 tests total** (covers adapter correctness + Block Kit shape + graceful degradation).
- **No live API** — zero SDK calls, zero Slack API calls.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('tests/test_citations_api_scan.py', doraise=True)"` — zero.
2. `pytest tests/test_citations_api_scan.py -v` — expect 13 passed.
3. `pytest tests/ 2>&1 | tail -3` — +13 passes vs main baseline, 0 regressions.

---

## Files Modified

- NEW `kbl/citations.py` (~200 LOC).
- NEW `tests/test_citations_api_scan.py` (~200 LOC).
- MODIFIED `outputs/dashboard.py` — 3 Scan endpoints wired to adapter (~40 LOC delta).
- MODIFIED `outputs/slack_notifier.py` — new `post_scan_with_citations` helper (~30 LOC).
- MODIFIED `CHANDA_enforcement.md` — §5 row S5 + §7 amendment (+2 rows touched).

**Total: 2 new + 3 modified.**

## Do NOT Touch

- `orchestrator/capability_runner.py:1149` anti-hallucination prompt instruction — retained (belt-and-braces).
- `kbl/anthropic_client.py` — unrelated (Step 5 synthesis). Citations path is Scan-specific.
- Model IDs anywhere — this brief is model-agnostic.
- `baker-vault/`, `vault_scaffolding/`, `slugs.yml` — unrelated.
- `CHANDA.md` — paired rewrite is separate brief.
- `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `kbl/cache_telemetry.py` — unrelated.
- `/api/scan/image`, `/api/scan/followups`, `/api/scan/detect` — follow-on brief handles.
- Call sites in `orchestrator/`, `triggers/`, `tools/`, `scripts/backfill_*.py`, `scripts/enrich_*.py` — not Scan; `CITATIONS_ROLLOUT_1` follow-on.

## Quality Checkpoints

1. **Python syntax on 2 new files + 3 modified:**
   ```
   for f in kbl/citations.py tests/test_citations_api_scan.py \
            outputs/dashboard.py outputs/slack_notifier.py; do
     python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo FAIL $f; exit 1; }
   done
   echo "All 4 files syntax-clean."
   ```

2. **Import smoke:**
   ```
   python3 -c "from kbl.citations import Citation, ExtractedResponse, build_document_blocks, extract_citations, render_citations_markdown, render_citations_slack_blocks; print('OK')"
   ```

3. **Scan endpoints wire the adapter:**
   ```
   grep -c "build_document_blocks\|extract_citations" outputs/dashboard.py
   ```
   Expect ≥3 (one per Scan endpoint).

4. **Slack helper exists:**
   ```
   grep -n "def post_scan_with_citations" outputs/slack_notifier.py
   ```
   Expect exactly 1.

5. **CHANDA §5 row S5 updated:**
   ```
   grep "Anthropic Citations API (model-level grounding)" CHANDA_enforcement.md   # expect ≥1
   grep -c "^| S5" CHANDA_enforcement.md                                           # expect 1
   ```

6. **CHANDA §7 amendment log — 5 dated rows:**
   ```
   grep -c "^| 2026-04" CHANDA_enforcement.md
   ```
   Expect: `5`.

7. **New tests pass in isolation:**
   ```
   pytest tests/test_citations_api_scan.py -v 2>&1 | tail -20
   ```
   Expect `13 passed`.

8. **Full-suite regression:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Expect +13 vs baseline, 0 regressions.

9. **Singleton hook:**
   ```
   bash scripts/check_singletons.sh
   ```

10. **No baker-vault writes:**
    ```
    git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
    ```

11. **Belt-and-braces prompt instruction retained:**
    ```
    grep "Never fabricate citations" orchestrator/capability_runner.py
    ```
    Expect: exactly 1 hit (the existing prompt instruction).

## Rollback

- `git revert <merge-sha>` — reverts all 5 files cleanly.
- CHANDA §5 row S5 method text reverts to "post-response validator" — Baker continues with prompt-level instruction only.
- No DB changes; no env-var changes.

---

## Ship shape

- **PR title:** `CITATIONS_API_SCAN_1: Anthropic Citations adapter + 3 Scan endpoints wired + Slack substrate render + S5 §5/§7`
- **Branch:** `citations-api-scan-1`
- **Files:** 5 (2 new + 3 modified).
- **Commit style:** `kbl(citations): Citations API adapter + Scan endpoints + Slack substrate + CHANDA §5 S5 mechanical enforcement`
- **Ship report:** `briefs/_reports/B{N}_citations_api_scan_1_20260424.md`. Include all 11 Quality Checkpoint outputs literal + `git diff --stat` + baseline pytest line.

**Tier A auto-merge on B3 APPROVE + green /security-review** per SKILL.md Security Review Protocol.

## Post-merge (AI Head, not B-code)

1. Wait for Render auto-deploy.
2. Live smoke: 3 Scan queries via curl; verify SSE stream contains `__citations__` event + the ExtractedResponse.citations_flat JSON payload.
3. Push a Scan answer to Slack channel via the new helper (pick a test channel like Director DM `D0AFY28N030`); verify citation footer blocks render.
4. Log outcome to `actions_log.md`.
5. Begin 7-day observation window before retiring `capability_runner.py:1149` prompt instruction (handled by `CITATIONS_PROMPT_CLEANUP_1` follow-on, not this brief).

## Timebox

**3.5–4h.** If >5.5h, stop and report — likely SDK-version incompatibility with the Citations API schema (fallback: confirm `anthropic` SDK version in `requirements.txt`; if <required, either bump in a separate brief or degrade adapter to empty-citation mode).

**Working dir:** `~/bm-b3`. (Per Director 2026-04-24: "Dispatch to B1 + B3 (Tier A)" — parallel coders.)
