"""M365_GRAPH_MAIL_POLL_2 — unit tests for the Graph mail poller (mocked Graph).

Covers the 6 acceptance-criteria cases:
  1. dormant (is_ready False) → fully inert (no Graph/sink/DB/health side effects)
  2. 2 delta messages → 2 thread dicts in the exact sink shape
  3. @removed tombstones skipped (and drafts skipped)
  4. returned @odata.deltaLink persisted via set_cursor
  5. @odata.nextLink pagination followed
  6. failure path: ready-but-None raises in poll; caller reports_failure and does
     NOT advance watermark/cursor (silent-success bug must not regress)
"""
from unittest import mock

import pytest

import triggers.graph_mail_trigger as gmt


def _mk_msg(mid, conv, subject, name, addr, date, body="<p>hi</p>",
            is_draft=False):
    return {
        "id": mid,
        "conversationId": conv,
        "subject": subject,
        "from": {"emailAddress": {"name": name, "address": addr}},
        "receivedDateTime": date,
        "body": {"contentType": "html", "content": body},
        "isDraft": is_draft,
    }


def _fake_client(ready=True):
    client = mock.MagicMock(name="GraphClient")
    client.is_ready.return_value = ready
    client.cfg.mail_user = "dvallen@brisengroup.com"
    return client


@pytest.fixture(autouse=True)
def _reset_folder_state():
    """GRAPH_INGEST_SCOPE_WIDEN_1: the folder-list cache + per-folder failure
    counter are per-process module state — reset around every test."""
    gmt._reset_folder_cache()
    gmt._folder_poll_failures = 0
    yield
    gmt._reset_folder_cache()
    gmt._folder_poll_failures = 0


def _folders(*specs):
    """Build a pollable-folder list; each spec is an id str or (id, displayName)."""
    out = []
    for s in specs:
        if isinstance(s, tuple):
            out.append({"id": s[0], "displayName": s[1]})
        else:
            out.append({"id": s, "displayName": s})
    return out


# ── Test 1: dormant → fully inert ────────────────────────────────────────────
def test_dormant_is_fully_inert():
    client = _fake_client(ready=False)
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "should_skip_poll") as skip, \
         mock.patch.object(gmt, "report_success") as ok, \
         mock.patch.object(gmt, "report_failure") as fail, \
         mock.patch.object(gmt.trigger_state, "set_watermark") as wm, \
         mock.patch.object(gmt.trigger_state, "set_cursor") as cur, \
         mock.patch("triggers.email_trigger._process_email_threads") as sink:
        gmt.check_new_graph_messages()

    # zero Graph HTTP
    client.get.assert_not_called()
    client.get_url.assert_not_called()
    # zero DB + health + sink side effects
    skip.assert_not_called()
    ok.assert_not_called()
    fail.assert_not_called()
    wm.assert_not_called()
    cur.assert_not_called()
    sink.assert_not_called()


def test_poll_dormant_returns_empty():
    client = _fake_client(ready=False)
    with mock.patch.object(gmt, "GraphClient", return_value=client):
        assert gmt.poll_graph_mail() == []
    client.get.assert_not_called()
    client.get_url.assert_not_called()


