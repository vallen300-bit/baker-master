"""COCKPIT_BOOT_RETRY_1 — startup hydration must not wedge the cockpit.

The cockpit paints its static layout before the live `/api/agents` hydration.
This source-level probe locks the browser-side timeout/abort contract because
the repository has no browser test runner in CI.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


JS = (Path(__file__).resolve().parent.parent / "scripts" / "cockpit_static" / "cockpit.js").read_text()


def _between(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end, source.index(start))]


def test_poll_abort_timeout_is_wired_to_the_agents_fetch():
    helper = _between(JS, "async function fetchWithTimeout", "function poll")
    assert "new AbortController()" in helper
    assert "setTimeout" in helper
    assert "controller.abort()" in helper
    assert "signal: controller.signal" in helper
    assert "clearTimeout(timeoutId)" in helper
    assert 'request timed out after " + timeoutMs + "ms' in helper


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_hung_fetch_is_aborted_by_the_real_browser_helper():
    probe = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("async function fetchWithTimeout");
const end = source.indexOf("function poll", start);
const helper = eval("(" + source.slice(start, end) + ")");

global.fetch = (_url, options) => new Promise((_resolve, reject) => {
  options.signal.addEventListener("abort", () => reject(new Error("aborted")));
});
const started = Date.now();
helper("/api/agents", {}, 25).then(
  () => { throw new Error("hung fetch unexpectedly resolved"); },
  (error) => {
    if (!String(error).includes("request timed out after 25ms")) {
      throw new Error("unexpected timeout error: " + error);
    }
    if (Date.now() - started > 500) {
      throw new Error("timeout helper exceeded probe budget");
    }
    process.exit(0);
  }
);
setTimeout(() => {
  throw new Error("hung fetch was not aborted");
}, 1000);
"""
    result = subprocess.run(
        ["node", "-e", probe, str(Path(__file__).resolve().parent.parent / "scripts" / "cockpit_static" / "cockpit.js")],
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_hung_poll_cannot_stack_and_boot_reaches_interval_setup():
    poll = _between(JS, "function poll()", "// ---- terminal overlay")
    assert "if (pollInFlight) return pollInFlight;" in poll
    assert "pollInFlight = null;" in poll

    boot = _between(JS, "async function boot()", "  // LAB_UNIFY_THEME_COCKPIT_EXTENSION_1")
    assert "await poll();" in boot
    assert "pollTimer = setInterval(poll, POLL_MS);" in boot
    assert JS.index("const POLL_TIMEOUT_MS = 10000;") < JS.index("async function fetchWithTimeout")
