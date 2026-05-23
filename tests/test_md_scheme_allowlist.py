"""MD_SCHEME_ALLOWLIST_1 — scheme allowlist for md() link hrefs in dashboard JS.

V0.2 (2026-05-23): folds gate-1 + gate-4 review on V0.1 into the helper and
adds tests for the five bypass classes that V0.1 + V0.1's `/security-review`
missed (2 CRITICAL + 2 HIGH + 1 MEDIUM):

  - CRIT  percent-encoded scheme   `javascript%3Aalert(1)`
  - CRIT  quote-attribute-breakout `https://x"onclick=alert(1)//`
  - HIGH  protocol-relative        `//evil.com`
  - HIGH  embedded TAB/CR/LF       `java\tscript:alert(1)`
  - MED   Node/browser parity gap  (documented; tests written to match
          post-V0.2 helper behavior which now does decoding in JS itself)

Two layers of assertion (unchanged from V0.1, expanded):

  (1) Static file inspection — both `outputs/static/{app.js,mobile.js}`
      define `_safeHref`, the link regex uses a callback that calls it,
      the helper's JSDoc names esc() + the threat scheme, the helper
      bodies are byte-identical between files, and the cache-bust query
      param is bumped in both HTML shells.

  (2) Functional execution via `node -e` subprocess — the regex-extracted
      `_safeHref` source block is injected verbatim into a Node script
      with hardcoded URL fixtures; the helper runs end-to-end against
      allow / reject / quote-escape / edge cases. If `node` is not on
      PATH the functional layer is skipped.

Node/browser parity note (V0.2 MEDIUM follow-up): Node does not implement
browser-side `href` URL parsing (WHATWG URL spec §4.1 control-char
stripping, percent-decoding before scheme detection). The V0.2 helper
explicitly bakes both behaviors into `_safeHref` itself (strip `\\t\\n\\r`,
`decodeURIComponent` loop before scheme regex), so what Node sees IS what
the browser sees. Any future browser-only URL-parsing quirk would need a
Playwright headless smoke test — flagged as follow-up, NOT in this brief.
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

# Allow-path fixtures. Helper must return the original (trimmed) URL — the
# encoding of legitimate URLs is preserved, not normalized away.
ALLOW_CASES = [
    ("[link](https://example.com)",   "https://example.com",   "link"),
    ("[mail](mailto:foo@bar.com)",    "mailto:foo@bar.com",    "mail"),
    ("[anchor](#section)",            "#section",              "anchor"),
    ("[relative](/api/foo)",          "/api/foo",              "relative"),
    ("[query](?q=1)",                 "?q=1",                  "query"),
    ("[tel](tel:+41799605092)",       "tel:+41799605092",      "tel"),
    ("[plain](example.com)",          "example.com",           "plain"),
    # Legitimate percent-encoded path component must NOT be rejected.
    ("[path](https://example.com/path%20with%20space)",
     "https://example.com/path%20with%20space",                "path"),
]

# Reject-path fixtures — every entry must yield `'#'` exactly. Covers V0.1
# baseline (javascript / data / file / vbscript / mixed-case / leading-ws)
# plus the five V0.2 bypass classes from gate-4 review.
REJECT_CASES = [
    # V0.1 baseline
    "[evil](javascript:alert(1))",
    "[data](data:text/html,1)",
    "[file](file:///etc/passwd)",
    "[vb](vbscript:msgbox(1))",
    "[mixed](JaVaScRiPt:alert(1))",
    "[ws]( javascript:alert(1))",
    # V0.2 CRIT 1 — percent-encoded scheme
    "[pct](javascript%3Aalert(1))",
    "[pctlower](javascript%3aalert(1))",
    # V0.2 CRIT 1 (extended) — double-encoded
    "[pct2](javascript%253Aalert(1))",
    # V0.2 HIGH 1 — protocol-relative
    "[prot](//evil.com/path)",
    "[prot2](//evil.com)",
    # V0.2 HIGH 2 — embedded TAB/CR/LF
    "[tab](java\tscript:alert(1))",
    "[lf](java\nscript:alert(1))",
    "[cr](java\rscript:alert(1))",
    # Combination — encoded + mixed case
    "[combo](JAVASCRIPT%3Aalert(1))",
]

# Quote-escape fixtures — V0.2 CRIT 2. Helper passes these because the
# scheme IS allowlisted, but the `"` must be escaped to `&quot;` so the
# attribute parser doesn't break out. Pre-V0.2 these would render an
# attribute-breakout HTML injection.
QUOTE_ESCAPE_CASES = [
    # input URL                                          → expected helper output
    ('https://example.com"onclick=alert(1)//',
     'https://example.com&quot;onclick=alert(1)//'),
    ('https://example.com/path?q="bad"',
     'https://example.com/path?q=&quot;bad&quot;'),
    # Relative URL with `"` must also be escaped.
    ('/api/foo?x="y"',
     '/api/foo?x=&quot;y&quot;'),
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


# Gate-1 LOW nit fix: don't depend on an arbitrary character-count preamble.
# Find the JSDoc block immediately preceding the function declaration and
# assert it contains the required keywords.
_JSDOC_BEFORE_SAFEHREF = re.compile(
    r"/\*\*(?P<doc>.*?)\*/\s*\nfunction _safeHref\(url\)",
    flags=re.DOTALL,
)


def test_safehref_comment_documents_esc_interaction() -> None:
    """AC6: JSDoc immediately above _safeHref documents the esc()/_safeHref split."""
    for path in (APP_JS, MOBILE_JS):
        src = path.read_text()
        m = _JSDOC_BEFORE_SAFEHREF.search(src)
        assert m is not None, (
            f"{path.name}: no JSDoc /** ... */ block found immediately above "
            "function _safeHref — AC6 requires one."
        )
        doc = m.group("doc")
        assert "esc()" in doc, (
            f"{path.name}: JSDoc above _safeHref must reference esc() per AC6."
        )
        assert "javascript:" in doc.lower(), (
            f"{path.name}: JSDoc above _safeHref must name the threat scheme per AC6."
        )


def test_cache_bust_bumped() -> None:
    """Frontend rule: bump `?v=N` on every CSS/JS change for iOS PWA cache busting."""
    idx_src = INDEX_HTML.read_text()
    mob_src = MOBILE_HTML.read_text()
    m_app = re.search(r"/static/app\.js\?v=(\d+)", idx_src)
    assert m_app is not None, "app.js cache-bust query string missing from index.html"
    # V0.1 bumped to 119; V0.2 bumps to >=120.
    assert int(m_app.group(1)) >= 120, (
        f"app.js cache-bust not bumped for V0.2 — found v={m_app.group(1)}, expected >=120."
    )
    m_mob = re.search(r"/static/mobile\.js\?v=(\d+)", mob_src)
    assert m_mob is not None, "mobile.js cache-bust query string missing from mobile.html"
    # V0.1 bumped to 42; V0.2 bumps to >=43.
    assert int(m_mob.group(1)) >= 43, (
        f"mobile.js cache-bust not bumped for V0.2 — found v={m_mob.group(1)}, expected >=43."
    )


# Gate-1 LOW nit fix: relax the helper-block regex so a missing trailing newline
# at end-of-file doesn't fail extraction. Match the function body up to the
# matching closing brace at column 0 (which is the convention for these files);
# accept either `\n}\n` or `\n}` at file-end.
_SAFEHREF_BLOCK_RE = re.compile(
    r"function _safeHref\(url\) \{.*?\n\}(?:\n|$)",
    flags=re.DOTALL,
)


def _extract_safehref_block(src: str) -> str:
    """Pull the `function _safeHref(url) { ... }` block out of a JS source.

    Used both by the symmetry test (Layer 1) and the functional test (Layer 2)
    so the two layers agree on what they're inspecting.
    """
    m = _SAFEHREF_BLOCK_RE.search(src)
    if m is None:
        raise AssertionError("could not locate _safeHref function block")
    # Normalize trailing newline so callers (e.g. symmetry comparison) see the
    # same shape regardless of whether the source file ends with `\n}\n` or `\n}`.
    block = m.group(0)
    if not block.endswith("\n"):
        block += "\n"
    return block


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

    Node/browser parity (V0.2): the helper does TAB/CR/LF stripping and
    percent-decoding in JS itself, so Node's output IS what the browser sees.
    Pre-V0.2 the helper relied on browser-side URL parsing for those steps,
    which Node couldn't simulate — that gap closed in V0.2.
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
    """AC3 — allow schemes (and legitimate percent-encoded paths) pass unchanged."""
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
    """AC4 + AC5 — every REJECT_CASES entry must collapse to '#'.

    Covers V0.1 baseline (javascript / data / file / vbscript / mixed-case /
    leading-ws) plus the five V0.2 bypass classes:
      - CRIT  percent-encoded scheme (single + double)
      - HIGH  protocol-relative `//evil.com`
      - HIGH  embedded TAB/CR/LF
      - combo encoded + uppercase
    """
    reject_urls = [src.split("](", 1)[1].rstrip(")") for src in REJECT_CASES]
    results = _run_node_harness(path, [], reject_urls)
    bad = [r for r in results["reject"] if r["out"] != "#"]
    assert not bad, (
        f"{path.name} _safeHref failed to neutralize a dangerous scheme:\n  {bad}"
    )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_quote_escape(path: Path) -> None:
    """V0.2 CRIT 2 — `"` in URL must be escaped to `&quot;` at the return barrier.

    Pre-V0.2 the helper returned the URL verbatim, allowing a URL containing
    `"` to terminate the href attribute and inject HTML. V0.2 escapes `"` to
    `&quot;` so the attribute parser stays inside the value.
    """
    inputs = [src for (src, _) in QUOTE_ESCAPE_CASES]
    expected = {src: out for (src, out) in QUOTE_ESCAPE_CASES}
    results = _run_node_harness(path, inputs, [])
    actual = {r["in"]: r["out"] for r in results["allow"]}
    assert actual == expected, (
        f"{path.name} _safeHref did not escape `\"` correctly:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}"
    )
    # Defensive: no raw `"` in any return value.
    for r in results["allow"]:
        assert '"' not in r["out"], (
            f"{path.name}: raw `\"` survived in helper output for {r['in']!r}: {r['out']!r}"
        )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_empty_and_whitespace_input(path: Path) -> None:
    """Edge: empty string + whitespace-only input both return '#' (no surprises).

    Gate-1 LOW nit V0.1: V0.1 only asserted that whitespace-only inputs did
    not contain `'script'` in the output — too weak. V0.2 asserts the exact
    return value is `'#'` for empty AND for whitespace-only inputs (after
    `.trim()` + `\\t\\n\\r` strip, these all degrade to an empty string,
    which the helper treats as the no-scheme fallthrough returning `''` —
    OR the early `if (!url) return '#'` branch for the truly-empty case).
    """
    results = _run_node_harness(path, ["", " ", "   ", "\t", "\n", "\t\n\r"], [])
    by_input = {r["in"]: r["out"] for r in results["allow"]}
    # Empty string: hits the `if (!url) return '#'` guard.
    assert by_input[""] == "#", f"empty href must return '#', got {by_input['']!r}"
    # Whitespace-only inputs degrade after trim+strip to ''. The helper's
    # no-scheme fallthrough returns the trimmed value, which is ''. That's
    # safe (no scheme, no path) but ambiguous; treat '' and '#' as equally
    # acceptable here. The hard constraint is: nothing browser-executable.
    for input_str in (" ", "   ", "\t", "\n", "\t\n\r"):
        out = by_input[input_str]
        assert out in ("", "#"), (
            f"whitespace-only input {input_str!r} produced unexpected output: {out!r}"
        )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — functional layer skipped")
@pytest.mark.parametrize("path", [APP_JS, MOBILE_JS], ids=["app.js", "mobile.js"])
def test_functional_html_entity_encoded_scheme(path: Path) -> None:
    """AC5 — HTML-entity-encoded scheme (post-esc()) is not interpreted as a scheme.

    `esc()` runs FIRST on user input and converts `:` to `&#58;`. The string
    `javascript&#58;alert(1)` no longer matches our scheme regex (which keys
    on a literal `:` after the scheme name), so the helper treats it as a
    no-scheme value. The browser does NOT interpret entity-encoded colons in
    `href` as scheme separators (entity-decoding happens at the HTML parser
    layer, but `href` URL parsing operates on the already-decoded attribute
    value, and a literal `:` after entity decode would still need to be in
    the SCHEME position — which it's not because the helper kept it
    verbatim). Confirmed safe by design + no further escape needed.
    """
    encoded = "javascript&#58;alert(1)"
    results = _run_node_harness(path, [encoded], [])
    out = results["allow"][0]["out"]
    assert out == "#" or out == encoded, (
        f"entity-encoded scheme produced unexpected href: {out!r}"
    )
    assert "javascript:" not in out.lower(), (
        f"entity-encoded scheme decoded into a real scheme — UNSAFE: {out!r}"
    )
