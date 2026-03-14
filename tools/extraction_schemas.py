"""
EXTRACTION-VALIDATION-1 — Pydantic validation for document extractions.

13 models (one per extraction type) with promote-over-time strategy:
  - Core fields validated with proper types
  - Extra fields Haiku invents are preserved under "_extra" key
  - Amount fields coerced from European strings to float
  - Never raises — returns (raw_dict, False) on validation failure

Public API:
  validate_extraction(doc_type, raw) -> (dict, bool)
  get_promotion_sql() -> str
"""
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger("baker.extraction_schemas")


# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort coercion of amount-like values to float.

    Handles: "€118.000", "5%", "1.234,56", "118000.00", dicts, None.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        # Haiku sometimes returns {"gross": 123, "net": 100} — keep as-is upstream
        return None
    if not isinstance(v, str):
        return None

    s = v.strip()
    if not s:
        return None

    # Strip currency symbols and whitespace
    s = re.sub(r'[€$£\s]', '', s)
    # Strip trailing % (e.g. "5%" → "5")
    s = s.rstrip('%')

    if not s:
        return None

    # European format: "1.234,56" → "1234.56"
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        # Could be "1234,56" (European decimal) or "1,234" (thousands)
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    elif '.' in s:
        # European thousands: "118.000" → dot followed by exactly 3 digits = thousands separator
        # Handles "1.234.567" (multiple dots) and "118.000" (single dot, 3 trailing digits)
        parts = s.split('.')
        if len(parts) >= 2 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace('.', '')

    try:
        return float(s)
    except (ValueError, OverflowError):
        return None


