# KBL-B Step 6 — `finalize` Pydantic schema + validation spec

**Author:** Code Brisen 3 (B3) — empirical lead
**Task:** `briefs/_tasks/CODE_3_PENDING.md` (2026-04-19 dispatch — STEP6-FINALIZE-SCHEMA-SPEC, task-commit `79a27a1`)
**Target consumer:** B1 implementation of `kbl/steps/step6_finalize.py`
**Status:** draft, pre-implementation. Reviewer: B2.
**Anchor:** KBL-B §4.7 (post-REDIRECT 2026-04-18 ratification — Step 6 deterministic, no model call).
**Related:** `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` §1.2 frontmatter spec + §3 worked examples (7 canonical output shapes this validator must accept).

---

## 1. Purpose & §4.7 anchor

Step 6 (`finalize`) is the last quality gate before the vault commit (Step 7). It is **deterministic** — no prompt, no model call, no `kbl_cost_ledger` row. Post the 2026-04-18 REDIRECT ratification, Step 6 does three mechanical jobs against the `opus_draft_markdown` produced by Step 5:

1. **Pydantic-validate** the frontmatter + body shape. Reject malformed drafts with `FinalizationError`.
2. **Build** `final_markdown` (Pydantic-round-tripped canonical form) + compute `target_vault_path` from `primary_matter` + `created` + title-slug.
3. **Write cross-link stubs** to `wiki/<m>/_links.md` for each slug in `related_matters`, idempotent by `source_signal_id`.

Anchor: KBL-B §4.7 (pipeline code brief lines 414-422). This spec expands that paragraph into an implementation-ready contract. No behavior specified here should contradict §4.7; where this spec is more specific, §4.7's wording prevails on intent, this spec prevails on mechanics.

---

## 2. Pydantic models

