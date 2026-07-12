#!/usr/bin/env bash
# auth_source_fetch.sh — vetted READ-ONLY authenticated-source reader for the researcher.
#
# RESEARCHER_TRANCHE3_11_AUTH_SOURCE_ACCESS_1 (b2, 2026-07-12; dispatch deputy #9337,
# Director order via lead #9334; codex design-verify #9391). The researcher hits 402 /
# login walls on paywalled specs + journals via WebFetch, and its Bash cage denies raw
# curl/python + Chrome WRITE verbs (fill/click/type) so it can never TYPE a credential.
#
# This wrapper is the sanctioned, STRUCTURALLY-ENFORCED path (codex #9391 F1/Q1): it
# DRIVES an authenticated read of the ALREADY-logged-in port-9222 debug-Chrome profile
# over CDP and returns the rendered text. The credential lives ONLY in that profile's
# cookies — it never touches the researcher. No fill/click/type => no credential-entry,
# no exfil leg. READ-ONLY: no writes outside stdout + the cage log; no arg-driven exec.
#
# ENFORCEMENT (codex #9391, LOCKED):
#   - The researcher NEVER drives Chrome for this feature; this script is the only path.
#     (Wrapper-emits-URL + method discipline was REJECTED as advisory — F1 HIGH.)
#   - URL is parsed with a real parser (urllib), HTTPS-ONLY, userinfo REJECTED, host
#     matched against a BAKED allow-list (exact or dotted-suffix) — no env override, no
#     researcher-writable config (Q3). Non-web schemes rejected.
#   - The FINAL post-redirect host is re-verified against the same allow-list BEFORE any
#     text is returned (Q1) — a redirect off the allow-list discards the read.
#   - Bash cage ships RESEARCHER_BASH_CAGE_ENFORCE=1 (LIVE, codex #9391 F2/Q4); this
#     script assumes ENFORCE-on.
#
# This is an ADDITIVE, read-only cage amendment (codex #9391 F3): it adds ONE exact vetted
# path to the researcher_bash_cage IS_VETTED allow-list; it relaxes NO existing deny.
#
# Usage:
#   auth_source_fetch.sh <https-url>     # print rendered body text of one allow-listed URL
set -u

CDP_HOST="127.0.0.1:9222"                    # HARD-PINNED debug-Chrome CDP endpoint
NAV_TIMEOUT_S=30                             # per-page load ceiling
CAGE_LOG="$HOME/.claude/projects/-Users-dimitry-bm-researcher/bash-cage.log"

# Baked allow-list (codex Q3 — NO env override, NO researcher-writable config). Hosts are
# matched exact OR as a dotted suffix (".arxiv.org" matches "export.arxiv.org"). Extension
# is a lead-approved edit to THIS constant, shipped via the normal PR merge.
AUTH_SOURCE_DOMAINS="arxiv.org
ieeexplore.ieee.org
dl.acm.org
papers.ssrn.com
link.springer.com
www.nature.com
www.sciencedirect.com
onlinelibrary.wiley.com
www.jstor.org
pubs.acs.org"

fail() { echo "auth_source_fetch: $1" >&2; exit "${2:-1}"; }

# --- arg parse: exactly one positional URL, no flags, no arg-driven exec ---
[ "$#" -eq 1 ] || fail "usage: auth_source_fetch.sh <https-url> (exactly one URL arg)" 1
case "$1" in
    -*) fail "no flags accepted; pass a single https URL" 1 ;;
esac
URL="$1"

# --- drive the authenticated CDP read (all validation + extraction in python) ---
# python3 is allowed to run INSIDE this cage-trusted script (same as read_message.sh);
# the cage denies raw python only as a top-level researcher command.
URL="$URL" CDP_HOST="$CDP_HOST" NAV_TIMEOUT_S="$NAV_TIMEOUT_S" \
ALLOWLIST="$AUTH_SOURCE_DOMAINS" python3 - <<'PYEOF'
import json, os, sys, time, urllib.parse, urllib.request

url = os.environ["URL"]
cdp_host = os.environ["CDP_HOST"]
nav_timeout = int(os.environ["NAV_TIMEOUT_S"])
allowlist = [h.strip().lower() for h in os.environ["ALLOWLIST"].splitlines() if h.strip()]


