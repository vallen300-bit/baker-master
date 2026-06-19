"""AI_HOTEL_REMEMBER_KEY_1 — persist the access key so a bare/bookmarked link
still authenticates (Director "can't see my card" empty-feed root cause).

This is a static-page-only change (no backend touched), so these are source-level
guards on the JS logic; the live AC1–AC6 browser exercise runs at POST_DEPLOY on
prod (the behaviour needs the deployed same-origin page + a real key).

  AC1/AC2  ?key= persisted to localStorage['aih.key']; bare link falls back to it.
  AC3      capture-page nokey gate evaluates against the RESOLVED key.
  AC4      ?key= stripped from the URL via history.replaceState (other params kept).
  AC5/AC6  localStorage wrapped in try/catch (Safari private mode); graceful empty.
"""

from __future__ import annotations

from pathlib import Path


def test_dashboard_page_remembers_and_strips_key():
    src = Path("outputs/static/ai-hotel.html").read_text()
    seg = src[src.index("function noteKey()"):src.index("function cardKind(")]
    # AC1: persist on keyed visit
    assert "localStorage.setItem('aih.key',k)" in seg
    # AC2: fall back to stored key when URL has none (KEY_PASTE_SELFSERVE_1 added
    # an in-memory session fallback after the stored-key read).
    assert "localStorage.getItem('aih.key')" in seg
    assert "return _aihSessionKey||''" in seg
    # AC4: strip key from URL, preserving any other query params
    assert "u.delete('key')" in seg and "history.replaceState" in seg
    assert "location.pathname+(qs?('?'+qs):'')" in seg
    # AC5/AC6: every localStorage/history access is wrapped in try/catch
    assert seg.count("catch(e)") >= 4


def test_capture_page_resolves_and_strips_key():
    src = Path("outputs/static/ai-hotel-capture.html").read_text()
    head = src[src.index("var params=new URLSearchParams"):src.index("var fileInput=")]
    assert "localStorage.setItem('aih.key',KEY)" in head     # AC1 persist
    assert "localStorage.getItem('aih.key')||''" in head     # AC2 fallback
    assert "params.delete('key')" in head and "history.replaceState" in head  # AC4 strip
    assert "catch(e)" in head                                 # AC5/AC6 try/catch
    # AC3: the nokey gate keys off the resolved KEY variable, not the raw URL param.
    assert "if(!KEY){ nokey.classList.add('show'); }" in src


def test_no_key_logged_to_console():
    """Kill criterion #2: the key must never be logged to console."""
    for f in ("outputs/static/ai-hotel.html", "outputs/static/ai-hotel-capture.html"):
        src = Path(f).read_text()
        assert "console.log(KEY" not in src
        assert "console.log('aih.key'" not in src and "console.log(\"aih.key\"" not in src
