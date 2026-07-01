"""M365_GRAPH_MAIL_POLL_2: Microsoft Graph inbound mail poller (delta query).

Independent source adapter — mirrors triggers/exchange_poller.py. Produces
thread dicts and hands them to the shared sink _process_email_threads().
Dormant unless BAKER_USE_GRAPH=true (GraphClient.is_ready() is the single gate).
Never raises to the scheduler; one failure must not affect other pollers.
"""
from __future__ import annotations
import base64
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from kbl.graph_client import GraphClient
from config.settings import GraphConfig
from triggers.state import trigger_state
from triggers.sentinel_health import report_success, report_failure, should_skip_poll

logger = logging.getLogger(__name__)

_SOURCE = "graph_mail_poll"          # watermark key + per-folder cursor prefix
_SELECT = "id,conversationId,subject,from,receivedDateTime,body,isDraft,hasAttachments"

# GRAPH_INGEST_SCOPE_WIDEN_1 (Director-caught miss 2026-07-01, lead Option B):
# Graph has NO mailbox-wide message delta (/users/{u}/messages/delta does not
# exist — verified MS Learn message:delta docs). Delta is per-folder ONLY. So we
# widen ingestion from Inbox-only to WHOLE-MAILBOX by enumerating every mail
# folder and running a per-folder delta, minus the folders that must never be
# ingested as inbound signal.
#
# EXCLUDE (HARD): Sent Items / Drafts / Deleted Items / Junk Email — Sent/Drafts
# would ingest Dimitry's own outbound as inbound (pollutes Box 5 direction logic);
# Deleted/Junk are noise. Excluded by well-known folder id (locale-proof) with a
# displayName deny-set as belt-and-suspenders if well-known resolution hiccups.
_EXCLUDED_WELLKNOWN = ("sentitems", "drafts", "deleteditems", "junkemail")
_EXCLUDED_DISPLAYNAMES = frozenset(
    {"Sent Items", "Drafts", "Deleted Items", "Junk Email"}
)

# Delta-reset safety (LOAD-BEARING, AC3): a fresh per-folder delta with no state
# token would re-pull that folder's ENTIRE history — mailbox-wide that is the
# ~119k backlog the brief forbids. On first encounter of a folder we seed the
# initial delta with $filter=receivedDateTime ge {now - _SEED_LOOKBACK} (the ONLY
# $filter message:delta supports); Graph bakes the bound into the returned
# deltaLink so every subsequent poll is truly incremental. A small lookback gives
# a safety margin for mail that landed just before cutover without a real backfill.
_SEED_LOOKBACK = timedelta(days=1)

# Folder-hierarchy walk is bounded + cached (lead: "bound the folder walk to a
# cached list refreshed hourly, not every tick"). The poll runs every few minutes;
# re-enumerating the whole hierarchy each tick is needless Graph load. Cache the
# pollable-folder list for _FOLDER_CACHE_TTL; refresh lazily when stale.
_FOLDER_CACHE_TTL = timedelta(hours=1)
_FOLDER_WALK_GUARD = 500             # hard ceiling on hierarchy-walk iterations

# Lazy per-process folder-list cache. Reset by tests via _reset_folder_cache().
_folder_cache: dict = {"folders": None, "fetched_at": None}

# Surfaced, never-silently-swallowed counter: incremented whenever a single
# folder's poll fails (fetch None / mid-pagination None / exception). One folder
# failing must NOT abort the whole poll (lead), but the failure must stay visible.
_folder_poll_failures = 0


def folder_poll_failures() -> int:
    """Read the surfaced per-folder poll-failure counter (test/health hook)."""
    return _folder_poll_failures


def _reset_folder_cache() -> None:
    """Clear the folder-list cache (test hook; also safe at runtime — forces a
    re-enumeration on the next poll)."""
    _folder_cache["folders"] = None
    _folder_cache["fetched_at"] = None
# M365_GRAPH_ATTACHMENT_FETCH_DIAG_1: do NOT use $select on the /attachments
# COLLECTION. Graph 400s with "Could not find a property named contentBytes"
# when contentBytes is named in a collection $select (confirmed on Render, bus
# #4348) — the very bug that left hasAttachments=true messages with 0 stored.
# Requesting the collection WITHOUT $select returns full fileAttachment objects
# (id, name, contentType, size, isInline AND contentBytes), which is exactly
# what _capture_graph_attachments needs. $top is fine; $select is not.
_attachment_store_missing_logged = False

# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1: a message id's namespace (standard vs
# immutable) is NOT reliably derivable from its prefix OR character class —
# live-data probe (G2 codex F1) found AAMk ids WITH '-'/'_' (standard) and AAQk
# ids WITHOUT them (immutable). So we do NOT classify. Instead the by-id
# attachment fetch is ATTEMPT-THEN-FALLBACK: try the id in its native namespace
# first (never regresses the working standard path), and only on failure retry
# once carrying Prefer: IdType="ImmutableId" (catches immutable-form ids). This
# is namespace-agnostic by construction.
_IMMUTABLE_ID_HEADER = {"Prefer": 'IdType="ImmutableId"'}

# Surfaced, never-silently-dropped counter: incremented whenever a message with
# hasAttachments=true yields zero persisted attachment rows because the by-id
# Graph fetch FAILED on BOTH attempts (not because the message is genuinely
# attachment-empty). Exposed for the regression test + any future health probe.
_attachment_fetch_failures = 0


def attachment_fetch_failures() -> int:
    """Read the surfaced attachment-fetch-failure counter (test/health hook)."""
    return _attachment_fetch_failures


def _html_to_text(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:10000]              # cap, mirroring exchange_poller


def _to_thread(m: dict) -> dict | None:
    if m.get("isDraft"):
        return None
    sender = (m.get("from") or {}).get("emailAddress") or {}
    body = (m.get("body") or {})
    text_block = (
        f"Email Thread: {m.get('subject','(no subject)')}\n"
        f"From: {sender.get('name','')} <{sender.get('address','')}>\n"
        f"Date: {m.get('receivedDateTime','')}\n\n"
        f"{_html_to_text(body.get('content',''))}"
    )
    return {
        "text": text_block,
        "metadata": {
            "source": "graph",
            "thread_id": m.get("conversationId") or m.get("id"),
            "subject": m.get("subject", ""),
            "primary_sender": sender.get("name", ""),
            "primary_sender_email": sender.get("address", ""),
            "received_date": m.get("receivedDateTime", ""),
        },
    }


def fetch_attachment_raw_value(
    client: GraphClient,
    real_message_id: str,
    attachment_id: str,
    max_retries: int = 0,
):
    """F4 (BAKER_M365_LARGE_ATTACHMENT_FETCH_1): shared raw-byte attachment fetch.

    GET /users/{u}/messages/{realid}/attachments/{attid}/$value -> raw bytes,
    for BOTH fileAttachment (incl. >5 MiB, where the collection omits
    contentBytes) AND message/rfc822 itemAttachment (.eml MIME). Returns
    ``(payload_bytes, content_type)`` or ``None`` (referenceAttachment $value 405,
    or any fetch failure — caller leaves/records the row metadata_only).

    ``max_retries`` forwards to ``get_bytes`` 429/503 backoff (the backfill passes
    >0 to honor Retry-After; forward ingest passes 0 — a poll must not block).

    DELIBERATELY SEPARATE from ``_fetch_attachments_page`` (deputy-codex F4): that
    path carries the documented ``$select=contentBytes`` 400 quirk and must not be
    broadened. This is a single-attachment $value GET, no $select. URL-encodes the
    user, message id, and attachment id (base64 ids carry '/' '+').
    """
    if not real_message_id or not attachment_id:
        return None
    user = quote(client.cfg.mail_user, safe="")
    mid = quote(real_message_id, safe="")
    aid = quote(attachment_id, safe="")
    path = f"/users/{user}/messages/{mid}/attachments/{aid}/$value"
    return client.get_bytes(path, max_retries=max_retries)


