---
brief_id: GMAIL_POLLING_DIAGNOSTIC_1
report_author: b4
report_date: 2026-05-25
report_type: READ-ONLY DIAGNOSTIC (no code changes)
working_branch: b4/gmail-polling-diagnostic-1
bus_ack: msg #1021 (ack/gmail-polling-diagnostic-1)
---

# B4 diagnosis — Gmail polling outage (documents/email stale 9 days)

## 1. Bottom line

`documents` rows with `source_path LIKE 'email:%'` (email-attachment-as-document writes) have been silently failing since **2026-05-16 08:44:33Z** despite a healthy poll cycle that still writes to `email_messages` every 5 min. **Probable root cause: `extract_attachments_text()` in `scripts/extract_gmail.py:618-708` is silently catching all extraction/storage failures and emitting only `debug`/`warning`-level logs that don't propagate to Render — so the actual failure mode cannot be named from log evidence alone.** Confidence: **medium-high** for "silent-swallow is the proximate fault path"; **medium-low** for the specific underlying error (top 3 hypotheses below).

## 2. Evidence chain

### 2a. Disconnect confirmed via 4 queries

| Source-prefix | latest doc | last_12h | last_24h | last_14d | total |
|---|---|---|---|---|---|
| `dropbox` | 2026-05-25 09:55Z | 904 | 925 | 1,529 | 5,065 |
| `email`   | **2026-05-16 08:44Z** | **0** | **0** | 19 | 311 |
| `upload`  | 2026-04-06 05:53Z | 0 | 0 | 0 | 7 |

`email_messages` is healthy: 750 rows in last 14 days, max(received_date)=2026-05-25 09:30Z, watermarks `email_poll`/`exchange_poll`/`bluewin_poll`/`email_poll_checked` all advancing. So the poll is firing, fetching mail, and writing email metadata. The break is between `format_thread`→`extract_attachments_text` and the `documents` INSERT, not in the poll itself.

### 2b. Email-prefix documents daily counts (cliff at 2026-05-16)

| Day | docs (email:%) |
|---|---|
| 2026-05-11 | 3 |
| 2026-05-12 | 2 |
| 2026-05-13 | 5 |
| 2026-05-14 | 1 |
| 2026-05-15 | 5 |
| 2026-05-16 | 3 (last at 08:44:33Z) |
| 2026-05-17 → 2026-05-25 | **0** |

### 2c. 53 counterparty emails since 2026-05-17 with NO documents row

Known-attachment subjects in the gap window with zero `documents` rows:

- 2026-05-23 23:10 — `service-facturation-ma@edf.fr` — *"Votre facture électronique EDF au format PDF"*
- 2026-05-22 11:43 — `karin.koehler@brisengroup.com` — *"FW: CBH - Letters to be signed"*
- 2026-05-22 09:11 — `balazs.csepregi@brisengroup.com` — *"Fwd: Q&A / ESG / Debt Model"*
- 2026-05-21 16:14 — `rolf.huebner@brisengroup.com` — *"April results and reporting"*
- 2026-05-21 14:28 — `edita.vallen@brisengroup.com` — *"Hagenur Investigation reports : water damage"*
- 2026-05-21 06:39/06:43 — Annaberg Valuation proposal thread

SQL: `SELECT COUNT(DISTINCT em.message_id) AS total, COUNT(*) FILTER (...) AS with_doc FROM email_messages em WHERE received_date > '2026-05-17' AND sender_email matching counterparty/brisengroup` → `(53, 0)`.

### 2d. Poll IS running — Render logs last 2h

```
2026-05-25T08:52:11.571 | INFO | Email trigger: checking for new threads...
2026-05-25T08:52:13.124 | INFO | Email trigger: 1 new threads found
2026-05-25T08:52:55.110 | INFO | Email trigger: 1 processed, 0 queued for briefing, 0 skipped (dedup)
2026-05-25T08:52:55.509 | INFO | Email trigger: poll cycle complete
```
Same pattern every ~5 min through 09:24Z. No errors. No "skipping" messages from `extract_attachments_text` (because its `except Exception` blocks log at `debug`, which the production logger level filters out).

