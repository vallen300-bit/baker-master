"""
BACKFILL_BLUEWIN_1 unit tests — parser + dedup + cursor + folder detection.
Mock IMAP / fake DB cursor only; no live credentials, no live Postgres.
"""

import email.mime.application
import email.mime.multipart
import email.mime.text
from datetime import timezone

import pytest

from scripts.backfill_bluewin import (
    INSERT_MESSAGE_SQL,
    chunks,
    detect_sent_folder,
    extract_attachments,
    format_cursor,
    insert_message_row,
    message_id_for,
    parse_cursor,
    parse_message,
)


# ── fixtures ────────────────────────────────────────────────────────────


def _mime_with_attachment(message_id="<abc-123@bluewin.ch>") -> bytes:
    outer = email.mime.multipart.MIMEMultipart()
    outer["Subject"] = "=?utf-8?q?Vertr=C3=A4ge_Q2?="
    outer["From"] = '"Hans Muster" <hans@example.ch>'
    outer["To"] = "dvallen@bluewin.ch"
    outer["Date"] = "Mon, 12 Apr 2021 10:30:00 +0200"
    if message_id:
        outer["Message-ID"] = message_id
    outer.attach(email.mime.text.MIMEText("Guten Tag, anbei die Datei.", "plain"))
    pdf = email.mime.application.MIMEApplication(b"%PDF-1.4 fake", _subtype="pdf")
    pdf.add_header("Content-Disposition", "attachment", filename="vertrag.pdf")
    outer.attach(pdf)
    return outer.as_bytes()


class FakeCursor:
    """Captures executed SQL; simulates ON CONFLICT dedup on message_id."""

    def __init__(self, existing_ids=None):
        self.existing = set(existing_ids or [])
        self.calls = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        mid = params[0] if params else None
        if mid in self.existing:
            self.rowcount = 0
        else:
            self.existing.add(mid)
            self.rowcount = 1


# ── parsing ─────────────────────────────────────────────────────────────


def test_parse_message_fields():
    parsed, atts = parse_message(_mime_with_attachment(), "INBOX", 7, 42)
    assert parsed["message_id"] == "abc-123@bluewin.ch"  # <> stripped
    assert parsed["thread_id"] == "abc-123@bluewin.ch"
    assert parsed["sender_name"] == "Hans Muster"
    assert parsed["sender_email"] == "hans@example.ch"
    assert parsed["subject"] == "Verträge Q2"  # RFC 2047 decoded
    assert "anbei die Datei" in parsed["full_body"]
    assert parsed["received_date"].tzinfo is not None
    assert parsed["received_date"].astimezone(timezone.utc).year == 2021
    assert len(atts) == 1


def test_attachment_extraction():
    _, atts = parse_message(_mime_with_attachment(), "INBOX", 7, 42)
    (fname, mime, payload) = atts[0]
    assert fname == "vertrag.pdf"
    assert mime == "application/pdf"
    assert payload == b"%PDF-1.4 fake"


def test_body_part_not_extracted_as_attachment():
    _, atts = parse_message(_mime_with_attachment(), "INBOX", 7, 42)
    assert all(m == "application/pdf" for _, m, _ in atts)  # text/plain body skipped


def test_message_id_fallback_deterministic():
    raw = _mime_with_attachment(message_id=None)
    p1, _ = parse_message(raw, "INBOX", 7, 42)
    p2, _ = parse_message(raw, "INBOX", 7, 42)
    assert p1["message_id"] == p2["message_id"] == "bluewin-INBOX-7-uid-42"
    p3, _ = parse_message(raw, "INBOX", 8, 42)  # validity reset -> different id
    assert p3["message_id"] != p1["message_id"]


def test_message_id_for_strips_angle_brackets():
    msg = email.message_from_bytes(_mime_with_attachment())
    assert message_id_for(msg, "INBOX", 1, 1) == "abc-123@bluewin.ch"


# ── dedup INSERT contract ───────────────────────────────────────────────


def test_insert_sql_contract():
    assert "ON CONFLICT (message_id) DO NOTHING" in INSERT_MESSAGE_SQL
    assert "NULL" in INSERT_MESSAGE_SQL  # priority hard-NULL, no LLM


def test_insert_dedup_rowcount():
    parsed, _ = parse_message(_mime_with_attachment(), "INBOX", 7, 42)
    cur = FakeCursor()
    assert insert_message_row(cur, parsed) == 1  # first insert
    assert insert_message_row(cur, parsed) == 0  # dedup
    sql, params = cur.calls[0]
    assert params[-1] == "bluewin"  # source column


# ── cursor ──────────────────────────────────────────────────────────────


def test_cursor_roundtrip():
    assert parse_cursor(format_cursor(1618000000, 5123)) == (1618000000, 5123)


