"""
BAKER_CAPTURE_BLINDSPOTS_1: Pure-Python tests for the iPhone export parser.
Skips cleanly when outputs.dashboard cannot import (Python 3.9 PEP-604 chain).
"""

from __future__ import annotations

import pytest


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


@_skip_without_dashboard
def test_parses_three_messages_with_continuation():
    from outputs.dashboard import parse_iphone_export
    text = (
        "[2026-05-12, 14:23:01] Dimitry Vallen: First message\n"
        "and a continuation line\n"
        "[2026-05-12, 14:24:10] Peter Storer: Reply from Peter\n"
        "[2026-05-12, 14:25:00] Dimitry Vallen: Last\n"
    )
    out = parse_iphone_export(text, director_name="Dimitry Vallen")
    assert len(out) == 3
    assert out[0]["body"] == "First message\nand a continuation line"
    assert out[0]["is_director"] is True
    assert out[1]["sender"] == "Peter Storer"
    assert out[1]["is_director"] is False
    assert out[2]["body"] == "Last"


@_skip_without_dashboard
def test_drops_deleted_and_encrypted_placeholders():
    from outputs.dashboard import parse_iphone_export
    text = (
        "[2026-05-12, 10:00:00] Dimitry Vallen: real message\n"
        "[2026-05-12, 10:01:00] Peter Storer: <This message was deleted>\n"
        "[2026-05-12, 10:02:00] Peter Storer: \u200e<encrypted>\n"
        "[2026-05-12, 10:03:00] Dimitry Vallen: <This message was edited>\n"
        "[2026-05-12, 10:04:00] Peter Storer: kept\n"
    )
    out = parse_iphone_export(text)
    bodies = [m["body"] for m in out]
    assert bodies == ["real message", "kept"]


@_skip_without_dashboard
def test_auto_detects_dd_mm_yyyy_locale():
    from outputs.dashboard import parse_iphone_export
    text = "[12/05/2026, 14:23:01] Dimitry Vallen: hi\n"
    out = parse_iphone_export(text)
    assert len(out) == 1
    ts = out[0]["timestamp"]
    # 12/05/2026 → DD/MM/YYYY → 12 May 2026
    assert ts.year == 2026 and ts.month == 5 and ts.day == 12


@_skip_without_dashboard
def test_is_director_flag_case_insensitive_substring():
    from outputs.dashboard import parse_iphone_export
    text = (
        "[2026-05-12, 14:23:01] dimitry vallen 🇨🇭: lowercase\n"
        "[2026-05-12, 14:24:00] Peter Storer: not director\n"
    )
    out = parse_iphone_export(text, director_name="Dimitry Vallen")
    assert out[0]["is_director"] is True
    assert out[1]["is_director"] is False


@_skip_without_dashboard
def test_returns_empty_when_no_parseable_lines():
    from outputs.dashboard import parse_iphone_export
    out = parse_iphone_export("just garbage with no timestamps\nat all\n")
    assert out == []


@_skip_without_dashboard
def test_iphone_export_id_is_deterministic_and_prefixed():
    from datetime import datetime
    from outputs.dashboard import _iphone_export_id
    ts = datetime(2026, 5, 12, 14, 23, 1)
    a = _iphone_export_id("393358345678@c.us", ts, True, "hello")
    b = _iphone_export_id("393358345678@c.us", ts, True, "hello")
    c = _iphone_export_id("393358345678@c.us", ts, False, "hello")
    assert a == b  # determinism
    assert a != c  # is_director bit changes id
    assert a.startswith("iphone:393358345678@c.us:20260512T142301:1:")