### 2e. Cost circuit breaker is HOT — but is NOT the root cause of the start

| Day | daily cost | hard-stop tripped? |
|---|---|---|
| 2026-05-13 | €17.47 | no |
| 2026-05-14 | €55.49 | no |
| 2026-05-15 | €28.95 | no |
| 2026-05-16 | €21.67 | **no** ← gap starts |
| 2026-05-17 | €14.10 | no |
| 2026-05-18 | €12.85 | no |
| 2026-05-19 | €8.44 | no |
| 2026-05-20 | €36.16 | no |
| 2026-05-21 | €115.31 | **yes (1st day)** |
| 2026-05-22 | €104.19 | yes |
| 2026-05-23 | €103.58 | yes |
| 2026-05-24 | €115.86 | yes |
| 2026-05-25 | €104.88 (08:50Z so far) | yes |

`COST_HARD_STOP_EUR=100.0` (default in `orchestrator/cost_monitor.py:50`). Hard stop first tripped 2026-05-21 — five days AFTER the documents/email cliff. So the breaker is real but it's a SECOND, COMPOUNDING defect, not the trigger.

Render logs at 2026-05-25 ~08:50Z show breaker actively blocking BOTH paths:
- `baker.extraction_engine | WARNING | Extraction skipped (circuit breaker at EUR 104.87): email:19e5e123cad56775` — Tier-2 message-content extraction (`orchestrator/extraction_engine.py:614`)
- `baker.document_pipeline | ERROR | Document classification blocked by circuit breaker (€104.88)` — downstream document classify/extract (`tools/document_pipeline.py:195`, `309`)

Daily cost is now ~88% `capability_runner` (€92/day) — likely a Cortex Phase-3 specialist loop or runaway dispatch. Out of scope for THIS brief but flag for separate diagnosis.

### 2f. Code-path map (READ-ONLY)

```
embedded_scheduler.py register email_poll every 300s
  → triggers/email_trigger.py:611 check_new_emails()
    [skips: should_skip_poll('email') | 429 backoff | poll_gmail() exception]
    → poll_gmail() at :432
        sets extract_gmail._gmail_service = service
        → scripts/extract_gmail.py:931 extract_poll(service)
            → fetch_thread_detail(service, tid)
            → format_thread(thread, messages) at :376
                → extract_attachments_text(_gmail_service, msg) at :618
                    → _extract_text_from_bytes(file_bytes, filename, ext) at :711
                        → tools/ingest/extractors.py:29 extract(filepath)
                            → _extract_pdf via pdfplumber for *.pdf
                    if results:
                        → memory/store_back.py:432 store_document_full(source_path='email:{mid}/{name}', ...)
                            → INSERT INTO documents ... ON CONFLICT (file_hash) DO UPDATE
                            content-hash dedup at :451-456 (SHA-256 of full_text[:10000].strip().lower())
                        → tools/document_pipeline.py:410 queue_extraction(doc_id)
  → _process_email_threads(new_threads) at :765
    per-thread: store_email_message(...), classify_trigger, deadlines, meetings, substack, etc.
```

Critical: **the only `email:%` documents-INSERT site in production is `scripts/extract_gmail.py:690-696`** (`extract_attachments_text`). Every other write path is a backfill script (`scripts/backfill_email_attachments.py`, `scripts/backfill_missed_attachments.py`) that's only invoked manually.

### 2g. No relevant code change in the cliff window 2026-05-14 to 2026-05-17

Commits to `scripts/extract_gmail.py`, `tools/ingest/extractors.py`, `memory/store_back.py:store_document_full`, `tools/document_pipeline.py`, `triggers/email_trigger.py` poll path — last touched **2026-04-XX** (`e86517e — VIP sender allowlist`) before today. Two PRs landed 2026-05-16:

