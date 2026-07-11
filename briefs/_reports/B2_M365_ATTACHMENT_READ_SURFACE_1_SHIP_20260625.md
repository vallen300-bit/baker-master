# B2 SHIP REPORT — BAKER_M365_ATTACHMENT_READ_SURFACE_1

- **PR:** #421 → https://github.com/vallen300-bit/baker-master/pull/421
- **Branch:** `b2/m365-attachment-read-surface-1` (off main @ 339f040a)
- **Commit:** 1c87dc08
- **Brief:** `briefs/_tasks/BAKER_M365_ATTACHMENT_READ_SURFACE_1.md` (dispatch dbbb929)
- **Reply target:** lead
- **Date:** 2026-06-25

## Done rubric
The desk can retrieve named M365/Graph attachment bytes/text through an auth-gated Baker tool. Tool built + registered; gate chain pending; POST_DEPLOY_AC after merge+deploy.

## Step-1 diagnosis (AC1 — posted to lead bus #4242)
Prod `email_attachments`: **97,668 rows** (graph 88,973 / bluewin 8,672), **94,986 with bytes**, 2,682 metadata-only (>5MB). Migration applied, store reachable, store-unavailable warning did not cause aggregate silent-skip. **Root cause = no-read-surface, NOT empty-store → no backfill** (lead accepted #4243/#4244).

## Change
- `kbl/attachment_store.py` — `list_attachments(message_id, source)` read helper (metadata only, id-ordered). Byte fetch reuses `get_attachment(id)`. No schema change; applied migration untouched.
- `tools/email.py` — `baker_email_attachment_read`: LIST (enumerate) + FETCH (text + optional base64 bytes by filename/index). Source-aware. Reuses `scripts.extract_gmail` text pipeline (lazy import). >5MB metadata-only → bytes-unavailable. Never raises to MCP layer.
- Auto-registers via `EMAIL_TOOLS`/`EMAIL_TOOL_NAMES`/`dispatch_email`.

## Acceptance criteria
- **AC1** Step-1 prod diagnosis posted ✓ (#4242).
- **AC2** `baker_email_attachment_read` returns list + bytes/text by name/index ✓ (25 unit tests; live exercise at POST_DEPLOY_AC).
- **AC3** Named desk attachments retrievable — store presence confirmed for the resolvable ids (n18=3 w/ bytes, n33=2 w/ bytes); see per-message note. No backfill needed.
- **AC4** Auth-gated, fail-closed, no unauth path ✓ — inherits `POST /mcp` → `_mcp_verify_key` (401, fail-closed). Pending G4 lead /security-review.
- **AC5** Tests added ✓; gate chain + POST_DEPLOY_AC_VERDICT pending.

## Security posture (G4 input)
- Auth: transport-level X-Baker-Key, fail-closed 401 (`bool(_BAKER_API_KEY) and key == _BAKER_API_KEY`). Identical to `baker_email_read`/`baker_gmail_attachment_read`. No separate unauth path.
- SQL: parameterized (`%s`) throughout `list_attachments`. No injection.
- Read-only: no Graph re-fetch, no filesystem write, no mutation.
- Bounded: list scoped to one message_id; fetch is one row; `include_bytes` explicit opt-in.
- Fault-tolerant: store calls try/except → []/None; dispatch never raises.

## Per-message confirm (nice-to-have, lead #4248)
10 target ids were truncated mid-string in dispatch. Confirmed present-with-bytes for the 2 with unambiguous long suffixes: **n18** Erstentwurf+Anlage10 (3 attachments), **n33** Aukera fee (2). The other 8 can't be confirmed from truncated ids. n15 (short-hex `19e833…`) and n17 (gmail-style `…@brisengroup.com`) returned 0 under their given ids — non-Graph id variants, likely id-scheme mismatch not store gap. Real per-message proof = live tool exercise at POST_DEPLOY_AC; recommend desk supplies full ids or pulls live once deployed.

## Tests (literal)
- `tests/test_email_attachment_read.py`: **25 passed in 0.16s**.
- Regression `test_m365_mail_surface` + `test_gmail`: **59 passed, 3 skipped** (live-DB skips).
- Run under python3.12 venv (local Python is 3.9; `mcp` needs ≥3.10).

## Gate plan
G2 codex (effort=HIGH) → G3 deputy AC → **G4 lead /security-review (mandatory)** → merge → POST_DEPLOY_AC_VERDICT v1.

---

## POST-DEPLOY (merged PR #421 @ e6b6c81, Render live)

Live exercise via prod MCP `POST /mcp` (X-Baker-Key), tool present in prod tools/list (count 53):
- **AC2 LIST n18** → attachment_count=3: Darlehensvertrag redline PDF (678,847 B), Darlehensvertrag 2. Entwurfsfassung .docx (324,263 B), Anlage 10 .docm (39,502 B). source=graph, storage=db.
- **AC2 FETCH n18 index=1** → text_extracted=true, ~139,190 chars real loan-contract text ("Darlehensvertrag … Lilienmatt Immobilien GmbH …"), content_sha256 ef47aeca…, bytes retrievable.
- **AC3 LIST n33** → attachment_count=2: image001.png (78,603 B), Gebührenvereinbarung fee PDF (260,317 B).
- **AC4 NO-KEY POST /mcp** → HTTP **401** (fail-closed). Auth gate live.

All live ACs PASS. Tool delivers n18/n33 load-bearing docs to baden-baden-desk. The 6 AAQk-form messages remain true-empty pending `M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1` (b1).
