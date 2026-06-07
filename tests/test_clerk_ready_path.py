"""CLERK_READY_PATH_CONTRADICTION_FIX_1 — regression tests.

The bug (Director hit it live): Clerk advertised
  'Ready: /Baker-Project/search_results_nvidia.txt'
on a search-only turn — no file was ever saved, /Baker-Project is not even an
allowed save prefix — then refused to open it as 'outside authorized prefixes'.

Root cause (diagnosis #2289): the worker derived the Director-visible Ready/draft
path from two UNGROUNDED sources — a free-text `Ready:` regex scrape of the model
answer, and the unverified file_save INPUT-arg path (which can echo a path that
_file_save then BLOCKED).

The fix grounds the path in a VERIFIED save:
  - clerk_runtime.run() captures the real Dropbox path from a status:"ready"
    file_save result only, on result['saved_paths'];
  - clerk_bus_worker._extract_draft consumes ONLY that list; no verified save ->
    no draft path.

Pure unit tests — fake model client / canned dicts, no live Qwen/DB/Dropbox.
"""
from __future__ import annotations

import json

import pytest

from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _verified_saved_path,
)
from orchestrator.clerk_bus_worker import _extract_draft


class _FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("no fake response left")
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _cfg(max_steps=12, timeout=180):
    from config.settings import Qwen3Config

    return Qwen3Config(
        base_url="https://qwen.example/v1",
        api_key="test-key",
        model="qwen3-coder",
        backend="qwen3_hosted",
        max_steps=max_steps,
        task_timeout_s=timeout,
    )


# ── _verified_saved_path helper: only a status:ready result yields a path ─────

def test_verified_saved_path_ready_returns_real_path():
    result = json.dumps({
        "status": "ready",
        "path": "/Baker-Feed/Clerk-Workbench/out.md",
        "metadata": {"path_display": "/Baker-Feed/Clerk-Workbench/out.md"},
    })
    assert _verified_saved_path(result) == "/Baker-Feed/Clerk-Workbench/out.md"


def test_verified_saved_path_blocked_returns_none():
    # _file_save returns this when the requested path is outside the working folder.
    result = json.dumps({
        "status": "blocked",
        "reason": "dropbox_path outside Clerk working folder",
        "dropbox_path": "/Baker-Project/search_results_nvidia.txt",
    })
    assert _verified_saved_path(result) is None


@pytest.mark.parametrize("result", [
    "not json at all",
    "",
    json.dumps({"status": "ready"}),            # ready but no path
    json.dumps({"status": "ready", "path": ""}),  # empty path
    json.dumps({"status": "ready", "path": "   "}),  # whitespace path
    json.dumps({"path": "/Baker-Feed/Clerk-Workbench/x.md"}),  # no status
    json.dumps(["/Baker-Feed/Clerk-Workbench/x.md"]),  # not a dict
])
def test_verified_saved_path_malformed_or_unverified_returns_none(result):
    assert _verified_saved_path(result) is None


# ── run() exposes saved_paths ONLY from a verified (status:ready) save ────────