- `8ca850e` (BAKER_WA_DIRECTOR_FILTER_1) deployed 13:22Z — modified `triggers/email_trigger.py` only by adding `kind="counterparty"` to 2 `send_whatsapp()` calls. Cannot break documents pipeline.
- `a13b2c9` (pm-state parallel) deployed 13:25Z — added `detect_parallel_pm_key` to `memory/store_back.py`; new function, doesn't alter `store_document_full`.

Both deployed **AFTER** the 08:44Z cutoff, so they can't have caused the start of the gap. `d8e9d2a` (scheduler watchdog fix) deployed at 05:56Z 2026-05-16 was live during the cliff but it doesn't touch the email-attachment path.

`requirements.txt` (`pdfplumber>=0.10.0`, `openpyxl>=3.1.0`, `python-docx>=1.0.0`) — no change in the window. But pip might have resolved a different version on the 2026-05-16 13:22Z redeploy if version constraints are loose.

### 2h. Silent-swallow proof

`scripts/extract_gmail.py` (annotated):

```python
# 660-663 — silent debug log on inline attachment extract failure
except Exception as e:
    logging.getLogger("sentinel.gmail").debug(
        f"Failed to extract inline attachment {filename}: {e}"
    )

# 677-680 — silent debug log on Gmail-API attachment download failure
except Exception as e:
    logging.getLogger("sentinel.gmail").debug(
        f"Failed to download attachment {filename}: {e}"
    )

# 703-706 — WARNING but non-fatal at the store-back step
except Exception as e:
    logging.getLogger("sentinel.gmail").warning(
        f"Email attachment document storage failed (non-fatal): {e}"
    )

# 723-725 in _extract_text_from_bytes — silent debug on extractor crash
except Exception as e:
    logging.getLogger("sentinel.gmail").debug(f"Text extraction failed for {filename}: {e}")
    return None
```

Plus the call in `format_thread:444-450`:
```python
try:
    attachments = extract_attachments_text(_gmail_service, msg)
    ...
except Exception:
    pass   # ← swallows everything wholesale
```

Production logger is at INFO level → all 4 `debug` lines are invisible. The WARNING at 703 would appear IF a store-back exception fires; absent in last 2h of Render logs grep'd for "attachment". So either no store-back exception is being thrown, OR the call chain bails out before that line via one of the silent `except` blocks above.

### 2i. Additional anomaly: `--- Attachment:` marker absent from `full_body` since 2026-03-09

`format_thread` builds attachment_blocks from the same `extract_attachments_text` call (line 444-448), then appends `=== ATTACHMENTS ===` + each `--- Attachment: {filename} ---` block to the formatted text (lines 488-491). Yet:

- Last `email_messages` row containing `--- Attachment:` in `full_body`: 2026-03-09 13:31Z (only 9 rows ever match).
- But documents kept being written with `email:%` prefix through 2026-05-16 08:44Z.

This is contradictory unless the documents row writes (line 690) and the attachment_blocks append (line 446) reached the production code path at different times — i.e. the same `extract_attachments_text` call simultaneously stored docs but `attachment_blocks` got built before the docs write inside the function and the call somehow returned partial data.

Working theory for the 2026-03-09→2026-05-16 window: `extract_attachments_text` succeeded enough to write docs but raised AFTER returning (or the outer `try/except` at format_thread:449-450 swallowed the post-return exception). And since 2026-05-16 the failure happens earlier — before the docs-INSERT line.

This is the **strongest evidence that the silent-swallow is the immediate fault path**: visibility into which `except` block actually fired would name the root cause directly.

## 3. What's broken vs what's working