def _insert_live_attachment(
    *,
    message_id: str,
    filename: str,
    mime_type: str,
    payload_bytes: bytes,
    provider_attachment_id: str | None = None,
):
    """Best-effort routed persistence (>5MiB->R2, <=5MiB->Neon); never breaks ingest.

    (Name retained from the pre-R2 helper — same role, now size-routed + carrying
    provider_attachment_id — so the live-poll parity + capture tests keep patching
    one stable seam.)"""
    global _attachment_store_missing_logged
    if not payload_bytes:
        return None
    try:
        from kbl.attachment_store import insert_attachment_routed
    except (ImportError, ModuleNotFoundError) as e:
        if not _attachment_store_missing_logged:
            logger.warning("Graph attachment store unavailable (non-fatal): %s", type(e).__name__)
            _attachment_store_missing_logged = True
        return None
    try:
        return insert_attachment_routed(
            message_id=message_id,
            source="graph",
            filename=filename,
            mime_type=mime_type,
            payload_bytes=payload_bytes,
            provider_attachment_id=provider_attachment_id,
        )
    except Exception as e:
        logger.warning("Graph attachment persist failed (non-fatal): %s", type(e).__name__)
        return None


def _persist_attachment_meta(
    *,
    message_id: str,
    filename: str,
    mime_type: str,
    size_bytes,
    provider_attachment_id: str,
    real_message_id: str | None = None,
):
    """Record a byte-empty attachment row (referenceAttachment / fetch failure) so
    the attachment is never a SILENT drop — it shows as metadata_only, eligible
    for a later on-demand read-path or backfill fetch. Best-effort.

    Persists ``real_message_id`` (the addressable AAMk id) + provider_attachment_id
    so the read-path self-heal can fetch Graph directly even though ``message_id``
    here is the conversationId store key (G3 F1)."""
    if not provider_attachment_id:
        return None
    try:
        from kbl.attachment_store import insert_attachment_meta
    except (ImportError, ModuleNotFoundError):
        return None
    try:
        return insert_attachment_meta(
            message_id=message_id,
            source="graph",
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            meta_key=provider_attachment_id,
            provider_attachment_id=provider_attachment_id,
            real_message_id=real_message_id,
        )
    except Exception as e:
        logger.warning("Graph attachment meta-record failed (non-fatal): %s", type(e).__name__)
        return None


def _fetch_attachments_page(client: GraphClient, message_id: str):
    """By-id attachment fetch, ATTEMPT-THEN-FALLBACK (G2 codex F1).

    Returns (page_or_None, used_immutable). Tries the id in its NATIVE namespace
    first (no Prefer — never regresses standard AAMk ids); only if that returns
    None retries once with Prefer: IdType="ImmutableId" (catches immutable AAQk
    ids). Namespace-agnostic: no prefix/char-class guessing. None iff BOTH fail.

    URL-ENCODES the message id (and mail_user, belt-and-suspenders per codex-arch
    #4337): standard AAMk ids are base64 and contain '/' and '+', which break the
    URL path route when interpolated raw (a '/' splits the path -> Graph 400/404
    -> attachments silently dropped). quote(..., safe="") percent-encodes them.
    """
    user = quote(client.cfg.mail_user, safe="")
    mid = quote(message_id, safe="")
    path = f"/users/{user}/messages/{mid}/attachments"
    # NO $select: contentBytes in a collection $select makes Graph 400 (bus #4348).
    # Bare collection GET returns full fileAttachment objects incl contentBytes.
    params = {"$top": 50}
    page = client.get(path, params=params)                       # attempt 1: native
    if page is not None:
        return page, False
    page = client.get(path, params=params, extra_headers=_IMMUTABLE_ID_HEADER)  # attempt 2: immutable
    return page, True