def _amount_validator(cls, v):
    """Pydantic field_validator for amount fields. Coerces or passes through."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        coerced = _coerce_float(v)
        return coerced if coerced is not None else v
    # dicts, lists — pass through (Haiku sometimes nests amounts)
    return v


# ─────────────────────────────────────────────
# Base model
# ─────────────────────────────────────────────

class _ExtractionBase(BaseModel):
    model_config = ConfigDict(extra='allow')


# ─────────────────────────────────────────────
# 13 extraction models
# ─────────────────────────────────────────────

class ContractExtraction(_ExtractionBase):
    parties: Optional[Any] = None
    value: Optional[Any] = None
    dates: Optional[Any] = None
    penalty_clauses: Optional[Any] = None
    retention_pct: Optional[Any] = None
    governing_law: Optional[Any] = None
    jurisdiction: Optional[Any] = None

    _coerce_retention = field_validator('retention_pct', mode='before')(_amount_validator)


class InvoiceExtraction(_ExtractionBase):
    amounts: Optional[Any] = None
    period: Optional[Any] = None
    cumulative_total: Optional[Any] = None
    deductions: Optional[Any] = None
    retention: Optional[Any] = None
    payment_terms: Optional[Any] = None
    due_date: Optional[Any] = None

    _coerce_cumulative = field_validator('cumulative_total', mode='before')(_amount_validator)


class NachtragExtraction(_ExtractionBase):
    amendment_number: Optional[Any] = None
    original_contract_ref: Optional[Any] = None
    scope_change: Optional[Any] = None
    price_change: Optional[Any] = None
    new_total: Optional[Any] = None
    approval_status: Optional[Any] = None

    _coerce_price = field_validator('price_change', mode='before')(_amount_validator)
    _coerce_total = field_validator('new_total', mode='before')(_amount_validator)


class SchlussrechnungExtraction(_ExtractionBase):
    total_claimed: Optional[Any] = None
    total_approved: Optional[Any] = None
    retentions: Optional[Any] = None
    deductions: Optional[Any] = None
    open_items: Optional[Any] = None

    _coerce_claimed = field_validator('total_claimed', mode='before')(_amount_validator)
    _coerce_approved = field_validator('total_approved', mode='before')(_amount_validator)


class CorrespondenceExtraction(_ExtractionBase):
    sender: Optional[Any] = None
    recipient: Optional[Any] = None
    date: Optional[Any] = None
    subject: Optional[Any] = None
    key_points: Optional[Any] = None
    action_items: Optional[Any] = None


class ProtocolExtraction(_ExtractionBase):
    meeting_date: Optional[Any] = None
    attendees: Optional[Any] = None
    key_decisions: Optional[Any] = None
    action_items: Optional[Any] = None
    next_meeting: Optional[Any] = None


class ReportExtraction(_ExtractionBase):
    report_type: Optional[Any] = None
    period: Optional[Any] = None
    key_findings: Optional[Any] = None
    recommendations: Optional[Any] = None


class LegalOpinionExtraction(_ExtractionBase):
    author: Optional[Any] = None
    date: Optional[Any] = None
    jurisdiction: Optional[Any] = None
    question: Optional[Any] = None
    conclusion: Optional[Any] = None
    risks: Optional[Any] = None
    recommendations: Optional[Any] = None


class FinancialModelExtraction(_ExtractionBase):
    model_type: Optional[Any] = None
    assumptions: Optional[Any] = None
    key_outputs: Optional[Any] = None
    scenarios: Optional[Any] = None


class LandRegisterExtraction(_ExtractionBase):
    property_address: Optional[Any] = None
    plot_number: Optional[Any] = None
    registered_owner: Optional[Any] = None
    encumbrances: Optional[Any] = None
    area_sqm: Optional[Any] = None

    _coerce_area = field_validator('area_sqm', mode='before')(_amount_validator)


class MeetingNotesExtraction(_ExtractionBase):
    date: Optional[Any] = None
    attendees: Optional[Any] = None
    topics: Optional[Any] = None
    decisions: Optional[Any] = None
    action_items: Optional[Any] = None


class ProposalExtraction(_ExtractionBase):
    proposer: Optional[Any] = None
    recipient: Optional[Any] = None
    scope: Optional[Any] = None
    value: Optional[Any] = None
    timeline: Optional[Any] = None
    conditions: Optional[Any] = None

    _coerce_value = field_validator('value', mode='before')(_amount_validator)


class PresentationExtraction(_ExtractionBase):
    title: Optional[Any] = None
    author: Optional[Any] = None
    date: Optional[Any] = None
    key_slides_summary: Optional[Any] = None
    audience: Optional[Any] = None


# ─────────────────────────────────────────────
# Registry: doc_type → model class
# ─────────────────────────────────────────────

_SCHEMA_MAP: dict[str, type[_ExtractionBase]] = {
    "contract": ContractExtraction,
    "invoice": InvoiceExtraction,
    "nachtrag": NachtragExtraction,
    "schlussrechnung": SchlussrechnungExtraction,
    "correspondence": CorrespondenceExtraction,
    "protocol": ProtocolExtraction,
    "report": ReportExtraction,
    "legal_opinion": LegalOpinionExtraction,
    "financial_model": FinancialModelExtraction,
    "land_register": LandRegisterExtraction,
    "meeting_notes": MeetingNotesExtraction,
    "proposal": ProposalExtraction,
    "presentation": PresentationExtraction,
}


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def validate_extraction(doc_type: str, raw: dict) -> tuple[dict, bool]:
    """Validate and normalize an extraction dict.

    Returns (normalized_dict, validated_flag). Never raises.
    - On success: core fields at top level, extras under "_extra" key, validated=True
    - On failure: raw dict returned unchanged, validated=False
    - Unknown doc_type: raw dict returned unchanged, validated=False
    """
    model_cls = _SCHEMA_MAP.get(doc_type)
    if not model_cls:
        return raw, False

    try:
        instance = model_cls.model_validate(raw)

        # Split core fields from extras
        core = {}
        for field_name in instance.model_fields:
            core[field_name] = getattr(instance, field_name)

        # Extras added by Haiku (not in the model)
        extras = instance.__pydantic_extra__ or {}
        if extras:
            core["_extra"] = dict(extras)

        return core, True

    except Exception as e:
        logger.warning(f"Validation failed for {doc_type}: {e}")
        return raw, False


def get_promotion_sql() -> str:
    """Return SQL to find frequently-occurring extra fields across validated extractions.

    Run monthly. Any field appearing in >20% of its type across 10+ docs → promote to schema.
    """
    return """
WITH extra_keys AS (
    SELECT
        extraction_type,
        jsonb_object_keys(structured_data->'_extra') AS key
    FROM document_extractions
    WHERE structured_data ? '_extra'
      AND validated = TRUE
),
type_counts AS (
    SELECT extraction_type, COUNT(*) AS total
    FROM document_extractions
    WHERE validated = TRUE
    GROUP BY extraction_type
)
SELECT
    ek.extraction_type,
    ek.key,
    COUNT(*) AS occurrences,
    tc.total AS type_total,
    ROUND(100.0 * COUNT(*) / tc.total, 1) AS pct_of_type
FROM extra_keys ek
JOIN type_counts tc ON ek.extraction_type = tc.extraction_type
GROUP BY ek.extraction_type, ek.key, tc.total
HAVING COUNT(*) >= 10
ORDER BY ek.extraction_type, occurrences DESC;
"""