| Component | Status | Evidence |
|---|---|---|
| `email_poll` apscheduler job | ✅ WORKING | Render logs every ~5 min, watermark advancing |
| Bluewin / Exchange independent polls | ✅ WORKING | watermarks advancing 2026-05-25 |
| Gmail OAuth read scope | ✅ WORKING | `GMAIL_ATTACHMENT_READ_1` end-to-end PASS at AH1's smoke earlier today |
| `email_messages` INSERT | ✅ WORKING | 750 rows last 14d, latest 2026-05-25 09:30Z |
| `_process_email_threads` per-thread classification/deadlines | partial — cost-breaker hot since 2026-05-21 | logs show classifications happening but many `Document classification blocked` errors |
| `documents` INSERT for `email:%` source_path | ❌ **BROKEN** since 2026-05-16 08:44Z | DB query 1a; daily count cliff |
| `extract_attachments_text` visibility | ❌ silent-swallow | 4 debug-level `except` blocks; outer `except Exception: pass` |
| Cost circuit breaker | ❌ HOT (compounding defect, not root cause) | €104-€115/day vs €100 hard stop; first tripped 2026-05-21 |
| Hag-desk on-demand attachment read | ✅ WORKING | not blocked; Tuesday LG Wien filing unaffected |

## 4. Recommended fix

Split into TWO sequential briefs. Brief A unblocks visibility so root cause can be named; Brief B fixes the underlying bug once named.

### Brief A — `GMAIL_ATTACHMENT_VISIBILITY_PATCH_1` (~20 min, AH1-authorable now)

Convert silent debug logs to structured WARNING/INFO so the next 1-2 poll cycles surface the actual failure mode.

**File:** `scripts/extract_gmail.py`

| Line | Change |
|---|---|
| 618 (function top) | Add `logger = logging.getLogger("sentinel.gmail")` at module top (if not present); add `logger.info(f"extract_attachments_text: message_id={message_id} parts={len(attachment_parts)}")` |
| 660-663 | Change `.debug(...)` → `.warning(f"inline-attachment extract FAILED — mid={message_id} file={filename} err_type={type(e).__name__} err={e}")` |
| 677-680 | Change `.debug(...)` → `.warning(f"gmail-attachment-download FAILED — mid={message_id} file={filename} err_type={type(e).__name__} err={e}")` |
| 703-706 | Already WARNING — extend to log `err_type={type(e).__name__}` |
| 707 (just after the block) | Add `logger.info(f"extract_attachments_text: message_id={message_id} stored {len(results)} attachments")` |
| 723-725 (`_extract_text_from_bytes`) | Change `.debug(...)` → `.warning(f"_extract_text_from_bytes FAILED — file={filename} ext={ext} err_type={type(e).__name__} err={e}")` |

**File:** `scripts/extract_gmail.py` line 444-450 — change `except Exception: pass` to `except Exception as _ae: logger.warning(f"format_thread: extract_attachments_text raised — mid={msg.get('id','?')} err_type={type(_ae).__name__} err={_ae}")`. This is the wholesale-swallow that hides everything.

No behavior change; only visibility. ≤15 line edit. Tests: existing pytest stays green; add 1 new unit test that mocks `_extract_text_from_bytes` to raise and asserts a WARNING log line is emitted with `err_type=`.

### Brief B — `GMAIL_POLLING_FIX_1` (size depends on Brief A's findings)

After Brief A ships and 1-2 poll cycles fire, Render logs will name the actual exception class + filename. Three most likely outcomes + fix shape:

1. **`pdfplumber.PSException` / `PDFSyntaxError` / `KeyError`** on PDF parsing → the pdfplumber transitive dependency changed on the 2026-05-16 13:22Z redeploy (pip resolution rolled forward `pdfminer.six` or similar). Fix: pin `pdfminer.six==<known-good>` in `requirements.txt`, or add a `try: text = pdfplumber...; except: try: text = pypdf2_fallback...` two-stage extractor.
2. **`HttpError 403 Insufficient Permission`** on `service.users().messages().attachments().get()` → Gmail OAuth scope drift. Refresh-token may have been re-issued by Google with reduced scopes during the 2026-05-16 deploy. Fix: re-mint refresh token with full `gmail.readonly` (+ `gmail.modify` for label removal).
3. **`hashlib.sha256` short-circuit / `store_document_full` returning the existing-id silently** → content_hash dedup at `memory/store_back.py:451-456` is matching against historical PDFs (template letters, signed-letter cover pages, EDF invoice header). Fix: include `message_id` or `received_date` in the content_hash input, or remove the dedup early-return for `email:%` source_paths.