def _capture_graph_attachments(client: GraphClient, m: dict) -> int:
    """Store Graph file attachments for a live message, non-fatally.

    M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1:
    - The by-id attachment READ uses the real per-message id (m['id']) and is
      attempt-then-fallback (native, then Prefer: IdType="ImmutableId"). A fetch
      that fails on BOTH attempts for a hasAttachments=true message is surfaced
      LOUDLY (ERROR + counter), never silently dropped.
    - The STORE KEY (conversationId-keying, Option (a) #4317) is thread_id =
      (conversationId or id), MATCHING email_messages.message_id and the
      baker_email_attachment_read lookup (email_trigger.py:933 keys every email
      source by thread_id). Persisting attachments under the real per-message id
      would key them by a value the read tool never queries — the systemic
      mismatch that made captured attachments unreachable.
    """
    global _attachment_fetch_failures
    fetch_id = m.get("id")
    if not m.get("hasAttachments") or not fetch_id:
        return 0
    # Read by the real message id; store under thread_id (conversationId-or-id).
    store_key = m.get("conversationId") or fetch_id
    try:
        page, used_immutable = _fetch_attachments_page(client, fetch_id)
        if page is None:
            # Both native + ImmutableId failed for a message that declares
            # attachments — silent-skip class bug (Lesson #107). Surface loudly;
            # do NOT let it look like a true-empty message.
            _attachment_fetch_failures += 1
            logger.error(
                "Graph attachment fetch FAILED on both native + ImmutableId "
                "(hasAttachments=true, 0 stored) — attachments NOT persisted, "
                "surfaced (count=%d)",
                _attachment_fetch_failures,
            )
            return 0
        stored = 0
        for att in page.get("value", []):
            if att.get("isInline"):
                continue
            graph_att_id = att.get("id")
            name = att.get("name", "")
            ctype = att.get("contentType") or "application/octet-stream"
            payload = None
            encoded = att.get("contentBytes")
            if encoded:
                try:
                    payload = base64.b64decode(encoded)
                except Exception as e:
                    logger.warning("Graph attachment decode failed (non-fatal): %s", type(e).__name__)
                    payload = None
            if payload is None:
                # F1: contentBytes absent (large fileAttachment / rfc822
                # itemAttachment) OR decode failed — DO NOT silently skip. Fetch
                # the raw bytes by $value (F4 shared helper). This is the fix for
                # the 2,628-row byte-empty residue going forward.
                raw = fetch_attachment_raw_value(client, fetch_id, graph_att_id) if graph_att_id else None
                if raw is not None:
                    payload, fetched_ct = raw
                    if fetched_ct:
                        ctype = fetched_ct
            if payload is None:
                # $value unavailable (referenceAttachment 405 / fetch failure):
                # record metadata_only so the attachment is NEVER a silent drop.
                # store_key may be the conversationId; real_message_id=fetch_id is
                # the addressable AAMk id the read-path self-heal needs (G3 F1).
                _persist_attachment_meta(
                    message_id=store_key, filename=name, mime_type=ctype,
                    size_bytes=att.get("size"), provider_attachment_id=graph_att_id,
                    real_message_id=fetch_id,
                )
                continue
            att_row_id = _insert_live_attachment(
                message_id=store_key,
                filename=name,
                mime_type=ctype,
                payload_bytes=payload,
                provider_attachment_id=graph_att_id,
            )
            if att_row_id:
                stored += 1
        if stored == 0:
            # Fetch SUCCEEDED but nothing persisted — surfaced (not silent), yet
            # distinct from the FAILED path above: this is benign (all-inline /
            # signature images), so WARNING + no failure-counter bump.
            logger.warning(
                "Graph attachments: hasAttachments=true but 0 file rows stored "
                "(fetch ok via %s namespace — likely all-inline).",
                "immutable" if used_immutable else "native",
            )
        return stored
    except Exception as e:
        # An exception on a hasAttachments=true message also dropped attachments —
        # surface loudly + count, same class as the None-fetch failure above.
        _attachment_fetch_failures += 1
        logger.error(
            "Graph attachment capture FAILED (hasAttachments=true): %s — "
            "attachments NOT persisted, surfaced (count=%d)",
            type(e).__name__,
            _attachment_fetch_failures,
        )
        return 0


def _excluded_folder_ids(client: GraphClient) -> set:
    """Resolve the ids of the never-ingest folders (Sent/Drafts/Deleted/Junk).

    Resolves each well-known folder by its locale-proof name (GET
    /users/{u}/mailFolders/{wellKnownName}). Fault-tolerant: a well-known GET that
    fails (or returns None) is logged and skipped — we degrade to the displayName
    deny-set at walk time rather than crash the whole poll. Never raises.
    """
    user = quote(client.cfg.mail_user, safe="")
    ids: set = set()
    for wk in _EXCLUDED_WELLKNOWN:
        try:
            f = client.get(f"/users/{user}/mailFolders/{wk}", params={"$select": "id"})
        except Exception as e:                       # pragma: no cover - defensive
            logger.warning("graph mail: well-known folder %s lookup errored (non-fatal): %s", wk, type(e).__name__)
            continue
        if f and f.get("id"):
            ids.add(f["id"])
        else:
            logger.warning("graph mail: well-known folder %s did not resolve — relying on displayName deny-set", wk)
    return ids