def test_run_exposes_saved_path_on_ready_save(monkeypatch):
    reg = ClerkToolRegistry()
    monkeypatch.setattr(reg, "_file_save", lambda args: json.dumps({
        "status": "ready",
        "path": "/Baker-Feed/Clerk-Workbench/out.md",
        "metadata": {"path_display": "/Baker-Feed/Clerk-Workbench/out.md"},
    }))
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("s1", "file_save", {"content": "x", "filename": "out.md"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("Saved the note.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=reg, cfg=_cfg())
    result = agent.run("save this note to my folder")
    assert result["status"] == "ready"
    assert result["saved_paths"] == ["/Baker-Feed/Clerk-Workbench/out.md"]


def test_run_blocked_save_exposes_no_saved_path(monkeypatch):
    # The model tried to save to /Baker-Project; _file_save blocks it. Even though the
    # model then emits a 'Ready: /Baker-Project/...' line, run() must expose NO path.
    reg = ClerkToolRegistry()
    monkeypatch.setattr(reg, "_file_save", lambda args: json.dumps({
        "status": "blocked",
        "reason": "dropbox_path outside Clerk working folder",
        "dropbox_path": "/Baker-Project/x.txt",
    }))
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("s1", "file_save", {"content": "x", "dropbox_path": "/Baker-Project/x.txt"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("Ready: /Baker-Project/x.txt")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=reg, cfg=_cfg())
    result = agent.run("save this note to my folder")
    assert result["status"] == "ready"
    assert result["saved_paths"] == []


def test_run_search_only_turn_exposes_no_saved_path(monkeypatch):
    # A grounded search that saved nothing must still expose saved_paths == [] — so a
    # hallucinated 'Ready:' line in the answer has no real path behind it.
    monkeypatch.setitem(
        __import__("sys").modules, "outputs.dashboard",
        __import__("types").SimpleNamespace(search_documents_core=lambda *a, **k: {
            "results": [{"id": 1, "title": "n.pdf", "summary": "nvidia"}], "total": 48, "mode": "semantic",
        }),
    )
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("c1", "baker_search", {"query": "nvidia"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("48 documents mention nvidia. Ready: /Baker-Project/search_results_nvidia.txt")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("how many documents mention nvidia")
    assert result["status"] == "ready"
    assert result["saved_paths"] == []


# ── worker _extract_draft: path ONLY from verified saved_paths ───────────────

def test_extract_draft_hallucinated_ready_line_yields_no_path():
    # The exact live bug: model wrote a Ready: line, the turn was search-only, no
    # file_save, no saved_paths. The worker must NOT surface that path.
    result = {
        "status": "ready",
        "answer": "48 documents mention nvidia. Ready: /Baker-Project/search_results_nvidia.txt / Source: baker_search",
        "tool_calls": [{"name": "baker_search", "input": {"query": "nvidia"}}],
        "saved_paths": [],
    }
    content, path = _extract_draft(result)
    assert path is None
    assert "Ready: /Baker-Project" in content  # answer preserved as draft content


def test_extract_draft_blocked_save_input_path_not_surfaced():
    # file_save was attempted to /Baker-Project and blocked -> saved_paths empty.
    # The unverified INPUT-arg path must NOT leak as a draft path.
    result = {
        "status": "ready",
        "answer": "I tried to save the results.",
        "tool_calls": [{"name": "file_save", "input": {"content": "draft body", "dropbox_path": "/Baker-Project/x.txt"}}],
        "saved_paths": [],
    }
    content, path = _extract_draft(result)
    assert path is None
    assert content == "draft body"  # preview content still comes from the attempt


def test_extract_draft_real_save_surfaces_verified_path():
    result = {
        "status": "ready",
        "answer": "Saved.",
        "tool_calls": [{"name": "file_save", "input": {"content": "draft body", "filename": "out.md"}}],
        "saved_paths": ["/Baker-Feed/Clerk-Workbench/out.md"],
    }
    content, path = _extract_draft(result)
    assert path == "/Baker-Feed/Clerk-Workbench/out.md"
    assert content == "draft body"


def test_extract_draft_missing_saved_paths_key_yields_no_path():
    # Defensive: a result dict with no saved_paths key at all (older shape) -> None,
    # never a scraped path.
    result = {
        "status": "ready",
        "answer": "Ready: /Baker-Feed/Clerk-Workbench/out.md",
        "tool_calls": [],
    }
    _, path = _extract_draft(result)
    assert path is None


def test_extract_draft_multiple_verified_saves_last_wins():
    result = {
        "saved_paths": ["/Baker-Feed/Clerk-Workbench/a.md", "/Baker-Feed/Clerk-Workbench/b.md"],
        "answer": "Saved two files.",
        "tool_calls": [],
    }
    _, path = _extract_draft(result)
    assert path == "/Baker-Feed/Clerk-Workbench/b.md"