**Out of scope for this brief but flag:** the runaway `capability_runner` daily cost (€92/day, 88% of total) is what's tripping the breaker daily. Separate diagnostic dispatch — possibly a Cortex Phase-3 specialist that's looping, or a dispatch that's re-firing every cycle without dedup.

## 5. Risks of the recommended fix

| Risk | Likelihood | Mitigation |
|---|---|---|
| Brief A WARNING spam if every attachment fails | medium | logs are 5-min cadence; ~5-15 WARNINGs/hour at worst until Brief B ships |
| Brief B (option 1) pdfplumber pin regresses a fix already shipped | low | run pytest + integration tests on a recent PDF before merge |
| Brief B (option 2) re-minting OAuth invalidates other Baker integrations | medium | mint to NEW token, test side-by-side, swap env var only after smoke |
| Brief B (option 3) removing dedup floods documents table with duplicates | medium | scope the dedup-skip strictly to `source_path LIKE 'email:%'`; keep dropbox dedup intact |
| Brief A logs leak filenames containing sensitive metadata to Render log retention | low | filenames already in `source_path` written to PG; no new exposure |

## 6. Fix brief vs rolling cleanup

**Recommendation: dispatch Brief A as a standalone ≤20-min fix now.** It's prerequisite for naming the root cause and has zero behavior risk. Defer Brief B to a second dispatch after 1-2 poll cycles produce diagnostic WARNING logs (~10 min wait post-deploy).

Do NOT fold this into a `STATE_FILE_REFRESH_2`-style rolling cleanup — it's an active operational defect (counterparty mail reasoning blind for 9 days) and rolling cleanups bundle non-urgent issues that benefit from batching. This one needs visibility-first → fix-second sequencing, with a clean handoff between briefs.

Separately: file `CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1` as a peer brief for the €92/day capability_runner spend that's driving the breaker. That's a compounding defect; without addressing it, even a perfectly-fixed extract_attachments_text will see its downstream classify/extract continue to be blocked daily.

---

## Investigation steps — what ran, what didn't

| Step | Status | Note |
|---|---|---|
| 1. Confirm disconnect via 4 SQL queries | ✅ done | §2a, §2b, §2c |
| 2. Read poll code path | ✅ done | §2f |
| 3. Manually exercise `check_new_emails()` with DEBUG | ⊘ skipped | would write to prod tables in unintended ways; the brief explicitly cautions; indirect evidence sufficient |
| 4. Verify Gmail-side delivery externally | ⊘ skipped | 53 counterparty emails with attachment-suggestive subjects already in `email_messages` since 2026-05-17 (§2c) — Gmail delivery confirmed by data |
| 5. git log scan 2026-05-14 to 2026-05-17 | ✅ done | §2g — no smoking-gun commit |
| 6. Render log scrape 24h `email_poll` | ✅ done | §2d, §2e |
| 7. Upstream-return early-exit anti-pattern | ✅ done | bluewin/exchange polls are wrapped in `try/except` non-fatal (lines 625-642) — not the issue; the silent-swallow inside `extract_attachments_text` is the analog defect §2h |

## References

- `briefs/BRIEF_GMAIL_POLLING_DIAGNOSTIC_1.md` — this brief
- `scripts/extract_gmail.py:618-708` `extract_attachments_text` — primary suspect site
- `scripts/extract_gmail.py:711-725` `_extract_text_from_bytes` — silent-swallow on extractor crash
- `memory/store_back.py:432-484` `store_document_full` — content-hash dedup
- `orchestrator/cost_monitor.py:50,538-567` `COST_HARD_STOP_EUR=100.0` + `check_circuit_breaker`
- Lead bus #1018 (dispatch)
- B4 bus #1021 (ACK)
- Deputy bus #1006 (original gap finding)
- AH1 bus #1004 (scheduler is fine, separate defect)
