"""MD_SCHEME_ALLOWLIST_1 — scheme allowlist for md() link hrefs in dashboard JS.

Two layers of assertion:

  (1) Static file inspection — both `outputs/static/app.js` and
      `outputs/static/mobile.js` define `_safeHref`, the link regex no
      longer uses literal `'$2'` substitution, and the cache-bust query
      param is bumped in the matching HTML shells.

  (2) Functional execution — when `node` is available on PATH, extract
      each file's `_safeHref` source block in Python, inject it into a
      Node script verbatim, and assert allow / reject / edge-case
      behavior end-to-end. If `node` is not installed the functional
      layer is skipped (static layer still runs).

Brief gate-1+2 reviewer instruction (BRIEF_MD_SCHEME_ALLOWLIST_1) warns
that code-shape review is necessary but NOT sufficient — the rejection
branch must actually fire. The Node-subprocess layer below executes the
real helper against `[evil](javascript:alert(1))` and friends so the
reject path is exercised, not just inspected.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "outputs" / "static" / "app.js"
MOBILE_JS = REPO_ROOT / "outputs" / "static" / "mobile.js"
INDEX_HTML = REPO_ROOT / "outputs" / "static" / "index.html"
MOBILE_HTML = REPO_ROOT / "outputs" / "static" / "mobile.html"

VULN_LITERAL = '<a href="$2" target="_blank" rel="noopener">$1</a>'

ALLOW_CASES = [
    ("[link](https://example.com)",   "https://example.com",   "link"),
    ("[mail](mailto:foo@bar.com)",    "mailto:foo@bar.com",    "mail"),
    ("[anchor](#section)",            "#section",              "anchor"),
    ("[relative](/api/foo)",          "/api/foo",              "relative"),
    ("[query](?q=1)",                 "?q=1",                  "query"),
    ("[tel](tel:+41799605092)",       "tel:+41799605092",      "tel"),
    ("[plain](example.com)",          "example.com",           "plain"),
]

REJECT_CASES = [
    "[evil](javascript:alert(1))",
    "[data](data:text/html,1)",
    "[file](file:///etc/passwd)",
    "[vb](vbscript:msgbox(1))",
    "[mixed](JaVaScRiPt:alert(1))",
    "[ws]( javascript:alert(1))",
]


# ---------------------------------------------------------------------------
# Layer 1 — static file assertions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_safehref_helper_defined(path: Path) -> None:
    src = path.read_text()
    assert "function _safeHref(url)" in src, (
        f"_safeHref helper missing in {path.name} — brief AC1+AC2 require "
        "the same allowlist helper in both files."
    )
    for scheme in ("'https'", "'http'", "'mailto'", "'tel'"):
        assert scheme in src, f"allowlist scheme {scheme} missing in {path.name}"


@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_link_regex_uses_safehref_callback(path: Path) -> None:
    src = path.read_text()
    assert VULN_LITERAL not in src, (
        f"{path.name} still uses the unsafe literal '$2' href substitution. "
        "The link regex must wrap the URL via _safeHref()."
    )
    assert "_safeHref(url)" in src, (
        f"{path.name} link replacement does not call _safeHref(url)."
    )


def test_safehref_comment_documents_esc_interaction() -> None:
    """AC6: comment near the helper documents the esc()/_safeHref split."""
    for path in (APP_JS, MOBILE_JS):
        src = path.read_text()
        idx = src.index("function _safeHref(url)")
        preamble = src[max(0, idx - 600) : idx]
        assert "esc()" in preamble, (
            f"{path.name}: comment above _safeHref must reference esc() per AC6."
        )
        assert "javascript:" in preamble.lower(), (
            f"{path.name}: comment above _safeHref must name the threat scheme per AC6."
        )


def test_cache_bust_bumped() -> None:
    """Frontend rule: bump `?v=N` on every CSS/JS change for iOS PWA cache busting."""
    idx_src = INDEX_HTML.read_text()
    mob_src = MOBILE_HTML.read_text()
    m_app = re.search(r"/static/app\.js\?v=(\d+)", idx_src)
    assert m_app is not None, "app.js cache-bust query string missing from index.html"
    assert int(m_app.group(1)) >= 119, (
        f"app.js cache-bust not bumped — found v={m_app.group(1)}, expected >=119."
    )
    m_mob = re.search(r"/static/mobile\.js\?v=(\d+)", mob_src)
    assert m_mob is not None, "mobile.js cache-bust query string missing from mobile.html"
    assert int(m_mob.group(1)) >= 42, (
        f"mobile.js cache-bust not bumped — found v={m_mob.group(1)}, expected >=42."
    )


def _extract_safehref_block(src: str) -> str:
    """Pull the `function _safeHref(url) { ... }` block out of a JS source.

    Used both by the symmetry test (Layer 1) and the functional test (Layer 2)
    so the two layers agree on what they're inspecting.
    """
    m = re.search(r"function _safeHref\(url\) \{.*?\n\}\n", src, flags=re.DOTALL)
    if m is None:
        raise AssertionError("could not locate _safeHref function block")
    return m.group(0)


def test_implementations_are_symmetric() -> None:
    """AC2 — _safeHref function bodies must be byte-identical between files."""
    app_fn = _extract_safehref_block(APP_JS.read_text())
    mob_fn = _extract_safehref_block(MOBILE_JS.read_text())
    assert app_fn == mob_fn, (
        "AC2 violated: _safeHref function bodies differ between app.js and mobile.js. "
        "Both must be byte-identical so reviewers can diff a single block."
    )


# ---------------------------------------------------------------------------
# Layer 2 — functional execution via Node subprocess
# ---------------------------------------------------------------------------

NODE = shutil.which("node")


def _run_node_harness(path: Path, allow_urls: list[str], reject_urls: list[str]) -> dict:
    """Inject _safeHref source verbatim into a Node script and run it.

    Construction is build-from-source (no dynamic eval / Function constructor):
    Python extracts the function block from the JS file, inserts it as plain
    JS source at the top of the Node script, then appends a fixed harness
    that imports nothing and calls _safeHref directly.
    """
    src = path.read_text()
    safehref_src = _extract_safehref_block(src)
    harness = safehref_src + """
