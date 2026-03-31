"""
Baker 3.0 — Item 0a: Universal Real-Time Extraction Engine

Every signal entering Baker gets structured extraction on arrival.
- T1/T2 signals: Agentic RAG extraction (context-aware, tool calls)
- T3 signals: Single Haiku call (literal extraction, cheap)

Produces universal schema stored in signal_extractions table.
Downstream consumers (obligation generator, deadlines, convergence, etc.)
read from signal_extractions instead of re-scanning raw text.
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone

from config.settings import config

logger = logging.getLogger("baker.extraction_engine")

# Rate limiter: max 3 concurrent extractions (Cowork pushback #7)
_EXTRACTION_SEMAPHORE = threading.Semaphore(3)

# Extraction types
EXTRACTION_TYPES = [
    "commitment", "deadline", "decision", "question",
    "action_item", "financial", "intelligence", "follow_up",
]

# ─────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────

def _ensure_signal_extractions_table():
    """Create signal_extractions table if not exists."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signal_extractions (
                    id SERIAL PRIMARY KEY,
                    source_channel VARCHAR(20) NOT NULL,
                    source_id TEXT,
                    media_type VARCHAR(20),
                    extraction_tier VARCHAR(5),
                    extracted_items JSONB NOT NULL DEFAULT '[]',
                    linked_meeting TEXT,
                    processed_at TIMESTAMPTZ DEFAULT NOW(),
                    processing_ms INTEGER,
                    token_cost NUMERIC(10,6)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_se_channel
                ON signal_extractions(source_channel)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_se_processed
                ON signal_extractions(processed_at)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_se_items
                ON signal_extractions USING GIN(extracted_items)
            """)
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not ensure signal_extractions table: {e}")


_table_ensured = False


def _ensure_table_once():
    global _table_ensured
    if not _table_ensured:
        _ensure_signal_extractions_table()
        _table_ensured = True


def _store_extractions(source_channel, source_id, extracted_items,
                       extraction_tier, media_type=None, linked_meeting=None,
                       processing_ms=0, token_cost=0.0):
    """Write extraction results to signal_extractions table."""
    _ensure_table_once()
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO signal_extractions
                    (source_channel, source_id, media_type, extraction_tier,
                     extracted_items, linked_meeting, processing_ms, token_cost)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                source_channel, source_id, media_type, extraction_tier,
                json.dumps(extracted_items), linked_meeting,
                processing_ms, token_cost,
            ))
            conn.commit()
            cur.close()
            logger.info(
                f"Stored {len(extracted_items)} extraction(s) for "
                f"{source_channel}:{source_id} (tier={extraction_tier}, "
                f"{processing_ms}ms)"
            )
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"_store_extractions failed: {e}")


# ─────────────────────────────────────────────────
# Haiku extraction (T3 — cheap, literal)
# ─────────────────────────────────────────────────

_HAIKU_EXTRACTION_PROMPT = """Extract structured items from this content. For each item provide:
- type: one of commitment, deadline, decision, question, action_item, financial, intelligence, follow_up
- text: what the item says (concise, one sentence)
- who: person responsible or mentioned (name only, or null)
- directed_to: person it's directed at (name only, or null)
- when: date/deadline if any (YYYY-MM-DD format, or null)
- confidence: high, medium, or low

Return a JSON array. Empty array [] if nothing to extract.
Do NOT extract greetings, signatures, or routine pleasantries.

