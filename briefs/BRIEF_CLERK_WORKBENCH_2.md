# BRIEF: CLERK_WORKBENCH_2 — Clerk Qwen3 surface (endpoint + editable workbench) + AC hardening

## Context
Phase 1 (CLERK_WORKBENCH_1, PR #301 merged) built the headless Clerk runtime on Qwen3-Coder:
`orchestrator/clerk_runtime.run_clerk_task(task, approval_token)` — Qwen3 tool-calling loop + tool
registry + in-code 7-item denylist + gemini-2.5-pro escalation. It is PROVEN live (denylist blocks
payment/email-send against the real paid `qwen/qwen3-coder`; OpenRouter funded $50, key in 1P
`CLERK_QWEN_API_KEY`). But the engine has **no caller** — there is no surface for the Director to
drive Clerk on Qwen3. Phase 2 builds that surface + folds two findings from the Phase-1 live AC.

### Surface contract
- **Surfaces:** (1) `POST /api/clerk/run` — JSON `{task, approval_token?}` → invokes `run_clerk_task`,
  returns `{session_id, status, result, draft_path}`. (2) `GET /clerk/edit/<session_id>` — browser-
  editable HTML page showing the converted document for Director review. (3) `POST /api/clerk/save/<session_id>`
  → writes the edited content to a Dropbox working folder or an EXACT Director/AH1-approved vault path.
- **Auth:** all three gated by `X-Baker-Key` (they fetch emails/docs + write files) — never anonymous.
- **States:** loading (Clerk working) / editable (doc ready) / saved (confirmed + path shown) / error
  (Clerk blocked or tool failed — show the denylist reason / pending_approval clearly).
- **Trigger:** Director (or the Clerk picker) POSTs a task → polls/streams status → opens the edit page.
- **Approval:** denylist items 5-7 surface as a "needs your approval" state; the `approval_token`
  originates CALLER-side (Director action in the UI), NEVER from the model.
- **Mobile:** desktop dashboard surface (no iOS PWA requirement this phase); cache-bust any static asset.

## Estimated time: ~1.5–2 days
## Complexity: High
## Task class: cross-layer feature (HTTP endpoints + editable UI + session store)
## Harness-V2: applies — G0 codex PASS required before build; G1/G2/G3 + POST_DEPLOY_AC on ship.

---

## SCOPE — Phase 2

1. **`POST /api/clerk/run`** (`outputs/dashboard.py`) — auth-gated; body `{task, approval_token?}`;
   calls `run_clerk_task`; persists the session (task, status, result, draft content/path) to Postgres
   (NOT in-memory — survives restart); returns `{session_id, status, ...}`. Fault-tolerant; LIMITed queries.
2. **`GET /clerk/edit/<session_id>`** — serves the converted document in an editable surface (textarea/
   contenteditable for md/txt/html; for DOCX/PDF show extracted text editable + keep the original link).
   Read the session from Postgres. 404 cleanly on unknown id.
3. **`POST /api/clerk/save/<session_id>`** — writes edited content to the destination via the existing
   `file_save` tool path (Dropbox working prefix or exact approved vault path — same allowlist + path-
   boundary checks Phase 1 hardened). Returns the final path. Approval-gated for any non-working-folder target.
4. **AC-HARDENING-1 (from Phase-1 live AC):** a tool that raises `SystemExit`/`BaseException` (observed:
   the gmail dispatch hard-exits when creds are absent) currently ESCAPES the registry's `except Exception`
   and kills the runtime. Fix: the tool registry `execute` must catch `BaseException` (or explicitly guard
   `SystemExit`/`KeyboardInterrupt` appropriately) and return a sanitized error dict — NO tool can terminate
   `run_clerk_task`. Add a regression test (a tool that raises SystemExit → controlled error result).
5. **Session store** — new table `clerk_sessions` (id, task, status, draft_content, draft_path,
   source_meta, created_at) via migration; all writes fault-tolerant + rollback.

## Out of scope / Do NOT touch
- The Phase-1 runtime internals beyond AC-HARDENING-1 (denylist, SSRF guard, escalation — done + verified).
- The Claude Code Haiku picker Clerk — stays as the conversational/terminal fallback.
- Render env wiring (CLERK_QWEN_* + CLERK_MODEL_BACKEND + switch to paid `qwen/qwen3-coder`) — **AH1 Tier-B**,
  not deputy-codex; AH1 wires it at deploy so the endpoint goes live on Qwen3.

## Acceptance Criteria
- **AC1** `POST /api/clerk/run` with a benign task returns a session_id + status; session persisted in PG.
- **AC2** `GET /clerk/edit/<session_id>` renders the converted doc editable; unknown id → clean 404.
- **AC3** `POST /api/clerk/save` writes to a Dropbox working folder; a non-approved vault path is rejected
  unless an approved path/token is supplied (reuses Phase-1 allowlist + path-boundary).
- **AC4** Denylist still enforced end-to-end through the endpoint (payment task → blocked response;
  email-send → pending_approval surfaced in the UI state).
- **AC5 (hardening)** A tool raising SystemExit returns a controlled error, does NOT kill `run_clerk_task`.
- **AC6** All three endpoints auth-gated (no `X-Baker-Key` → 401/403); sessions survive a restart.
- **POST_DEPLOY_AC** (after AH1 wires Render): live `POST /api/clerk/run` does a real Qwen3 fetch→convert,
  `/clerk/edit` opens it, save writes to Dropbox — full round-trip on prod against paid `qwen/qwen3-coder`.

## Gate plan (Harness V2)
G0 codex design (deputy-codex posts design to lead — High complexity, UI + endpoints + session store) →
build → G1 lead pytest → G2 /security-review (auth, the editable surface XSS, file_save path safety,
SSRF already done) → G3 codex → merge → AH1 wires Render → POST_DEPLOY_AC.

## Context Contract (for deputy-codex)
- Reuse the Phase-1 `file_save` allowlist + path-boundary + denylist + `run_clerk_task` — do not re-implement.
- Session store in Postgres, never in-memory (Render restarts roll instances).
- The editable page must be XSS-safe (escape model/document content; vanilla JS `createTextNode`, not innerHTML).
- approval_token originates caller/Director-side, NEVER model-side (Phase-1 invariant).
- Keep the Haiku picker Clerk working as the fallback; this adds the Qwen3 dashboard surface alongside it.
