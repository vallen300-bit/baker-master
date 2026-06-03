"""Baker AI — Ingestion data models."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IngestResult:
    """Result of ingesting a single file."""
    filename: str
    file_hash: str
    file_size_bytes: int
    collection: str
    chunk_count: int
    project: Optional[str] = None
    role: Optional[str] = None
    point_ids: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None
    error: Optional[str] = None
    card_data: Optional[dict] = None          # Business card extracted fields
    contact_result: Optional[dict] = None     # Contact write result (action, contact_id)
    # INGEST_RETRIEVAL_GAP_FIX_1: expose extracted text so callers can mirror the
    # dropbox-trigger two-write pattern (Qdrant chunks here + Postgres `documents`
    # row in the caller) without re-extracting (re-extract = double Vision cost on images).
    full_text: Optional[str] = None           # Full extracted text (pre-chunk)
    token_count: int = 0                      # Rough token estimate of full_text
    document_id: Optional[int] = None         # documents.id once the caller persists the row
