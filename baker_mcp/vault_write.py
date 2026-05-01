"""Vault write — GitHub Contents API direct commit (BAKER_VAULT_WRITE_1).

Bypasses the read-only Render mirror entirely. Strict path whitelist + append-only
enforcement. Every write audited to baker_actions (audit emitted by caller in
baker_mcp_server._dispatch — this module returns the data the caller needs).

Scope invariants (per brief §Solution):
  * Whitelist enforced at path-validation layer (6 path classes)
  * Append-only except wiki/matters/<slug>/_session-state.md
  * Hard-block on gold.md (anywhere under wiki/), wiki/_cortex/**, slugs.yml,
    _priorities.yml (anywhere under wiki/), _ops/**, _install/**
  * curated/ and proposed-gold.md require source/confidence/provenance
    frontmatter with non-empty values
  * Token redaction: every error string surfaced to logs / audit / caller
    is run through _redact() — strips URL-embedded tokens AND Bearer tokens

Authorization tiers (Tier A standing-auth vs Tier B Director-consult per path
class) are enforced at the agent/skill layer (Cowork SKILL.md prose), NOT here.
This module enforces structural guardrails only.
"""
from __future__ import annotations

import base64
import re
from typing import Optional

import httpx

GITHUB_API = "https://api.github.com"
VAULT_REPO = "vallen300-bit/baker-vault"

# ALLOWED path patterns — caller-supplied path must match one of these regexes.
# Slugs validated against alphanumeric+hyphen ([a-z0-9-]+).
# Tuple shape: (regex, klass, overwrite_allowed).
_ALLOWED_PATTERNS: list[tuple[str, str, bool]] = [
    # _session-state.md — overwrite OK (only overwrite-allowed class)
    (r"^wiki/matters/[a-z0-9-]+/_session-state\.md$", "session_state", True),
    # curated/<YYYY-MM-DD>-<slug-topic>.md — append-only, frontmatter required
    (r"^wiki/matters/[a-z0-9-]+/curated/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$", "curated", False),
    # _inbox/handoff-<date>-<src>-to-<tgt>.md — append-only
    (r"^wiki/_inbox/handoff-\d{4}-\d{2}-\d{2}-[a-z0-9-]+-to-[a-z0-9-]+\.md$", "handoff", False),
    # proposed-gold.md — append-only, frontmatter required
    (r"^wiki/matters/[a-z0-9-]+/proposed-gold\.md$", "proposed_gold", False),
    # decisions/<date>-<topic>.md — append-only
    (r"^wiki/matters/[a-z0-9-]+/decisions/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$", "decision", False),
    # red-flags.md — append-only
    (r"^wiki/matters/[a-z0-9-]+/red-flags\.md$", "red_flags", False),
]

# HARD-BLOCK paths — never writable, even by accident.
# Defense-in-depth: catch alternate placements anywhere in the tree, not just
# the canonical path. Reviewer flag (R6): alternate `gold.md` / `_cortex/`
# placements would otherwise slip through allowed-pattern fall-through.
_BLOCKED_PATTERNS: list[str] = [
    r"^wiki/.*gold\.md$",            # any gold.md anywhere under wiki/ (incl. proposed-gold filtered FIRST below)
    r"^wiki/_cortex/.*\.md$",        # cortex meta-knowledge — Director-only
    r"^slugs\.yml$",
    r"^wiki/.*_priorities\.yml$",    # any _priorities.yml anywhere under wiki/
    r"^_ops/.*$",
    r"^_install/.*$",
]

# proposed-gold.md is explicitly allowed by the second-from-last allow-rule.
# We must NOT block it via the generic `gold\.md$` blocker. Whitelist the
# proposed-gold path before evaluating blockers. Defense-in-depth still
# applies via the allow-pattern's strict regex (must match exact shape).
_PROPOSED_GOLD_RE = re.compile(r"^wiki/matters/[a-z0-9-]+/proposed-gold\.md$")


class VaultWriteError(ValueError):
    """Raised on any path / mode / frontmatter / API rejection."""