# ── Test 2: 2 messages → 2 thread dicts in exact shape ───────────────────────
def test_two_messages_exact_thread_shape():
    page = {
        "value": [
            _mk_msg("m1", "c1", "Subject One", "Alice", "alice@x.com",
                    "2026-06-04T10:00:00Z", body="<b>Body one</b>"),
            _mk_msg("m2", "c2", "Subject Two", "Bob", "bob@y.com",
                    "2026-06-04T10:05:00Z", body="Body two"),
        ],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?$deltatoken=abc",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("inbox-id")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()

    assert len(threads) == 2
    t0 = threads[0]
    assert set(t0.keys()) == {"text", "metadata"}
    assert set(t0["metadata"].keys()) == {
        "source", "thread_id", "message_id", "subject", "primary_sender",
        "primary_sender_email", "received_date",
    }
    assert t0["metadata"] == {
        "source": "graph",
        "thread_id": "c1",
        # BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1: per-message id (m['id']) carried for the
        # sink's per-message dedup; conversationId stays in thread_id.
        "message_id": "m1",
        "subject": "Subject One",
        "primary_sender": "Alice",
        "primary_sender_email": "alice@x.com",
        "received_date": "2026-06-04T10:00:00Z",
    }
    assert t0["text"].startswith("Email Thread: Subject One")
    assert "Body one" in t0["text"]
    assert "<b>" not in t0["text"]            # HTML stripped
    assert threads[1]["metadata"]["thread_id"] == "c2"


# ── AC1: a message in a NON-Inbox folder is ingested ─────────────────────────
def test_non_inbox_folder_message_ingested():
    """AC1: a rule-filed subfolder message reaches the sink shape (the exact
    Siegfried-class miss). Inbox-only scope would never see it."""
    page = {
        "value": [_mk_msg("mf", "cf", "Filed", "Siegfried", "s@brandner.at",
                          "2026-07-01T13:09:00Z")],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?$deltatoken=sub",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders",
                           return_value=_folders(("sub-folder-id", "Aukera"))), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()

    assert [t["metadata"]["thread_id"] for t in threads] == ["cf"]
    # polled the subfolder's delta, not Inbox's
    called_path = client.get.call_args_list[0].args[0]
    assert "mailFolders/sub-folder-id/messages/delta" in called_path


# ── Test 3: @removed tombstones + drafts skipped ─────────────────────────────
def test_removed_and_drafts_skipped():
    page = {
        "value": [
            _mk_msg("m1", "c1", "Real", "Alice", "alice@x.com",
                    "2026-06-04T10:00:00Z"),
            {"id": "m2", "@removed": {"reason": "deleted"}},
            _mk_msg("m3", "c3", "Draft", "Me", "me@x.com",
                    "2026-06-04T10:10:00Z", is_draft=True),
        ],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?$deltatoken=z",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("inbox-id")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()

    assert len(threads) == 1
    assert threads[0]["metadata"]["thread_id"] == "c1"


# ── Test 4: per-folder deltaLink persisted under the folder-keyed source ─────
def test_deltalink_persisted_per_folder():
    delta = "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=persist-me"
    page = {"value": [], "@odata.deltaLink": delta}
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-9")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor:
        threads = gmt.poll_graph_mail()

    assert threads == []
    # cursor keyed PER FOLDER (graph_mail_poll:folder:<id>), not the bare source
    set_cursor.assert_called_once_with("graph_mail_poll:folder:fid-9", delta)


def test_stored_cursor_followed_via_get_url():
    """Cursored folder → followed via get_url (host-pin), not a fresh delta get()."""
    stored = "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=stored"
    page = {"value": [], "@odata.deltaLink": stored + "-next"}
    client = _fake_client(ready=True)
    client.get_url.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-1")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=stored), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        gmt.poll_graph_mail()

    client.get_url.assert_called_once_with(stored)
    client.get.assert_not_called()      # no fresh delta when a cursor exists


# ── AC3: first-encounter delta is SEEDED (no full-history backfill) ──────────
def test_first_encounter_seeds_receiveddatetime_filter():
    """AC3: an un-cursored folder's initial delta carries $filter=receivedDateTime
    ge {seed} so cutover pulls only recent mail, NOT the folder's whole history."""
    page = {"value": [], "@odata.deltaLink": "d"}
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-7")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        gmt.poll_graph_mail()

    params = client.get.call_args_list[0].kwargs.get("params") or {}
    assert params.get("$filter", "").startswith("receivedDateTime ge ")
    assert params.get("$top") == 50


def test_seed_filter_format():
    """The seed filter uses now - _SEED_LOOKBACK, Graph's ONLY supported message
    delta filter form."""
    from datetime import datetime, timezone
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    got = gmt._folder_seed_filter(now)
    expected_seed = (now - gmt._SEED_LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert got == f"receivedDateTime ge {expected_seed}"


# ── Test 5: nextLink pagination followed within a folder ─────────────────────
def test_nextlink_pagination_followed():
    next_url = "https://graph.microsoft.com/v1.0/me/delta?$skiptoken=page2"
    delta = "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=final"
    page1 = {
        "value": [_mk_msg("m1", "c1", "P1", "A", "a@x.com",
                          "2026-06-04T10:00:00Z")],
        "@odata.nextLink": next_url,
    }
    page2 = {
        "value": [_mk_msg("m2", "c2", "P2", "B", "b@x.com",
                          "2026-06-04T10:05:00Z")],
        "@odata.deltaLink": delta,
    }
    client = _fake_client(ready=True)
    client.get.return_value = page1
    client.get_url.return_value = page2
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-2")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor:
        threads = gmt.poll_graph_mail()

    client.get_url.assert_called_once_with(next_url)
    assert [t["metadata"]["thread_id"] for t in threads] == ["c1", "c2"]
    set_cursor.assert_called_once_with("graph_mail_poll:folder:fid-2", delta)


# ── AC4: delta semantics dedup — a cursored quiet folder re-emits nothing ────
def test_cursored_quiet_folder_reemits_nothing():
    """AC4 (poller layer): once a folder's deltaLink is stored, following it returns
    only NEW changes — an unchanged folder yields []. (Boundary dups are absorbed by
    the unchanged store-layer ON CONFLICT on message_id.)"""
    client = _fake_client(ready=True)
    client.get_url.return_value = {"value": [], "@odata.deltaLink": "d2"}
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-3")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value="stored-delta"), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()
    assert threads == []


# ── AC5 + failure semantics ──────────────────────────────────────────────────
def test_single_folder_none_raises_total_failure():
    """One-folder mailbox whose delta returns None → all folders failed → poll RAISES
    (no silent success; watermark not advanced by the caller)."""
    client = _fake_client(ready=True)
    client.get.return_value = None
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-1")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None):
        with pytest.raises(RuntimeError):
            gmt.poll_graph_mail()


def test_one_folder_failure_does_not_abort_poll():
    """AC5: folder A's fetch fails, folder B succeeds → B's mail still ingested, poll
    does NOT raise, the failure is surfaced via the counter."""
    good = {"value": [_mk_msg("m2", "c2", "OK", "B", "b@x.com",
                              "2026-07-01T09:00:00Z")],
            "@odata.deltaLink": "dl"}
    client = _fake_client(ready=True)
    client.get.side_effect = [None, good]     # folder A → None (fails); folder B → page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders",
                           return_value=_folders("bad-id", "good-id")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"):
        threads = gmt.poll_graph_mail()

    assert [t["metadata"]["thread_id"] for t in threads] == ["c2"]
    assert gmt.folder_poll_failures() == 1     # A's failure surfaced, not swallowed


def test_empty_folder_enumeration_raises():
    """Ready but folder enumeration yields nothing → listing failed (a real mailbox
    always has Inbox) → RAISE, don't silently succeed."""
    client = _fake_client(ready=True)
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=[]):
        with pytest.raises(RuntimeError):
            gmt.poll_graph_mail()


def test_nextlink_none_mid_pagination_raises():
    next_url = "https://graph.microsoft.com/v1.0/me/delta?$skiptoken=page2"
    page1 = {"value": [], "@odata.nextLink": next_url}
    client = _fake_client(ready=True)
    client.get.return_value = page1
    client.get_url.return_value = None
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-1")), \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor:
        with pytest.raises(RuntimeError):
            gmt.poll_graph_mail()
    set_cursor.assert_not_called()     # no partial cursor persisted


def test_check_failure_reports_and_does_not_advance():
    client = _fake_client(ready=True)
    client.get.return_value = None     # ready-but-None → poll raises
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("fid-1")), \
         mock.patch.object(gmt, "should_skip_poll", return_value=False), \
         mock.patch.object(gmt, "report_success") as ok, \
         mock.patch.object(gmt, "report_failure") as fail, \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor") as set_cursor, \
         mock.patch.object(gmt.trigger_state, "set_watermark") as set_wm:
        gmt.check_new_graph_messages()    # must NOT raise to scheduler

    fail.assert_called_once()
    assert fail.call_args[0][0] == "graph_mail"
    ok.assert_not_called()
    set_wm.assert_not_called()         # watermark NOT advanced on failure
    set_cursor.assert_not_called()     # cursor NOT advanced on failure


def test_check_success_advances_watermark_and_calls_sink():
    page = {
        "value": [_mk_msg("m1", "c1", "S", "A", "a@x.com",
                          "2026-06-04T10:00:00Z")],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/delta?$deltatoken=ok",
    }
    client = _fake_client(ready=True)
    client.get.return_value = page
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_get_pollable_folders", return_value=_folders("inbox-id")), \
         mock.patch.object(gmt, "should_skip_poll", return_value=False), \
         mock.patch.object(gmt, "report_success") as ok, \
         mock.patch.object(gmt, "report_failure") as fail, \
         mock.patch.object(gmt.trigger_state, "get_cursor", return_value=None), \
         mock.patch.object(gmt.trigger_state, "set_cursor"), \
         mock.patch.object(gmt.trigger_state, "set_watermark") as set_wm, \
         mock.patch("triggers.email_trigger._process_email_threads") as sink:
        gmt.check_new_graph_messages()

    sink.assert_called_once()
    assert len(sink.call_args[0][0]) == 1     # one thread handed to sink
    set_wm.assert_called_once()
    ok.assert_called_once_with("graph_mail")
    fail.assert_not_called()


# ── Folder enumeration + exclusion (AC2) ─────────────────────────────────────
def test_enumerate_includes_nested_childfolders():
    """The walk descends into childFolders so rule-filed subfolders are covered."""
    top = {"value": [
        {"id": "inbox-id", "displayName": "Inbox", "childFolderCount": 1},
    ]}
    children = {"value": [
        {"id": "aukera-id", "displayName": "Aukera", "childFolderCount": 0},
    ]}
    client = _fake_client(ready=True)
    # top-level list, then the childFolders of inbox-id
    client.get.side_effect = [top, children]
    folders = gmt._enumerate_folders(client, excluded_ids=set())
    ids = {f["id"] for f in folders}
    assert ids == {"inbox-id", "aukera-id"}


def test_excluded_wellknown_and_subtree_pruned():
    """AC2: Sent/Drafts/Deleted/Junk are dropped by id AND their subtree is pruned
    (no descent into a Deleted Items childFolder)."""
    top = {"value": [
        {"id": "inbox-id", "displayName": "Inbox", "childFolderCount": 0},
        {"id": "deleted-id", "displayName": "Deleted Items", "childFolderCount": 1},
        {"id": "junk-name-id", "displayName": "Junk Email", "childFolderCount": 0},
    ]}
    client = _fake_client(ready=True)
    client.get.side_effect = [top]     # only ONE call → Deleted subtree NOT walked
    folders = gmt._enumerate_folders(client, excluded_ids={"deleted-id"})
    ids = {f["id"] for f in folders}
    assert ids == {"inbox-id"}                    # deleted (by id) + junk (by name) gone
    assert client.get.call_count == 1             # excluded subtree pruned (no 2nd call)


def test_excluded_folder_ids_resolves_wellknown():
    """Each well-known folder name is resolved to its real id; complete=True."""
    client = _fake_client(ready=True)
    client.get.side_effect = [
        {"id": "sent-id"}, {"id": "drafts-id"},
        {"id": "deleted-id"}, {"id": "junk-id"},
    ]
    ids, complete = gmt._excluded_folder_ids(client)
    assert ids == {"sent-id", "drafts-id", "deleted-id", "junk-id"}
    assert complete is True
    # resolved via well-known names (locale-proof), one GET each
    paths = [c.args[0] for c in client.get.call_args_list]
    assert any(p.endswith("/mailFolders/sentitems") for p in paths)
    assert any(p.endswith("/mailFolders/junkemail") for p in paths)


def test_excluded_folder_ids_incomplete_when_lookup_none():
    """codex G3: a well-known lookup returning None marks the set INCOMPLETE (so the
    caller fails closed) — never silently trusted as authoritative."""
    client = _fake_client(ready=True)
    client.get.side_effect = [
        {"id": "sent-id"}, None,            # drafts lookup fails
        {"id": "deleted-id"}, {"id": "junk-id"},
    ]
    ids, complete = gmt._excluded_folder_ids(client)
    assert complete is False
    assert "sent-id" in ids                 # the ones that resolved are still returned


def test_folder_list_cached_not_reenumerated_within_ttl():
    """lead: bound the walk to a cached list, not every tick. Two polls within TTL →
    one enumeration."""
    client = _fake_client(ready=True)
    with mock.patch.object(gmt, "_excluded_folder_ids", return_value=(set(), True)) as exc, \
         mock.patch.object(gmt, "_enumerate_folders",
                           return_value=_folders("inbox-id")) as enum:
        first = gmt._get_pollable_folders(client)
        second = gmt._get_pollable_folders(client)
    assert first == second == _folders("inbox-id")
    enum.assert_called_once()          # cached — walked once, not twice
    exc.assert_called_once()


def test_folder_cache_refreshes_after_ttl():
    """A stale cache (older than TTL) triggers a fresh enumeration."""
    client = _fake_client(ready=True)
    from datetime import datetime, timezone, timedelta
    with mock.patch.object(gmt, "_excluded_folder_ids", return_value=(set(), True)), \
         mock.patch.object(gmt, "_enumerate_folders",
                           return_value=_folders("inbox-id")) as enum:
        gmt._get_pollable_folders(client)
        # age the cache past the TTL
        gmt._folder_cache["fetched_at"] = (
            datetime.now(timezone.utc) - gmt._FOLDER_CACHE_TTL - timedelta(minutes=1)
        )
        gmt._get_pollable_folders(client)
    assert enum.call_count == 2         # re-enumerated after expiry


# ── codex G3 HIGH regression: fail-closed hard-exclude (German-locale safety) ─
def test_fail_closed_when_excludes_unresolved_on_cold_cache():
    """codex G3 HIGH: if the well-known hard-exclude lookup is INCOMPLETE and there is
    no last-known-good set, REFUSE to poll (return []) rather than walk folders and
    risk returning a localized Sent/Junk ('Gesendete Elemente') as pollable. The walk
    must never run in this state."""
    client = _fake_client(ready=True)
    with mock.patch.object(gmt, "_excluded_folder_ids",
                           return_value=({"sent-id"}, False)), \
         mock.patch.object(gmt, "_enumerate_folders") as enum:
        folders = gmt._get_pollable_folders(client)
    assert folders == []                # fail-closed
    enum.assert_not_called()            # never walked → never exposed an unclassified folder


def test_poll_fails_closed_raises_end_to_end():
    """End-to-end: unresolved excludes + cold cache → poll RAISES (report_failure,
    watermark not advanced), and no message-delta fetch is issued."""
    client = _fake_client(ready=True)
    with mock.patch.object(gmt, "GraphClient", return_value=client), \
         mock.patch.object(gmt, "_excluded_folder_ids",
                           return_value=({"sent-id"}, False)):
        with pytest.raises(RuntimeError):
            gmt.poll_graph_mail()
    # never reached a per-folder delta GET (the exclusion set was untrustworthy)
    assert client.get.call_count == 0


def test_reuse_last_known_good_on_resolution_blip():
    """A transient incomplete resolution AFTER a complete one reuses the proven
    excluded-id set (does not fail closed, does not fall back to display-strings)."""
    client = _fake_client(ready=True)
    from datetime import datetime, timezone, timedelta
    captured = []
    with mock.patch.object(gmt, "_excluded_folder_ids",
                           side_effect=[({"sent-id", "drafts-id"}, True),
                                        ({"sent-id"}, False)]), \
         mock.patch.object(gmt, "_enumerate_folders",
                           side_effect=lambda c, excluded: captured.append(set(excluded))
                           or _folders("inbox-id")):
        gmt._get_pollable_folders(client)                 # complete → caches good set
        gmt._folder_cache["fetched_at"] = (
            datetime.now(timezone.utc) - gmt._FOLDER_CACHE_TTL - timedelta(minutes=1)
        )
        gmt._get_pollable_folders(client)                 # incomplete → reuse good set
    assert captured[0] == {"sent-id", "drafts-id"}
    assert captured[1] == {"sent-id", "drafts-id"}        # reused, NOT the partial {"sent-id"}


def test_localized_german_sent_excluded_by_displayname_belt():
    """Defense-in-depth: even with excluded_ids empty, a German 'Gesendete Elemente'
    (Sent, DE) folder is dropped by the localized displayName deny-set."""
    top = {"value": [
        {"id": "inbox-id", "displayName": "Posteingang", "childFolderCount": 0},
        {"id": "sent-de-id", "displayName": "Gesendete Elemente", "childFolderCount": 0},
        {"id": "drafts-de-id", "displayName": "Entwürfe", "childFolderCount": 0},
    ]}
    client = _fake_client(ready=True)
    client.get.side_effect = [top]
    folders = gmt._enumerate_folders(client, excluded_ids=set())
    ids = {f["id"] for f in folders}
    assert ids == {"inbox-id"}          # German Sent + Drafts dropped by name belt


# ---------------------------------------------------------------------------
# M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1 — immutable-id attachment-skip fix.
#
# Root cause (b2 bus #4257): messages whose id is in immutable form had
# attachments silently dropped because the by-id Graph attachment fetch was
# issued WITHOUT Prefer: IdType="ImmutableId". Fix (G2 codex F1): the id's
# namespace is NOT derivable from prefix/char-class (live probe found AAMk ids
# WITH '-'/'_' and AAQk ids WITHOUT), so the fetch is ATTEMPT-THEN-FALLBACK —
# native first, then retry once with the immutable header; count a failure only
# if BOTH attempts fail.
# ---------------------------------------------------------------------------

# Live-shape ids (G2 F1): char-class does NOT map to namespace. A standard AAMk
# id that contains '-'/'_', and an immutable AAQk id with none — these prove the
# fix never inspects the id, only attempts then falls back.
_AAMK_WITH_DASH = "AAMkAGI2T-Hg_x9Q1Zr0nBcVg8w=="     # standard, but base64url chars
_AAQK_NO_DASH = "AAQkAGI2THgx9Q1Zr0nBcVg8wAAAA=="      # immutable, no '-'/'_'
_PREFER = {"Prefer": 'IdType="ImmutableId"'}


@pytest.fixture(autouse=True)
def _reset_attachment_counter():
    gmt._attachment_fetch_failures = 0
    yield
    gmt._attachment_fetch_failures = 0


def _att(name="doc.pdf", ctype="application/pdf", content=b"PDFDATA", inline=False):
    import base64 as _b64
    return {
        "id": "att-1",
        "name": name,
        "contentType": ctype,
        "size": len(content),
        "contentBytes": _b64.b64encode(content).decode(),
        "isInline": inline,
    }


def _prefer_of(call):
    return (call.kwargs or {}).get("extra_headers")


def test_immutable_id_reaches_prefer_fallback_and_persists():
    """AC1 (test-shaped): native fetch fails -> ImmutableId retry succeeds + persists."""
    client = _fake_client()
    client.get.side_effect = [None, {"value": [_att()]}]   # attempt1 native fails, attempt2 immutable ok
    m = {"id": _AAQK_NO_DASH, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1") as ins:
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 1
    ins.assert_called_once()
    assert client.get.call_count == 2
    assert _prefer_of(client.get.call_args_list[0]) is None       # attempt 1: native, no Prefer
    assert _prefer_of(client.get.call_args_list[1]) == _PREFER     # attempt 2: ImmutableId
    assert gmt.attachment_fetch_failures() == 0


def test_native_success_never_sends_prefer():
    """No regression: a native-resolvable id persists on attempt 1, no fallback, no Prefer."""
    client = _fake_client()
    client.get.return_value = {"value": [_att()]}
    m = {"id": _AAMK_WITH_DASH, "hasAttachments": True}            # has '-'/'_' but is standard
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1"):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 1
    assert client.get.call_count == 1                             # no fallback needed
    assert _prefer_of(client.get.call_args_list[0]) is None


def test_aamk_with_dash_stays_native_first():
    """Live-shape: a standard id that CONTAINS '-'/'_' is still tried native-first (char-class unused)."""
    client = _fake_client()
    client.get.return_value = {"value": [_att()]}
    m = {"id": _AAMK_WITH_DASH, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1"):
        gmt._capture_graph_attachments(client, m)
    assert _prefer_of(client.get.call_args_list[0]) is None       # native first regardless of chars


def test_aaqk_without_dash_reaches_immutable_retry():
    """Live-shape: an immutable id with NO '-'/'_' still reaches the ImmutableId retry."""
    client = _fake_client()
    client.get.side_effect = [None, {"value": [_att()]}]
    m = {"id": _AAQK_NO_DASH, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1"):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 1
    assert client.get.call_count == 2
    assert _prefer_of(client.get.call_args_list[1]) == _PREFER


def test_both_attempts_failed_is_surfaced_not_silent(caplog):
    """AC2: native + ImmutableId both fail on hasAttachments=true -> surfaced, never silent."""
    client = _fake_client()
    client.get.return_value = None            # both attempts fail
    m = {"id": _AAQK_NO_DASH, "hasAttachments": True}
    import logging
    with caplog.at_level(logging.ERROR):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 0
    assert client.get.call_count == 2                              # both attempts made
    assert gmt.attachment_fetch_failures() == 1                    # surfaced via counter
    assert any("FAILED" in r.message for r in caplog.records)      # surfaced via ERROR log


def test_exception_during_capture_is_surfaced(caplog):
    """AC2: an exception mid-capture also counts + logs, never silently returns 0."""
    client = _fake_client()
    client.get.side_effect = RuntimeError("boom")
    m = {"id": _AAQK_NO_DASH, "hasAttachments": True}
    import logging
    with caplog.at_level(logging.ERROR):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 0
    assert gmt.attachment_fetch_failures() == 1


def test_all_inline_is_benign_no_failure_count(caplog):
    """Successful fetch, only inline parts -> 0 stored, surfaced as WARNING, NOT a failure."""
    client = _fake_client()
    client.get.return_value = {"value": [_att(inline=True)]}
    m = {"id": _AAMK_WITH_DASH, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1"):
        stored = gmt._capture_graph_attachments(client, m)
    assert stored == 0
    assert gmt.attachment_fetch_failures() == 0            # benign, not a failure


def test_no_attachments_flag_skips_fetch():
    """hasAttachments=false -> no Graph call at all."""
    client = _fake_client()
    m = {"id": _AAQK_NO_DASH, "hasAttachments": False}
    assert gmt._capture_graph_attachments(client, m) == 0
    client.get.assert_not_called()


# --- Option (a) conversationId keying (#4317) -------------------------------
# Attachments are READ by the real per-message id but STORED under thread_id
# (conversationId-or-id), matching email_messages.message_id + the read tool.

def test_store_key_is_conversation_id_when_present():
    """Read by real id; persist under conversationId (matches email_messages keying)."""
    client = _fake_client()
    client.get.return_value = {"value": [_att()]}
    real_id = "AAMkRealMessageId=="
    conv_id = "AAQkConversationId=="
    m = {"id": real_id, "conversationId": conv_id, "hasAttachments": True}
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1") as ins:
        gmt._capture_graph_attachments(client, m)
    # FETCH used the real per-message id (percent-encoded in the URL path)...
    from urllib.parse import quote as _q
    assert _q(real_id, safe="") in client.get.call_args_list[0].args[0]
    # ...but the STORE key is the conversationId.
    assert ins.call_args.kwargs["message_id"] == conv_id


def test_fetch_path_url_encodes_message_id():
    """codex-arch #4337: base64 ids ('/', '+') must be percent-encoded in the path,
    else a '/' splits the URL route and the attachment fetch fails."""
    client = _fake_client()
    client.get.return_value = {"value": []}
    real_id = "AAMkAGI2/Hg+x9Q=="                 # base64 standard: contains '/' and '+'
    gmt._fetch_attachments_page(client, real_id)
    path = client.get.call_args_list[0].args[0]
    assert "%2F" in path and "%2B" in path         # '/' and '+' percent-encoded
    assert "/Hg+" not in path                       # raw chars no longer in the path


def test_fetch_path_no_contentbytes_in_collection_select():
    """M365_GRAPH_ATTACHMENT_FETCH_DIAG_1 (bus #4348): contentBytes in a $select on
    the /attachments COLLECTION makes Graph 400 ('Could not find a property named
    contentBytes'), silently dropping attachments. The fetch must NOT send $select;
    a bare collection GET returns full fileAttachment objects incl contentBytes."""
    client = _fake_client()
    client.get.return_value = {"value": []}
    gmt._fetch_attachments_page(client, "AAMkRealMessageId==")
    params = client.get.call_args_list[0].kwargs.get("params") or {}
    assert "$select" not in params                  # no $select on the collection at all
    # belt-and-suspenders: contentBytes never named in any outgoing param
    assert "contentBytes" not in str(params)
    assert params.get("$top") == 50                 # $top is still fine


def test_store_key_falls_back_to_message_id_without_conversation():
    """No conversationId -> store under the message id (mirrors thread_id = conv or id)."""
    client = _fake_client()
    client.get.return_value = {"value": [_att()]}
    real_id = "AAMkRealMessageId=="
    m = {"id": real_id, "hasAttachments": True}     # no conversationId
    with mock.patch.object(gmt, "_insert_live_attachment", return_value="row-1") as ins:
        gmt._capture_graph_attachments(client, m)
    assert ins.call_args.kwargs["message_id"] == real_id
