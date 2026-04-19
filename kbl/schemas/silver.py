"""Pydantic models for KBL Silver documents (Step 6 finalize contract).

Canonical spec: ``briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md`` §2 + OQ
resolutions at ``briefs/_drafts/KBL_B_STEP6_OQ_RESOLUTIONS_20260419.md``.

Five models:

* :class:`MatterSlug` — constrained str; regex + slug_registry ACTIVE
  membership validator.
* :class:`MoneyMention` — ``{amount: int, currency: Literal[...]}``. Step
  6 builds these from Opus's emitted ``list[str]`` via ``_parse_money_string``
  (see ``kbl.steps.step6_finalize``); the raw strings live in
  ``opus_draft_markdown`` frontmatter for prompt-cache stability.
* :class:`SilverFrontmatter` — the full frontmatter schema (required +
  optional keys per Step 5 prompt §1.2 + OQ-resolved shape). Key order
  is load-bearing; Pydantic v2 preserves insertion order, the serializer
  must not sort.
* :class:`SilverDocument` — frontmatter + body (300-8000 chars). Validates
  body-length + no-self-promotion (Inv 4/8).
* :class:`CrossLinkStub` — one queued row for ``kbl_cross_link_queue``.
  Option C cross-link flow: Step 6 on Render builds the Markdown
  ``stub_row`` string + UPSERTs; Step 7 on Mac Mini reads unrealized
  rows + appends verbatim to ``wiki/<target>/_links.md``. Step 6 never
  writes to the filesystem (Inv 9).

Inv 4 + Inv 8 are structurally enforced via ``Literal['pipeline']`` +
``Literal['silver']`` on :class:`SilverFrontmatter` — a draft with
``author: director`` or ``voice: gold`` cannot be validated; R18 catches
body-smuggled variants as a backup.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, List, Literal, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# --------------------------- MatterSlug ---------------------------


_SLUG_REGEX = r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$"


def _validate_slug_against_registry(v: str) -> str:
    """Reject slugs not in the slugs.yml ACTIVE set.

    RETIRED slugs are valid on READ (historical back-compat) but Step 6
    is a NEW write, so RETIRED must be rejected here — we never mint a
    retired-slug Silver entry.
    """
    from kbl.slug_registry import active_slugs

    if v not in active_slugs():
        raise ValueError(f"slug '{v}' is not in slugs.yml ACTIVE set")
    return v


MatterSlug = Annotated[
    str,
    StringConstraints(pattern=_SLUG_REGEX, strip_whitespace=True),
    AfterValidator(_validate_slug_against_registry),
]


# --------------------------- Literal enums ---------------------------


Vedana = Literal["threat", "opportunity", "routine"]
Voice = Literal["silver"]
Author = Literal["pipeline"]
StubStatus = Literal["stub_auto", "stub_cross_link", "stub_inbox"]
Currency = Literal["EUR", "USD", "CHF", "GBP", "RUB"]


# --------------------------- MoneyMention ---------------------------


class MoneyMention(BaseModel):
    """One structured money entry. Parsed from Opus's raw string forms
    (``'EUR 1200000'``, ``'€1.2M'``, ``'CHF 800K'``, ``'£3000'``) by
    ``kbl.steps.step6_finalize._parse_money_string``. Amount is the
    integer unit count, not minor units (Opus emits whole-unit amounts).
    """

    amount: int
    currency: Currency

    model_config = ConfigDict(extra="forbid")

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be positive integer")
        return v


# --------------------------- SilverFrontmatter ---------------------------


class SilverFrontmatter(BaseModel):
    """Frontmatter schema for a finalized Silver document.

    Required keys (always present on emit): ``title``, ``voice``,
    ``author``, ``created``, ``source_id``, ``primary_matter``,
    ``related_matters``, ``vedana``, ``triage_score``,
    ``triage_confidence``.

    Optional: ``thread_continues``, ``deadline``, ``money_mentioned``.
    Stub-only: ``status`` (set exclusively by deterministic stub writers
    in Step 5 — ``stub_auto`` / ``stub_cross_link`` / ``stub_inbox``;
    MUST be None on FULL_SYNTHESIS decisions — provenance gate enforced
    at Step 6 entry, not at this model level).

    Inv 4 + Inv 8 structural enforcement: ``voice: Literal['silver']``
    and ``author: Literal['pipeline']`` — a draft that sets ``gold`` or
    ``director`` fails validation at the field layer.

    KEY ORDER is load-bearing (prompt cache stability + Director read
    pattern). Pydantic v2 preserves field-declaration order in
    ``model_dump()``; don't reorder fields without updating the Step 5
    prompt too.
    """

    # --- required ---
    title: str
    voice: Voice
    author: Author
    created: datetime
    source_id: str
    primary_matter: Optional[MatterSlug] = None
    related_matters: List[MatterSlug] = Field(default_factory=list)
    vedana: Vedana
    triage_score: int = Field(ge=0, le=100)
    triage_confidence: float = Field(ge=0.0, le=1.0)

    # --- optional ---
    thread_continues: List[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    money_mentioned: List[MoneyMention] = Field(default_factory=list)

    # --- stub-only ---
    status: Optional[StubStatus] = None

    model_config = ConfigDict(extra="forbid")

    # --- field validators ---

    @field_validator("title")
    @classmethod
    def _title_shape(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        if len(v) > 160:
            raise ValueError(f"title too long ({len(v)} chars; max 160)")
        if v.endswith("."):
            raise ValueError("title must not end with period (per Step 5 prompt §1.2)")
        return v

    @field_validator("created")
    @classmethod
    def _created_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("created must be timezone-aware")
        if v.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("created must be UTC (found offset != 00:00)")
        return v

    @field_validator("deadline")
    @classmethod
    def _deadline_iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"deadline must be YYYY-MM-DD: {e}") from e
        return v

    @field_validator("money_mentioned")
    @classmethod
    def _money_cap(cls, v: List[MoneyMention]) -> List[MoneyMention]:
        if len(v) > 3:
            raise ValueError(f"money_mentioned capped at 3 entries (got {len(v)})")
        return v

    @field_validator("thread_continues")
    @classmethod
    def _thread_continues_paths(cls, v: List[str]) -> List[str]:
        """Lenient path validation per OQ3: ``^wiki/.*\\.md$`` only. Full
        canonical R20 regex is applied to ``target_vault_path`` in the
        Step 6 path builder, not here — historical vault paths pre-v9
        may contain characters the strict regex rejects."""
        for i, p in enumerate(v):
            if not (p.startswith("wiki/") and p.endswith(".md")):
                raise ValueError(
                    f"thread_continues[{i}]='{p}' must match wiki/*.md"
                )
        return v

    # --- model validators ---

    @model_validator(mode="after")
    def _no_primary_in_related(self) -> "SilverFrontmatter":
        if self.primary_matter and self.primary_matter in self.related_matters:
            raise ValueError(
                f"related_matters MUST NOT contain primary_matter "
                f"('{self.primary_matter}')"
            )
        # order-preserving dedupe.
        seen = set()
        deduped: List[str] = []
        for slug in self.related_matters:
            if slug not in seen:
                seen.add(slug)
                deduped.append(slug)
        object.__setattr__(self, "related_matters", deduped)
        return self

    @model_validator(mode="after")
    def _null_primary_implies_empty_related(self) -> "SilverFrontmatter":
        if self.primary_matter is None and self.related_matters:
            raise ValueError(
                "primary_matter=null with non-empty related_matters is invalid "
                "(per §4.2 invariant — null-matter signal cannot carry cross-links)"
            )
        return self


# --------------------------- SilverDocument ---------------------------


_FORBIDDEN_BODY_MARKERS = (
    "voice: gold",
    "voice:gold",
    "author: director",
    "author:director",
)


class SilverDocument(BaseModel):
    """Frontmatter + body. The YAML-serialized form is ``final_markdown``."""

    frontmatter: SilverFrontmatter
    body: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("body")
    @classmethod
    def _body_length(cls, v: str) -> str:
        n = len(v)
        if n < 300:
            raise ValueError(f"body too short ({n} chars; min 300)")
        if n > 8000:
            raise ValueError(f"body too long ({n} chars; max 8000)")
        return v

    @field_validator("body")
    @classmethod
    def _no_gold_self_promotion(cls, v: str) -> str:
        """R18 backup: Opus may smuggle ``voice: gold`` into body prose
        (prompt injection or subtle bug). Reject any occurrence — Gold
        promotion is Director-only (Inv 8)."""
        lower = v.lower()
        for pat in _FORBIDDEN_BODY_MARKERS:
            if pat in lower:
                raise ValueError(
                    f"body contains forbidden self-promotion marker "
                    f"'{pat}'; Gold promotion is Director-only (Inv 8)"
                )
        return v

    @model_validator(mode="after")
    def _stub_status_matches_shape(self) -> "SilverDocument":
        """Stub decisions emit short deterministic bodies (≤600 chars).
        Full-synthesis bodies can be short too (lower bound 300 — the
        _body_length floor covers that) but a stub + long body can only
        come from an upstream bug (stub writer accidentally emitting
        prose)."""
        if self.frontmatter.status is not None and len(self.body) > 600:
            raise ValueError(
                f"frontmatter.status='{self.frontmatter.status}' implies "
                f"deterministic stub shape, but body is {len(self.body)} "
                f"chars (max 600 for stubs); upstream stub writer bug"
            )
        return self


# --------------------------- CrossLinkStub ---------------------------


class CrossLinkStub(BaseModel):
    """One queued cross-link row for ``kbl_cross_link_queue`` (Option C).

    Step 6 builds the ``stub_row`` Markdown string once and UPSERTs by
    ``(source_signal_id, target_slug)``. Step 7 on Mac Mini reads
    ``realized_at IS NULL`` rows, appends ``stub_row`` verbatim to
    ``wiki/<target_slug>/_links.md``, then sets ``realized_at = NOW()``
    in the same git transaction.

    ``stub_row`` shape (B3 spec §4):
        ``<!-- stub:signal_id=<id> --> - YYYY-MM-DD | source_path | vedana | excerpt``

    The Markdown-comment prefix gives Step 7 a cheap regex hit for
    idempotency re-run checks (replaces rather than appends on the same
    signal). Excerpt is optional; capped at 140 chars single-line.
    """

    source_signal_id: str
    source_path: str
    created: datetime
    vedana: Vedana
    excerpt: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("excerpt")
    @classmethod
    def _excerpt_length(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if len(v) > 140:
            raise ValueError(f"excerpt too long ({len(v)} chars; max 140)")
        if "\n" in v:
            raise ValueError("excerpt must be single-line (no newlines)")
        return v

    def render_stub_row(self) -> str:
        """Render to the Markdown-row form Step 7 appends verbatim.

        Format pinned by B3 spec §4 + Option C dispatch. Single line;
        ``wiki/<target>/_links.md`` is append-only for Step 7.
        """
        date_stamp = self.created.strftime("%Y-%m-%d")
        excerpt = (self.excerpt or "").replace("|", "\\|").strip()
        return (
            f"<!-- stub:signal_id={self.source_signal_id} -->"
            f" - {date_stamp} | {self.source_path} | {self.vedana}"
            f" | {excerpt}"
        )
