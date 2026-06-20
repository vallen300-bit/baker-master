"""AI_HOTEL_KEY_PASTE_SELFSERVE_1 — self-service key entry on the keyless empty
state (closes the dashboard-route gap remember-key #385/#386 can't reach).

Static-page-only change (no backend touched), so these are source-level guards on
the JS logic; live AC1-AC4 run via Chrome MCP at POST_DEPLOY on prod.

  AC1  keyless empty state renders a key input + load button.
  AC2  valid key loads cards without reload + persists aih.key.
  AC4  wrong key → inline "not accepted", input stays, key NOT stored (probe-first).
  AC6  Safari private mode (localStorage throws) → in-memory session-key fallback.
"""

from __future__ import annotations

from pathlib import Path


def _src() -> str:
    return Path("outputs/static/ai-hotel.html").read_text()


def test_empty_state_renders_key_entry():
    src = _src()
    # AC1: the keyless branch routes to the self-service entry, not a dead hint.
    assert "function renderKeyEntry(main)" in src
    notes = src[src.index("function renderNotes(main)"):src.index("function cardAsText(")]
    assert "renderKeyEntry(main)" in notes
    assert "throw new Error('unauth')" in notes
    seg = src[src.index("function renderKeyEntry(main)"):src.index("function renderNotes(main)")]
    assert "type='password'" in seg and "Paste access key" in seg
    assert "Load field notes" in seg
    assert "Enter access code" in seg and "/api/ai-hotel/pin-auth" in seg


def test_probe_before_persist_and_session_fallback():
    src = _src()
    seg = src[src.index("function renderKeyEntry(main)"):src.index("function renderNotes(main)")]
    # AC2/AC4: probe the key with a fetch BEFORE storing; only persist on success.
    assert "fetch('/api/ai-hotel/captures?limit=1'" in seg
    assert "throw new Error('unauth')" in seg
    persist_idx = seg.index("localStorage.setItem('aih.key',k)")
    success_then = seg.index(".then(function(){")
    assert success_then < persist_idx          # setItem lives in the success .then, not the catch
    # AC4: wrong key shows inline message + leaves input; no silent store in catch.
    key_probe = seg[seg.index("fetch('/api/ai-hotel/captures?limit=1'"):]
    catch_seg = key_probe[key_probe.index(".catch(function(e){"):]
    assert "Key not accepted" in catch_seg
    assert "localStorage.setItem" not in catch_seg
    # AC2: reload-free re-render via show('notes').
    assert "show('notes')" in seg
    # AC6: in-memory session fallback set on success + consulted by noteKey().
    assert "_aihSessionKey=k" in seg
    nk = src[src.index("function noteKey()"):src.index("function cardKind(")]
    assert "_aihSessionKey" in nk and "return _aihSessionKey||''" in nk
    # AC2: localStorage write is try/catch-wrapped (Safari private safe).
    assert "try{localStorage.setItem('aih.key',k);}catch(e){}" in seg


def test_no_key_logged_or_leaked():
    """Kill criterion: key never echoed to console or beyond the X-Baker-Key header."""
    src = _src()
    assert "console.log(k)" not in src and "console.log(KEY" not in src
    assert "console.log('aih.key'" not in src
    # the entry input is type=password (not rendered as plaintext DOM value)
    seg = src[src.index("function renderKeyEntry(main)"):src.index("function renderNotes(main)")]
    assert "inp.type='password'" in seg


def test_forget_key_affordance():
    src = _src()
    assert "Forget key" in src
    assert "localStorage.removeItem('aih.key')" in src
    assert "_aihSessionKey=''" in src
