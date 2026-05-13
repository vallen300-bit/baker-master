---
brief_id: DEADLINE_FEEDBACK_LOOP_1
brief_version: 1.0
author: AH1
target: b3
dispatched: 2026-05-13
trigger_class: TIER_B_DB_MIGRATION_+_DASHBOARD_UI_+_ENDPOINT
mandatory_2nd_pass: true
security_review_required: true
effort_estimate: ~4h
complexity: Medium
predecessor: DEADLINE_SIGNAL_HYGIENE_1 (PR #202 merged 6c31b05; Scope C 352/352 applied 2026-05-13 commit 2ed9896)
followup: SIGNAL_CLASSIFIER_TIER2_1 (NOT this brief — phase 3 Gemini classifier, gated on 2+ weeks of click corpus from THIS brief)
ratified_spec: _ops/ideas/2026-05-13-smart-signal-classification.md (Director-ratified Q1-Q4 + Gemini swap 2026-05-13)
---

# BRIEF: DEADLINE_FEEDBACK_LOOP_1 — dashboard click-feedback capture for phase-3 classifier training corpus

## Context

Phase 1 (DEADLINE_SIGNAL_HYGIENE_1) closed the false-positive hole at the classifier (threshold 1→3 + noise blacklist + matter-closed filter). It produces NO training signal for phase 3 — the Gemini classifier upgrade Director ratified 2026-05-13 in `_ops/ideas/2026-05-13-smart-signal-classification.md`.

Phase 3 needs labeled ground truth: for each surfaced deadline, did Director find it useful, noisy, mis-attributed to a matter, or wrongly extracted as a deadline at all? Today the dashboard offers only `dismiss` (mute) and `complete` (mark done) — binary signals, no granular labels, no audit trail of "this was wrong-matter; should have been X."

This brief adds the labeled-feedback surface and the persistence layer for the click corpus. Effort ~4h. Scope is deliberately bounded — no phase 3 classifier work in this brief (that ships separately, gated on 2+ weeks of clicks captured here).

**Director-ratified anchor:** *"Rest is okay. All ratified."* (Director, 2026-05-13, on the 4-phase sequencing + Gemini Flash/Pro stack swap).

## Estimated time: ~4h
## Complexity: Medium
## Prerequisites
- `BAKER_VAULT_PATH` set (existing)
- Predecessor DEADLINE_SIGNAL_HYGIENE_1 merged (✅ 6c31b05, Scope C applied 2ed9896)
- slugs.yml v23 live (✅ 7da63ec — `slug_registry.normalize()` resolves 5 new raw labels; needed for `wrong-matter` corrected_slug validation)

---

## Scope — single-shot brief, 4 parts shipping together

| Part | What | Files |
|---|---|---|
| 1. Migration | New `deadline_feedback` table | `migrations/20260513b_deadline_feedback.sql` |
| 2. Backend | 1 new endpoint + augment 2 existing + 1 thin GET for slug list | `outputs/dashboard.py`, `models/deadline_feedback.py` (NEW) |
| 3. Frontend | 2 new buttons on deadline-card triage bar + safe DOM-constructed dropdown for `wrong-matter` slug correction | `outputs/static/app.js`, `outputs/static/index.html` |
| 4. Tests | pytest coverage on endpoint + write paths | `tests/test_deadline_feedback.py` (NEW) |

---

## Part 1 — Migration: `deadline_feedback` table

### Problem
No persistence layer for granular Director feedback. Existing `deadlines.status` flips (`active` → `dismissed`/`completed`) overwrite state; they don't preserve a labeled corpus of "click X happened at time T against deadline Y with reason Z."

### Schema verification (DB schema verified — Lesson #3b)

`deadlines` table columns (verified via `models/deadlines.py:76-106` — CREATE + ALTER TABLE bootstrap):
```
id, description, due_date, source_type, source_id, source_snippet,
confidence, priority, status, dismissed_reason, last_reminded_at,
reminder_stage, created_at, updated_at,
severity, assigned_to, assigned_by, matter_slug, obligation_type,
is_critical, critical_flagged_at,
recurrence, recurrence_anchor_date, recurrence_count, parent_deadline_id
```

No existing `deadline_feedback` table. Verified clean grep: `grep -rn "deadline_feedback" --include="*.py"` returns 0 hits across `kbl/`, `orchestrator/`, `models/`, `outputs/`, `triggers/`. Migration creates fresh — no bootstrap collision (Migration-vs-bootstrap drift trap from `tasks/lessons.md` — checked, clear).

### Implementation

`migrations/20260513b_deadline_feedback.sql`:

```sql
-- DEADLINE_FEEDBACK_LOOP_1: labeled click-feedback corpus for phase-3 classifier training.
--
-- Each row is one Director click on a surfaced deadline. Rows accumulate as the
-- ground-truth corpus for SIGNAL_CLASSIFIER_TIER2_1 (phase 3, dispatched after
-- 2+ weeks of clicks land here).
--
-- feedback_type values:
--   'confirm'        — Director marked the deadline as done (Mark Done click)
--   'mute'           — Director dismissed the deadline as noise (Dismiss click)
--   'wrong_matter'   — Director flagged matter_slug as incorrect; corrected_matter_slug captures the right one
--   'wrong_deadline' — Director flagged the row as "not actually a deadline" (extraction error)
--
-- The deadline row's status flip (dismiss/complete) happens in the same request
-- — feedback rows are write-only and additive. Deleting a deadline does NOT
-- cascade-delete its feedback rows (history-preserving by design; phase 3
-- reads even orphaned feedback to learn from past mistakes).

CREATE TABLE IF NOT EXISTS deadline_feedback (
    id                       SERIAL PRIMARY KEY,
    deadline_id              INTEGER NOT NULL,
    feedback_type            VARCHAR(20) NOT NULL,
    original_matter_slug     TEXT,           -- deadline.matter_slug at click time (may be NULL)
    corrected_matter_slug    TEXT,           -- only for feedback_type='wrong_matter'; validated against slug_registry
    original_description     TEXT NOT NULL,  -- snapshot of deadline.description at click time
    original_source_type     VARCHAR(50),    -- snapshot of deadline.source_type
    director_note            TEXT,           -- optional free-text (NULL by default; reserved for future inline notes)
    clicked_at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT deadline_feedback_type_check
        CHECK (feedback_type IN ('confirm', 'mute', 'wrong_matter', 'wrong_deadline'))
);

CREATE INDEX IF NOT EXISTS idx_deadline_feedback_clicked_at
    ON deadline_feedback (clicked_at DESC);
CREATE INDEX IF NOT EXISTS idx_deadline_feedback_deadline_id
    ON deadline_feedback (deadline_id);
CREATE INDEX IF NOT EXISTS idx_deadline_feedback_type
    ON deadline_feedback (feedback_type);
```

No `DROP TABLE` rollback section — feedback table is additive, low-risk, no foreign-key dependencies.

### Verification
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'deadline_feedback'
ORDER BY ordinal_position;
-- Expect: 9 rows (id, deadline_id, feedback_type, original_matter_slug,
--                 corrected_matter_slug, original_description,
--                 original_source_type, director_note, clicked_at)
```

---

## Part 2 — Backend: 1 new endpoint + augment 2 existing + slug list GET

### Problem
- No endpoint exists for `wrong_matter` / `wrong_deadline` feedback (these are NEW verbs).
- Existing `/api/deadlines/{id}/dismiss` and `/api/deadlines/{id}/complete` don't write to `deadline_feedback` — the corpus loses 100% of legacy-button clicks. Backward-compat fix: those endpoints write a corpus row too.
- Frontend needs the active-slug list for the wrong-matter dropdown → thin new GET endpoint.

### Pre-check: no endpoint shadow (Lesson #11)
```bash
grep -n "/api/deadlines/.*feedback\|/api/feedback\|/api/slug-registry" outputs/dashboard.py
```
Verified: 0 hits. New routes don't shadow existing patterns.

### Files modified

#### NEW: `models/deadline_feedback.py`

```python
"""DEADLINE_FEEDBACK_LOOP_1: persistence layer for Director-click corpus.

Single-purpose module — write-only from the dashboard, read-only from phase-3
classifier training jobs (SIGNAL_CLASSIFIER_TIER2_1, future).
"""
from __future__ import annotations

import logging
from typing import Optional

import psycopg2.extras

from models.deadlines import get_conn, put_conn

logger = logging.getLogger(__name__)

VALID_FEEDBACK_TYPES = frozenset({"confirm", "mute", "wrong_matter", "wrong_deadline"})


def insert_feedback(
    deadline_id: int,
    feedback_type: str,
    original_matter_slug: Optional[str],
    corrected_matter_slug: Optional[str],
    original_description: str,
    original_source_type: Optional[str],
    director_note: Optional[str] = None,
) -> Optional[int]:
    """Insert one feedback row. Returns the new id or None on failure.

    Fault-tolerant: caller does NOT see exceptions; failures log + return None.
    Callers are status-flip endpoints (dismiss/complete) where the primary
    write (status update) must succeed even if feedback logging is degraded.
    """
    if feedback_type not in VALID_FEEDBACK_TYPES:
        logger.error(f"deadline_feedback: invalid type {feedback_type!r}")
        return None

    conn = get_conn()
    if not conn:
        logger.warning("deadline_feedback: no DB connection")
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO deadline_feedback
                (deadline_id, feedback_type, original_matter_slug,
                 corrected_matter_slug, original_description,
                 original_source_type, director_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (deadline_id, feedback_type, original_matter_slug,
             corrected_matter_slug, original_description,
             original_source_type, director_note),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        conn.rollback()  # CRITICAL — Python backend rule
        logger.error(f"deadline_feedback insert failed: {e}")
        return None
    finally:
        put_conn(conn)


def get_recent_feedback(limit: int = 100) -> list:
    """Read recent feedback rows (DESC by clicked_at). LIMIT enforced (Python backend rule)."""
    conn = get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, deadline_id, feedback_type, original_matter_slug,
                   corrected_matter_slug, original_description,
                   original_source_type, director_note, clicked_at
            FROM deadline_feedback
            ORDER BY clicked_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        return list(rows)
    except Exception as e:
        conn.rollback()
        logger.error(f"deadline_feedback read failed: {e}")
        return []
    finally:
        put_conn(conn)
```

#### MODIFY: `outputs/dashboard.py`

**A.** Add new feedback endpoint AFTER line 7213 (last existing `/api/deadlines/*` route — the PATCH endpoint):

```python
@app.post("/api/deadlines/{deadline_id}/feedback", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def deadline_feedback_api(deadline_id: int, request: Request):
    """DEADLINE_FEEDBACK_LOOP_1: capture labeled Director click for phase-3 training corpus.

    Body shape:
        {
            "feedback_type": "confirm" | "mute" | "wrong_matter" | "wrong_deadline",
            "corrected_matter_slug": "hagenauer-rg7"  # optional, only for wrong_matter
        }

    Side effects:
        - confirm:        status -> completed   (mirrors /complete endpoint)
        - mute:           status -> dismissed   (mirrors /dismiss endpoint)
        - wrong_matter:   no status flip; matter_slug NOT mutated on deadlines table
                          (the row stays visible — Director is correcting the
                          classifier's label, not removing the row from view)
        - wrong_deadline: status -> dismissed with reason 'wrong_deadline'
                          (this isn't a deadline — remove from view but tag the
                          dismiss reason distinctly so phase 3 sees it)
    """
    try:
        payload = await request.json()
        feedback_type = payload.get("feedback_type")
        corrected_slug_raw = payload.get("corrected_matter_slug")

        from models.deadlines import get_deadline_by_id, update_deadline
        from models.deadline_feedback import insert_feedback, VALID_FEEDBACK_TYPES
        from kbl.slug_registry import normalize as slug_normalize

        if feedback_type not in VALID_FEEDBACK_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"feedback_type must be one of {sorted(VALID_FEEDBACK_TYPES)}",
            )

        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")

        # Validate corrected slug for wrong_matter (canonical or known alias).
        # Hallucinated slugs become None; the click still records but with NULL.
        corrected_slug = None
        if feedback_type == "wrong_matter" and corrected_slug_raw:
            corrected_slug = slug_normalize(corrected_slug_raw)
            if corrected_slug is None:
                logger.warning(
                    f"deadline_feedback: wrong_matter received unknown slug "
                    f"{corrected_slug_raw!r} on deadline {deadline_id} — corpus row will store NULL"
                )

        # Snapshot fields off the deadline row at click time
        fid = insert_feedback(
            deadline_id=deadline_id,
            feedback_type=feedback_type,
            original_matter_slug=dl.get("matter_slug"),
            corrected_matter_slug=corrected_slug,
            original_description=dl.get("description") or "",
            original_source_type=dl.get("source_type"),
            director_note=None,
        )

        # Side-effect status flip (verb-specific)
        if feedback_type == "confirm":
            update_deadline(deadline_id, status="completed",
                            dismissed_reason="Completed via dashboard feedback")
        elif feedback_type == "mute":
            update_deadline(deadline_id, status="dismissed",
                            dismissed_reason="Muted via dashboard feedback")
        elif feedback_type == "wrong_deadline":
            update_deadline(deadline_id, status="dismissed",
                            dismissed_reason="wrong_deadline")
        # wrong_matter: no status change (deadline stays visible; only label corrected)

        return {"status": "ok", "feedback_id": fid, "deadline_id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/feedback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**B.** Add thin slug-registry GET endpoint (placement: near other registry-style routes; if none exist nearby, place adjacent to the new feedback endpoint above):

```python
@app.get("/api/slug-registry", tags=["registry"], dependencies=[Depends(verify_api_key)])
async def slug_registry_api(status: str = Query("active", regex="^(active|all)$")):
    """DEADLINE_FEEDBACK_LOOP_1: serve canonical slug list for wrong-matter dropdown."""
    try:
        from kbl.slug_registry import active_slugs, canonical_slugs
        slugs = sorted(active_slugs() if status == "active" else canonical_slugs())
        return {"slugs": slugs, "count": len(slugs), "status_filter": status}
    except Exception as e:
        logger.error(f"/api/slug-registry failed: {e}")
        return {"slugs": [], "count": 0, "error": str(e)}
```

**C.** AUGMENT existing `/dismiss` endpoint (current lines 6853-6867). Replace block:

```python
# OLD line 6853-6867
@app.post("/api/deadlines/{deadline_id}/dismiss", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def dismiss_deadline_api(deadline_id: int):
    """Dismiss a deadline."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        update_deadline(deadline_id, status="dismissed", dismissed_reason="Dismissed via dashboard")
        return {"status": "dismissed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/dismiss failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# NEW — augmented to write 'mute' feedback row for the corpus
@app.post("/api/deadlines/{deadline_id}/dismiss", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def dismiss_deadline_api(deadline_id: int):
    """Dismiss a deadline. Also writes a 'mute' feedback row for the training corpus."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        from models.deadline_feedback import insert_feedback
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        # DEADLINE_FEEDBACK_LOOP_1: corpus row first; failure here must NOT block the dismiss
        insert_feedback(
            deadline_id=deadline_id,
            feedback_type="mute",
            original_matter_slug=dl.get("matter_slug"),
            corrected_matter_slug=None,
            original_description=dl.get("description") or "",
            original_source_type=dl.get("source_type"),
            director_note=None,
        )
        update_deadline(deadline_id, status="dismissed", dismissed_reason="Dismissed via dashboard")
        return {"status": "dismissed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/dismiss failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**D.** AUGMENT existing `/complete` endpoint (current lines 6870-6884). Same pattern — write a `confirm` feedback row before the status flip:

```python
# NEW — augmented to write 'confirm' feedback row for the corpus
@app.post("/api/deadlines/{deadline_id}/complete", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def complete_deadline_api(deadline_id: int):
    """Mark a deadline as completed. Also writes a 'confirm' feedback row for the corpus."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        from models.deadline_feedback import insert_feedback
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        # DEADLINE_FEEDBACK_LOOP_1: corpus row first; failure here must NOT block the complete
        insert_feedback(
            deadline_id=deadline_id,
            feedback_type="confirm",
            original_matter_slug=dl.get("matter_slug"),
            corrected_matter_slug=None,
            original_description=dl.get("description") or "",
            original_source_type=dl.get("source_type"),
            director_note=None,
        )
        update_deadline(deadline_id, status="completed", dismissed_reason="Completed via dashboard")
        return {"status": "completed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/complete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**E.** Verify `Request` is imported. Check the top of `outputs/dashboard.py` — grep for `from fastapi import` to confirm `Request` is already in the import list. If not, add to existing FastAPI import (Lesson on missing imports).

---

## Part 3 — Frontend: 2 new triage buttons + matter-correction dropdown (XSS-safe)

### Problem
The deadline-card triage bar today (`_landingTriageBar` at `outputs/static/app.js:2955`) shows: Draft Email / Draft WA / Analyze / Summarize / Dossier / ClickUp / Delegate / Dismiss / Ask Baker / Mark Done. Need 2 new pills: **Wrong Matter** and **Not a Deadline**, plus an inline dropdown for `wrong-matter` to capture the corrected slug.

### Verified file:line anchors

- `outputs/static/app.js:2955` — `_landingTriageBar(aid, title, body, cardType, itemId)` definition
- `outputs/static/app.js:2977-2978` — `if (cardType === 'deadline')` branch — Mark Done button only
- `outputs/static/app.js:3078` — `_landingDismiss(cardType, itemId, btn)` (existing — used by ✕ Dismiss button, now also writes a 'mute' feedback row via the augmented backend endpoint)
- `outputs/static/app.js:3101` — `_landingMarkDone(deadlineId, btn)` (existing — used by ✓ Mark Done button, now also writes a 'confirm' feedback row via the augmented backend endpoint)
- `outputs/static/index.html:575` — `<script src="/static/app.js?v=112">` → bump to `?v=113` (iOS PWA cache bust — Lesson #4 + frontend rule)

Mobile path: `outputs/static/mobile.html` + `mobile.js` do NOT render deadlines (verified — `grep -in deadline mobile.*` returns 0 hits). PWA on iPhone uses `index.html` + `app.js` via responsive CSS. **No mobile.js changes needed.**

### XSS discipline (Lesson + security hook anchor)

The wrong-matter dropdown must NOT use `innerHTML` to inject user-or-API-derived strings. Build the dropdown with `document.createElement` + `textContent` + `appendChild`. The `esc()` helper used elsewhere in the file is fine for static `_landingTriageBar` markup (its inputs are constant ASCII button labels), but it is NOT the right tool for dynamic option-list construction.

### Implementation

#### A. Add 2 new buttons to `_landingTriageBar` deadline branch

`outputs/static/app.js:2977-2978` — replace the existing 2-line `if (cardType === 'deadline')` block:

```javascript
// OLD
} else if (cardType === 'deadline') {
    html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_landingMarkDone(' + itemId + ',this)">✓ Mark Done</button>';
} else if (cardType === 'meeting') {

// NEW
} else if (cardType === 'deadline') {
    html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_landingMarkDone(' + itemId + ',this)">✓ Mark Done</button>';
    // DEADLINE_FEEDBACK_LOOP_1: 2 new feedback verbs for phase-3 training corpus
    html += '<button class="triage-pill" onclick="event.stopPropagation();_deadlineWrongMatter(' + itemId + ',this)">⚠ Wrong Matter</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_deadlineWrongDeadline(' + itemId + ',this)">✗ Not a Deadline</button>';
} else if (cardType === 'meeting') {
```

The button labels are static ASCII; `_landingTriageBar`'s existing string-concat pattern stays consistent with the surrounding code. No user-derived data flows through these strings.

#### B. Add 4 new JS functions after `_landingMarkDone` at line 3107 (XSS-safe DOM construction)

```javascript
// DEADLINE_FEEDBACK_LOOP_1: Wrong Matter — show inline matter-slug dropdown.
// Uses document.createElement + textContent + appendChild (no innerHTML on
// dynamic content) per XSS discipline. Slug values come from /api/slug-registry
// — they are canonical strings from a YAML registry, NOT user input — but the
// DOM-construction pattern is the correct default regardless of current safety.
function _deadlineWrongMatter(deadlineId, btn) {
    var card = btn.closest('.card');
    if (!card) return;
    var dropId = 'wrong-matter-drop-' + deadlineId;
    var existing = document.getElementById(dropId);
    if (existing) {
        existing.style.display = existing.style.display === 'none' ? 'flex' : 'none';
        return;
    }
    _ensureActiveSlugsLoaded().then(function(slugs) {
        var row = document.createElement('div');
        row.id = dropId;
        row.style.display = 'flex';
        row.style.gap = '6px';
        row.style.padding = '8px 16px 12px';
        row.style.alignItems = 'center';
        row.style.flexWrap = 'wrap';

        var label = document.createElement('span');
        label.style.fontSize = '12px';
        label.style.color = 'var(--text2)';
        label.textContent = 'Correct matter:';
        row.appendChild(label);

        var select = document.createElement('select');
        select.id = 'wrong-matter-select-' + deadlineId;
        select.style.padding = '4px 8px';
        select.style.border = '1px solid var(--border)';
        select.style.borderRadius = '6px';
        select.style.fontSize = '12px';
        select.style.fontFamily = 'var(--font)';

        var placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '— select —';
        select.appendChild(placeholder);

        for (var i = 0; i < slugs.length; i++) {
            var opt = document.createElement('option');
            opt.value = slugs[i];           // attribute setter — safe
            opt.textContent = slugs[i];     // textContent — XSS-safe
            select.appendChild(opt);
        }
        row.appendChild(select);

        var submit = document.createElement('button');
        submit.className = 'triage-pill';
        submit.style.background = 'var(--blue)';
        submit.style.color = '#fff';
        submit.style.borderColor = 'var(--blue)';
        submit.textContent = 'Submit';
        submit.addEventListener('click', function(ev) {
            ev.stopPropagation();
            _deadlineSubmitWrongMatter(deadlineId, submit);
        });
        row.appendChild(submit);

        var detail = card.querySelector('.triage-detail');
        if (detail) detail.appendChild(row);
    });
}

// DEADLINE_FEEDBACK_LOOP_1: Submit wrong-matter correction
function _deadlineSubmitWrongMatter(deadlineId, btn) {
    var sel = document.getElementById('wrong-matter-select-' + deadlineId);
    var correctedSlug = sel ? sel.value : '';
    if (!correctedSlug) {
        _showToast('Pick a matter first');
        return;
    }
    var card = btn.closest('.card');
    bakerFetch('/api/deadlines/' + deadlineId + '/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({feedback_type: 'wrong_matter', corrected_matter_slug: correctedSlug})
    }).then(function() {
        // Don't remove the card — wrong_matter is a label correction, deadline stays visible
        var drop = document.getElementById('wrong-matter-drop-' + deadlineId);
        if (drop) drop.remove();
        _showToast('Matter corrected → ' + correctedSlug);
    });
}

// DEADLINE_FEEDBACK_LOOP_1: Not a Deadline — flag extraction error + dismiss
function _deadlineWrongDeadline(deadlineId, btn) {
    var card = btn.closest('.card');
    bakerFetch('/api/deadlines/' + deadlineId + '/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({feedback_type: 'wrong_deadline'})
    }).then(function() {
        if (card) { card.style.opacity = '0.3'; setTimeout(function() { card.remove(); }, 500); }
        _showToast('Flagged: not a deadline');
    });
}

// DEADLINE_FEEDBACK_LOOP_1: Cache active slugs on first dropdown open
function _ensureActiveSlugsLoaded() {
    if (window._activeSlugs && window._activeSlugs.length > 0) {
        return Promise.resolve(window._activeSlugs);
    }
    return bakerFetch('/api/slug-registry?status=active', {method: 'GET'})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            window._activeSlugs = (data.slugs || []).sort();
            return window._activeSlugs;
        })
        .catch(function() {
            window._activeSlugs = [];
            return [];
        });
}
```

#### C. Cache bust bump

`outputs/static/index.html:575` — `<script src="/static/app.js?v=112">` → `<script src="/static/app.js?v=113">`.

If `style.css` is also modified (it shouldn't be — pills reuse existing `.triage-pill` class), bump `?v=74` accordingly. Verify after edit: `grep -n "app.js?v=" outputs/static/index.html`.

---

## Part 4 — Tests

### NEW: `tests/test_deadline_feedback.py`

```python
"""DEADLINE_FEEDBACK_LOOP_1: pytest coverage for the feedback endpoint + persistence layer.

Skip-pattern: tests that require TEST_DATABASE_URL (live PG) are gated with
@pytest.mark.skipif. Pure-validation tests run unconditionally.
"""
import os
import pytest


def test_valid_feedback_types_whitelist():
    from models.deadline_feedback import VALID_FEEDBACK_TYPES
    assert VALID_FEEDBACK_TYPES == frozenset({"confirm", "mute", "wrong_matter", "wrong_deadline"})


def test_insert_feedback_rejects_invalid_type(monkeypatch):
    """Invalid feedback_type returns None without touching DB."""
    from models.deadline_feedback import insert_feedback
    from models import deadlines as deadlines_mod
    call_count = {"n": 0}
    def fake_get_conn():
        call_count["n"] += 1
        return None
    monkeypatch.setattr(deadlines_mod, "get_conn", fake_get_conn)
    result = insert_feedback(
        deadline_id=1, feedback_type="invalid_verb",
        original_matter_slug=None, corrected_matter_slug=None,
        original_description="test", original_source_type="test",
    )
    assert result is None
    assert call_count["n"] == 0


def test_unknown_slug_normalize_returns_none():
    """Hallucinated slugs must normalize to None — gate for the wrong_matter validation."""
    from kbl.slug_registry import normalize
    assert normalize("totally-fake-slug-9999") is None


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_insert_feedback_round_trip():
    """Live-PG: insert + read back."""
    from models.deadline_feedback import insert_feedback, get_recent_feedback
    fid = insert_feedback(
        deadline_id=99999, feedback_type="mute",
        original_matter_slug="hagenauer-rg7", corrected_matter_slug=None,
        original_description="test fixture", original_source_type="test",
    )
    assert fid is not None and isinstance(fid, int)
    rows = get_recent_feedback(limit=10)
    assert any(r["id"] == fid for r in rows)
    found = next(r for r in rows if r["id"] == fid)
    assert found["feedback_type"] == "mute"
    assert found["original_matter_slug"] == "hagenauer-rg7"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_endpoint_writes_corpus_row():
    """End-to-end via FastAPI TestClient: POST /api/deadlines/{id}/feedback writes row."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from datetime import datetime

    client = TestClient(app)
    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")

    did = insert_deadline(
        description="test feedback fixture",
        due_date=datetime.now(),
        source_type="test", source_id="test-feedback-1",
        confidence="high",
    )
    assert did is not None

    r = client.post(
        f"/api/deadlines/{did}/feedback",
        headers={"X-Baker-Key": api_key, "Content-Type": "application/json"},
        json={"feedback_type": "wrong_matter", "corrected_matter_slug": "hagenauer-rg7"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["feedback_id"] is not None


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_endpoint_rejects_unknown_feedback_type():
    """Invalid feedback_type returns 400 with whitelist hint."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from datetime import datetime

    client = TestClient(app)
    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")

    did = insert_deadline(
        description="reject-test fixture", due_date=datetime.now(),
        source_type="test", source_id="test-feedback-reject", confidence="high",
    )
    r = client.post(
        f"/api/deadlines/{did}/feedback",
        headers={"X-Baker-Key": api_key, "Content-Type": "application/json"},
        json={"feedback_type": "nonsense"},
    )
    assert r.status_code == 400


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs live PG")
def test_dismiss_endpoint_writes_mute_corpus_row():
    """Backward-compat: existing /dismiss endpoint also writes a 'mute' feedback row."""
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    from models.deadlines import insert_deadline
    from models.deadline_feedback import get_recent_feedback
    from datetime import datetime

    client = TestClient(app)
    api_key = os.getenv("BAKER_API_KEY", "")
    if not api_key:
        pytest.skip("needs BAKER_API_KEY")

    did = insert_deadline(
        description="dismiss-compat fixture", due_date=datetime.now(),
        source_type="test", source_id="test-dismiss-compat", confidence="high",
    )
    r = client.post(f"/api/deadlines/{did}/dismiss", headers={"X-Baker-Key": api_key})
    assert r.status_code == 200
    rows = get_recent_feedback(limit=20)
    assert any(rw["deadline_id"] == did and rw["feedback_type"] == "mute" for rw in rows)
```

### Ship gate

```bash
pytest tests/test_deadline_feedback.py -v
bash scripts/check_singletons.sh
python3 -c "import py_compile; py_compile.compile('models/deadline_feedback.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
```

All must produce literal green output. **No "pass by inspection" — REQUEST_CHANGES if claimed** (Lesson per `tasks/lessons.md` + CLAUDE.md hard rule).

---

## Files Modified

- `migrations/20260513b_deadline_feedback.sql` — NEW: `deadline_feedback` table + 3 indexes
- `models/deadline_feedback.py` — NEW: `insert_feedback()` + `get_recent_feedback()`
- `outputs/dashboard.py` — ADD `/api/deadlines/{id}/feedback` (POST) + `/api/slug-registry` (GET); AUGMENT `/dismiss` + `/complete` to write feedback rows
- `outputs/static/app.js` — ADD 2 buttons in `_landingTriageBar` deadline branch (line ~2977); ADD 4 functions after `_landingMarkDone` (line ~3107): `_deadlineWrongMatter`, `_deadlineSubmitWrongMatter`, `_deadlineWrongDeadline`, `_ensureActiveSlugsLoaded`
- `outputs/static/index.html` — bump `app.js?v=112` → `?v=113` at line 575
- `tests/test_deadline_feedback.py` — NEW

## Do NOT Touch

- `kbl/slug_registry.py` — read-only consumer; `normalize()` + `active_slugs()` used as-is
- `migrations/` prior files — append-only; no edits to applied migrations
- `outputs/static/mobile.html` / `mobile.js` — do not render deadlines (verified clean grep)
- `models/deadlines.py` table-creation bootstrap (lines 76-106) — do NOT add `deadline_feedback` here; migration owns it
- `_match_matter_slug()` / classifier code (`orchestrator/pipeline.py`) — phase 3 territory; out of scope for this brief
- `outputs/static/style.css` — no new classes needed; reuse `.triage-pill` + standard form-element styling

## Quality Checkpoints

1. **DB column verification post-deploy** (Lesson #2/#3/#3b). Run on prod:
   ```sql
   SELECT column_name FROM information_schema.columns WHERE table_name = 'deadline_feedback' ORDER BY ordinal_position;
   ```
   Expect 9 rows. Missing = migration didn't apply.

2. **Endpoint live check.** From local terminal:
   ```bash
   curl -X POST "https://baker-master.onrender.com/api/deadlines/99999/feedback" \
        -H "X-Baker-Key: $BAKER_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"feedback_type": "mute"}'
   ```
   Expect 404 (deadline 99999 doesn't exist) — proves the endpoint is registered and auth works. NOT 500 (server error) or 405 (route shadow conflict).

3. **iOS PWA cache bust** (Lesson #4 + frontend rule). After deploy, hard-reload dashboard on iPhone PWA. The 2 new buttons must appear on a deadline card on first reload — if not, `?v=113` didn't propagate or service worker cached the old `app.js`.

4. **375px mobile viewport test** (frontend rule). Resize browser to 375px wide. New buttons must wrap properly inside the existing `.triage-actions` flex container without breaking the row layout.

5. **wrong_matter dropdown UX.** Click "Wrong Matter" on a real deadline. Dropdown shows ~30+ active slugs. Pick one, Submit. Toast appears. Card stays visible (label corrected, not dismissed).

6. **Backward-compat corpus capture.** Dismiss any deadline via the existing "✕ Dismiss" button. Then:
   ```sql
   SELECT id, feedback_type, original_matter_slug, original_description, clicked_at
   FROM deadline_feedback ORDER BY clicked_at DESC LIMIT 5;
   ```
   Expect the latest row with `feedback_type='mute'`. Proves the augmented `/dismiss` endpoint writes corpus rows.

7. **XSS surface clean.** Inspect the rendered wrong-matter dropdown DOM. Each `<option>` element's value + display text must be set via `option.value=` / `option.textContent=`, NOT via `innerHTML`. No user-derived data flows through `innerHTML` in any new code path.

## Verification SQL

Run on prod 24h after deploy:

```sql
-- Volume + verb distribution
SELECT feedback_type, COUNT(*) AS n
FROM deadline_feedback
WHERE clicked_at > NOW() - INTERVAL '24 hours'
GROUP BY feedback_type
ORDER BY n DESC;

-- Wrong-matter corrections (the high-signal training rows)
SELECT id, deadline_id, original_matter_slug, corrected_matter_slug,
       LEFT(original_description, 80) AS desc_preview, clicked_at
FROM deadline_feedback
WHERE feedback_type = 'wrong_matter'
ORDER BY clicked_at DESC
LIMIT 20;

-- Sanity check: backward-compat dismiss/complete clicks write rows
SELECT feedback_type, COUNT(*) AS n,
       MAX(clicked_at) AS last_seen
FROM deadline_feedback
WHERE feedback_type IN ('mute', 'confirm')
  AND clicked_at > NOW() - INTERVAL '24 hours'
GROUP BY feedback_type;
```

---

## Bus posting (per `_ops/processes/agent-bus-posting-contract.md`)

On PR open + on each ship state change, bus-post to `lead` with `topic=ship/DEADLINE_FEEDBACK_LOOP_1`. Same pattern as DEADLINE_SIGNAL_HYGIENE_1 (PR #202 → msg #217). No PL paste-block (contract retired 2026-05-11).

## Phase boundary

This brief ships the **capture surface** only. Phases 3-4 (Gemini classifier upgrade + multi-dim envelope) are deliberately out of scope per Director's ratified sequencing — they fire after this brief produces 2+ weeks of click corpus. Do not extend scope into classifier code in this PR.
