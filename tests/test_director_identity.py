"""Tests for baker.director_identity — C2 Inv 5 single source of truth."""
from __future__ import annotations

import pytest

from baker import director_identity
from baker.director_identity import (
    DIRECTOR_EMAILS,
    DIRECTOR_PHONES,
    _normalize_phone,
    is_director_sender,
)


# ------------------------------ phone normalization ------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+41 79 960 50 92", "41799605092"),
        ("+41799605092", "41799605092"),
        ("41799605092@c.us", "41799605092"),
        ("41799605092", "41799605092"),
        ("+41-79-960-50-92", "41799605092"),
        ("tel:+41.79.960.50.92", "41799605092"),
        # S1 (PR #7 review): `00` is the international-dial prefix
        # (E.164 alternate to `+`) — must canonicalize to the same form.
        ("0041 79 960 50 92", "41799605092"),
        ("0041799605092", "41799605092"),
    ],
)
def test_normalize_phone_strips_non_digits(raw: str, expected: str) -> None:
    assert _normalize_phone(raw) == expected


def test_normalize_phone_handles_empty() -> None:
    assert _normalize_phone("") == ""


def test_normalize_phone_malformed_does_not_crash() -> None:
    """B1 impl must not raise on garbage input — returns digits only."""
    assert _normalize_phone("not-a-phone") == ""
    assert _normalize_phone("()") == ""


# ------------------------------ email branch ------------------------------


@pytest.mark.parametrize(
    "sender",
    [
        "dvallen@brisengroup.com",
        "DVallen@brisengroup.com",                  # case-insensitive
        "  dvallen@brisengroup.com  ",              # whitespace tolerant
        "Dimitry Vallen <dvallen@brisengroup.com>", # name-wrapped
        "vallen300@gmail.com",
        "office.vienna@brisengroup.com",
    ],
)
def test_director_email_recognized(sender: str) -> None:
    signal = {"source": "email", "payload": {"sender": sender}}
    assert is_director_sender(signal) is True


def test_director_email_meeting_organizer_recognized() -> None:
    signal = {
        "source": "meeting",
        "payload": {"organizer": "dvallen@brisengroup.com"},
    }
    assert is_director_sender(signal) is True


def test_non_director_email_not_recognized() -> None:
    signal = {
        "source": "email",
        "payload": {"sender": "stranger@example.com"},
    }
    assert is_director_sender(signal) is False


# ------------------------------ whatsapp branch ------------------------------


@pytest.mark.parametrize(
    "sender",
    [
        "+41 79 960 50 92",
        "+41799605092",
        "41799605092@c.us",
        "41799605092",
        "+41-79-960-50-92",
        # S1 (PR #7 review): `00` international-dial prefix equivalent of `+`.
        "0041 79 960 50 92",
        "0041799605092",
    ],
)
def test_director_whatsapp_recognized_all_formats(sender: str) -> None:
    signal = {"source": "whatsapp", "payload": {"sender": sender}}
    assert is_director_sender(signal) is True


def test_director_whatsapp_recognized_from_chat_id_field() -> None:
    """Some WA payloads stick the sender phone in ``chat_id``."""
    signal = {
        "source": "whatsapp",
        "payload": {"chat_id": "41799605092@c.us"},
    }
    assert is_director_sender(signal) is True


def test_non_director_whatsapp_not_recognized() -> None:
    signal = {
        "source": "whatsapp",
        "payload": {"sender": "+43 664 123 4567"},
    }
    assert is_director_sender(signal) is False


def test_whatsapp_missing_sender_returns_false() -> None:
    assert is_director_sender({"source": "whatsapp", "payload": {}}) is False


# ------------------------------ adapter variants ------------------------------


class _StubSignal:
    """Minimal duck-typed signal — dataclass-shaped."""

    def __init__(self, source: str, payload: dict) -> None:
        self.source = source
        self.payload = payload


def test_accepts_object_with_attributes() -> None:
    sig = _StubSignal(source="email", payload={"sender": "vallen300@gmail.com"})
    assert is_director_sender(sig) is True


def test_accepts_plain_dict_with_nested_payload() -> None:
    signal = {
        "source": "email",
        "payload": {"sender": "vallen300@gmail.com"},
    }
    assert is_director_sender(signal) is True


def test_unknown_source_returns_false_not_raise() -> None:
    """Conservative: unknown source yields 'not director' without crashing."""
    signal = {"source": "rss", "payload": {"sender": "anything"}}
    assert is_director_sender(signal) is False


def test_null_signal_returns_false() -> None:
    """Defensive — callers might pass None during integration bring-up."""
    assert is_director_sender(None) is False


# ------------------------------ module constants ------------------------------


def test_constants_are_frozensets() -> None:
    """Immutability guard — callers must not mutate these at runtime."""
    assert isinstance(director_identity.DIRECTOR_EMAILS, frozenset)
    assert isinstance(director_identity.DIRECTOR_PHONES, frozenset)


def test_director_phone_is_canonical_form() -> None:
    """Stored constant is itself digits-only so lookup is a direct hit."""
    for phone in DIRECTOR_PHONES:
        assert phone == _normalize_phone(phone)


def test_director_emails_are_all_lowercase() -> None:
    for email in DIRECTOR_EMAILS:
        assert email == email.lower()
