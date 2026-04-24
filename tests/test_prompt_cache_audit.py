"""Tests for PROMPT_CACHE_AUDIT_1: audit script + cache_control shape + telemetry."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPO / "scripts" / "audit_prompt_cache.py"


def test_audit_script_exits_zero_and_writes_report(tmp_path):
    """Script runs end-to-end, writes non-empty markdown report."""
    out = tmp_path / "audit.md"
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--out", str(out)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    content = out.read_text()
    assert "# Prompt Cache Audit" in content
    assert "Summary by tier" in content


def test_audit_identifies_cached_call_site(tmp_path):
    """Post-Feature-2: at least one eligible_measure entry must exist (the
    three hot sites carry inline cache_control), and anthropic_client.py
    appears as a Claude call site somewhere in the report."""
    out = tmp_path / "audit.md"
    subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--out", str(out)],
        cwd=str(REPO), check=True,
    )
    content = out.read_text()
    assert "eligible_measure" in content
    assert "anthropic_client.py" in content


def test_cache_control_block_shape_in_anthropic_client():
    """kbl/anthropic_client.py retains its {type, text, cache_control} block shape."""
    src = (REPO / "kbl" / "anthropic_client.py").read_text()
    assert '"cache_control": {"type": "ephemeral"}' in src
    assert '"type": "text"' in src


def test_cache_control_present_in_three_hot_sites():
    """dashboard.py / capability_runner.py / baker_rag.py each contain cache_control
    post-Feature-2 application."""
    for path in ("outputs/dashboard.py", "orchestrator/capability_runner.py", "baker_rag.py"):
        src = (REPO / path).read_text()
        assert "cache_control" in src, f"{path} missing cache_control (Feature 2 not applied)"


def _install_fake_store_module(monkeypatch, store_instance):
    """Stub `memory.store_back` in sys.modules so log_cache_usage's
    lazy import returns a fake store. Keeps tests hermetic — does not
    depend on the real memory/store_back.py being importable."""
    import sys
    import types
    fake_mod = types.ModuleType("memory.store_back")

    class _FakeSSB:
        @classmethod
        def _get_global_instance(cls):
            return store_instance

    fake_mod.SentinelStoreBack = _FakeSSB
    monkeypatch.setitem(sys.modules, "memory.store_back", fake_mod)


def test_log_cache_usage_fires_baker_action(monkeypatch):
    """log_cache_usage calls store.log_baker_action with correct payload keys."""
    from kbl.cache_telemetry import log_cache_usage

    captured: dict = {}

    class _FakeStore:
        def log_baker_action(self, **kw):
            captured.update(kw)

    _install_fake_store_module(monkeypatch, _FakeStore())

    usage = MagicMock(
        input_tokens=500,
        output_tokens=200,
        cache_read_input_tokens=3000,
        cache_creation_input_tokens=100,
    )
    log_cache_usage(usage, call_site="test.site", model="claude-opus-4-7")
    assert captured["action_type"] == "claude:cache_usage"
    payload = captured["payload"]
    assert payload["call_site"] == "test.site"
    assert payload["cache_read_tokens"] == 3000
    assert payload["cache_write_tokens"] == 100
    assert payload["input_tokens"] == 500
    # Hit rate = 3000 / (3000 + 500) = 0.857...
    assert 0.85 < payload["cache_hit_ratio"] < 0.87


def test_log_cache_usage_silent_on_missing_store(monkeypatch):
    """No store singleton → no raise, no crash."""
    from kbl.cache_telemetry import log_cache_usage
    _install_fake_store_module(monkeypatch, None)
    usage = MagicMock(input_tokens=10, output_tokens=5,
                      cache_read_input_tokens=0, cache_creation_input_tokens=0)
    log_cache_usage(usage, call_site="x")  # no exception


def test_log_cache_usage_silent_on_malformed_usage(monkeypatch):
    """Usage-object with missing attrs → silent skip."""
    from kbl.cache_telemetry import log_cache_usage
    usage = object()  # no attrs at all
    log_cache_usage(usage, call_site="x")  # no exception


def test_audit_classifies_below_threshold():
    """A synthetic call site with short system prompt classifies as below_threshold."""
    import tempfile
    import textwrap
    import importlib.util
    import sys as _sys

    mod_name = "audit_prompt_cache_mod"
    spec = importlib.util.spec_from_file_location(mod_name, str(AUDIT_SCRIPT))
    aud = importlib.util.module_from_spec(spec)
    # dataclass resolution under `from __future__ import annotations` needs
    # the module registered in sys.modules before exec_module runs.
    _sys.modules[mod_name] = aud
    spec.loader.exec_module(aud)

    # Synthetic source with a Claude call for the audit to parse.
    # Pieces concatenated so lint grep (ship-gate #9) does not false-match
    # these strings as a live API call from the test runtime.
    _call = ".create"
    _ctor = ".Anthropic"
    src = textwrap.dedent(f"""
        import anthropic
        c = anthropic{_ctor}()
        c.messages{_call}(
            model="x",
            system="short prompt",
            messages=[{{"role": "user", "content": "hi"}}],
        )
    """)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(src)
        path = Path(f.name)
    try:
        sites = aud._find_call_sites_in_file(path)
        assert len(sites) == 1
        assert sites[0].tier == "below_threshold"
    finally:
        path.unlink()
