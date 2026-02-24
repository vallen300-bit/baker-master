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