Target Python version: 3.11+. Pydantic: v2. File location: `kbl/schemas/silver.py` (proposed — B1's call if a different path fits better).

### 2.1 `MatterSlug` — constrained str

```python
from typing import Annotated
from pydantic import StringConstraints, AfterValidator

# Regex: canonical v9 shape — lowercase, digits, dash; 2-30 chars; no leading/trailing dash
_SLUG_REGEX = r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$"

def _validate_slug_against_registry(v: str) -> str:
    """Reject slugs not present in the v9 registry's ACTIVE set.
    The RETIRED set is accepted on READ (historical backward compat per
    slugs.yml comment), but Step 6 validation is for NEW writes, so
    RETIRED must be rejected here — we are never minting a retired-slug
    Silver entry."""
    from kbl.slug_registry import active_slugs
    if v not in active_slugs():
        raise ValueError(f"slug '{v}' is not in slugs.yml v9 ACTIVE set")
    return v

MatterSlug = Annotated[
    str,
    StringConstraints(pattern=_SLUG_REGEX, strip_whitespace=True),
    AfterValidator(_validate_slug_against_registry),
]
```

Rationale: regex catches shape violations (uppercase, spaces, trailing dash — cheap + precise), the AfterValidator catches out-of-registry slugs using the same `kbl/slug_registry.active_slugs()` call Step 1 uses. Aligned with slugs.yml v9 (33 active, 1 retired at time of spec — 2026-04-19).

### 2.2 `Vedana`, `Voice`, `Author`, `StubStatus` — Literal enums

```python
from typing import Literal

Vedana      = Literal["threat", "opportunity", "routine"]
Voice       = Literal["silver"]   # Step 6 can ONLY write silver (Inv 8)
Author      = Literal["pipeline"] # Step 6 can ONLY write pipeline (Inv 4)
StubStatus  = Literal["stub_auto", "stub_cross_link", "stub_inbox"]
```

Rationale:
- `Voice` is a single-value Literal by design. Gold promotion is the Director's action per CHANDA Inv 8 — Step 6 structurally cannot write `voice: gold`. A draft that arrives with `voice: gold` fails validation.
- `Author` is `Literal["pipeline"]` for the same reason against CHANDA Inv 4. A draft with `author: director` fails validation. Director promotion flips this field later in the lifecycle (outside Step 6).
- `StubStatus` is only set by the deterministic stub writers upstream (Step 5 boundaries). Full-synthesis outputs from Opus MUST NOT include `status` — Pydantic rejects it. See worked example 7 in Step 5 prompt §3.

### 2.3 `SilverFrontmatter` — the full model

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timezone

class MoneyMention(BaseModel):
    """One entry in money_mentioned[]. Parsed from string forms like
    'EUR 1200000' / '€1.2M' / 'CHF 800K' / '£3000'. Stored normalized."""
    amount: int                                      # in minor units? NO — stored as integer units, ccy-labeled
    currency: Literal["EUR", "USD", "CHF", "GBP", "RUB"]

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be positive integer")
        return v


class SilverFrontmatter(BaseModel):
    """All 8 required + 6 optional keys from STEP5-OPUS-PROMPT §1.2
    frontmatter spec, plus pipeline-injected telemetry fields
    (triage_score, triage_confidence, status). Step 6 assembles the
    full frontmatter by reading the Opus draft + signal_queue columns.

    KEY ORDER is load-bearing — Pydantic v2 preserves insertion order;
    serializer must not sort. The Step 5 prompt trains Opus on the
    ordered sequence; scrambling the order breaks prompt-caching + the
    Director's human read pattern."""

    # --- required: emitted by Opus (or deterministic stub writer) ---
    title:            str                             # 1-160 chars (widened from 80 — titles with money figures run long)
    voice:            Voice                           # Literal['silver']
    author:           Author                          # Literal['pipeline']
    created:          datetime                        # ISO 8601, UTC, timezone-aware
    source_id:        str                             # signal_queue.signal_id
    primary_matter:   MatterSlug | None               # null allowed — Step 1 may return null
    related_matters:  list[MatterSlug] = []           # empty list [] is canonical, never None
    vedana:           Vedana                          # Literal[threat|opportunity|routine]

    # --- pipeline-injected at finalize (read from signal_queue row) ---
    triage_score:      int = Field(ge=0, le=100)      # 0-100, int
    triage_confidence: float = Field(ge=0.0, le=1.0)  # 0.0-1.0, float

    # --- optional: emitted by Opus when applicable ---
    thread_continues:  list[str] = []                 # vault paths (validated in §3)
    deadline:          str | None = None              # YYYY-MM-DD date string (see §3)
    money_mentioned:   list[MoneyMention] = []        # capped at 3 by validator

    # --- optional: written by deterministic stub writers only ---
    status:            StubStatus | None = None       # None for full synthesis; set only by stub writers

    # --- normalizers / cross-field validators ---
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
            # not UTC — reject. Silver canonicals are UTC per convention.
            raise ValueError("created must be UTC (found offset != 00:00)")
        return v

    @field_validator("deadline")
    @classmethod
    def _deadline_iso_date(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"deadline must be YYYY-MM-DD: {e}") from e
        return v

    @field_validator("money_mentioned")
    @classmethod
    def _money_cap(cls, v: list[MoneyMention]) -> list[MoneyMention]:
        if len(v) > 3:
            raise ValueError(f"money_mentioned capped at 3 entries (got {len(v)})")
        return v

    @model_validator(mode="after")
    def _no_primary_in_related(self) -> "SilverFrontmatter":
        if self.primary_matter and self.primary_matter in self.related_matters:
            raise ValueError(
                f"related_matters MUST NOT contain primary_matter "
                f"('{self.primary_matter}'); dedupe upstream"
            )
        # dedupe related_matters in place (order-preserving)
        seen = set()
        deduped = []
        for slug in self.related_matters:
            if slug not in seen:
                seen.add(slug)
                deduped.append(slug)
        self.related_matters = deduped
        return self

    @model_validator(mode="after")
    def _null_primary_implies_empty_related(self) -> "SilverFrontmatter":
        if self.primary_matter is None and self.related_matters:
            raise ValueError(
                "primary_matter=null with non-empty related_matters is invalid "
                "(per §4.2 invariant — a null-matter signal cannot carry cross-links)"
            )
        return self

    @model_validator(mode="after")
    def _status_only_for_stubs(self) -> "SilverFrontmatter":
        # Opus full-synthesis outputs MUST NOT include status.
        # status is reserved for the upstream deterministic stub writers.
        # This is enforced at the FRONTMATTER level; the caller determines
        # whether the decision was full_synthesis vs stub_* via signal_queue.step_5_decision
        # and passes the appropriate flag to the validator — see §3.7.
        return self  # cross-check happens in SilverDocument.finalize_from_draft()
```

### 2.4 `SilverDocument` — frontmatter + body

```python
class SilverDocument(BaseModel):
    """Full Silver document — frontmatter + body. The finalized YAML-
    serialized form of this is `final_markdown`."""

    frontmatter: SilverFrontmatter
    body:        str

    @field_validator("body")
    @classmethod
    def _body_length(cls, v: str) -> str:
        # ~300-800 tokens ≈ 1500-4000 chars for prose with moderate
        # structure. Upper bound relaxed to 8000 chars for signals with
        # dense quantitative content (long money_mentioned lists, many
        # decisions). Lower bound 300 chars accommodates stub-shape
        # outputs (Ex 7, ~300-400 chars).
        n = len(v)
        if n < 300:
            raise ValueError(f"body too short ({n} chars; min 300)")
        if n > 8000:
            raise ValueError(f"body too long ({n} chars; max 8000)")
        return v

    @field_validator("body")
    @classmethod
    def _no_gold_self_promotion(cls, v: str) -> str:
        # Anti-self-promotion: Opus must not smuggle "voice: gold" or
        # "author: director" into the body text (e.g., inside a fake
        # code-fenced YAML block). This catches subtle prompt-injection
        # from the signal and subtle Opus bugs.
        forbidden_patterns = [
            "voice: gold",
            "voice:gold",
            "author: director",
            "author:director",
        ]
        for pat in forbidden_patterns:
            if pat in v.lower():
                raise ValueError(
                    f"body contains forbidden self-promotion marker "
                    f"'{pat}'; Gold promotion is Director-only (Inv 8)"
                )
        return v

    @model_validator(mode="after")
    def _stub_status_matches_shape(self) -> "SilverDocument":
        """status frontmatter field + body shape must agree:
          - status == 'stub_auto' / 'stub_cross_link' / 'stub_inbox'
            → body should be ≤ 600 chars (deterministic stub shape)
          - status is None (full synthesis)
            → body should be ≥ 1500 chars normally. We WARN but do NOT
              reject on 300-1499 chars — Opus can produce tight legitimate
              outputs for very thin signals.
        This validator only REJECTS on stub + long-body mismatch, because
        that shape can only come from an upstream bug (stub writer emitting
        prose). It does NOT reject on full-synthesis + short-body —
        the underlying _body_length floor at 300 covers that case.
        """
        if self.frontmatter.status is not None and len(self.body) > 600:
            raise ValueError(
                f"frontmatter.status='{self.frontmatter.status}' implies "
                f"deterministic stub shape, but body is {len(self.body)} "
                f"chars (max 600 for stubs); upstream stub writer bug"
            )
        return self
```

### 2.5 `CrossLinkStub` — cross-link row model

```python
class CrossLinkStub(BaseModel):
    """One row in wiki/<m>/_links.md for a related matter. Sorted by
    created DESC within the file. Idempotent by source_signal_id."""

    source_signal_id: str          # signal_queue.signal_id — idempotency key
    source_path:      str          # e.g. 'wiki/hagenauer-rg7/2026-03-30_admin-claim.md'
    created:          datetime     # from parent Silver's frontmatter.created
    vedana:           Vedana       # from parent Silver's frontmatter.vedana
    excerpt:          str | None = None  # optional 1-line (<=140 char) summary

    @field_validator("excerpt")
    @classmethod
    def _excerpt_length(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v) > 140:
            raise ValueError(f"excerpt too long ({len(v)} chars; max 140)")
        if "\n" in v:
            raise ValueError("excerpt must be single-line (no newlines)")
        return v
```

---

## 3. Validation rules (enumerated)

| # | Rule | Enforcement point | Failure → |
|---|------|-------------------|-----------|
| R1 | `author == 'pipeline'` — always | `SilverFrontmatter.author` Literal | `FinalizationError` |
| R2 | `voice == 'silver'` — always | `SilverFrontmatter.voice` Literal | `FinalizationError` |
| R3 | `primary_matter` ∈ v9 ACTIVE slugs ∪ {null} | `MatterSlug` AfterValidator (null bypass at field level) | `FinalizationError` |
| R4 | each entry of `related_matters` ∈ v9 ACTIVE slugs | `MatterSlug` AfterValidator, per entry | `FinalizationError` |
| R5 | `primary_matter ∉ related_matters` | `SilverFrontmatter._no_primary_in_related` model_validator | `FinalizationError` |
| R6 | `related_matters` is deduplicated (order preserved) | same model_validator (mutating) | auto-fixed, no error |
| R7 | `primary_matter is None` ⇒ `related_matters == []` | `SilverFrontmatter._null_primary_implies_empty_related` | `FinalizationError` |
| R8 | `vedana` ∈ `{threat, opportunity, routine}` strictly | `Vedana` Literal | `FinalizationError` |
| R9 | `triage_score` is int in [0, 100] | `Field(ge=0, le=100)` | `FinalizationError` |
| R10 | `triage_confidence` is float in [0.0, 1.0] | `Field(ge=0.0, le=1.0)` | `FinalizationError` |
| R11 | `created` is timezone-aware, UTC | `_created_utc` field_validator | `FinalizationError` |
| R12 | `title` non-empty, ≤160 chars, no trailing period | `_title_shape` field_validator | `FinalizationError` |
| R13 | `deadline` is `YYYY-MM-DD` if present | `_deadline_iso_date` field_validator | `FinalizationError` |
| R14 | `money_mentioned` capped at 3 | `_money_cap` field_validator | `FinalizationError` |
| R15 | each `money_mentioned` has positive int amount + ISO-4217 ccy ∈ {EUR, USD, CHF, GBP, RUB} | `MoneyMention` Literal + amount validator | `FinalizationError` |
| R16 | `status` ∈ `{stub_auto, stub_cross_link, stub_inbox, null}` | `StubStatus` Literal with None default | `FinalizationError` |
| R17 | body length ∈ [300, 8000] chars | `SilverDocument._body_length` | `FinalizationError` |
| R18 | body contains no forbidden self-promotion markers (`voice: gold`, `author: director`) | `SilverDocument._no_gold_self_promotion` | `FinalizationError` |
| R19 | `frontmatter.status` set ⇒ body ≤ 600 chars | `SilverDocument._stub_status_matches_shape` | `FinalizationError` |
| R20 | `target_vault_path` matches `^wiki/[a-z0-9-]+/\d{4}-\d{2}-\d{2}_[\w-]+\.md$` | path builder (§3.6) before write | `FinalizationError` |
| R21 | each `thread_continues` entry matches R20's regex OR starts with `wiki/` and ends `.md` (lenient) | `_thread_continues_paths` (proposed — see OQ3) | `FinalizationError` |

### 3.6 `target_vault_path` construction

Build order (deterministic, in `step6_finalize.build_target_path()`):

```python
def build_target_path(fm: SilverFrontmatter) -> str:
    matter = fm.primary_matter or "_inbox"
    date_stamp = fm.created.strftime("%Y-%m-%d")
    title_slug = _title_to_slug(fm.title)  # lowercase, dash, strip punctuation, cap 60 chars
    return f"wiki/{matter}/{date_stamp}_{title_slug}.md"
```

Regex for validation:

```
^wiki/[a-z0-9-]+/\d{4}-\d{2}-\d{2}_[\w-]+\.md$
```

**Collision handling:** if `target_vault_path` already exists in the vault, append `-2`, `-3`, … before `.md`. The finalize step does NOT read the vault filesystem directly; it relies on Step 7's git-harness to surface collisions and re-invoke the builder with a `suffix` hint. (Out of scope for this spec — Step 7 concern.)

### 3.7 `status` field provenance gate

`SilverFrontmatter.status` is only set when the upstream decision path was one of `stub_only` / `cross_link_only` / `skip_inbox` / `paused_cost_cap`. Opus full-synthesis outputs MUST NOT include `status`.

Cross-check enforced at the Step 6 entry point, not inside the Pydantic model (the model has no knowledge of `step_5_decision`):

```python
def finalize(signal_row: dict) -> SilverDocument:
    raw = signal_row["opus_draft_markdown"]
    fm_dict, body = _parse_frontmatter(raw)
    fm = SilverFrontmatter(**fm_dict)

    step5_decision = signal_row["step_5_decision"]
    if step5_decision == "full_synthesis" and fm.status is not None:
        raise FinalizationError(
            f"Opus emitted status='{fm.status}' on full_synthesis decision; "
            f"that field is reserved for deterministic stub writers"
        )
    if step5_decision != "full_synthesis" and fm.status is None:
        raise FinalizationError(
            f"deterministic stub writer should have set status for decision "
            f"'{step5_decision}' but status is None"
        )

    # inject telemetry from signal_queue row
    fm.triage_score = signal_row["triage_score"]
    fm.triage_confidence = signal_row["triage_confidence"]

    return SilverDocument(frontmatter=fm, body=body)
```

---

## 4. Cross-link stub file format (`wiki/<m>/_links.md`)

For each slug in the parent Silver's `related_matters`, Step 6 appends (or replaces-in-place) one stub to `wiki/<slug>/_links.md`.

### 4.1 File shape

```markdown
---
title: Cross-links inbox for <slug>
voice: silver
author: pipeline
updated: <ISO 8601 UTC of latest write>
---

# Cross-links for `<slug>`

Automated index of Silver entries in other matters that cross-reference this one. Sorted by `created` descending. Safe to read; do not edit — each row is rewritten on its source signal's re-finalize.

## Entries

- **2026-03-30T11:20:00Z** | threat | [wiki/hagenauer-rg7/2026-03-30_admin-claim.md](...) | `email:19d0ff2c87b4ffee` | Hagenauer administrator €1.2M variation claim against Brisen
- **2026-03-21T17:45:00Z** | opportunity | [wiki/ao/2026-03-21_tonbach-capital-call-commit.md](...) | `meeting:01KM83CE3MP1P7AP1C22HHG77V` | AO verbal commit €7M Apr/May/Jun tranching
```

**Each row:** `- **<created ISO>** | <vedana> | <markdown link to source_path> | \`<source_signal_id>\` | <excerpt or source title>`

### 4.2 Idempotency rule (load-bearing)

Each stub is identified by `source_signal_id` (backtick-delimited in the row). When Step 6 writes a stub, it MUST:

1. Read the existing `_links.md` (or synthesize a fresh header if absent).
2. Scan entries. If a row contains `` `<source_signal_id>` `` (exact backtick match), **REPLACE that row in place** — do NOT append a second entry. Preserves idempotency across Step 5 retries, Gold re-promotions that force Silver re-finalize, and manual ops reruns.
3. Otherwise, insert the row in created-DESC-sorted position.
4. Re-serialize the file and atomic-write (see §4.3).

**Regex for match detection:**

```
^-\s+\*\*[^|]+\*\*\s+\|\s+\w+\s+\|\s+\[[^\]]+\]\([^\)]+\)\s+\|\s+`<ESCAPED_SIGNAL_ID>`\s+\|.*$
```

with `<ESCAPED_SIGNAL_ID>` being `re.escape(source_signal_id)`.

**Performance note:** `_links.md` files are bounded by active cross-linking volume per matter. A matter with 500 cross-links still fits in a few KB — no pagination needed in Phase 1.

### 4.3 Atomic write pattern

```python
from pathlib import Path
import tempfile, os

def atomic_write(path: Path, content: str) -> None:
    """Temp file + rename. Filesystem atomic on POSIX.
    The rename guarantees readers either see the old file or the
    complete new file — never a half-written state."""
    tmp_dir = path.parent
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=tmp_dir, prefix=f".{path.name}.", suffix=".tmp",
        delete=False,
    ) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp_path = Path(f.name)
    tmp_path.replace(path)   # atomic on same filesystem
```

**Invariant:** `_links.md` is never truncated to zero bytes in a visible state. If the vault reader ever observes an empty `_links.md`, something broke.

### 4.4 Absent-file bootstrap

If `wiki/<slug>/_links.md` does not exist when Step 6 tries to write, it is created with the §4.1 header + the single stub row. `os.makedirs(parent, exist_ok=True)` on the matter directory as a safety (should already exist but not guaranteed for brand-new slugs).

---

## 5. Error matrix (Pydantic failure → state transition)

| Failure class | Trigger examples | `FinalizationError` raised? | State transition | Retry |
|---|---|:-:|---|---|
| Missing required frontmatter key | `vedana:` not in draft | ✓ | `finalize_failed` on first try, then `opus_failed` for R3 retry ladder | R3 (Opus retry) — up to 3 |
| Invalid enum value | `voice: draft`, `vedana: neutral` | ✓ | same | R3 |
| Unknown slug | `primary_matter: jibberish` | ✓ | same | R3 |
| `primary_matter ∈ related_matters` (rule R5) | cross-contamination | ✓ | same | R3 |
| `primary_matter is None` with non-empty `related_matters` (R7) | malformed null-primary draft | ✓ | same | R3 |
| Body too short (<300 chars) on full_synthesis | Opus refused to synthesize | ✓ | same | R3 |
| Body too long (>8000 chars) | Opus over-synthesized | ✓ | same | R3 |
| `target_vault_path` regex fail (R20) | title slugging produced empty / illegal chars | ✓ | same | R3 |
| `status` set on full_synthesis (§3.7) | Opus smuggled `status: stub_auto` | ✓ | same | R3 |
| `status` NOT set on stub decision (§3.7) | stub writer bug upstream | ✓ | `finalize_failed` terminal; route to inbox; log as pipeline-bug | no retry (bug, not draft quality) |
| Forbidden body marker (R18) | body contains `voice: gold` | ✓ | same | R3 |
| Cross-link write I/O error | disk full, permission denied | ✓ | state stays `finalize_running`; retry once with 500ms backoff | 1 retry; if still failing → `finalize_failed`, ERROR log; signal returns to claimable pool on next tick |
| Cross-link write atomicity failure (orphaned tmp) | process killed mid-rename | silent | next tick scans tmp files, removes orphans age >5min | n/a |
| All 3 Opus retries exhausted | Opus persistently produces malformed drafts | — | `finalize_failed` terminal → route to `wiki/_inbox/` with raw `opus_draft_markdown` attached | no further retry |

**State-transition invariant:** `finalize_failed` is the ONLY terminal state reachable from Step 6 errors. `opus_failed` is a transient-retry state handled by the Step 5 R3 ladder. `finalize_running` is the claim state; only the claim owner can transition out.

---

## 6. Logging spec

All logs written to `kbl_log` table per existing convention. No stdout.

| Event | Level | Component | Message format | Extra fields |
|---|---|---|---|---|
| Pydantic validation failure (per failed field) | `WARN` | `finalize` | `f"{field}: {reason}"` e.g., `"vedana: input_value='neutral' not in Vedana enum"` | `signal_id`, `step_5_decision`, `failure_count` (1, 2, 3) |
| `status` provenance gate violation (§3.7) | `ERROR` | `finalize` | `f"status provenance mismatch: decision={step5_decision}, status={status}"` | `signal_id`, `step_5_decision` |
| Cross-link write failure (IO) | `ERROR` | `finalize` | `f"cross-link write failed: {path}: {errno_reason}"` | `signal_id`, `source_signal_id`, `target_slug`, `retry_count` (0 or 1) |
| Cross-link orphaned tmp cleanup | `INFO` | `finalize` | `f"cleaned orphan tmp: {path} age={age_seconds}s"` | `signal_id=null` |
| `finalize_failed` terminal (after 3 Opus retries) | `ERROR` | `finalize` | `f"terminal finalize failure after {n} Opus retries; routed to inbox"` | `signal_id`, `target_vault_path=null`, `inbox_path` |
| Success | no log | — | — | — |

**Rule:** one row per distinct failed field. If Pydantic raises `ValidationError` with 3 field errors, 3 WARN rows are emitted, one per field, same `signal_id` + incrementing `validation_error_idx` (0, 1, 2) for joinability.

---

## 7. Open questions for AI Head

1. **OQ1 — `sources` vs `source_id` naming.** Task dispatch (2026-04-19) lists `sources` as a frontmatter key. Step 5 prompt (all 7 worked examples + invariants summary at line 179) uses singular `source_id`. Opus has been trained on singular in every example. **Recommend:** keep `source_id` singular; if plural is needed later (e.g., multi-source consolidation per Ex dispatch option 7), introduce `source_ids: list[str] = []` as a NEW optional field and retire `source_id` at a future Step 5 re-authoring. For this spec I use `source_id`. AI Head confirm.

2. **OQ2 — `title` length: 80 or 160 chars?** Step 5 prompt §1.2 says "under 80 chars, no trailing period." But Ex 6's worked-example title is 91 chars ("AO advisor signals Jun/Jul/Aug split preference — possible unwind of Tonbach commit"). Either relax the Step 5 guidance to 160 to match real outputs, or tighten this validator to 80 and force Opus to compress. **Recommend:** relax to 160 — titles with money figures and cross-matter hints legitimately run longer than 80 chars. I've specified 160 in R12. AI Head confirm.

3. **OQ3 — `thread_continues` path validation strictness.** Full R20 regex validation on `thread_continues` entries would reject paths with unusual characters that existed pre-v9. Lenient alternative: just `^wiki/.*\.md$`. **Recommend lenient** for thread_continues only — these are historical vault paths, not new writes; enforce tight regex only on `target_vault_path` (new write). Specified in R21. AI Head confirm.

4. **OQ4 — `money_mentioned` format: structured vs string.** Step 5 worked examples emit strings like `[3000 GBP]`, `[1200000 EUR, 600000 EUR]`. This spec parses into a `MoneyMention` model with `amount: int`, `currency: Literal`. That means Step 6 must do the parse — Opus emits strings, validator normalizes. **Recommend:** keep Opus emitting strings (prompt stability), add a string→MoneyMention parser in Step 6. Alternative is to re-author Step 5 prompt to emit structured JSON, but that invalidates prompt-cache and is expensive. Parser for Step 6 is ~30 lines. I'll note this as an implementation item for B1 — the spec shows the target model, B1 owns the parser. AI Head confirm direction.

5. **OQ5 — `status` setting on cross_link_only decisions.** Step 5 spec §1 says `cross_link_only` results in a "deterministic cross-link stub, Step 5 NOT called" — unclear if this stub writer sets `status: stub_cross_link` or shares `status: stub_auto`. **Recommend:** three distinct values (`stub_auto`, `stub_cross_link`, `stub_inbox`) per §2.2 so the Director can distinguish the three stub provenances from frontmatter alone. Specified. AI Head confirm.

6. **OQ6 — Currency enum completeness.** I've included `{EUR, USD, CHF, GBP, RUB}` in `MoneyMention.currency`. RUB is present because AO deals are Russian-linked. Missing candidates: `PLN` (Cupial is Polish-linked — Polish money amounts could appear), `AED` (Wertheimer's UAE angle), `JPY` (Minor Hotels is Thai but could reference Japan). **Recommend:** ship with `{EUR, USD, CHF, GBP, RUB}` as the canonical currencies. Add others when a concrete signal surfaces the need (low cost — one-line enum extension + Pydantic cache invalidation; validators have no state). AI Head confirm.

