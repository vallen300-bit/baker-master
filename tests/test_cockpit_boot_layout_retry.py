"""COCKPIT_BOOT_LAYOUT_RETRY_1 - static contract for resilient cockpit boot."""
import re
from pathlib import Path


JS = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "cockpit_static"
    / "cockpit.js"
).read_text()


def _boot_body() -> str:
    match = re.search(r"  async function boot\(\) \{(?P<body>.*?)\n  \}\n\n  document\.addEventListener",
                      JS, flags=re.S)
    assert match, "boot() body not found"
    return match.group("body")


def test_boot_retries_layout_with_bounded_backoff_and_timeout():
    assert "const BOOT_RETRY_DELAYS_MS = [0, 1500, 4000];" in JS
    assert "const BOOT_FETCH_TIMEOUT_MS = 8000;" in JS
    assert "AbortSignal.timeout(BOOT_FETCH_TIMEOUT_MS)" in JS
    assert "async function fetchLayoutWithRetry()" in JS
    assert "for (const delay of BOOT_RETRY_DELAYS_MS)" in JS
    assert 'if (!r.ok) throw new Error("layout HTTP " + r.status);' in JS


def test_failed_boot_self_heals_without_duplicate_initialization():
    boot = _boot_body()
    assert "if (bootReady || bootInFlight) return;" in boot
    assert "bootInFlight = true;" in boot
    assert "bootInFlight = false;" in boot
    assert "buildSidebar();" in boot
    assert "if (pollTimer === null) pollTimer = setInterval(poll, POLL_MS);" in boot
    assert 'connEl.textContent = "layout load failed — retrying";' in boot
    assert "armBootSelfHeal();" in boot
    assert "disarmBootSelfHeal();" in boot
    assert "const BOOT_SELF_HEAL_MS = 60000;" in JS
    assert "bootSelfHealTimer = setInterval(() => { void boot(); }, BOOT_SELF_HEAL_MS);" in JS
    assert "clearInterval(bootSelfHealTimer);" in JS


def test_visibility_retry_only_runs_when_page_is_visible():
    assert 'document.addEventListener("visibilitychange", () => {' in JS
    assert 'document.visibilityState === "visible" && !bootReady' in JS