Content ({source_channel}):
{content}"""


def _extract_flash(content, source_channel, source_id):
    """T3: Single Gemini Flash call, literal extraction. (was _extract_haiku)"""
    start = time.time()
    try:
        from orchestrator.gemini_client import call_flash

        # Truncate very long content for T3
        text = content[:6000] if len(content) > 6000 else content

        prompt = _HAIKU_EXTRACTION_PROMPT.format(
            source_channel=source_channel,
            content=text,
        )

        resp = call_flash(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )

        result_text = resp.text.strip()
        # Parse JSON from response
        items = _parse_json_array(result_text)

        elapsed_ms = int((time.time() - start) * 1000)

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="t3_extraction")
        except Exception:
            pass

        logger.info(
            f"Flash extraction: {len(items)} items from {source_channel}:{source_id} "
            f"({elapsed_ms}ms)"
        )
        return items, elapsed_ms, 0.0005

    except Exception as e:
        logger.error(f"Flash extraction failed for {source_channel}:{source_id}: {e}")
        elapsed_ms = int((time.time() - start) * 1000)
        return [], elapsed_ms, 0.0


# ─────────────────────────────────────────────────
# T2: Gemini Pro single-pass extraction (GEMINI-MIGRATION-1)
# ─────────────────────────────────────────────────

def _extract_pro(content, source_channel, source_id):
    """T2: Gemini Pro single-pass extraction — structured output, no tool calls."""
    start = time.time()
    try:
        from orchestrator.gemini_client import call_pro

        text = content[:12000] if len(content) > 12000 else content

        prompt = _HAIKU_EXTRACTION_PROMPT.format(
            source_channel=source_channel,
            content=text,
        )

        resp = call_pro(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )

        result_text = resp.text.strip()
        items = _parse_json_array(result_text)

        elapsed_ms = int((time.time() - start) * 1000)

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="t2_extraction")
        except Exception:
            pass

        logger.info(
            f"Pro extraction: {len(items)} items from {source_channel}:{source_id} "
            f"({elapsed_ms}ms)"
        )
        return items, elapsed_ms, 0.002

    except Exception as e:
        logger.error(f"Pro extraction failed for {source_channel}:{source_id}: {e}")
        elapsed_ms = int((time.time() - start) * 1000)
        return [], elapsed_ms, 0.0


# ─────────────────────────────────────────────────
# Agentic RAG extraction (T1 only — deep, context-aware)
# ─────────────────────────────────────────────────

_AGENTIC_EXTRACTION_PROMPT = """You are Baker's extraction engine. Analyze this {source_channel} content and extract ALL structured items.

For each item, classify as: commitment, deadline, decision, question, action_item, financial, intelligence, or follow_up.

Use the context from Baker's memory (provided by tool results) to:
- Link items to the correct matter (hagenauer, cupial, annaberg, etc.)
- Identify contacts by full name and role
- Match deadlines against existing tracked deadlines
- Detect if an action item is new or already known

Content to analyze:
{content}

Extract items as a JSON array. Each item:
{{
  "type": "commitment|deadline|decision|question|action_item|financial|intelligence|follow_up",
  "text": "concise description",
  "who": "person name or null",
  "directed_to": "person name or null",
  "when": "YYYY-MM-DD or null",
  "confidence": "high|medium|low",
  "completion_signals": ["how to detect this is done"],
  "related_matter": "matter slug or null",
  "related_contacts": ["name1", "name2"],
  "sentiment": "neutral|positive|negative|urgent"
}}

Be specific: names, dates, amounts. Set confidence to "low" if inferring.
Empty array [] if nothing to extract."""


def _extract_agentic(content, source_channel, source_id):
    """T1/T2: Agentic extraction with tool calls for context enrichment."""
    start = time.time()
    try:
        from orchestrator.agent import ToolExecutor
        from orchestrator.capability_registry import CapabilityRegistry
        import anthropic

        client = anthropic.Anthropic()
        executor = ToolExecutor()

        # Focused tool set for extraction (not all 18)
        extraction_tools = [
            {
                "name": "search_calendar",
                "description": "Search calendar events near this signal's time to find related meetings.",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
            {
                "name": "get_matter_context",
                "description": "Get full context for a business matter (people, history, status).",
                "input_schema": {"type": "object", "properties": {"matter": {"type": "string"}}, "required": ["matter"]},
            },
            {
                "name": "get_contact",
                "description": "Get contact details, role, relationship, and recent interactions.",
                "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            },
            {
                "name": "get_deadlines",
                "description": "Get active deadlines, optionally filtered by matter or keyword.",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
        ]

        # Truncate content for prompt
        text = content[:12000] if len(content) > 12000 else content

        prompt = _AGENTIC_EXTRACTION_PROMPT.format(
            source_channel=source_channel,
            content=text,
        )

        messages = [{"role": "user", "content": prompt}]
        total_cost = 0.0

        # Agent loop: max 3 iterations (focused, not open-ended)
        for iteration in range(4):
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4000,
                tools=extraction_tools,
                messages=messages,
            )
            total_cost += 0.01  # ~$0.01 per Opus call

            # Check if Claude wants to use tools
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                # Claude is done — extract the text response
                text_blocks = [b for b in response.content if b.type == "text"]
                result_text = text_blocks[0].text.strip() if text_blocks else "[]"
                items = _parse_json_array(result_text)
                elapsed_ms = int((time.time() - start) * 1000)
                logger.info(
                    f"Agentic extraction: {len(items)} items from {source_channel}:{source_id} "
                    f"({iteration + 1} iterations, {elapsed_ms}ms)"
                )
                return items, elapsed_ms, total_cost

            # Execute tool calls
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_use in tool_uses:
                try:
                    result = executor.execute(tool_use.name, tool_use.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": str(result)[:3000],
                    })
                except Exception as te:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": f"Error: {te}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

        # If we hit max iterations, parse whatever we have
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning(f"Agentic extraction hit max iterations for {source_channel}:{source_id}")
        return [], elapsed_ms, total_cost

    except Exception as e:
        logger.error(f"Agentic extraction failed for {source_channel}:{source_id}: {e}")
        elapsed_ms = int((time.time() - start) * 1000)
        return [], elapsed_ms, 0.0


# ─────────────────────────────────────────────────
# Visual extraction (photos, whiteboards)
# ─────────────────────────────────────────────────

def _extract_visual(image_data, source_channel, source_id, tier):
    """Extract structured data from images (whiteboards, screenshots, etc.)."""
    start = time.time()
    try:
        import base64

        from orchestrator.gemini_client import call_flash

        # Step 1: Vision — read and classify the image
        vision_prompt = """Analyze this image and:
1. Classify it as: whiteboard, diagram, handwritten, screenshot, business_card, or document_photo
2. Extract all text content visible in the image
3. Extract structured items (action items, decisions, deadlines, names, amounts)

Return JSON:
{
  "media_type": "whiteboard|diagram|handwritten|screenshot|business_card|document_photo",
  "text_content": "all visible text",
  "extracted_items": [
    {"type": "action_item", "text": "...", "who": "...", "when": "...", "confidence": "..."}
  ]
}"""

        # Handle both base64 and file path
        if isinstance(image_data, str) and len(image_data) > 1000:
            # Likely base64
            image_content = {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data},
            }
        else:
            # File path — read and encode
            import base64 as b64
            with open(image_data, "rb") as f:
                encoded = b64.b64encode(f.read()).decode()
            image_content = {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded},
            }

        resp = call_flash(
            messages=[{
                "role": "user",
                "content": [image_content, {"type": "text", "text": vision_prompt}],
            }],
            max_tokens=2000,
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="visual_extraction")
        except Exception:
            pass

        result_text = resp.text.strip()
        parsed = _parse_json_object(result_text)

        media_type = parsed.get("media_type", "document_photo")
        items = parsed.get("extracted_items", [])
        text_content = parsed.get("text_content", "")

        # Step 2: If T1, enrich with agentic context; T2 uses Pro
        if tier == 1 and text_content:
            enriched_items, _, extra_cost = _extract_agentic(
                text_content, source_channel, source_id
            )
        elif tier == 2 and text_content:
            enriched_items, _, extra_cost = _extract_pro(
                text_content, source_channel, source_id
            )
            if enriched_items:
                items = enriched_items  # Use enriched version

        # Step 3: Auto-link to meeting (within 1 hour)
        linked_meeting = _find_nearby_meeting()

        elapsed_ms = int((time.time() - start) * 1000)
        cost = 0.002 + (0.01 if tier in (1, 2) else 0)

        return items, media_type, linked_meeting, elapsed_ms, cost

    except Exception as e:
        logger.error(f"Visual extraction failed: {e}")
        elapsed_ms = int((time.time() - start) * 1000)
        return [], None, None, elapsed_ms, 0.0


def _find_nearby_meeting():
    """Find a meeting that ended within the last hour (for photo linking)."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title FROM meeting_transcripts
                WHERE ingested_at > NOW() - INTERVAL '2 hours'
                ORDER BY ingested_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            cur.close()
            if row:
                return row[0]
            return None
        finally:
            store._put_conn(conn)
    except Exception:
        return None


# ─────────────────────────────────────────────────
# Specialist output extraction
# ─────────────────────────────────────────────────

def extract_specialist_output(task_id, specialist_slug, output_text):
    """
    Extract structured data from dossier/deep analysis output.
    Called once on completion. Only for research dossiers and deep analyses.
    No re-extraction loop (Cowork pushback #2).
    """
    if not output_text or len(output_text) < 200:
        return

    logger.info(f"Extracting from specialist output: {specialist_slug} (task {task_id})")

    def _run():
        with _EXTRACTION_SEMAPHORE:
            items, elapsed_ms, cost = _extract_flash(
                output_text[:8000], "specialist", f"{specialist_slug}-{task_id}"
            )
            if items:
                _store_extractions(
                    source_channel="specialist",
                    source_id=f"{specialist_slug}-{task_id}",
                    extracted_items=items,
                    extraction_tier="T2",
                    processing_ms=elapsed_ms,
                    token_cost=cost,
                )

    threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────────
