# BRIEF: CLERK_WORKBENCH_1 — Qwen3-Coder runtime for the Clerk document agent

## Context
Clerk (slug `clerk`) is Brisen's cheap, Director-facing document clerk: fetch emails + documents,
convert to editable form, open for Director review, and file the result. Today it runs inside the
Claude Code picker pinned to Haiku 4.5 (interim) — a Claude-Code session can only run a Claude
model, so it cannot reach the ratified target model. **Director ratified 2026-06-05: Clerk's
target runtime is Qwen3-Coder (default) with gemini-2.5-pro as the hard-task fallback** (supersedes
codex spec #1833's gemini-flash-lite default — Qwen3-Coder is multimodal, 1M context, open-source/
self-hostable, ~$0.3/$0.8 per M). This brief builds the runtime that lets Clerk run on Qwen3-Coder.

### Surface contract: N/A — Phase 1 is headless plumbing (model client + agent loop + tools); the `/clerk/edit/<session_id>` browser workbench page is explicitly deferred to Phase 2.

## Estimated time: ~1.5–2 days (Phase 1 only)
## Complexity: High
## Prerequisites: Qwen3-Coder API access provisioned (AH1 Tier-B — see §0); `GEMINI_API_KEY` already live.
## Task class: cross-layer feature (new subsystem: model client + agent loop + tools)
## Harness-V2: applies — G0 codex PASS required before build; G1/G2/G3 + POST_DEPLOY_AC on ship.

---

## SCOPE — Phase 1 (this brief)

Build the **headless Clerk agent runtime** on Qwen3-Coder with the core tool loop and ONE proven
end-to-end path (fetch email → convert → file to Dropbox). **DEFER to Phase 2** (separate brief):
the browser-editable workbench page `/clerk/edit/<session_id>` + Save round-trip. Phase 1 delivers
the converted file path back (the current interim behavior), so it is independently shippable.

### Architecture (locked)
1. **Qwen3-Coder client** — new OpenAI-compatible client (mirror the existing `GeminiToolClient`
   pattern at `orchestrator/gemini_client.py:323`). Qwen3-Coder is reachable via an OpenAI-compatible
   `/chat/completions` endpoint with function-calling (host = your provisioned endpoint, §0). Config:
   base_url + api_key + model name + a `CLERK_MODEL_BACKEND` flag (`qwen3_hosted` | `qwen3_ollama_local`)
   so the same loop can point at a local Ollama (`http://localhost:11434/v1`) for on-device/private runs.
