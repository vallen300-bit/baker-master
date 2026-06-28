"""Tests for BRISEN_LAB_WIP_MATERIALS_PANEL_1 — the cockpit WIP-materials panel.

Path-traversal rejection is THE risk, so those cases come FIRST (brief §TDD).
Two layers are exercised independently:
  * bare-segment rejection (separators / ``..`` / dotfiles), and
  * the reused ``vault_mirror._normalize_and_resolve`` guard, proven via
    symlink escapes that bypass the segment check.

Hermetic: a temp dir stands in for the vault mirror via ``VAULT_MIRROR_PATH``;
``vault_mirror.mirror_path()`` reads that env on every call, so no module
reload is needed.
"""

from __future__ import annotations

import os

import pytest

import wip_materials

_SYMLINKS_SUPPORTED = hasattr(os, "symlink")


@pytest.fixture
def wip_mirror(tmp_path, monkeypatch):
    mirror = tmp_path / "baker-vault-mirror"
    wip = mirror / "wiki" / "_wip"
    loop = wip / "airport-loop"
    loop.mkdir(parents=True)
    (loop / "baker-loop-airport-metaphor-v2.html").write_text("<h1>Loop v2</h1>")
    (loop / "baker-loop-airport-metaphor-v1.html").write_text("<h1>Loop v1</h1>")
    (loop / "loop-log.md").write_text("# loop log\n")
    # Non-allowlisted file — must never list or serve.
    (loop / "secret.py").write_text("print('nope')")
    # Dotfile — must never list.
    (loop / ".hidden.html").write_text("<h1>hidden</h1>")
    # An empty topic folder.
    (wip / "empty-topic").mkdir()

    # Traversal targets OUTSIDE _wip: inside wiki/, inside _ops/, at root.
    (mirror / "wiki" / "wiki-secret.md").write_text("WIKI SECRET")
    (mirror / "_ops").mkdir(parents=True)
    (mirror / "_ops" / "ops-secret.md").write_text("OPS SECRET")
    (mirror / "slugs.yml").write_text("SLUGS SECRET")

    monkeypatch.setenv("VAULT_MIRROR_PATH", str(mirror))
    monkeypatch.delenv("VAULT_MIRROR_REMOTE", raising=False)
    return {"mirror": mirror, "wip": wip, "loop": loop}


# ---------------------------------------------------------------------------
# 1. PATH-TRAVERSAL REJECTION — written first (brief §TDD)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "topic,name",
    [
        ("airport-loop", "../../slugs.yml"),       # parent-escape to root
        ("airport-loop", "../wiki-secret.md"),     # one-level escape into wiki/
        ("airport-loop", "/etc/passwd"),           # absolute path
        ("airport-loop", "..%2f..%2fslugs.yml"),   # (decoded form has no sep, but ..)
        ("..", "baker-loop-airport-metaphor-v2.html"),  # topic escape
        ("airport-loop/..", "x.html"),             # separator in topic
        (".", "x.html"),                           # dot topic
        ("airport-loop", ".."),                    # dot-dot name
        ("airport-loop", ".hidden.html"),          # dotfile
    ],
)
def test_safe_path_rejects_traversal(wip_mirror, topic, name):
    assert wip_materials.safe_path(topic, name) is None


def test_safe_path_rejects_non_allowlisted_extension(wip_mirror):
    # File exists, but .py is not servable.
    assert (wip_mirror["loop"] / "secret.py").exists()
    assert wip_materials.safe_path("airport-loop", "secret.py") is None


def test_safe_path_rejects_missing_file(wip_mirror):
    assert wip_materials.safe_path("airport-loop", "does-not-exist.html") is None
    assert wip_materials.safe_path("no-such-topic", "x.html") is None


@pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="symlinks unavailable")
def test_safe_path_rejects_symlink_escape_outside_wiki(wip_mirror):
    """A symlink whose real target leaves wiki/ entirely — caught by the
    reused vault_mirror resolver (realpath fold + wiki/ prefix check)."""
    link = wip_mirror["loop"] / "escape-root.html"
    os.symlink(wip_mirror["mirror"] / "slugs.yml", link)
    assert wip_materials.safe_path("airport-loop", "escape-root.html") is None


@pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="symlinks unavailable")
def test_safe_path_rejects_symlink_escape_into_wiki_but_outside_wip(wip_mirror):
    """A symlink that stays inside wiki/ but leaves _wip — caught by the
    stricter WIP_ROOT containment layer (vault_mirror would allow it)."""
    link = wip_mirror["loop"] / "escape-wiki.md"
    os.symlink(wip_mirror["mirror"] / "wiki" / "wiki-secret.md", link)
    assert wip_materials.safe_path("airport-loop", "escape-wiki.md") is None


