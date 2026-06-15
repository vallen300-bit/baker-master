---
status: PENDING
brief_id: AI_HOTEL_FIELD_CAPTURE_1
to: b2
from: lead
dispatched_by: lead
dispatched: 2026-06-15
task_class: feature
harness_v2: "full — Context Contract + gate plan + done rubric below"
owner_arc: lead (Director-assigned full autonomous lifecycle; Director at HiTEC, unreachable 15-17 Jun)
---

# BRIEF: AI_HOTEL_FIELD_CAPTURE_1 — one-tap mobile photo/voice capture → classified → live "Field notes" in the AI Hotel dashboard

> **Dispatch note (lead):** Director assigned this to lead for full autonomous build+deploy+deliver so he can USE it on the HiTEC floor. You build; lead drives gates → /security-review → Tier-A merge → deploy → POST_DEPLOY_AC → lead delivers the phone bookmark to Director. Ship report routes to **lead**. Canonical brief authored by cowork-ah1 (content lane owner); vault mirror coordinated by lead+cowork — **you do NOT touch the vault file**, lead/cowork handle that copy.

## Context
Director request (2026-06-15). Director is at HiTEC San Antonio (15–17 Jun). He wants to walk the floor and, from his phone, **snap a photo or dictate a note** and have it land in the **AI Hotel** stakeholder dashboard (`/static/ai-hotel.html`) — with an LLM **sorting what goes where**. Today the dashboard is a static hardcoded-JS artifact; placement is manual. This brief adds: capture → LLM classify → store → render live in a new "Field notes" section, no redeploy per capture.

The photo-understanding piece already exists and MUST be reused: `POST /api/scan/image` (`outputs/dashboard.py` ~line 9155) accepts an image + question, resizes, base64-encodes, calls Claude Vision via `_llm_call(model, max_tokens, messages=[{image+text}])` → `.text` + `.usage`. **Copy its image-handling + LLM pattern verbatim — do NOT reinvent, do NOT guess a model name.**

## Context Contract (Harness V2)
- **Task class:** feature (backend endpoints + DB table + 2 frontend surfaces). NOT docs-only.
- **Stable paths:** new routes under `/api/ai-hotel/*`; new static pages under `/static/`. Reuse existing `/static` mount (`_static_dir = outputs/static`, dashboard.py:343) + `verify_api_key`.
- **Blast radius:** additive only. New table, two new endpoints, one new static page, one new section in an existing static page. No change to existing endpoints, the curated `AREAS`/`STAKEHOLDERS` data, or `mobile.html`.
- **Rollback:** revert the PR; drop the new table. No data migration of existing rows.

## Estimated time: ~3–4h · Complexity: Medium · Prerequisites: none

---

