from orchestrator import cortex_lite_policy as p


def test_lite_disabled_preserves_existing_behavior(monkeypatch):
    monkeypatch.delenv("CORTEX_LITE_ENABLED", raising=False)
    assert p.lite_enabled() is False
    assert p.matter_allowed("movie") is True
    assert p.direct_fire_allowed() is True


def test_lite_allowlist_defaults(monkeypatch):
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.delenv("CORTEX_LITE_MATTERS", raising=False)
    assert p.matter_allowed("oskolkov") is True
    assert p.matter_allowed("hagenauer-rg7") is True
    assert p.matter_allowed("movie") is False


def test_lite_allowlist_env_override(monkeypatch):
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_MATTERS", "oskolkov,mo-vie-am")
    assert p.matter_allowed("oskolkov") is True
    assert p.matter_allowed("mo-vie-am") is True
    assert p.matter_allowed("hagenauer-rg7") is False


def test_lite_direct_fire_hard_off(monkeypatch):
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    assert p.direct_fire_allowed() is False


def test_stale_threshold_constant():
    assert p.stale_pending_hours() == 72.0
