"""COCKPIT_SERVE_STOPGAP_1 — serve frozen cockpit HTML from baker-vault.

Interim bridge until the Publisher write slice serves these artifacts directly.
Reads only from baker-vault main through GitHub Contents API and keeps a short
in-process cache to avoid repeated API hits from Director page clicks.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

_PROJECT_CODE_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$")
_VAULT_OWNER = os.getenv("BAKER_VAULT_GITHUB_OWNER", "vallen300-bit")
_VAULT_REPO = os.getenv("BAKER_VAULT_GITHUB_REPO", "baker-vault")
_BASE_DIR = "_ops/build/baker-os-v2/05_outputs/flight-dashboards"
_CACHE_TTL_S = int(os.getenv("COCKPIT_HTML_CACHE_SECONDS", "120"))
_GITHUB_API = "https://api.github.com"
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, "CockpitHtml"]] = {}


class CockpitConfigError(RuntimeError):
    """The service is not configured to read baker-vault."""


class CockpitNotFound(FileNotFoundError):
    """No cockpit HTML exists for the requested project."""


@dataclass(frozen=True)
class CockpitHtml:
    project_code: str
    path: str
    html: str


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def normalize_project_code(raw: str) -> str:
    code = str(raw or "").strip().upper()
    if not _PROJECT_CODE_RE.fullmatch(code):
        raise ValueError("invalid project_code")
    return code


def _token() -> str:
    token = os.getenv("BAKER_VAULT_READ_TOKEN", "").strip()
    if not token:
        raise CockpitConfigError("BAKER_VAULT_READ_TOKEN is not configured")
    return token


def _contents_url(path: str) -> str:
    encoded = urllib.parse.quote(path, safe="/")
    return f"{_GITHUB_API}/repos/{_VAULT_OWNER}/{_VAULT_REPO}/contents/{encoded}?ref=main"


def _github_json(path: str) -> Any:
    req = urllib.request.Request(
        _contents_url(path),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_token()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "baker-master-cockpit-serve",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise CockpitNotFound(path) from e
        raise RuntimeError(f"GitHub contents read failed: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError("GitHub contents read failed") from e


def _dashboard_sort_key(entry: dict[str, Any]) -> tuple[int, tuple[int, ...], str]:
    name = str(entry.get("name") or "")
    numbers = tuple(int(x) for x in re.findall(r"\d+", name))
    return (max(numbers) if numbers else -1, numbers, name)


def _pick_dashboard(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    dashboards = [
        e for e in entries
        if e.get("type") == "file"
        and str(e.get("name") or "").lower().endswith(".html")
        and "dashboard" in str(e.get("name") or "").lower()
    ]
    if not dashboards:
        return None
    return max(dashboards, key=_dashboard_sort_key)


def _read_file_content(path: str) -> str:
    payload = _github_json(path)
    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise CockpitNotFound(path)
    encoded = str(payload.get("content") or "")
    if not encoded:
        raise CockpitNotFound(path)
    raw = base64.b64decode(encoded)
    return raw.decode("utf-8")


# "Back to Arrivals" control injected into every served cockpit — the desk
# cockpit files have no board-return control of their own (they are also opened
# standalone). Serving-layer injection keeps the vault files untouched and
# covers every flight at once. Same-origin /arrivals; the PIN cookie already set.
#
# Pattern-E cockpits (sidebar <aside> present) get the Director-ratified form
# (12 Jul 2026): "← Arrivals" as the FIRST sidebar element, in the cockpit's own
# .golink accent register ("open →" / "sources →" card links), replacing the
# redundant desk kicker ("AO Desk" etc — hidden via `aside>.kicker`; the nested
# .projects/.asks section kickers are unaffected). var(--brand) inherits the
# cockpit's light/dark theme; fallback is the ratified light-mode brand.
_BACK_CRUMB_STYLE = (
    '<style id="arrivals-back">'
    "aside>.kicker{display:none}"
    ".arrivals-back{display:inline-block;margin:2px 0 16px;padding:0 10px;"
    "font:600 12.5px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;"
    "color:var(--brand,var(--blue,#006399));text-decoration:none;cursor:pointer}"
    ".arrivals-back:hover{text-decoration:underline}"
    "</style>"
)
_BACK_CRUMB = '<a class="arrivals-back" href="/arrivals">&#8592; Arrivals</a>'
_ASIDE_RE = re.compile(r"<aside(?:\s[^>]*)?>", re.IGNORECASE)
# Content pages without a sidebar (flight snapshot .wrap, flight dashboard main):
# the breadcrumb opens the content flow instead. padding:0 — these pages have no
# kicker grid to align to.
_CONTENT_CRUMB_STYLE = _BACK_CRUMB_STYLE.replace("padding:0 10px;", "padding:0;")
_CONTENT_OPEN_RE = re.compile(r'<main(?:\s[^>]*)?>|<div class="wrap">', re.IGNORECASE)
_H1_RE = re.compile(r"<h1(?:\s[^>]*)?>", re.IGNORECASE)

# Fallback for cockpits without a sidebar: floating fixed pill (pre-12-Jul form),
# mirrors the cockpit's native ".backlink" pill so it stays reachable on scroll.
_BACK_BUTTON = (
    '<a href="/arrivals" '
    'style="position:fixed;top:14px;left:14px;z-index:99999;display:inline-block;'
    "font:600 12.5px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;"
    "color:var(--ink-3,#676C6F);background:var(--surface,#FFFFFF);"
    "border:1px solid var(--line-strong,#DADCDD);border-radius:6px;padding:6px 12px;"
    'text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,.12);">&#8592; Arrivals</a>'
)


def _inject_back_button(html: str) -> str:
    """Insert the ARRIVALS return control (Director-ratified breadcrumb, 12 Jul):
    right after the first <aside> when a sidebar exists; else at the top of the
    content flow (after <main>/<div class="wrap">, or before the first <h1>);
    else the floating-pill fallback before the last </body> (or appended — a
    fixed-position anchor renders anywhere)."""
    if not html:
        return _BACK_BUTTON
    m = _ASIDE_RE.search(html)
    if m:
        at = m.end()
        return html[:at] + _BACK_CRUMB_STYLE + _BACK_CRUMB + html[at:]
    m = _CONTENT_OPEN_RE.search(html)
    if m:
        at = m.end()
        return html[:at] + _CONTENT_CRUMB_STYLE + _BACK_CRUMB + html[at:]
    m = _H1_RE.search(html)
    if m:
        at = m.start()
        return html[:at] + _CONTENT_CRUMB_STYLE + _BACK_CRUMB + html[at:]
    idx = html.lower().rfind("</body>")
    if idx == -1:
        return html + _BACK_BUTTON
    return html[:idx] + _BACK_BUTTON + html[idx:]


def fetch_cockpit_html(project_code: str) -> CockpitHtml:
    code = normalize_project_code(project_code)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(code)
        if hit and hit[0] > now:
            return hit[1]

    folder = f"{_BASE_DIR}/{code}"
    payload = _github_json(folder)
    if not isinstance(payload, list):
        raise CockpitNotFound(folder)
    selected = _pick_dashboard(payload)
    if not selected:
        raise CockpitNotFound(folder)
    path = str(selected.get("path") or "")
    if not path.startswith(f"{folder}/"):
        raise CockpitNotFound(folder)
    html = _inject_back_button(_read_file_content(path))
    result = CockpitHtml(project_code=code, path=path, html=html)

    with _CACHE_LOCK:
        _CACHE[code] = (now + _CACHE_TTL_S, result)
    return result
