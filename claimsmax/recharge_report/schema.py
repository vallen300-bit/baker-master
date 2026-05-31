"""Recharge-report schema — Pydantic v2 model bound to the canonical Pichler V3
EN-only register (D-017, Director-ratified 2026-05-26). Each field maps 1:1 to a
{{slot}} in the V3 HTML template. No optional fields, no extras.

H2 count, H2 order, claim-figures triplet, evidence-table 3-col, split-table 70/30,
delta-conflict accent are THE CONTRACT — do NOT modify without Director ratification
(template version bump, not in-line drift).
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimFiguresRow(BaseModel):
    """One row inside the .claim-figures block. Three rows total per spine §3."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    row_kind: Literal["before", "headline", "ceiling"] = Field(
        description="Which of the three triplet rows: Before / Conservative (headline) / Max Ceiling"
    )
    label: str = Field(description="Left-hand label. Plain English, no HTML.")
    value: str = Field(
        description="Right-hand value. Currency formatted, plain text (\u20ac35,000 style)."
    )


class EvidenceRow(BaseModel):
    """One row of the .evidence-table (3 columns: date, document, what it proves)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: str = Field(
        description="Date or period. Plain text (e.g. '15 Nov 2023', 'Q2 2025', 'baseline')."
    )
    document: str = Field(description="Document reference. Plain text.")
    proves: str = Field(description="What it proves. One sentence, plain English.")


class SplitTableRow(BaseModel):
    """One row of the .split-table (label + numeric)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(description="Left column label. Plain English.")
    amount: str = Field(
        description="Right column numeric. Currency formatted (\u20ac18,000 style)."
    )
    row_kind: Literal["item", "total", "sub"] = Field(
        description="'item' = ordinary row, 'total' = bordered total row, 'sub' = indented Vorbehalt/ceiling row"
    )


class ArgumentItem(BaseModel):
    """One numbered argument in 'Brisen's Arguments (to be validated)'."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str = Field(
        description="Headline sentence. One short clause rendered as <strong>."
    )
    body: str = Field(
        description="Supporting paragraph. 2-3 short lines separated by <br> per spine rule 2 (no walls of text)."
    )


class RechargeReport(BaseModel):
    """Canonical Pichler V3 EN-only recharge-failure report. Each field is one slot.

    Word-count targets per spine + ClaimsMax bake-off:
    - Background bullets: <= 5 items, one line each.
    - 'What X failed to do': <= 3 bullets per spine rule 5 (duplicates removed).
    - 'What happened with the <trade> work': 3-5 short paragraphs, <= 80 words each.
    - Arguments: 5-8 items.
    - Evidence rows: 5-9 rows.
    - Split-table rows: 3-6 line items + 1 total + 0-3 sub rows.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # --- Title block (spine §1) ---
    report_title: str = Field(
        description="Trade-name H1 title (e.g. 'Lohberger / Commercial Kitchen'). Plain text, max 60 chars."
    )
    claim_type: str = Field(
        description="Claim-type subtitle (e.g. 'Recharge-Failure Claim'). Plain text, max 40 chars."
    )
    report_date: str = Field(
        description="Date string for the report-meta line (e.g. '29 May 2026')."
    )
    report_time: str = Field(
        description="Time string for the report-meta line (e.g. '08:00')."
    )

    # --- Tagline + provenance (spine §2) ---
    tagline: str = Field(
        description="Italic strategic-frame sentence. 1-2 sentences, <= 50 words. Declarative, no hedges."
    )
    version_marker: str = Field(
        description="Bold provenance line under the tagline (e.g. 'Edita-solo audit \u00b7 corpus enrichment pending'). <= 80 chars."
    )

    # --- Claim-figures triplet (spine §3) ---
    claim_figures: list[ClaimFiguresRow] = Field(
        description="Exactly 3 rows in order: before / headline / ceiling.",
        min_length=3,
        max_length=3,
    )

    # --- The parties (spine §4 / H2 #1) ---
    parties: str = Field(
        description=(
            "HTML <ol> body with 2-4 <li> items. Identify counterparty (Firma + FN + UID + "
            "Sitz + GF if known), then Brisen-side lead. Plain English, no German legal "
            "vocab. Target ~120-160 words. Counsel-readable in 30 seconds (spine rule 1)."
        )
    )

    # --- Background (H2 #2) ---
    background: str = Field(
        description=(
            "HTML <ol> body, 4-6 numbered items. Each item is one fact, one line. No prose "
            "paragraphs inside the list. Target ~100-140 words total."
        )
    )

    # --- What happened with the <trade> work (H2 #3) ---
    trade_h2_suffix: str = Field(
        description=(
            "Trade descriptor that completes the H2 heading 'What happened with the <X> "
            "work' (e.g. 'Lohberger', 'drywall', 'HVAC'). Plain text, <= 25 chars."
        )
    )
    what_happened: str = Field(
        description=(
            "3-5 short <p> paragraphs, <= 80 words each. Chronological narrative of the "
            "trade work and where it broke. Target ~250-320 words total. No bullets."
        )
    )

    # --- What Hagenauer failed to do (H2 #4) ---
    what_hag_failed: str = Field(
        description=(
            "HTML <ul> body, max 3 bullets (spine rule 5 — duplicates removed). Each "
            "bullet <= 30 words, declarative. Target ~80-120 words total."
        )
    )

    # --- The evidence chain (H2 #5) ---
    evidence_chain: list[EvidenceRow] = Field(
        description=(
            "5-9 rows of the evidence-table. Chronological. Mix of baseline contracts, "
            "dated documents, and 'full period' negative-evidence rows. Each row's 'proves' "
            "column <= 35 words."
        ),
        min_length=5,
        max_length=9,
    )

    # --- The amount Brisen claims (H2 #6) — split-table + Delta-Conflict ---
    amount_claimed: list[SplitTableRow] = Field(
        description=(
            "Split-table rows in display order: line items (kind='item'), then exactly 1 "
            "total (kind='total'), then 0-3 sub rows (kind='sub') for Vorbehalt/Mehrkosten "
            "ceiling. Total rows 3-8."
        ),
        min_length=3,
        max_length=8,
    )
    amount_claimed_notes: str = Field(
        description=(
            "2 short <p> paragraphs after the split-table. Reserve-of-rights wording. "
            "<= 100 words total."
        )
    )
    delta_conflict: str = Field(
        description=(
            "Single paragraph for the .delta-conflict accent block. Names same-loss-two-"
            "expressions OR cross-trade severability. 60-120 words. Lead with the conflict, "
            "end with how it's resolved (Bauer extraction / severability split / pending "
            "evidence)."
        )
    )

    # --- Brisen's Arguments (to be validated) (H2 #7) ---
    arguments: list[ArgumentItem] = Field(
        description=(
            "5-8 numbered arguments. Each: bolded headline + 2-3 short body lines "
            "(separated by <br> per spine rule 2). Framed as working positions awaiting "
            "counsel validation, never legal verdicts (spine rule 4)."
        ),
        min_length=5,
        max_length=8,
    )


# Canonical H2 ordering (for renderer + validator). The 7 EN H2s as they appear in V3.
# The 3rd H2 carries the trade suffix at runtime ("What happened with the <X> work") —
# the validator uses a regex match for that position, not exact string equality.
EN_H2_ORDER: list[str] = [
    "The parties",
    "Background",
    "What happened with the {trade} work",
    "What Hagenauer failed to do",
    "The evidence chain",
    "The amount Brisen claims",
    "Brisen's Arguments (to be validated)",
]

assert len(EN_H2_ORDER) == 7, "Canonical Pichler V3 EN register is exactly 7 H2 sections"
