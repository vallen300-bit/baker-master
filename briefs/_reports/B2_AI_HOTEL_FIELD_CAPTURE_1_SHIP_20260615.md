# B2 SHIP REPORT — AI_HOTEL_FIELD_CAPTURE_1

- **Date:** 2026-06-15
- **Brief:** `briefs/_tasks/CODE_2_PENDING.md` (dispatched by lead, Director-assigned, HiTEC-urgent)
- **PR:** #366 — https://github.com/vallen300-bit/baker-master/pull/366
- **Branch:** `b2/ai-hotel-field-capture-1`
- **Bus:** ship → lead #3090 (thread 895532d2)

## Delivered (all 5 features)
1. **`migrations/20260615b_ai_hotel_captures.sql`** — persistent capture store. Resized image stored as **base64 TEXT in Postgres** (Render FS ephemeral — never disk). Idempotent (`IF NOT EXISTS`), `migrate:up`/`migrate:down` markers, commented down-section.
2. **`POST /api/ai-hotel/capture`** — reuses `scan_image` content-type allowlist + 20 MB cap + PIL downscale verbatim; second pass caps encoded size ~500 KB for DB. Classifies via the **same** `_llm_call("gemini-2.5-flash")` shape + `log_api_cost`. Defensive JSON parse (strips code fences) → fail-soft `general`; invalid section coerced. Parameterized INSERT, `conn.rollback()` on except, never 500-silent.
3. **`GET /api/ai-hotel/captures`** — newest-first, `LIMIT` clamped ≤200, fail-soft empty list, builds `data:` URL from stored base64.
4. **`outputs/static/ai-hotel-capture.html`** — mobile-first bookmark page. Camera (`capture="environment"`) + textarea (phone mic dictation) + Send. Key from `?key=` URL → `X-Baker-Key`. No secrets committed. States: idle / no-key (Send disabled) / sending / saved / error. Same-origin (no CORS).
5. **`outputs/static/ai-hotel.html`** — "Field notes" nav + read-only section. Safe DOM only (text nodes; no `innerHTML` of model/server text). Coloured section tags, thumbnail, timestamp. `show('hotel')` default unaffected; curated `AREAS`/`STAKEHOLDERS` untouched.

## Verification (G1)
- `tests/test_ai_hotel_capture.py` — **12/12 pass** (source-level + TestClient with stubbed store/LLM): auth, 400-on-empty, classify+store, parse-fail fail-soft, invalid-section coercion, fenced JSON, bad image type, read data-URL build, dismissed-hidden, limit-clamp.
- Both static pages: JS syntax-checked via `node --check`.
- Routes register; full suite collects clean (3495 tests).
- Compile-clean on `dashboard.py`.

## Not done by b2 (lead-driven gates)
AH2/codex static review → `/security-review` (MANDATORY Tier-A, upload endpoint, Lesson #52) → Tier-A merge → deploy → `POST_DEPLOY_AC_VERDICT` (Quality Checkpoints 1–6, incl. persistence #5 across a Render redeploy). Live-on-phone test is the done-rubric and belongs to the post-deploy gate.

## Heads-up (pre-existing, NOT this PR)
`tests/test_migration_runner.py::test_migration_file_has_up_marker` fails on clean `main` — 13 older migration files lack the `migrate:up` marker. My migration **has** the marker and is **not** in the flagged list. Out of scope to fix here (would touch others' migration files). Flagged to lead.