7. **OQ7 — `null` vs `None` for `primary_matter`.** YAML supports `null` as a literal; Pydantic parses both `None` and the string `"null"` → None by default if the field is `Optional`. Worked examples 1, 4, 6 all emit `primary_matter: <slug>`. Worked example 7 is routine with `primary_matter: mo-vie-am`. Need confirmation: can `primary_matter: null` appear in production, and if so, what's the valid `related_matters` state? I have R7 enforcing null-primary ⇒ empty-related. AI Head confirm.

8. **OQ8 — Body `⚠ CONTRADICTION:` pattern validation.** Step 5 Ex 6 uses the marker as a body-level annotation. Should Step 6 validate its format (exact regex `^⚠ CONTRADICTION: .+wiki/.+\.md.+$`), count occurrences, or leave freeform? **Recommend leave freeform** — over-constraining Opus on an already-rare output shape creates more false rejections than true-catch events. The marker's job is to flag to Director, not to be machine-parsed. AI Head confirm.

---

## 8. CHANDA pre-push self-check

| Test | Assessment |
|---|---|
| **Q1 Loop Test** | Pure spec authoring. No touch on Leg 1 (Gold reading — upstream in Step 5 prompt), no touch on Leg 2 (ledger write — upstream in Director actions + Step 1), no touch on Leg 3 (Step 1 integration). Spec targets Step 6 `finalize`, which sits on the output side of the loop (Silver → vault), downstream of where loop reads happen. **Pass.** |
| **Q2 Wish Test** | Serves wish (synthesis → validated Silver → Director review → promotion). Tighter schema = fewer malformed Silver drafts escaping to vault = Director's trust in the loop survives. Engineering convenience is co-satisfied (B1 ships Step 6 in one pass instead of clarifying as they go). **Pass.** |
| **Inv 1** (Gold-read-before-Silver-compile) | Not in scope of Step 6. Step 5 handles Leg 1 mandate. Step 6 consumes Opus output, doesn't re-read Gold. |
| **Inv 3** (Step 1 reads hot.md + ledger every run) | Not in scope. Same argument as Inv 1. |
| **Inv 4** (author: director untouched by agents) | **Structurally enforced** by `Author = Literal["pipeline"]`. Step 6 cannot write `author: director`; validator rejects any draft that does. Complete coverage via Pydantic at R1 + R18 (body marker). |
| **Inv 5** (every wiki file has frontmatter) | **Structurally enforced** by `SilverDocument(frontmatter=..., body=...)` — no path to write a body without frontmatter through this validator. |
| **Inv 6** (cross-link never skipped) | Structurally enforced: `related_matters` non-empty + `step_5_decision='full_synthesis'` ⇒ Step 6 writes cross-link stubs per §4. Skip would require a code bug, not a spec loophole. |
| **Inv 7** (ayoniso alerts never override) | Out of scope — ayoniso is a Step 1 concern. Step 6 neither emits nor consumes ayoniso signals. |
| **Inv 8** (Silver→Gold by Director edit only) | **Structurally enforced** by `Voice = Literal["silver"]`. Step 6 cannot auto-promote. R18 catches body-smuggled `voice: gold`. Complete. |
| **Inv 9** (Mac Mini single writer) | Out of scope — Step 7 harness concern. |
| **Inv 10** (prompts don't self-modify) | Step 6 has no prompt. Spec is a stable document; implementation changes go through B1 PRs under normal review, not runtime mutation. Vacuously pass. |
| **Invariant-structural-enforcement summary** | Invs 4, 5, 6, 8 are all enforced STRUCTURALLY at the Pydantic type level — a draft that violates them cannot be finalized, period. This is the design win of making Step 6 deterministic post-REDIRECT: static types + validators guarantee the invariants at compile-adjacent cost, not at runtime argument. |

**Overall:** GREEN self-check. No Leg touched, no invariant weakened, four invariants structurally strengthened.

---

*Drafted 2026-04-19 by B3 for AI Head + B1 assembly. Direct-to-main per option A. B1: implement `kbl/steps/step6_finalize.py` + `kbl/schemas/silver.py` against this spec; open questions OQ1-OQ8 first if any block implementation. B2 review optional post-commit.*
