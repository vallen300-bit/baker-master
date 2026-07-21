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
const end = source.indexOf("function setLayoutStatus", start);
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

    boot = _between(JS, "function boot()", "  // LAB_UNIFY_THEME_COCKPIT_EXTENSION_1")
    assert "if (bootReady) return Promise.resolve();" in boot
    assert "if (bootInFlight) return bootInFlight;" in boot
    assert "await poll();" in boot
    assert "if (pollTimer === null) pollTimer = setInterval(poll, POLL_MS);" in boot
    assert JS.index("const POLL_TIMEOUT_MS = 10000;") < JS.index("async function fetchWithTimeout")


def test_layout_boot_retries_and_self_heals_without_duplicate_timers():
    assert "const LAYOUT_RETRY_DELAYS_MS = [1500, 4000];" in JS
    assert "const LAYOUT_TIMEOUT_MS = 8000;" in JS
    assert "const LAYOUT_SELF_HEAL_MS = 60000;" in JS
    loader = _between(JS, "async function loadLayoutWithRetry()", "function clearLayoutSelfHeal")
    assert 'url("/cockpit_layout.json")' in loader
    assert "LAYOUT_TIMEOUT_MS" in loader
    assert 'setLayoutStatus("Layout load failed — retrying")' in loader
    assert "LAYOUT_RETRY_DELAYS_MS[attempt]" in loader
    assert 'setLayoutStatus("Layout load failed — " + e.message)' in JS
    assert 'document.addEventListener("visibilitychange"' in JS
    assert "document.visibilityState === \"visible\"" in JS
    assert "clearInterval(layoutHealTimer)" in JS
    assert "if (layoutHealTimer !== null) return;" in JS