## Feature 1: `ai_hotel_captures` table
Captures must persist across Render deploys (Render FS is ephemeral — do NOT write images to disk). Store the resized image as base64 text in Postgres. New migration (follow `migrations/` convention; **confirm next migration number doesn't collide on pull**):

```sql
CREATE TABLE IF NOT EXISTS ai_hotel_captures (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        TEXT NOT NULL CHECK (source IN ('photo','note')),
    note_text     TEXT,
    image_b64     TEXT,                 -- resized JPEG base64 (NULL for note-only); cap ~500KB
    image_media   TEXT,
    section_guess TEXT NOT NULL DEFAULT 'general'
                  CHECK (section_guess IN ('use_case','stakeholder','research','comms','general')),
    related_area  TEXT,
    summary       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'new'
                  CHECK (status IN ('new','promoted','dismissed'))
);
CREATE INDEX IF NOT EXISTS idx_ai_hotel_captures_created ON ai_hotel_captures (created_at DESC);
```
Constraints: `image_b64` already resized (reuse scan_image downscale ≤3.5MB, then further cap ~500KB — smaller max dimension if needed). Migration idempotent (`IF NOT EXISTS`).

---

## Feature 2: `POST /api/ai-hotel/capture` (write)
No `/api/ai-hotel/*` routes exist (grep-confirm). Model the handler on `scan_image` (dashboard.py:9155).

```python
@app.post("/api/ai-hotel/capture", tags=["ai-hotel"], dependencies=[Depends(verify_api_key)])
async def ai_hotel_capture(image: UploadFile = File(None), note: str = Form("")):
    # 1) require at least one of image/note
    # 2) if image: reuse scan_image validate+resize+base64 block VERBATIM
    #    (content-type allowlist, 20MB hard cap, PIL progressive downscale).
    #    Further cap encoded size ~500KB (smaller thumbnail dim) for DB.
    # 3) classification messages: image block (if any) + note + instruction (prompt below).
    #    resp = _llm_call(<SAME model string as scan_image>, max_tokens=600, messages=[...]); answer = resp.text
    #    log_api_cost(<model>, resp.usage.input_tokens, resp.usage.output_tokens, source="ai_hotel_capture")
    # 4) Parse model JSON {section_guess, related_area, summary}. Defensive: parse-fail OR
    #    section_guess not in allowed set -> section_guess='general', related_area=None, summary=first 200 chars.
    # 5) INSERT (parameterized). try/except + conn.rollback().
    # 6) return {"id":..., "section_guess":..., "related_area":..., "summary":...}
```

**Classification prompt:**
> You are sorting a field note captured by Brisen's chairman at a hospitality-tech exhibition into one section of the "AI Hotel" dashboard (a NVIDIA × Mandarin Oriental × Brisen strategy map). Sections: `use_case` (an AI hotel capability area: flagship, concierge/reservations, staff training, operations/personalization, digital twins/design, discovery/GEO, robotics), `stakeholder` (a party's give/get: NVIDIA, Mandarin Oriental, Brisen, AI startups, investor/owner/lender, guests), `research` (a study/source/competitor/market datapoint), `comms` (something about outreach to NVIDIA or MOHG), `general` (anything else worth keeping). Return STRICT JSON only: `{"section_guess":"<one of the five>","related_area":"<short tag or null>","summary":"<≤18-word plain-English summary>"}`. No prose.

Constraints: keep scan_image content-type allowlist + 20MB cap; reject non-image uploads. Parameterized SQL only; `conn.rollback()` in except; never 500 silently (return JSON error). `note` is Director dictation — store as text, never interpolate into SQL or the model system role unsanitized.

---

## Feature 3: `GET /api/ai-hotel/captures` (read)
```python
@app.get("/api/ai-hotel/captures", tags=["ai-hotel"], dependencies=[Depends(verify_api_key)])
async def ai_hotel_captures(limit: int = 100):
    # SELECT id, created_at, source, note_text, image_b64, image_media,
    #        section_guess, related_area, summary, status
    #   FROM ai_hotel_captures WHERE status <> 'dismissed'
    #   ORDER BY created_at DESC LIMIT :limit  (clamp <=200)
    # Return {"captures":[{..., "image":"data:<media>;base64,<b64>" if image_b64 else None}, ...]}
    # try/except + rollback; on error return {"captures":[]} (fail-soft).
```
Constraints: LIMIT mandatory (clamp ≤200); try/except + rollback; fail-soft empty list.

---

## Feature 4: Capture surface — `outputs/static/ai-hotel-capture.html` (new, mobile-first)
Director needs one bookmarkable URL: tap → camera or dictation → Send.
- Self-contained mobile-first page (mirror `mobile.html` simplicity; no framework).
- Controls: big **Camera** button (`<input type="file" accept="image/*" capture="environment">`), a **textarea** (phone mic = dictation), **Send**, small result line ("Saved → tagged: <section>").
- **Auth (no secrets in repo):** page reads `key` from its own URL query (`?key=...`). Director bookmarks `…/static/ai-hotel-capture.html?key=<API_KEY>`. Send POST sends key via the `X-API-Key`/`key` mechanism `verify_api_key` already accepts (confirm which during build). If `key` absent → "open with your key" + disable Send. Do NOT hardcode any key.
- Same-origin fetch (page served from baker-master, posts to baker-master `/api/...`) — no CORS.
- On success show returned `section_guess` + `summary`.
- States: idle / no-key (Send disabled) / sending / saved (section+summary) / error.

