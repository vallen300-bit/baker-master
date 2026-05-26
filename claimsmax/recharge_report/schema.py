"""Recharge-report schema — Pydantic v2 model bound to the 11-section Pichler/HEAD-4
canonical template. Each field maps 1:1 to a {{slot}} in the scaffold. No optional
fields, no extras, no defaults.

Section count and order are the contract — do NOT modify without Director ratification.
"""
from pydantic import BaseModel, Field, ConfigDict


class RechargeReport(BaseModel):
    """The 11-section Director-facing recharge-failure report. Each field is one H2 slot."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    executive_summary: str = Field(
        description=(
            "2-4 sentences. Bottom-line outcome of the recharge attempt. "
            "Declarative, no bullets, no subordinate headings. Target ~120-150 words."
        )
    )
    scope_of_report: str = Field(
        description=(
            "2-3 sentences naming the trade, time window, counterparty, "
            "and the recharge claim being evaluated. Target ~100-120 words."
        )
    )
    counterparty_and_contract: str = Field(
        description=(
            "Counterparty identity, contract reference, and legal basis "
            "for the recharge attempt. Target ~150-180 words."
        )
    )
    evidence_base: str = Field(
        description=(
            "Numbered list (1-5) of evidence items: invoices, payment records, "
            "site reports, expert opinions. Cite document refs. Target ~180-220 words."
        )
    )
    cost_reconstruction: str = Field(
        description=(
            "What was paid, by whom, to whom. Include the single Delta-Conflict "
            "paragraph (Mehrkosten/Differenzmethode) here if applicable — NOT as a "
            "separate H2. Reasoning may use extended-thinking mode. Target ~200-250 words."
        )
    )
    recharge_basis: str = Field(
        description=(
            "Legal and factual basis for why the counterparty owes the claimed amount. "
            "Cite contract clauses + statute where relevant. Target ~150-180 words."
        )
    )
    counterparty_defence: str = Field(
        description=(
            "Anticipated counterparty defence with at least one named, foreseeable "
            "argument and our planned response. Target ~150-180 words."
        )
    )
    risks_and_open_questions: str = Field(
        description=(
            "Numbered list of open risks, missing evidence, or decisions "
            "pending Ofenheimer / Bauer review. Target ~120-150 words."
        )
    )
    numbers_claimed: str = Field(
        description=(
            "Single paragraph stating the claim quantum: filed EUR, Vorbehalt EUR, "
            "sub-positions if any. Numbers cited with source. Target ~80-120 words."
        )
    )
    recommendation: str = Field(
        description=(
            "Director-facing recommendation in 1-2 sentences. Names the action and "
            "the responsible party. Target ~50-80 words."
        )
    )
    anchors: str = Field(
        description=(
            "Provenance: source docs, vault paths, ratification anchors, date verified. "
            "Numbered list. Target ~80-120 words."
        )
    )


# Canonical H2 heading-to-field map (for renderer + validator). KEEP IN SYNC.
SECTION_ORDER: list[tuple[str, str]] = [
    ("Executive summary", "executive_summary"),
    ("Scope of this report", "scope_of_report"),
    ("Counterparty and contract structure", "counterparty_and_contract"),
    ("Evidence base", "evidence_base"),
    ("Cost reconstruction — what was paid, by whom", "cost_reconstruction"),
    ("Recharge basis — why the counterparty owes", "recharge_basis"),
    ("Counterparty defence anticipated", "counterparty_defence"),
    ("Risks and open questions", "risks_and_open_questions"),
    ("Numbers we are claiming", "numbers_claimed"),
    ("Recommendation", "recommendation"),
    ("Anchors", "anchors"),
]

assert len(SECTION_ORDER) == 11, "Canonical Pichler/HEAD-4 contract is exactly 11 sections"
