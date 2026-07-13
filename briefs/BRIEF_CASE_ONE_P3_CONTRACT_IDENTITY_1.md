# BRIEF: CASE_ONE_P3_CONTRACT_IDENTITY_1 — CloudEvents typed envelope + server-side POST validation + id-only dedup + claim-check + execute-obligation contract + server-derived identity

> Case One bus-hardening **P3** (contract & identity, E4/E5/E11/E12/E13 + tonight's E20 crossed-gate
> duplication + the `deduped:true` false-positive storm). Authored by deputy (AH2, standing bus-health
> owner) from ARM's plan (vault #178, P3 section) + researcher validation #9763 (relayed lead #9913).
> **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.** Codex suspended (#9711) → Claude-side independent
> review before merge. Sequenced after P1 (delivery) + P2 (liveness, b1 build in flight).

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: backend-contract (brisen-lab bus daemon: typed envelope, POST-time schema validation, id-only dedup, claim-check artifact ref, server-derived identity) + fleet client scripts (envelope construction, full-text/artifact path)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: high

## Context

**Context Contract.** Repos: brisen-lab (`bus.py` POST path — envelope schema validation + id-only dedup + identity mapping; `db.py` — envelope columns + artifact table; migration) + fleet clients (`bus_post.sh` + helpers construct the typed envelope, supply full text or artifact reference). **No new service** — the typed-envelope layer sits on the existing Postgres source-of-truth (graduated path, transport doc). Builds ON P1 (idempotency key) + P2 (server identity is consumed by P2.1 owner-liveness) — do NOT redo them.

Contract & identity is the fourth story. The delivery layer is being made honest (P1) and the liveness layer detectable (P2), but the **message itself is still untyped, unbounded, and mis-attributable**: a positional post accepted an 8-char garbage body ("dispatch", E4); there is no first-class full-text/artifact path (E5); assignment truth is split across N prompt files and a file-mirror that diverges from the bus (E11/E13); and the shared-key path stamps the sender as `daemon` instead of the real seat (E12). Tonight added two contract defects live: every genuinely-new lead post returned `deduped:true` (content-hash dedup false-positive — the envelope has no unique `id` to dedup on), and lost/late messages caused **three duplicate gate legs** (E20, below).

### SCOPE DEDUPE (MANDATORY — lead #9563 discipline). Already shipped / owned elsewhere; this brief must NOT re-cover:
- **P1 client idempotency key** — authored in P1. P3 does NOT invent a second key: it PROMOTES the P1 key to the CloudEvents envelope `id` and makes that `id` the **sole** dedup basis (killing content-hash dedup). One key, two layers — P1 supplies it, P3 canonicalizes it.
- **P1 row+side-effect dedup transaction** — P3 changes only the dedup *predicate* (match on `id`, never on body hash), not the transaction.
- **P2 lease/heartbeat** — untouched. P3 supplies the server-derived identity that P2.1 owner-liveness was flagged to depend on; if P2 shipped first with the interim shared-key id, P3 upgrades it.
- **Row-level dedup (`023d95f`)** — the storage exists; P3 corrects what it keys on.

## Problem

Five contract/identity gaps — all reproduced live:

1. **No typed schema; POST accepts garbage (E4).** A positional post accepted an 8-char body ("dispatch") as a valid task. Natural-language prose as the *only* contract means malformed/underspecified messages enter the system and fail downstream, not at the door.
2. **No first-class full text / no artifact path (E5).** Bodies truncate with no explicit flag and no large-payload path; full-text was a per-seat retrofit. A reader cannot tell a complete message from a silently-clipped one.
3. **Assignment truth is split; startup scans instead of executes (E11/E13).** The execute-obligation lives in N prompt-file copies and a file-mirror that diverges from the bus, so a seat reports "here is what I would do" instead of acting, and two sources disagree on "my current assignment."
4. **Sender identity is forgeable / mislabeled (E12).** The shared-key MCP path stamps the sender as `daemon`; identity is client-asserted, not server-derived — so attribution, owner-liveness (P2.1), and audit all rest on a spoofable field.
5. **Dedup keys on the wrong thing → false-positives + lost messages (E20 / tonight).** With no unique envelope `id`, the daemon deduped on content: every genuinely-new lead post tonight returned `deduped:true`, and lost/late delivery (0-unacked false-clean 3×) caused **three duplicate gate legs** (my crossed b4 gate-2 dispatch; the gate order crossing the merge; the verdict crossing the merge). Dedup must key on a unique id, never on content.

## Fix (five pieces, build on P1 + P2)

### P3.1 — CloudEvents-shaped typed envelope + server-side POST validation + id-only dedup (E4 / E20)
Every message is a typed envelope with the CloudEvents-minimal required attributes: `id` (the P1 idempotency key — unique, the SOLE dedup basis), `source` (server-derived sender, per P3.4), `type`/`kind` (enum), `subject`/`topic`. The daemon validates the envelope **at POST** (E4): reject a body under a min length, an unknown `kind`/`topic` enum, or a missing required attribute — with a distinct 4xx + reason, never a silent accept. Dedup matches on `id` **only** — content-hash dedup is removed (fixes tonight's `deduped:true` on new content). Same `id` twice → true idempotent replay; different `id` → always a new message even if the body is identical.

### P3.2 — Full text first-class + claim-check for large payloads (E5)
Full text is first-class for every seat. When a payload exceeds the inline bound, the sender stores it as an **artifact** and the envelope carries a reference (claim-check pattern), not a truncated body. Any truncation is an **explicit flag** on the envelope — a reader can always tell complete from clipped, and can fetch the artifact by reference. No per-seat full-text retrofit.

### P3.3 — Execute-obligation in the contract; one source of assignment truth (E11/E13)
The envelope carries the **execute-obligation** as a typed field (`kind=assignment` implies "act on receipt", distinct from `reply`/`fyi`), so an assignment is not N prompt-file copies a fresh session may miss. The bus is the **single source of truth** for "my current assignment"; the file-mirror is derived-read-only or retired, so it cannot diverge (E13). A seat that receives `kind=assignment` executes, it does not scan-and-report (E11).

### P3.4 — Server-derived, unforgeable per-seat identity (E12)
The daemon maps the authenticated terminal key → the real seat slug **server-side**; the `source`/sender attribute is stamped by the server, never accepted from the client. Kill the shared-key path that stamps `daemon`. This gives P2.1 owner-liveness a trustworthy owner, makes audit attribution sound, and closes the easiest mislabeling path. (Full unforgeable tokens/rotation can phase; v1 minimum = server maps key→slug and refuses a client-supplied sender.)

## Files Modified

- brisen-lab: migration (envelope columns `id`/`source`/`kind`/`topic`/`truncated`/`artifact_ref`; artifact table; dedup unique index on `id`); `bus.py` (POST-time envelope schema validation + reject-with-reason; id-only dedup predicate replacing content-hash; server key→slug identity map; claim-check store/fetch); `db.py`. Reuse P1's idempotency key + dedup transaction — change only the predicate + add validation.
- Fleet clients: `bus_post.sh` + helpers construct the typed envelope (supply `id`, `kind`, `topic`; full text or artifact reference; never a raw positional body); ack/read helpers surface the `truncated` flag + artifact fetch.
- Tests in brisen-lab (garbage-body rejected at POST; unknown enum rejected; id-only dedup — same id dedups, identical body + new id does NOT; claim-check round-trip; truncation flag; server refuses client-supplied sender / maps key→slug) + a fleet round-trip test.

## Verification

1. **Typed validation (E4):** POST an 8-char / empty / unknown-kind body → rejected at POST with a distinct 4xx + reason; a well-formed envelope accepted. No garbage enters storage.
2. **id-only dedup (E20 / tonight):** same `id` twice → one row, idempotent replay; **identical body with a new `id` → a SECOND row** (proves content-hash dedup is gone, fixing the `deduped:true`-on-new-content defect).
3. **Claim-check + full text (E5):** an over-bound payload → stored as artifact, envelope carries the reference + `truncated` flag; reader fetches full text by reference; a complete message is distinguishable from a clipped one.
4. **Execute-obligation / single truth (E11/E13):** a `kind=assignment` envelope is the one canonical current-assignment; the file-mirror is derived/read-only and cannot diverge; a seat acts on receipt rather than scan-reporting.
5. **Server identity (E12):** a post over the shared-key path is stamped with the real seat slug server-side, NOT `daemon`; a client-supplied sender field is refused/overridden. Owner-liveness (P2.1) reads a trustworthy owner.
6. **Live AC:** post-deploy fleet drill — garbage rejected at the door, new-content posts never false-dedup, large payload round-trips by reference, every seat attributed correctly. Emit `POST_DEPLOY_AC_VERDICT v1`. Deputy folds contract/identity metrics into the delivery-health dashboard (P4).

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) typed envelope validated at POST, garbage rejected with reason; (2) dedup keys on `id` ONLY, content-hash dedup removed (new-content never false-dedups); (3) claim-check + explicit truncation flag, full text first-class; (4) execute-obligation typed + bus is single assignment truth, file-mirror can't diverge; (5) server-derived identity, shared-key `daemon` stamp killed; (6) live drill AC + `POST_DEPLOY_AC_VERDICT v1`.
- **done-state class:** production contract correctness → live fleet drill AC required (compile-clean ≠ done — Lesson #8).
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → builder implements → **independent Claude-side review by lead BEFORE merge** (codex suspended per Director #9711 until lifted; #9255 independent-verdict-before-merge holds, Claude-side) → lead merges → deploy → deputy verifies live as bus-health owner.
- **Harness-V2:** covered inline (Context Contract + done rubric + gate plan).

## Dedupe / cross-links

- Builds on P1 (idempotency key — P3 promotes it to envelope `id`) + P2 (consumes server identity for owner-liveness) + row dedup `023d95f` (changes the predicate). Does NOT redo them.
- Sequencing: P2 build is in flight at b1; if P2 ships with the interim shared-key id, P3.4 upgrades owner-liveness to the server-derived slug — call this dependency out in the build.
- P4 (behavioral enforcement + observability + delivery-health dashboard) consumes P3's typed envelope for tracing/correlation IDs — sequence P4 after P3.
- **NEW LEDGER CASE — E20 (crossed-gate duplication from lost/late delivery):** lost/late messages (0-unacked false-clean 3× tonight: gate order #9991, gate-2 verdict #9995/#9997, lead reply #10011) caused three duplicate/crossed work legs — my b4 gate-2 dispatch crossing an already-complete run, and the gate order + verdict both crossing the merge. Root cause spans P1 (delivery loss) + P3 (content-hash dedup false-positive `deduped:true`). Named per lead #10011.
- Evidence: training-file crosswalk E4/E5/E11/E12/E13 (`05_outputs/2026-07-12-case-one-bus-hardening-training-file.md`) + this session's live E20 + `deduped:true` storm + `bus_busy_retry` flap (checkpoint `_checkpoints/DEPUTY_ROLL_2026-07-13.md`).
</content>
