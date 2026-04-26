"""Tests for kbl.gold_writer — Tier B programmatic write path."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from kbl import gold_writer
from kbl.gold_writer import (
    CallerNotAuthorized,
    GoldEntry,
    GoldWriteError,
    append,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Build a fixture vault root with _ops + wiki/matters/<slug> dirs."""
    (tmp_path / "_ops").mkdir(parents=True)
    matter_dir = tmp_path / "wiki" / "matters" / "alpha"
    matter_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture(autouse=True)
def _slug_registry_using_test_vault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES / "vault"))
    from kbl import slug_registry
    slug_registry.reload()
    yield
    slug_registry.reload()


def _entry(**overrides) -> GoldEntry:
    base = dict(
        iso_date="2026-04-26",
        topic="alpha topic",
        ratification_quote='"yes" (Director, 2026-04-26).',  # DV. appended by renderer
        background="Background.",
        resolution="Resolution.",
        authority_chain="Director RA-21",
        carry_forward="none",
        matter=None,
    )
    base.update(overrides)
    return GoldEntry(**base)


# Helper: stub the failure-log DB so tests don't need Postgres.


@pytest.fixture(autouse=True)
def _stub_failure_log(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        gold_writer, "_log_failure", lambda *a, **kw: True
    )


def test_append_global_entry_writes_to_director_gold_global(vault: Path):
    target = append(_entry(), vault_root=vault)
    assert target == vault / "_ops" / "director-gold-global.md"
    text = target.read_text(encoding="utf-8")
    assert "## 2026-04-26 — alpha topic" in text
    assert "**Ratification:**" in text
    assert "DV." in text
    assert "**Background:** Background." in text


def test_append_matter_entry_writes_to_wiki_matters_gold(vault: Path):
    target = append(_entry(matter="alpha"), vault_root=vault)
    assert target == vault / "wiki" / "matters" / "alpha" / "gold.md"
    assert target.read_text(encoding="utf-8").count("## 2026-04-26 — alpha topic") == 1


def test_caller_stack_rejects_cortex_module(vault: Path):
    """A caller whose module starts with cortex_ must be rejected.

    inspect.stack() reads frame.f_globals['__name__'] — the module in which
    the function was DEFINED. We rebind the test helper's globals to a fake
    cortex_* module via FunctionType so the guard sees a cortex caller.
    """
    fake_cortex = types.ModuleType("cortex_test_caller")
    fake_cortex.__dict__["append"] = append
    sys.modules["cortex_test_caller"] = fake_cortex

    def _do_write_template(entry, vault_root):
        return append(entry, vault_root=vault_root)

    rebound = types.FunctionType(
        _do_write_template.__code__,
        fake_cortex.__dict__,
        name="_do_write",
    )

    try:
        with pytest.raises(CallerNotAuthorized):
            rebound(_entry(), vault)
    finally:
        del sys.modules["cortex_test_caller"]


def test_unknown_matter_slug_raises_GoldWriteError(vault: Path):
    with pytest.raises(GoldWriteError, match="not canonical"):
        append(_entry(matter="not-a-real-slug"), vault_root=vault)


def test_failure_logged_to_gold_write_failures(
    vault: Path, monkeypatch: pytest.MonkeyPatch
):
    """Drift validation failure must call _log_failure and re-raise."""
    calls: list[tuple] = []

    def _capturing_log(entry, target, error, caller_stack, **kw):
        calls.append((entry.topic, error, caller_stack[:80]))
        return True

    monkeypatch.setattr(gold_writer, "_log_failure", _capturing_log)

    bad = _entry(topic="")  # SCHEMA: missing topic
    with pytest.raises(GoldWriteError):
        append(bad, vault_root=vault)
    assert len(calls) == 1
    assert calls[0][1] == "drift_validate"
    assert "SCHEMA" in calls[0][2]


def test_dv_initials_required_via_drift_detector(
    vault: Path, monkeypatch: pytest.MonkeyPatch
):
    """If ratification_quote already has DV, renderer doesn't double-append."""
    target = append(
        _entry(ratification_quote='"yes" DV.'),
        vault_root=vault,
    )
    text = target.read_text(encoding="utf-8")
    # No double DV.
    assert text.count(" DV.") == 1


def test_render_appends_dv_when_quote_lacks_it(vault: Path):
    """Renderer auto-appends DV. when ratification_quote omits it."""
    target = append(
        _entry(ratification_quote='"approved" (Director, 2026-04-26).'),
        vault_root=vault,
    )
    text = target.read_text(encoding="utf-8")
    assert "(Director, 2026-04-26). DV." in text


def test_matter_dir_must_exist(tmp_path: Path):
    """Brief: do not auto-create matter dir; fail loud."""
    (tmp_path / "_ops").mkdir()
    # No wiki/matters/alpha directory created.
    with pytest.raises(GoldWriteError, match="does not exist"):
        append(_entry(matter="alpha"), vault_root=tmp_path)


def test_existing_file_appended_not_overwritten(vault: Path):
    target = vault / "_ops" / "director-gold-global.md"
    target.write_text(
        "---\ntitle: existing\n---\n\n## 2026-04-25 — Earlier\n\n**Ratification:** 'old' DV.\n",
        encoding="utf-8",
    )
    append(_entry(), vault_root=vault)
    text = target.read_text(encoding="utf-8")
    assert "## 2026-04-25 — Earlier" in text  # prior entry preserved
    assert "## 2026-04-26 — alpha topic" in text  # new entry added
