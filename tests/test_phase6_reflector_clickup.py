"""ClickUp write tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.6.

V1 default: REFLECTOR_CLICKUP_WRITE=false (Brief 5 deferred per Director
2026-04-30 channels-last). These tests cover both dormant + activated paths
so future Brief 5 V2+ flip is a 1-line env change.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from orchestrator.cortex_phase6_reflector import (
    write_proposed_actions_to_clickup,
)


CONTRACT_YAML = """\
```yaml
contract_version: 1
list_map:
  oskolkov:
    drafts_deliverables: "111"
    folder_id: "f1"
  movie:
    drafts_deliverables: "222"
    folder_id: "f2"
tag_only_matters:
  - constantinos
tag_only_routing:
  constantinos: oskolkov
```
"""


def _write_contract(tmp_path: Path) -> Path:
    p = tmp_path / "cortex-clickup-surface-contract.md"
    p.write_text(CONTRACT_YAML, encoding="utf-8")
    return p


def test_dormant_when_env_false(monkeypatch, tmp_path: Path):
    """V1 default — env unset / false returns None, no API call."""
    monkeypatch.delenv("REFLECTOR_CLICKUP_WRITE", raising=False)
    contract = _write_contract(tmp_path)
    with mock.patch("clickup_client.ClickUpClient") as mock_client:
        result = write_proposed_actions_to_clickup(
            cycle_id="aaa",
            matter_slug="oskolkov",
            proposal_text="x",
            cited_ids=[],
            triaga_outcome="helpful",
            contract_path=contract,
        )
    assert result is None
    mock_client.assert_not_called()


def test_active_creates_task_with_correct_list_id(monkeypatch, tmp_path: Path):
    """REFLECTOR_CLICKUP_WRITE=true + contract present -> create_task called
    with list_id from contract."""
    monkeypatch.setenv("REFLECTOR_CLICKUP_WRITE", "true")
    contract = _write_contract(tmp_path)

    fake_task = {"id": "tk1", "url": "https://app.clickup.com/t/tk1"}
    fake_client = mock.MagicMock()
    fake_client.create_task.return_value = fake_task
    fake_module = mock.MagicMock()
    fake_module.ClickUpClient.return_value = fake_client

    with mock.patch.dict("sys.modules", {"clickup_client": fake_module}):
        result = write_proposed_actions_to_clickup(
            cycle_id="cycle-xyz",
            matter_slug="oskolkov",
            proposal_text="proposal text",
            cited_ids=["oskolkov-001"],
            triaga_outcome="helpful",
            contract_path=contract,
        )

    assert result == "https://app.clickup.com/t/tk1"
    fake_client.create_task.assert_called_once()
    kwargs = fake_client.create_task.call_args.kwargs
    assert kwargs["list_id"] == "111"  # oskolkov's list


def test_tag_only_matter_routes_to_parent(monkeypatch, tmp_path: Path):
    """constantinos -> oskolkov per tag_only_routing; list_id is parent's."""
    monkeypatch.setenv("REFLECTOR_CLICKUP_WRITE", "true")
    contract = _write_contract(tmp_path)

    fake_task = {"id": "tk2", "url": "https://app.clickup.com/t/tk2"}
    fake_client = mock.MagicMock()
    fake_client.create_task.return_value = fake_task
    fake_module = mock.MagicMock()
    fake_module.ClickUpClient.return_value = fake_client

    with mock.patch.dict("sys.modules", {"clickup_client": fake_module}):
        write_proposed_actions_to_clickup(
            cycle_id="cycle-tag",
            matter_slug="constantinos",
            proposal_text="-",
            cited_ids=[],
            triaga_outcome="helpful",
            contract_path=contract,
        )

    kwargs = fake_client.create_task.call_args.kwargs
    # constantinos routes to oskolkov's list_id ("111"), not its own.
    assert kwargs["list_id"] == "111"


def test_unknown_matter_returns_none(monkeypatch, tmp_path: Path):
    """matter_slug absent from list_map and tag_only_matters -> None + warn."""
    monkeypatch.setenv("REFLECTOR_CLICKUP_WRITE", "true")
    contract = _write_contract(tmp_path)
    fake_module = mock.MagicMock()

    with mock.patch.dict("sys.modules", {"clickup_client": fake_module}):
        result = write_proposed_actions_to_clickup(
            cycle_id="cycle-unknown",
            matter_slug="not-in-contract",
            proposal_text="-",
            cited_ids=[],
            triaga_outcome="helpful",
            contract_path=contract,
        )
    assert result is None
    fake_module.ClickUpClient.assert_not_called()


def test_missing_contract_returns_none(monkeypatch, tmp_path: Path):
    """REFLECTOR_CLICKUP_WRITE=true but contract file absent (V1 default
    state — Brief 5 deferred) -> None + warning, no client construction."""
    monkeypatch.setenv("REFLECTOR_CLICKUP_WRITE", "true")
    missing = tmp_path / "does-not-exist.md"
    fake_module = mock.MagicMock()

    with mock.patch.dict("sys.modules", {"clickup_client": fake_module}):
        result = write_proposed_actions_to_clickup(
            cycle_id="c",
            matter_slug="oskolkov",
            proposal_text="-",
            cited_ids=[],
            triaga_outcome="helpful",
            contract_path=missing,
        )
    assert result is None
    fake_module.ClickUpClient.assert_not_called()
