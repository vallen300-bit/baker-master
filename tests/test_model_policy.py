"""BAKER_DASHBOARD_V2_MODEL_LOCK_1 — regression tests for the trusted-extraction
model policy.

Guarantee under test: Gemini Flash is never invoked on a trusted (Director-visible)
extraction/generation path. Trusted paths route through the central policy
(`call_trusted` -> `call_pro`) or, for dashboard `_llm_call` sites, pass a non-Flash
gemini model string that the router now honors.

These tests spy on `orchestrator.gemini_client.call_flash`: if a trusted path ever
calls it, the spy trips and the test fails (AC7).
"""
import pytest

from orchestrator import model_policy as mp
from orchestrator.gemini_client import GeminiResponse


class _FlashSpy:
    """Records whether call_flash was invoked; never returns a usable response."""

    def __init__(self):
        self.called = False

    def __call__(self, *args, **kwargs):
        self.called = True
        return GeminiResponse("FLASH-SHOULD-NOT-RUN", 1, 1)


def _pro_stub(text="[]"):
    def _f(*args, **kwargs):
        return GeminiResponse(text, 10, 5)
    return _f


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — central policy
# ─────────────────────────────────────────────────────────────────────────────

def test_is_flash_detects_all_flash_variants():
    assert mp.is_flash("gemini-2.5-flash")
    assert mp.is_flash("gemini-1.5-flash-8b")
    assert mp.is_flash("GEMINI-2.5-FLASH")
    assert not mp.is_flash("gemini-2.5-pro")
    assert not mp.is_flash("claude-opus-4-8")


def test_is_allowed_for_trusted_fails_closed():
    assert not mp.is_allowed_for_trusted("gemini-2.5-flash")
    assert not mp.is_allowed_for_trusted("")
    assert not mp.is_allowed_for_trusted(None)
    assert mp.is_allowed_for_trusted("gemini-2.5-pro")
    assert mp.is_allowed_for_trusted("claude-opus-4-8")


def test_assert_trusted_model_raises_on_flash():
    with pytest.raises(mp.TrustedModelPolicyError):
        mp.assert_trusted_model("gemini-2.5-flash", context="unit")
    # Pro must not raise.
    mp.assert_trusted_model("gemini-2.5-pro", context="unit")


def test_trusted_extraction_model_defaults_to_pro(monkeypatch):
    monkeypatch.delenv("EXTRACTION_MIN_MODEL", raising=False)
    assert mp.trusted_extraction_model() == "gemini-2.5-pro"


def test_trusted_extraction_model_refuses_flash_override(monkeypatch):
    # An ops override that points at Flash must be rejected (fall back to default).
    monkeypatch.setenv("EXTRACTION_MIN_MODEL", "gemini-2.5-flash")
    resolved = mp.trusted_extraction_model()
    assert not mp.is_flash(resolved)
    assert resolved == "gemini-2.5-pro"


def test_trusted_extraction_model_honors_stronger_override(monkeypatch):
    monkeypatch.setenv("EXTRACTION_MIN_MODEL", "gemini-3-pro")
    assert mp.trusted_extraction_model() == "gemini-3-pro"


# ─────────────────────────────────────────────────────────────────────────────
# call_trusted wrapper — the single chokepoint every converted orchestrator site
# routes through. Proving it never touches Flash covers all of them.
# ─────────────────────────────────────────────────────────────────────────────

def test_call_trusted_routes_to_pro_never_flash(monkeypatch):
    import orchestrator.gemini_client as gc
    flash = _FlashSpy()
    monkeypatch.setattr(gc, "call_flash", flash)
    monkeypatch.setattr(gc, "call_pro", _pro_stub("ok"))
    resp = mp.call_trusted(
        [{"role": "user", "content": "x"}],
        context="unit", output_type="test",
    )
    assert resp.text == "ok"
    assert not flash.called


def test_call_trusted_refuses_when_floor_is_flash(monkeypatch):
    # Defense in depth: even if the floor somehow resolved to Flash, call_trusted
    # must refuse rather than silently run a barred model.
    import orchestrator.gemini_client as gc
    monkeypatch.setattr(gc, "call_pro", _pro_stub("ok"))
    monkeypatch.setattr(mp, "trusted_extraction_model", lambda: "gemini-2.5-flash")
    with pytest.raises(mp.TrustedModelPolicyError):
        mp.call_trusted([{"role": "user", "content": "x"}], context="unit")


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — T3 signal extraction never produces trusted output from Flash
# ─────────────────────────────────────────────────────────────────────────────