def die(msg, code=2):
    print("auth_source_fetch: %s" % msg, file=sys.stderr)
    sys.exit(code)


def host_allowed(host):
    """Exact or dotted-suffix match against the baked allow-list. Empty host => reject."""
    if not host:
        return False
    host = host.lower()
    for allowed in allowlist:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


# --- 1. structural URL gate (codex Q1: real parser, https-only, no userinfo) ---
parts = urllib.parse.urlsplit(url)
if parts.scheme != "https":
    die("scheme_not_https (only https:// is allowed, got %r)" % (parts.scheme or "",))
if parts.username or parts.password:
    die("userinfo_rejected (credentials in URL are not allowed)")
if not host_allowed(parts.hostname or ""):
    die("domain_not_allowlisted (%r not in the pinned research-source allow-list)"
        % (parts.hostname or "",))


# --- CDP helpers over websocket-client (available in the researcher env) ---
try:
    import websocket  # websocket-client (sync)
except Exception as exc:  # noqa: BLE001
    die("cdp_client_missing (websocket-client unavailable: %s)" % exc, 3)


def http_json(path):
    with urllib.request.urlopen("http://%s%s" % (cdp_host, path), timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=nav_timeout)
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        # Read frames until our reply id comes back (skip event frames).
        deadline = time.time() + nav_timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})
        raise TimeoutError("cdp_timeout waiting for %s" % method)

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


# --- 2. open a fresh target at the URL via the BROWSER endpoint (Target.createTarget) ---
try:
    browser_ws = http_json("/json/version")["webSocketDebuggerUrl"]
except Exception as exc:  # noqa: BLE001
    die("cdp_unreachable (is the port-9222 debug Chrome running? %s)" % exc, 3)

browser = CDP(browser_ws)
target_id = None
try:
    target_id = browser.call("Target.createTarget", {"url": url})["targetId"]
except Exception as exc:  # noqa: BLE001
    browser.close()
    die("cdp_create_target_failed (%s)" % exc, 3)

# --- 3. attach to the page target, wait for load, extract text + FINAL host ---
text, final_host = None, None
try:
    page_ws = None
    for t in http_json("/json/list"):
        if t.get("id") == target_id:
            page_ws = t.get("webSocketDebuggerUrl")
            break
    if not page_ws:
        die("cdp_page_ws_not_found")
    page = CDP(page_ws)
    try:
        page.call("Page.enable")
        # Wait for the REAL page to finish loading (not the initial blank document, which
        # is readyState=='complete' with an empty host). Require BOTH readyState complete
        # AND a non-empty host before proceeding — this is also what makes the final-host
        # redirect check meaningful.
        deadline = time.time() + nav_timeout
        while time.time() < deadline:
            probe = page.call("Runtime.evaluate",
                              {"expression": "document.readyState + '|' + document.location.host",
                               "returnByValue": True}).get("result", {}).get("value") or "|"
            ready, _, host_now = probe.partition("|")
            if ready == "complete" and host_now:
                final_host = host_now
                break
            time.sleep(0.5)
        if final_host is None:
            die("nav_timeout (page did not reach a loaded state with a host in %ss)"
                % nav_timeout, 4)
        # codex Q1: re-verify the FINAL post-redirect host BEFORE returning any text.
        if not host_allowed(final_host):
            die("redirect_off_allowlist (landed on %r, not allow-listed — read discarded)"
                % final_host)
        text = page.call("Runtime.evaluate",
                         {"expression": "document.body ? document.body.innerText : ''",
                          "returnByValue": True}).get("result", {}).get("value") or ""
    finally:
        page.close()
finally:
    # Always close the target we opened (never leave tabs behind).
    try:
        browser.call("Target.closeTarget", {"targetId": target_id})
    except Exception:  # noqa: BLE001
        pass
    browser.close()

# --- 4. emit (bash layer writes the cage audit line) ---
sys.stdout.write(text or "")
if not text:
    die("empty_extraction (page returned no body text — login wall or JS-gated?)", 4)
PYEOF
rc=$?
# Best-effort audit line (never fails the read).
{ printf '%s\t%s\tauth_source_fetch rc=%s\n' "$(date -u +%FT%TZ)" "$URL" "$rc" >> "$CAGE_LOG"; } 2>/dev/null || true
exit "$rc"
