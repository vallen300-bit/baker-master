"""Baker AI — Collection classifier.

Determines which Qdrant collection a file belongs to using:
1. Heuristic rules (filename patterns, path keywords)
2. Claude Haiku fallback for ambiguous files
"""
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("baker.ingest.classifier")

# Valid collections
VALID_COLLECTIONS = {
    "baker-people",
    "baker-deals",
    "baker-projects",
    "baker-conversations",
    "baker-whatsapp",
    "baker-clickup",
    "baker-documents",
}

DEFAULT_COLLECTION = "baker-documents"

# Heuristic patterns: (regex on filename+path, collection)
_PATTERNS = [
    (r"(?i)(contact|people|person|team|staff|employee)", "baker-people"),
    (r"(?i)(deal|investment|fund|portfolio|bond|epi|ubs)", "baker-deals"),
    (r"(?i)(project|hagenauer|rg7|cupial|movie|mo.vie|mandarin|mrci|lilienmat)", "baker-projects"),
    (r"(?i)(conversation|email|thread|inbox|gmail|message)", "baker-conversations"),
    (r"(?i)(whatsapp|wa_|chat_export)", "baker-whatsapp"),
    (r"(?i)(clickup|task|sprint|backlog)", "baker-clickup"),
]


def classify(filepath: Path, text_preview: str = "", use_llm: bool = True) -> str:
    """Classify a file into a Qdrant collection.

    Args:
        filepath: Source file path (used for heuristic matching).
        text_preview: First ~500 chars of extracted text (for LLM fallback).
        use_llm: Whether to use Claude Haiku for ambiguous files.

    Returns:
        Collection name string.
    """
    # Step 1: Heuristic match on filename + parent path
    search_string = str(filepath).lower()
    for pattern, collection in _PATTERNS:
        if re.search(pattern, search_string):
            logger.info("Classified '%s' → %s (heuristic)", filepath.name, collection)
            return collection

    # Step 2: LLM fallback
    if use_llm and text_preview.strip():
        llm_result = _classify_with_llm(filepath.name, text_preview[:500])
        if llm_result:
            return llm_result

    # Step 3: Default
    logger.info("Classified '%s' → %s (default)", filepath.name, DEFAULT_COLLECTION)
    return DEFAULT_COLLECTION


def _classify_with_llm(filename: str, text_preview: str) -> Optional[str]:
    """Use Claude Haiku to classify ambiguous files."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY — skipping LLM classification")
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — skipping LLM classification")
        return None

    collections_list = ", ".join(sorted(VALID_COLLECTIONS))
    prompt = (
        f"Classify this file into one of these Qdrant collections: {collections_list}\n\n"
        f"Filename: {filename}\n"
        f"Content preview:\n{text_preview}\n\n"
        f"Reply with ONLY the collection name, nothing else."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        result = resp.content[0].text.strip().lower()

        if result in VALID_COLLECTIONS:
            logger.info("Classified '%s' → %s (LLM)", filename, result)
            return result
        else:
            logger.warning("LLM returned invalid collection '%s' — using default", result)
            return None
    except Exception as e:
        logger.warning("LLM classification failed: %s", e)
        return None