def test_t3_extraction_uses_pro_not_flash(monkeypatch):
    import orchestrator.gemini_client as gc
    from orchestrator import extraction_engine as ee
    flash = _FlashSpy()
    monkeypatch.setattr(gc, "call_flash", flash)
    monkeypatch.setattr(gc, "call_pro", _pro_stub("[]"))
    items, _elapsed, _cost = ee._extract_t3_trusted(
        "Director must sign the lease by 2026-07-01.", "email", "id-1",
    )
    assert items == []
    assert not flash.called


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — email/manual deadline extraction uses Pro
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_deadlines_uses_pro_not_flash(monkeypatch):
    import orchestrator.gemini_client as gc
    from orchestrator import deadline_manager as dm
    flash = _FlashSpy()
    monkeypatch.setattr(gc, "call_flash", flash)
    monkeypatch.setattr(gc, "call_pro", _pro_stub("[]"))
    # source_type="manual" skips the email-only pre-filter; "[]" -> 0 inserts, no DB.
    inserted = dm.extract_deadlines(
        "Please submit the signed report by 2026-07-01. This is important.",
        "manual",
    )
    assert inserted == 0
    assert not flash.called


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — pipeline low-value trigger routing cannot pick Flash
# ─────────────────────────────────────────────────────────────────────────────

def test_pipeline_low_value_triggers_route_to_pro_not_flash(monkeypatch):
    import orchestrator.gemini_client as gc
    from orchestrator.pipeline import SentinelPipeline

    captured = {}

    def _capture_generate(model, messages, max_tokens=8192, system=None, **kwargs):
        captured["model"] = model
        return GeminiResponse("{}", 1, 1)

    flash = _FlashSpy()
    monkeypatch.setattr(gc, "call_flash", flash)
    monkeypatch.setattr(gc, "generate", _capture_generate)

    pipe = SentinelPipeline.__new__(SentinelPipeline)  # bypass __init__ (no DB/clients)
    prompt = {
        "messages": [{"role": "user", "content": "x"}],
        "system": "s",
        "metadata": {"tokens_estimated": 10},
    }
    for trig in ("rss_article", "dropbox_file_new", "clickup_task_updated",
                 "browser_change"):
        captured.clear()
        pipe.generate(prompt, trigger_type=trig, trigger_tier=3)
        assert captured["model"] == "gemini-2.5-pro", trig
        assert not mp.is_flash(captured["model"]), trig
    assert not flash.called


# ─────────────────────────────────────────────────────────────────────────────
# AC7 #4 — dashboard card-producing _llm_call routing honors the model string
# (the latent bypass: previously every gemini-* model fell through to call_flash)
# ─────────────────────────────────────────────────────────────────────────────

def test_llm_call_routes_pro_string_to_pro_not_flash(monkeypatch):
    # dashboard binds call_flash/call_pro into its own namespace at import, so we
    # patch outputs.dashboard.* (not gemini_client.*).
    import outputs.dashboard as dash
    flash = _FlashSpy()
    pro_hit = {}

    def pro(messages, max_tokens=2000, system=None, response_format=None, thinking_budget=None):
        pro_hit["hit"] = True
        return GeminiResponse("ok", 1, 1)

    monkeypatch.setattr(dash, "call_flash", flash)
    monkeypatch.setattr(dash, "call_pro", pro)
    resp = dash._llm_call("gemini-2.5-pro", messages=[{"role": "user", "content": "x"}])
    assert resp.text == "ok"
    assert pro_hit.get("hit")
    assert not flash.called


def test_llm_call_still_routes_flash_string_to_flash(monkeypatch):
    # Non-trusted housekeeping sites that legitimately keep Flash must still work.
    import outputs.dashboard as dash
    flash_hit = {}

    def flash(messages, max_tokens=2000, system=None, response_format=None, thinking_budget=None):
        flash_hit["hit"] = True
        return GeminiResponse("ok", 1, 1)

    monkeypatch.setattr(dash, "call_flash", flash)
    resp = dash._llm_call("gemini-2.5-flash", messages=[{"role": "user", "content": "x"}])
    assert resp.text == "ok"
    assert flash_hit.get("hit")
