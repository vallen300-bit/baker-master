"""Anthropic Citations API adapter.

Baker-side stable surface:

    build_document_blocks(documents) -> list[dict]
    extract_citations(response) -> ExtractedResponse
    render_citations_markdown(extracted) -> str
    render_citations_slack_blocks(extracted) -> list[dict]

Hides Anthropic SDK schema churn behind this module. Callers:
- outputs/dashboard.py scan endpoints (/api/scan, /api/scan/specialist, /api/scan/client-pm)
- outputs/slack_notifier.py (Scan-output Slack posting)

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

If the SDK version in use doesn't support this schema, the adapter degrades
gracefully — build_document_blocks emits documents without issue and
extract_citations returns an ExtractedResponse with empty citations. Scan
continues to work without citations; a logger.warning fires on truly
malformed citation objects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

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
        title = str(doc.get("title", f"Document {i + 1}") or f"Document {i + 1}")
        body = str(doc.get("body", "") or "")
        if not body:
            logger.debug(
                "build_document_blocks: skipping empty doc idx=%d title=%r",
                i, title,
            )
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
                # Reject objects without any citation attrs — SDK schema required
                if not hasattr(rc, "document_index") and not hasattr(rc, "cited_text"):
                    logger.warning(
                        "extract_citations: skip citation missing required attrs",
                    )
                    continue
                c = Citation(
                    document_index=int(getattr(rc, "document_index", 0)),
                    document_title=str(getattr(rc, "document_title", "") or ""),
                    cited_text=str(getattr(rc, "cited_text", "") or ""),
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
            f"{n}. **{c.document_title}** — \"{quote}\" "
            f"(chars {c.start_char_index}–{c.end_char_index})"
        )
        n += 1
    return "\n".join(lines)


def render_citations_slack_blocks(
    extracted: ExtractedResponse,
) -> list[dict]:
    """Render citations as a Slack Block Kit divider + section + context block.

    Returns an empty list if no citations. Block structure:

        [
          {"type": "divider"},
          {"type": "section", "text": {"type": "mrkdwn", "text": "*Sources*"}},
          {"type": "context", "elements": [
              {"type": "mrkdwn", "text": "1. *<title>* — \"...\""},
              ...
          ]}
        ]

    Slack caps enforced: ≤10 context elements, ≤140 chars per quote.
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