def test_cursor_empty_and_garbage():
    assert parse_cursor(None) == (None, 0)
    assert parse_cursor("") == (None, 0)
    assert parse_cursor("not-a-cursor") == (None, 0)


# ── sent folder detection ───────────────────────────────────────────────


def test_detect_sent_folder_special_use_flag():
    lines = [
        b'(\\HasNoChildren) "." "INBOX"',
        b'(\\HasNoChildren \\Sent) "." "Gesendete Objekte"',
    ]
    assert detect_sent_folder(lines) == "Gesendete Objekte"


def test_detect_sent_folder_name_fallback():
    lines = [
        b'(\\HasNoChildren) "." "INBOX"',
        b'(\\HasNoChildren) "." "Sent"',
        b'(\\HasNoChildren) "." "Drafts"',
    ]
    assert detect_sent_folder(lines) == "Sent"


def test_detect_sent_folder_none():
    assert detect_sent_folder([b'(\\HasNoChildren) "." "INBOX"']) is None
    assert detect_sent_folder([]) is None


# ── batching ────────────────────────────────────────────────────────────


def test_chunks():
    assert list(chunks(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]
    assert list(chunks([], 200)) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# ── folder quoting (Bluewin STATUS rejects unquoted names with spaces) ──


def test_quote_folder():
    from scripts.backfill_bluewin import _quote_folder
    assert _quote_folder("INBOX") == '"INBOX"'
    assert _quote_folder("Sent Messages") == '"Sent Messages"'
    assert _quote_folder('"Sent"') == '"Sent"'  # already quoted -> unchanged

# ── G3-S1: attachment-store failure must NOT advance the cursor ─────────


class FakeIMAP:
    """Minimal IMAP stub: one folder, two messages with one attachment each."""

    def __init__(self):
        self.raw = _mime_with_attachment()

    def status(self, mailbox, items):
        return "OK", [b'"INBOX" (UIDVALIDITY 7 MESSAGES 2)']

    def select(self, mailbox, readonly=False):
        return "OK", [b"2"]

    def uid(self, cmd, *args):
        if cmd == "search":
            return "OK", [b"1 2"]
        # fetch
        return "OK", [(b'1 (INTERNALDATE "12-Apr-2021 10:30:00 +0200" RFC822 {1}', self.raw)]


class FakeDBConn:
    def __init__(self):
        self.cur = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        conn = self

        class _Ctx:
            def __enter__(self_inner):
                return conn.cur

            def __exit__(self_inner, *a):
                return False

        return _Ctx()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _progress_writes(fake_conn):
    """Cursor-advance INSERTs only (read_progress SELECT doesn't count)."""
    return [c for c in fake_conn.cur.calls if "INSERT INTO email_backfill_progress" in c[0]]


def test_attachment_store_none_blocks_cursor(monkeypatch):
    """G3-S1: insert_attachment -> None => batch aborts loud, cursor NOT advanced."""
    import scripts.backfill_bluewin as bb

    monkeypatch.setattr(bb.time, "sleep", lambda s: None)  # no retry/batch waits
    fake_db = FakeDBConn()
    fake_db.cur.fetchone = lambda: None  # read_progress: no cursor yet

    with pytest.raises(bb.AttachmentStoreFailure):
        bb.backfill_folder(FakeIMAP(), fake_db, "INBOX",
                           lambda *a: None,  # store FAILURE semantics (None)
                           limit=None, batch_size=10)

    assert _progress_writes(fake_db) == []          # cursor never advanced
    assert fake_db.commits == 0                     # no partial batch committed
    assert fake_db.rollbacks == bb.MAX_BATCH_ATTEMPTS  # bounded retries, all rolled back


def test_attachment_store_exception_blocks_cursor(monkeypatch):
    """Same failure class: store raising must also roll back, not advance."""
    import scripts.backfill_bluewin as bb

    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    fake_db = FakeDBConn()
    fake_db.cur.fetchone = lambda: None

    def boom(*a):
        raise ConnectionError("pool exhausted")

    with pytest.raises(bb.AttachmentStoreFailure):
        bb.backfill_folder(FakeIMAP(), fake_db, "INBOX", boom, limit=None, batch_size=10)
    assert _progress_writes(fake_db) == []


def test_attachment_store_success_advances_cursor(monkeypatch):
    """Positive path: successful store => batch commits + cursor advances."""
    import scripts.backfill_bluewin as bb

    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    fake_db = FakeDBConn()
    fake_db.cur.fetchone = lambda: None

    p, i, a = bb.backfill_folder(FakeIMAP(), fake_db, "INBOX",
                                 lambda *args: 1,  # store returns row id
                                 limit=None, batch_size=10)
    assert p == 2 and a == 2
    assert len(_progress_writes(fake_db)) == 1      # cursor advanced once (one batch)
    assert fake_db.commits == 2                     # batch commit + write_progress commit