# ---------------------------------------------------------------------------
# 2. HAPPY PATH — listing + resolution
# ---------------------------------------------------------------------------


def test_list_topics_returns_sorted_subfolders(wip_mirror):
    assert wip_materials.list_topics() == ["airport-loop", "empty-topic"]


def test_list_files_returns_only_allowlisted_sorted(wip_mirror):
    files = wip_materials.list_files("airport-loop")
    names = [f["name"] for f in files]
    # 2 html + 1 md; secret.py and .hidden.html excluded.
    assert names == [
        "baker-loop-airport-metaphor-v1.html",
        "baker-loop-airport-metaphor-v2.html",
        "loop-log.md",
    ]
    assert all("modified" in f for f in files)


def test_list_files_empty_topic_is_empty(wip_mirror):
    assert wip_materials.list_files("empty-topic") == []


def test_list_files_unsafe_or_missing_topic_is_empty(wip_mirror):
    assert wip_materials.list_files("..") == []
    assert wip_materials.list_files("no-such-topic") == []


def test_safe_path_resolves_existing_html_and_md(wip_mirror):
    html = wip_materials.safe_path(
        "airport-loop", "baker-loop-airport-metaphor-v2.html"
    )
    assert html is not None and html.is_file()
    assert html.read_text() == "<h1>Loop v2</h1>"

    md = wip_materials.safe_path("airport-loop", "loop-log.md")
    assert md is not None and md.is_file()


def test_missing_mirror_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_MIRROR_PATH", str(tmp_path / "does-not-exist"))
    assert wip_materials.list_topics() == []
    assert wip_materials.list_files("airport-loop") == []
    assert wip_materials.safe_path("airport-loop", "x.html") is None


# ---------------------------------------------------------------------------
# 3. ROUTE INTEGRATION — /wip, /wip/list, /wip/file (auth + traversal + happy)
# ---------------------------------------------------------------------------

_KEY = "test-key-wip"


@pytest.fixture
def client(wip_mirror, monkeypatch):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setenv("BAKER_API_KEY", _KEY)
    dash._BAKER_API_KEY = _KEY
    return TestClient(dash.app)


def test_route_wip_page_requires_key(client):
    assert client.get("/wip").status_code == 401


def test_route_wip_page_renders_topics(client):
    r = client.get(f"/wip?key={_KEY}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "airport-loop" in r.text
    assert "empty-topic" in r.text


def test_route_wip_list_requires_key(client):
    assert client.get("/wip/list?topic=airport-loop").status_code == 401


def test_route_wip_list_returns_files(client):
    r = client.get(f"/wip/list?topic=airport-loop&key={_KEY}")
    assert r.status_code == 200
    data = r.json()
    names = [f["name"] for f in data["files"]]
    assert names == [
        "baker-loop-airport-metaphor-v1.html",
        "baker-loop-airport-metaphor-v2.html",
        "loop-log.md",
    ]
    # href is pre-built and carries the key for the iframe.
    assert all(h.startswith("/wip/file?") and "key=" in h
               for h in (f["href"] for f in data["files"]))


def test_route_wip_list_empty_topic(client):
    r = client.get(f"/wip/list?topic=empty-topic&key={_KEY}")
    assert r.status_code == 200
    assert r.json()["files"] == []


def test_route_wip_file_serves_html(client):
    r = client.get(
        f"/wip/file?topic=airport-loop"
        f"&name=baker-loop-airport-metaphor-v2.html&key={_KEY}"
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Loop v2" in r.text


def test_route_wip_file_serves_md_as_text(client):
    r = client.get(
        f"/wip/file?topic=airport-loop&name=loop-log.md&key={_KEY}"
    )
    assert r.status_code == 200
    assert "text/" in r.headers["content-type"]
    assert "loop log" in r.text


def test_route_wip_file_requires_key(client):
    r = client.get(
        "/wip/file?topic=airport-loop&name=baker-loop-airport-metaphor-v2.html"
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    "qs",
    [
        "topic=airport-loop&name=../../slugs.yml",
        "topic=airport-loop&name=../wiki-secret.md",
        "topic=..&name=baker-loop-airport-metaphor-v2.html",
        "topic=airport-loop&name=secret.py",
        "topic=airport-loop&name=does-not-exist.html",
    ],
)
def test_route_wip_file_traversal_returns_404(client, qs):
    r = client.get(f"/wip/file?{qs}&key={_KEY}")
    assert r.status_code == 404