def _enumerate_folders(client: GraphClient, excluded_ids: set) -> list:
    """Walk the whole mail-folder hierarchy (incl. nested childFolders) and return
    the pollable folders as ``[{"id", "displayName"}, ...]``.

    Excluded folders (id in ``excluded_ids`` OR displayName in the deny-set) are
    dropped AND their subtree is pruned — never recurse into Deleted Items / Junk /
    Sent / Drafts children. Iterative stack walk, bounded by _FOLDER_WALK_GUARD.
    Fault-tolerant: a sublevel fetch returning None just skips that subtree (logged);
    only a totally empty result signals failure (handled by the caller — a real
    mailbox always has Inbox). Never raises.
    """
    user = quote(client.cfg.mail_user, safe="")
    out: list = []
    stack = [f"/users/{user}/mailFolders"]          # start at the top level
    guard = 0
    while stack and guard < _FOLDER_WALK_GUARD:
        path = stack.pop()
        page = client.get(path, params={"$top": 100, "$select": "id,displayName,childFolderCount"})
        if page is None:
            logger.warning("graph mail: folder-level fetch returned None (subtree skipped)")
            continue
        while page is not None and guard < _FOLDER_WALK_GUARD:
            guard += 1
            for f in page.get("value", []):
                fid = f.get("id")
                if not fid:
                    continue
                name = f.get("displayName", "") or ""
                if fid in excluded_ids or name in _EXCLUDED_DISPLAYNAMES:
                    continue                         # drop folder + prune its subtree
                out.append({"id": fid, "displayName": name})
                if f.get("childFolderCount", 0):
                    stack.append(f"/users/{user}/mailFolders/{quote(fid, safe='')}/childFolders")
            nxt = page.get("@odata.nextLink")
            page = client.get_url(nxt) if nxt else None
    return out


def _get_pollable_folders(client: GraphClient) -> list:
    """Return the cached pollable-folder list, refreshing when older than
    _FOLDER_CACHE_TTL. On a refresh, re-resolve the excluded ids + re-walk. A refresh
    that yields an empty list does NOT overwrite a good cache (transient walk failure
    keeps the last known-good set); an empty result on a cold cache is returned as-is
    for the caller to treat as failure. Never raises."""
    now = datetime.now(timezone.utc)
    fetched = _folder_cache.get("fetched_at")
    cached = _folder_cache.get("folders")
    if cached is not None and fetched is not None and (now - fetched) < _FOLDER_CACHE_TTL:
        return cached
    excluded = _excluded_folder_ids(client)
    folders = _enumerate_folders(client, excluded)
    if folders:
        _folder_cache["folders"] = folders
        _folder_cache["fetched_at"] = now
        return folders
    # Cold cache + empty walk → return empty (caller raises). Warm cache + transient
    # empty → keep serving the last good list rather than go blind.
    return cached if cached is not None else folders


def _folder_seed_filter(now: datetime | None = None) -> str:
    """The $filter for a first-encounter (un-cursored) folder delta: the ONLY
    message:delta filter Graph supports — receivedDateTime ge {now - _SEED_LOOKBACK}.
    Bounds the initial sync so cutover does NOT trigger a full-history backfill."""
    now = now or datetime.now(timezone.utc)
    seed = now - _SEED_LOOKBACK
    return f"receivedDateTime ge {seed.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def _poll_folder(client: GraphClient, folder: dict) -> list:
    """Poll one folder's message delta. Returns thread dicts.

    First encounter (no stored cursor) seeds the delta from now-_SEED_LOOKBACK; else
    follows the stored per-folder @odata.deltaLink. RAISES on a ready-but-None page
    (auth/HTTP failure, NOT empty) so the caller counts it and does NOT advance THIS
    folder's cursor — the folder retries next tick. A genuinely quiet folder returns a
    page with value:[] + a deltaLink (persisted; no raise)."""
    folder_id = folder["id"]
    src_key = f"{_SOURCE}:folder:{folder_id}"
    cursor = trigger_state.get_cursor(src_key)       # stored per-folder deltaLink, or None
    if cursor:
        page = client.get_url(cursor)                # host-pinned follow
    else:
        page = client.get(
            f"/users/{client.cfg.mail_user}/mailFolders/{quote(folder_id, safe='')}/messages/delta",
            params={"$select": _SELECT, "$top": 50, "$filter": _folder_seed_filter()},
        )
    if page is None:                 # ready but no response → auth/HTTP/429 failure, NOT empty
        raise RuntimeError(f"graph mail: folder {folder_id} delta returned None while ready")

    results: list = []
    guard = 0
    while page is not None and guard < 50:           # bounded pagination
        guard += 1
        for m in page.get("value", []):
            if "@removed" in m:                      # delta tombstone / move-out
                continue
            t = _to_thread(m)
            if t:
                _capture_graph_attachments(client, m)
                results.append(t)
        nxt = page.get("@odata.nextLink")
        delta = page.get("@odata.deltaLink")
        if nxt:
            page = client.get_url(nxt)
            if page is None:         # mid-pagination failure → raise BEFORE persisting a partial cursor
                raise RuntimeError(f"graph mail: folder {folder_id} nextLink returned None (HTTP failure mid-pagination)")
            continue
        if delta:
            trigger_state.set_cursor(src_key, delta)  # persist ONLY on clean completion of THIS folder
        break
    return results