2. **Clerk agent loop** — a bounded tool-calling loop: system prompt (carries the 7-item denylist +
   Director-facing register) → Qwen3 proposes tool calls → Baker executes → loop until the task is
   done or a step cap (default 12 steps) / wall-clock cap (default 180s) is hit. **Retry once on the
   same model** for malformed tool/JSON output (codex spec #1833). **Escalate the failing single task
   only** to `gemini-2.5-pro` via the existing `GeminiToolClient` on: hard OCR, multi-document
   reconstruction, ambiguous extraction, or repeated (2×) schema/tool failure.
3. **Tool registry** — expose Baker capabilities as functions to the model. Phase 1 minimum set:
   `email_search` (by sender/subject/date/keyword/message-id — via `kbl/graph_client.py` Graph +
   existing Gmail path), `email_download` (body + attachments), `document_fetch` (Dropbox via
   `triggers/dropbox_client.py:198 download_file` + vault read), `format_convert` (PDF/DOCX/MD/TXT/HTML;
   OCR for scanned docs reuses the existing OCR path), `file_save` (write to a Dropbox working folder
   or an EXACT Director/AH1-approved vault path). All tools fault-tolerant (try/except + rollback on
   any DB touch); every DB query carries a LIMIT.
4. **Guardrails in the loop (the 7-item denylist — non-negotiable, enforced in code, not just prompt):**
   the loop MUST refuse / hard-block: (1) any payment/money action; (2) acting as the Director to an
   outside party; (3) writing code / changing production systems; (4) creating matter slugs or
   restructuring vault/folders; and MUST require an explicit Director-approval token before: (5) delete/
   move/archive/mark-email; (6) sending an external email (draft only); (7) any other irreversible action.
   Items 5–7 produce a DRAFT/PENDING artifact + a "needs Director approval" return, never auto-execute.

### Model wiring
- `config/settings.py`: add `Qwen3Config` (base_url, api_key, model, backend flag, enabled). Keep
  `GeminiConfig.pro_model = "gemini-2.5-pro"` as the escalation target. No secret literals — env-var names only.
- Default model = Qwen3-Coder; escalation = gemini-2.5-pro; retry-once-same-model on malformed output.

### Config flags
- `CLERK_MODEL_BACKEND` = `qwen3_hosted` (default) | `qwen3_ollama_local`.
- `CLERK_QWEN_BASE_URL`, `CLERK_QWEN_API_KEY`, `CLERK_QWEN_MODEL` (env).
- `CLERK_MAX_STEPS` (12), `CLERK_TASK_TIMEOUT_S` (180).

---

## §0 — Prerequisite (AH1 Tier-B, NOT deputy-codex): provision Qwen3-Coder access
Before build can be live-tested, AH1 provisions a Qwen3-Coder OpenAI-compatible endpoint
(candidate hosts: OpenRouter / Alibaba DashScope / Together / Fireworks), stores the key in 1Password
+ Render env (`CLERK_QWEN_API_KEY`, `CLERK_QWEN_BASE_URL`, `CLERK_QWEN_MODEL`). deputy-codex builds
against the config contract and can unit-test the loop with a mock client until the live key lands.

## Files Modified (deputy-codex — final list at G0)
- `config/settings.py` — add `Qwen3Config`.
- `orchestrator/clerk_runtime.py` (NEW) — Qwen3 client + Clerk agent loop + tool registry + guardrails.
- `orchestrator/gemini_client.py` — reuse `GeminiToolClient` for escalation (no change unless needed).
- tests: `tests/test_clerk_runtime.py` (NEW) — loop, retry, escalation, denylist-enforcement, one e2e (mockable).

## Do NOT Touch
- The Claude Code Haiku interim path (`clerk()` launcher) — stays as the rollback until Phase 1 proves parity.
- `outputs/dashboard.py` mail/scheduler surfaces — Phase 1 is headless; the `/clerk/edit` page is Phase 2.
- Any production poller / scheduler — Clerk runtime is invoked on demand, not on a timer.

## Acceptance Criteria (Phase 1)
- **AC1** Qwen3-Coder client makes a tool-calling round-trip (mock + live once key lands).
- **AC2** End-to-end: "fetch email <id> → convert to markdown → save to Dropbox path X" completes;
  the saved file exists and matches the source; return is a clean `Ready: <path> / Source: <…>`.
- **AC3** Malformed tool output retries once on Qwen3, then escalates that task to gemini-2.5-pro.
- **AC4** Denylist enforced IN CODE: a payment/slug/send-email/delete instruction is blocked or
  returned as DRAFT-pending-approval — never auto-executed (unit-tested for items 1–7).
- **AC5** Step + timeout caps hold; loop never runs unbounded; all tool calls fault-tolerant.
- **AC6** Cost: a typical fetch→convert→file task logs token usage; rough cost ≤ Haiku equivalent.

## Gate plan (Harness V2)
G0 codex PASS (dispatched to deputy-codex) → build → G1 lead literal pytest → G2 /security-review
(handles secrets + the external-endpoint call + email-tool surface) → G3 codex on PR → merge →
POST_DEPLOY_AC_VERDICT v1 once the live Qwen3 key is in Render.

## Context Contract (for deputy-codex)
- The 7-item denylist is the authoritative guardrail spec; it lives in `~/bm-clerk/CLAUDE.md`
  (Director-ratified 2026-06-05) and MUST be enforced in code, not just the system prompt.
- Mirror the existing `GeminiToolClient` (`orchestrator/gemini_client.py:323`) for the tool-call shape.
- Reuse `call_pro` / `GeminiToolClient` for escalation; do NOT build a second Gemini client.
- Clerk is Director-facing now (not bus-only-to-lead) — but THIS runtime is headless plumbing;
  register/voice lives in the picker, not here.
- Phase 2 (separate brief): the `/clerk/edit/<session_id>` browser workbench + Save round-trip.