# --------------------------------------------------------------------------
# Token redaction (mirrors vault_mirror._redact + extends with Bearer regex)
# --------------------------------------------------------------------------

_TOKEN_URL_RE = re.compile(r"https://x-access-token:[^@\s]+@")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+")


def _redact(text) -> str:
    """Strip tokenized URLs and Bearer tokens from text before logging/auditing.

    Mirrors vault_mirror._redact() and extends with Bearer redaction since the
    REST Contents API uses Authorization: Bearer (not the URL-embedded form).
    Applied at every error→audit + error→caller path.
    """
    if text is None:
        return ""
    s = _TOKEN_URL_RE.sub("https://x-access-token:REDACTED@", str(text))
    s = _BEARER_RE.sub("Bearer REDACTED", s)
    return s


# --------------------------------------------------------------------------
# Path validation
# --------------------------------------------------------------------------


def validate_path(path: str, mode: str) -> tuple[str, bool]:
    """Return (path_class, overwrite_allowed). Raises VaultWriteError on rejection.

    Order:
      1. Reject empty / non-string.
      2. Reject path-traversal vectors (absolute, backslash, ..).
      3. proposed-gold.md whitelist short-circuit (so the gold blocker doesn't
         catch it).
      4. Hard-block patterns.
      5. Allow patterns + mode check.
      6. Otherwise: not in whitelist → reject.
    """
    if not isinstance(path, str) or not path:
        raise VaultWriteError("path must be a non-empty string")
    if path.startswith("/") or "\\" in path or ".." in path:
        raise VaultWriteError(f"path must be relative without traversal: {path!r}")

    # proposed-gold.md is explicitly allowed; bypass the generic gold blocker.
    proposed_gold_match = _PROPOSED_GOLD_RE.match(path)

    if not proposed_gold_match:
        for blocked in _BLOCKED_PATTERNS:
            if re.match(blocked, path):
                raise VaultWriteError(f"path is hard-blocked: {path}")

    for pattern, klass, overwrite_ok in _ALLOWED_PATTERNS:
        if re.match(pattern, path):
            if mode == "overwrite" and not overwrite_ok:
                raise VaultWriteError(
                    f"path '{path}' (class={klass}) is append-only; "
                    "overwrite mode rejected"
                )
            return klass, overwrite_ok

    raise VaultWriteError(
        f"path '{path}' does not match any allowed pattern. "
        "See vault_write._ALLOWED_PATTERNS."
    )


# --------------------------------------------------------------------------
# Frontmatter validation
# --------------------------------------------------------------------------

_FRONTMATTER_REQUIRED_KLASSES = frozenset({"curated", "proposed_gold"})
_FRONTMATTER_REQUIRED_KEYS = frozenset({"source", "confidence", "provenance"})


def validate_frontmatter(content: str, klass: str) -> None:
    """For curated/ and proposed-gold writes: require frontmatter keys with non-empty values.

    Frontmatter format: leading `---\\n...\\n---\\n` block of YAML-style
    `key: value` lines. We DO NOT parse YAML strictly — substring-check at
    line-start and require non-whitespace after the colon.

    v2 fixes:
      - re.escape(key) defense for future metachar keys
      - require at least one non-whitespace character after the colon
        (v1 passed `source: ` empty value)
    """
    if klass not in _FRONTMATTER_REQUIRED_KLASSES:
        return
    if not content.startswith("---\n"):
        raise VaultWriteError(
            f"path class '{klass}' requires YAML frontmatter starting with '---'"
        )
    end = content.find("\n---\n", 4)
    if end == -1:
        raise VaultWriteError(
            f"path class '{klass}' frontmatter missing closing '---'"
        )
    frontmatter = content[4:end]
    missing: list[str] = []
    empty: list[str] = []
    for required_key in sorted(_FRONTMATTER_REQUIRED_KEYS):
        key_re = re.escape(required_key)
        if not re.search(rf"^{key_re}[ \t]*:", frontmatter, re.MULTILINE):
            missing.append(required_key)
        # `[ \t]*\S` — horizontal whitespace only, then non-whitespace, on the
        # SAME line as the key. `\s*` would eat the newline and falsely match
        # the next key's value.
        elif not re.search(rf"^{key_re}[ \t]*:[ \t]*\S", frontmatter, re.MULTILINE):
            empty.append(required_key)
    if missing:
        raise VaultWriteError(
            f"path class '{klass}' frontmatter missing required keys: {missing}. "
            f"Required: {sorted(_FRONTMATTER_REQUIRED_KEYS)}"
        )
    if empty:
        raise VaultWriteError(
            f"path class '{klass}' frontmatter keys present but empty: {empty}. "
            "Each required key must have a non-empty value."
        )