const allow = """ + json.dumps(allow_urls) + """;
const reject = """ + json.dumps(reject_urls) + """;
const results = { allow: [], reject: [] };
for (const u of allow) results.allow.push({ in: u, out: _safeHref(u) });
for (const u of reject) results.reject.push({ in: u, out: _safeHref(u) });
process.stdout.write(JSON.stringify(results));
"""
    proc = subprocess.run(
        [NODE, "-e", harness],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node harness for {path.name} exited {proc.returncode}; "
            f"stderr: {proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_allow_path(path: Path) -> None:
    """AC3 — allow schemes pass through unchanged."""
    allow_urls = [src.split("](", 1)[1].rstrip(")") for (src, _, _) in ALLOW_CASES]
    results = _run_node_harness(path, allow_urls, [])
    expected = {url: url for (_, url, _) in ALLOW_CASES}
    actual = {r["in"]: r["out"] for r in results["allow"]}
    assert actual == expected, (
        f"{path.name} _safeHref mangled an allow-path URL:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}"
    )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_reject_path(path: Path) -> None:
    """AC4 + AC5 — javascript / data / file / vbscript / mixed-case / leading-ws all → '#'."""
    reject_urls = [src.split("](", 1)[1].rstrip(")") for src in REJECT_CASES]
    results = _run_node_harness(path, [], reject_urls)
    bad = [r for r in results["reject"] if r["out"] != "#"]
    assert not bad, (
        f"{path.name} _safeHref failed to neutralize a dangerous scheme:\n  {bad}"
    )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_empty_input(path: Path) -> None:
    """Edge: empty string + whitespace-only input must not yield browser-executable href."""
    results = _run_node_harness(path, ["", " ", "   "], [])
    empties = [r for r in results["allow"] if r["in"] == ""]
    assert empties and empties[0]["out"] == "#", "empty href must collapse to '#'"
    for r in results["allow"]:
        out = (r["out"] or "").lower()
        assert "script" not in out and "javascript" not in out, (
            f"whitespace href produced suspicious output: {r}"
        )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_html_entity_encoded_scheme(path: Path) -> None:
    """AC5 — entity-encoded scheme (post-esc()) is not interpreted as a real scheme.

    `esc()` runs FIRST on user input and converts `:` to `&#58;`. The string
    `javascript&#58;alert(1)` no longer matches our scheme regex (which keys
    on a literal `:` after the scheme name), so the helper treats it as a
    relative URL and returns it as-is. The browser will NOT interpret the
    entity-encoded colon as a scheme separator when reading the href
    attribute — confirmed safe by design.
    """
    encoded = "javascript&#58;alert(1)"
    results = _run_node_harness(path, [encoded], [])
    out = results["allow"][0]["out"]
    # Either the helper rejected it to '#' OR returned it verbatim; both are
    # safe because the browser does not run entity-encoded schemes from hrefs.
    assert out == "#" or out == encoded, (
        f"entity-encoded scheme produced unexpected href: {out!r}"
    )
    assert "javascript:" not in out.lower(), (
        f"entity-encoded scheme decoded into a real scheme — UNSAFE: {out!r}"
    )