def poll_graph_mail() -> list:
    """Pull new mail across the WHOLE mailbox via per-folder delta. Returns thread
    dicts (same shape as poll_exchange).

    GRAPH_INGEST_SCOPE_WIDEN_1: enumerate every mail folder (minus Sent/Drafts/
    Deleted/Junk) and run a per-folder delta with a per-folder cursor. Fault-tolerant
    per folder — one folder's fetch error is counted + logged but does NOT abort the
    poll (lead). Two failure modes still RAISE (so the caller reports failure and does
    NOT advance the watermark, preserving the no-silent-success invariant):
      1. folder enumeration yields nothing while ready (a real mailbox always has
         Inbox → empty means an auth/HTTP failure listing folders), and
      2. EVERY enumerated folder failed to poll (systemic auth/HTTP failure).
    Returns [] only when dormant.
    """
    global _folder_poll_failures
    client = GraphClient(GraphConfig())
    if not client.is_ready():
        return []                    # dormant gate — no token, no HTTP

    folders = _get_pollable_folders(client)
    if not folders:                  # ready but no folders → listing failed, NOT empty
        raise RuntimeError("graph mail: folder enumeration returned no folders while ready (auth/HTTP failure)")

    results: list = []
    failures = 0
    for folder in folders:
        try:
            results.extend(_poll_folder(client, folder))
        except Exception as e:
            failures += 1
            _folder_poll_failures += 1
            logger.error(
                "graph mail: folder %s poll FAILED (non-fatal, this folder's cursor "
                "NOT advanced; count=%d): %s",
                folder.get("id"), _folder_poll_failures, type(e).__name__,
            )
            continue
    if failures and failures == len(folders):
        # Not one folder succeeded → systemic failure, not a quiet mailbox. Raise so
        # check_new_graph_messages reports failure + does not advance the watermark.
        raise RuntimeError(
            f"graph mail: ALL {failures} enumerated folders failed to poll while ready (systemic failure)"
        )
    return results


def check_new_graph_messages():
    """Scheduler entry — every GRAPH_MAIL_CHECK_INTERVAL seconds. Independent try/except.

    Fully inert when dormant (G0 v2 Finding 3): if BAKER_USE_GRAPH is off, return BEFORE
    any should_skip_poll / set_watermark / report_success — zero DB or health side effects,
    so a disabled source never looks 'healthy' in sentinel_health.
    """
    if not GraphClient(GraphConfig()).is_ready():
        return                       # dormant — zero side effects at all
    if should_skip_poll("graph_mail"):
        return
    try:
        threads = poll_graph_mail()
        if threads:
            logger.info("Graph mail: %d new threads to process", len(threads))
            from triggers.email_trigger import _process_email_threads
            _process_email_threads(threads)
        trigger_state.set_watermark(_SOURCE, datetime.now(timezone.utc))
        report_success("graph_mail")
    except Exception as e:
        report_failure("graph_mail", str(e))
        logger.error("Graph mail trigger failed (non-fatal): %s", type(e).__name__)