# JSON parsing helpers
# ─────────────────────────────────────────────────

def _parse_json_array(text):
    """Parse a JSON array from LLM response text."""
    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    import re
    match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding array in text
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


def _parse_json_object(text):
    """Parse a JSON object from LLM response text."""
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        return {}
    except json.JSONDecodeError:
        pass

    import re
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def extract_signal(source_channel, source_id, content, tier,
                   media_type=None, image_data=None):
    """
    Main entry point. Extracts structured data from any signal.
    Runs in a background thread with rate limiting.

    Args:
        source_channel: email, whatsapp, meeting, calendar, mobile_upload, specialist
        source_id: reference to original content
        content: text content to extract from
        tier: 1, 2, or 3 (from decision engine)
        media_type: if visual content (whiteboard, screenshot, etc.)
        image_data: base64 or file path for visual content
    """
    if not content and not image_data:
        return

    # Skip very short content
    if content and len(content) < 50 and not image_data:
        return

    def _run():
        with _EXTRACTION_SEMAPHORE:
            try:
                from orchestrator.cost_monitor import check_circuit_breaker
                allowed, daily_cost = check_circuit_breaker()
                if not allowed:
                    logger.warning(
                        f"Extraction skipped (circuit breaker at EUR {daily_cost:.2f}): "
                        f"{source_channel}:{source_id}"
                    )
                    return

                if image_data:
                    # Visual extraction
                    items, detected_media, linked_meeting, elapsed_ms, cost = _extract_visual(
                        image_data, source_channel, source_id, tier
                    )
                    _store_extractions(
                        source_channel=source_channel,
                        source_id=source_id,
                        extracted_items=items,
                        extraction_tier=f"T{tier}",
                        media_type=detected_media or media_type,
                        linked_meeting=linked_meeting,
                        processing_ms=elapsed_ms,
                        token_cost=cost,
                    )
                elif tier == 1:
                    # Agentic RAG extraction (Opus)
                    items, elapsed_ms, cost = _extract_agentic(
                        content, source_channel, source_id
                    )
                elif tier == 2:
                    # Gemini Pro extraction
                    items, elapsed_ms, cost = _extract_pro(
                        content, source_channel, source_id
                    )
                    _store_extractions(
                        source_channel=source_channel,
                        source_id=source_id,
                        extracted_items=items,
                        extraction_tier=f"T{tier}",
                        processing_ms=elapsed_ms,
                        token_cost=cost,
                    )
                else:
                    # T3: Haiku extraction
                    items, elapsed_ms, cost = _extract_flash(
                        content, source_channel, source_id
                    )
                    _store_extractions(
                        source_channel=source_channel,
                        source_id=source_id,
                        extracted_items=items,
                        extraction_tier="T3",
                        processing_ms=elapsed_ms,
                        token_cost=cost,
                    )

            except Exception as e:
                logger.error(
                    f"Extraction failed for {source_channel}:{source_id}: {e}",
                    exc_info=True,
                )

    # Run in background thread (non-blocking)
    threading.Thread(target=_run, daemon=True, name=f"extract-{source_channel}").start()


def extract_signal_sync(source_channel, source_id, content, tier,
                        media_type=None, image_data=None):
    """Synchronous version for testing. Same as extract_signal but blocks."""
    # Same logic but without threading — used in tests
    if not content and not image_data:
        return []

    if content and len(content) < 50 and not image_data:
        return []

    with _EXTRACTION_SEMAPHORE:
        if tier == 1:
            items, elapsed_ms, cost = _extract_agentic(content, source_channel, source_id)
        elif tier == 2:
            items, elapsed_ms, cost = _extract_pro(content, source_channel, source_id)
        else:
            items, elapsed_ms, cost = _extract_flash(content, source_channel, source_id)

        _store_extractions(
            source_channel=source_channel,
            source_id=source_id,
            extracted_items=items,
            extraction_tier=f"T{tier}",
            processing_ms=elapsed_ms,
            token_cost=cost,
        )
        return items