# --------------------------------------------------------------------------
# GitHub Contents API client (sync httpx — matches existing MCP dispatch
# convention; every other tool calls sync I/O from _dispatch())
# --------------------------------------------------------------------------


def _gh_get(path: str, token: str) -> Optional[dict]:
    """Fetch existing file metadata. Returns None on 404."""
    r = httpx.get(
        f"{GITHUB_API}/repos/{VAULT_REPO}/contents/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15.0,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _gh_put(
    path: str,
    content_b64: str,
    message: str,
    sha: Optional[str],
    token: str,
) -> httpx.Response:
    """Single PUT attempt. Returns the raw Response so caller can inspect 409 vs raise."""
    body: dict = {"message": message, "content": content_b64}
    if sha:
        body["sha"] = sha
    return httpx.put(
        f"{GITHUB_API}/repos/{VAULT_REPO}/contents/{path}",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=20.0,
    )


def write_vault_file(
    path: str,
    content: str,
    mode: str,
    commit_message: str,
    token: str,
) -> dict:
    """Validate + commit. Returns canonical result dict.

    Result keys:
      path, klass, mode_used, commit_sha, content_sha, html_url, bytes_written

    For 'append' mode: fetches existing file, decodes, concatenates new content
    after a separating newline if existing didn't end with one, re-encodes, PUTs
    with existing sha for conflict detection. On 409 Conflict, refresh sha and
    retry ONCE; on second 409, raise VaultWriteError.

    For 'overwrite' mode (only allowed on _session-state.md): replaces content.
    """
    klass, _ = validate_path(path, mode)
    validate_frontmatter(content, klass)

    if mode not in {"append", "overwrite"}:
        raise VaultWriteError(f"mode must be 'append' or 'overwrite', got: {mode!r}")

    def _build_payload(existing: Optional[dict]) -> tuple[str, Optional[str], str]:
        """Returns (content_b64, sha_for_request, new_content_str)."""
        if mode == "overwrite":
            new_content = content
            sha = existing.get("sha") if existing else None
        else:  # append
            if existing:
                existing_decoded = base64.b64decode(existing["content"]).decode("utf-8")
                sep = "" if existing_decoded.endswith("\n") else "\n"
                new_content = existing_decoded + sep + content
                sha = existing["sha"]
            else:
                new_content = content
                sha = None
        return (
            base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            sha,
            new_content,
        )

    # First attempt
    existing = _gh_get(path, token)
    content_b64, sha, new_content = _build_payload(existing)
    response = _gh_put(path, content_b64, commit_message, sha, token)

    # 409 retry-once with refreshed sha
    if response.status_code == 409:
        existing = _gh_get(path, token)
        content_b64, sha, new_content = _build_payload(existing)
        response = _gh_put(path, content_b64, commit_message, sha, token)
        if response.status_code == 409:
            raise VaultWriteError(
                f"persistent 409 Conflict on {path} after retry — "
                "concurrent writers detected; caller should retry from session"
            )

    response.raise_for_status()
    result = response.json()

    return {
        "path": path,
        "klass": klass,
        "mode_used": mode,
        "commit_sha": result["commit"]["sha"],
        "content_sha": result["content"]["sha"],
        "html_url": result["content"]["html_url"],
        "bytes_written": len(new_content.encode("utf-8")),
    }