---

## Feature 5: "Field notes" section in `outputs/static/ai-hotel.html`
Static hardcoded JS: `NAV`, `AREAS`, `STAKEHOLDERS`, `RESEARCH`, `COMMS`, render fns, `show(id)` router.
- Add `NAV` entry `{id:'notes',name:'Field notes',icon:'message'}` (after Communications).
- Add `renderNotes(main)`: read `key` from `location.search`; if absent → no-key hint. Else `fetch('/api/ai-hotel/captures?limit=100', {key as verify_api_key expects})` → newest-first cards: optional `<img>` thumbnail from data URL, the `summary`, coloured tag for `section_guess`+`related_area`, timestamp. Build via `document.createTextNode`/safe DOM (match existing file — **never innerHTML server/model text → XSS**).
- Wire `renderNotes` into `show(id)`. Reuse existing card classes (`.rcard`/`.scard`).
- Field notes are READ-only in the dashboard (capture happens on phone). Must not break `show('hotel')` default.

---

## Files Modified
- `migrations/<new>_ai_hotel_captures.sql` (Feature 1)
- `outputs/dashboard.py` — two new endpoints (Features 2–3)
- `outputs/static/ai-hotel-capture.html` — new (Feature 4)
- `outputs/static/ai-hotel.html` — Field notes nav + section (Feature 5)

## Do NOT Touch
- `POST /api/scan/image` + other existing endpoints — reuse the pattern, don't modify.
- `AREAS`/`STAKEHOLDERS`/`RESEARCH`/`COMMS` curated data — cowork-ah1's content lane.
- `outputs/static/mobile.html`; `outputs/static/index.html` cockpit nav (link shipped PR #365).
- **The vault file** `~/baker-vault/wiki/matters/nvidia/05_outputs/2026-06-15-stakeholder-dashboard-v6.html` — lead/cowork mirror it separately. Not your lane.

## Quality Checkpoints (post-deploy)
1. From a phone: open capture page with `?key=`, snap a booth photo, Send → response shows `section_guess`+`summary`.
2. Dictate a note (no photo), Send → saved + classified.
3. Open dashboard with `?key=` → "Field notes" lists both, newest first, thumbnail+tag.
4. Open dashboard WITHOUT a key → curated sections render fine; Field notes shows no-key hint (no console errors).
5. Redeploy Render → previously-captured notes still present (persistence — proves DB storage).
6. Mobile render of both surfaces (iPhone Safari).

## Verification SQL
```sql
SELECT id, created_at, source, section_guess, related_area, left(summary,60) AS summary,
       (image_b64 IS NOT NULL) AS has_image, status
FROM ai_hotel_captures ORDER BY created_at DESC LIMIT 20;
```

## Gate plan
- AH2/codex static review (upload endpoint = security surface: auth, file-type/size validation, SQL parameterization, XSS in new render).
- `/security-review` (Tier-A — new file-upload endpoint accepting external input). **MANDATORY, non-skippable (Lesson #52).** Lead runs this.
- Tier-A merge by lead on PASS-WITH-NITS.
- `POST_DEPLOY_AC_VERDICT v1` answering Quality Checkpoints 1–6 (must include persistence check #5).

## Done rubric
DONE = a photo AND a dictated note captured from a phone both appear, correctly sectioned, in the dashboard "Field notes" after a live test; survive a Render redeploy; no regression to curated sections; post-deploy AC verdict posted to bus. "Compiles"/"by inspection" is NOT done.

## Risks / lessons applied
- Ephemeral Render disk → Postgres base64, never disk. CORS → same-origin `/api/...`. LLM three-way match → reuse scan_image's exact `_llm_call`/`.text`/`.usage` + model string. XSS → text nodes only. Unbounded query/no rollback → LIMIT + `conn.rollback()` every except. Secrets → key only in Director's bookmark URL, nothing committed.

## Report
Bus-post to **lead** (per agent-bus-posting-contract): ship → PR#, G1 green (literal pytest), then await lead's gate sequence. Surface any blocker or scope-ambiguity to lead as plain technical prose.
