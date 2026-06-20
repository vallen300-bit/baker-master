# Checkpoint — cowork-ah1 — AI-Hotel field-notes research + readable card titles

**Rollover at ~86% context, 2026-06-20T06:4xZ. Successor claims via the attempt-bump commit (this file), NOT a bus ack.**

## Resume reads (in order)
1. This file.
2. cowork auto-memory `session_handover_2026-06-19_ai_hotel_field_notes_research_readable_titles.md` (FULL detail + recipes).
3. PINNED §A-COWORK-0619 (relayed to lead bus #3480 to fold).

## State
- **SHIPPED + LIVE:** `AI_HOTEL_READABLE_CARD_TITLE_1` — commit **f8fff72 → baker-master main** (verified live). Field-notes cards titled "Name · HH:MM" (capture time) not DB row numbers. Frontend-only `outputs/static/ai-hotel.html`. Lead-cleared #3477. Naming convention ratified everywhere. Worktree `/tmp/aih-titles`.
- **FILED:** 4-site research → vault `wiki/matters/nvidia/curated/2026-06-19-ai-hotel-field-notes-site-research.md` (baker_vault_write commit 4dd8d09). Site 24 (2900 Lakeside) = ALREADY ENTITLED 190-room hotel (Use Permit PLN2018-13582), owner Stratus, ~3mi NVIDIA — standout (a buyout). Sites 19/17/13 address-gated.

## OPEN (do next session)
1. **Researcher reply PENDING — bus #3478** (sites 1851 cap22 + 1856 cap23, GPS handed over). Check inbox; append findings to the vault note; surface to Director.
2. **Re-research site 19 as Sunnyvale Baylands Park** (Caribbean Dr / Lawrence Expwy) — capture 19's photos pinned the location the first pass missed. AWAITING Director confirm "Baylands Park". On confirm, re-dispatch researcher.
3. **"Open findings" drawer NOT built** — Director wants research to open from each card. Fast = embed findings (frontend); durable = DB write-back (migration + GET + render). Separate authorization; not greenlit.
4. **Storer 2-3 pager** still open (carried from §A-COWORK-0617); reconcile w/ lead §A-LEAD-0615 firewall before any NVIDIA outbound.

## Recipes
- Captures: `GET https://baker-master.onrender.com/api/ai-hotel/captures?limit=100` header `X-Baker-Key: bakerbhavanga`. Photos: `/captures/{id}/images` → data-URL strings (EXIF stripped). Decode base64 → file → Read to vision-inspect.
- Bus: `BAKER_ROLE=cowork-ah1 ~/Desktop/baker-code/scripts/bus_post.sh <to> "<body>" <topic>`; check `check-lead-inbox.sh`; ack `POST /msg/<id>/ack`.
- Vault write: `baker_vault_write` wiki/ paths only; curated/ frontmatter needs confidence+source+provenance.
- Dashboard push: ai-hotel.html is deputy-nominal but cowork ships it; git single-threaded — bus-clear lead before push; branch off latest origin/main.
