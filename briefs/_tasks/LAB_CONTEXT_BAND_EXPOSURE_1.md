# LAB_CONTEXT_BAND_EXPOSURE_1 — expose seat context band on /api/v2/terminals (Lab-side slice)

- **Status:** QUEUED — dispatch to deputy-codex after LAB_COCKPIT_CONTROLLER_1 ships (serialized, same builder). Independent of cockpit G0 (codex-arch #12055: "does not reopen cockpit G0").
- **Binding contract:** codex-arch #12055 (shape accepted with one required correction) — this brief IS that pinned contract.
- **Dispatcher:** lead. **Builder:** deputy-codex. **Gate:** cross-vendor PR review (Claude deputy) → lead merge → live URL check.
- **Repo:** brisen-lab.
- **Consumer:** cockpit BRIEF B-2 context badge — may consume ONLY after this slice is live.

## Context

Cockpit B-2 wants a context-remaining badge per card. Lab already ingests per-seat context bands via `/api/heartbeat` into Postgres; the public card payload just doesn't expose them. codex-arch #12055 accepted the shape with one correction (no session-age degradation) and pinned the source contract below.

**Context Contract (Harness V2):** builder reads ONLY: brisen-lab `db.py` (seat-context-band read/write paths cited below), `app.py` (/api/heartbeat ingest + /api/v2/terminals handler), existing tests for that endpoint. No baker-master files, no vault, no matter context.
**Task class:** small production API extension (public read payload, additive only).
**Done rubric / done-state:** merged + deployed + AC-5 live URL check green + POST_DEPLOY_AC_VERDICT posted.
**Gate plan:** G1 self-test → cross-vendor PR review (Claude deputy) → lead merge → live URL check.

## Files Modified (expected)

- brisen-lab `app.py` (/api/v2/terminals payload assembly) + `db.py` read helper if needed.
- NEW/extended tests for the endpoint (fresh / stale / missing row + session-age-never proof).
- Nothing else — additive payload fields only; no schema migration (table exists).

## Problem (1-liner)

Cockpit cards want a context-remaining badge; the data already exists in Lab Postgres but is not exposed on the public card payload.

## Pinned source contract (codex-arch #12055 — verbatim)

- Source table: `brisen_lab_seat_context_band` (`db.py:918-936`), ingested from `/api/heartbeat` (`app.py:935-956`). Fields: band ok/soft/hard, context_percent, measured, window_tokens, session_uuid, updated_at.
- Freshness: existing semantics exclude rows older than 900s (`db.py:1045-1068`) — reuse, do not invent new thresholds.
- This meter is explicitly SEPARATE from TokenPressure enforcement (`db.py:923-925`); do NOT reuse `state.pressure` / `controlContextPct` as if identical.

## Deliverables

1. **Extend the existing public `GET /api/v2/terminals` card payload** (NOT a new endpoint) with: `context_used_percent`, `context_remaining_percent`, `context_band`, `context_measured`, and `context_age_seconds` (or `context_stale` boolean — builder picks one, documents it).
2. **Null/unknown semantics:** no fresh row (>900s or absent) ⇒ context fields null/unknown. **HARD RULE: session age must NEVER populate any context field** — session age is not a proxy for token/window consumption (codex-arch OBJECT, #12055).
3. **Privacy:** expose NO transcript, NO session UUID, NO raw token detail on the public payload. `context_measured` flags estimated vs measured so the UI can mark approximations.

## Verification

Live-flow proofs (Lesson #8): every AC exercised against the running Lab (local dev + post-deploy Render); AC-4 requires both a behavioral test and a grep-level check that no session-age value feeds a context field.

## Quality Checkpoints / Acceptance criteria (live — Lesson #8)

- AC-1: seat with fresh heartbeat row → payload carries correct band/percent matching the DB row.
- AC-2: stale row (>900s) → context fields null/stale-marked; band absent.
- AC-3: seat with no row ever → null/unknown, no error, rest of card payload intact.
- AC-4: proof (test) that session age never populates context fields — grep-level + behavioral test.
- AC-5: live `curl https://brisen-lab.onrender.com/api/v2/terminals` post-deploy shows the new fields; existing consumers (Lab UI, cockpit controller glance proxy) unaffected.

## Out of scope

Any UI. TokenPressure/enforcement changes. New endpoints. Heartbeat ingest changes. Cockpit repo work.

## Report

Bus post to lead with PR ref; POST_DEPLOY_AC_VERDICT after merge + live URL check.
