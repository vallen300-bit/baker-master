#!/usr/bin/env python3
"""UserPromptSubmit hook — Brisen Lab V2 H7 auth chain (V0.3.7) + drain wiring.

BRIEF: ``briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md`` V0.3.7 amendment + Surface 5.

LIFECYCLE (V0.3.7 — Director-ratified Option D):
    1. Read JSON envelope from stdin (Claude Code passes prompt + session metadata)
    2. Compute prompt_hash = sha256(prompt_text)
    3. Generate ed25519 keypair (cryptography lib) — process memory only
    4. POST /auth/register-session-pubkey → daemon issues fresh server-side session_id
    5. Sign {worker_slug, session_id, prompt_hash, ts, nonce} (sign-FIRST then post —
       mirrors brisen-lab side HIGH fix; never burn local nonce before daemon confirms)
    6. POST /auth/human-confirmation → JWT
    7. Emit JWT via additionalContext for downstream MCP tool consumption
    8. Drain inbox (Surface 5): GET /msg/<terminal>?since=last_seen → ack each via
       POST /msg/<id>/ack (NM3 — sole authoritative ack path)
    9. Process exits; private key gone with it (forward secrecy scoped per-prompt)

CONTRACT (NON-NEGOTIABLE):
    - Exit 0 on EVERY error path. Hook bug = terminal-startup hazard (PR #149 discipline).
    - Drain stdin always (Claude Code SIGPIPE-safe).
    - Never log private key, JWT body, terminal-key, or signed payload.
    - Skip auth chain when BRISEN_LAB_V2_ENABLED!=true OR worker has no ratify authority.

Exit codes:
    Always 0. Hook never blocks Claude startup.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import sys
import time
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Constants — auth chain bound to roles with ratify_authority_level >= 1
# ---------------------------------------------------------------------------

# Per brief §9 Q1 ratification table: only these roles may post ratify_decision.
# Other workers (b1-b5, cortex) skip the auth chain (no JWT issued — process exits
# after drain side only). Defends N+1 unnecessary register-session-pubkey calls.
_AUTH_BEARING_ROLES = frozenset({
    "director", "cowork-ah1", "lead", "deputy", "architect",
    "ah1", "ah2",  # tolerate raw role tags from BAKER_ROLE
})

# Tunables — daemon tolerance window per brief §6 H7 §1.4
_REGISTER_TIMEOUT_S = 5.0
_HUMAN_CONFIRM_TIMEOUT_S = 5.0
_DRAIN_TIMEOUT_S = 8.0
# BUS_READ_UNACKED_SCAN_FIX_1: wide pull window for the full-unacked scan. `since`
# as the daemon selection filter silently dropped boundary/unacked messages; the
# drain now pulls this many rows and selects acknowledged_at==null client-side.
_DRAIN_SCAN_LIMIT = 2000

# Surface 6a (V0.2): retry register-session-pubkey once on 409 race-loss.
# The partial UNIQUE index on brisen_lab_session_keys rejects the second
# concurrent INSERT for one worker_slug; retrying once with jitter lets the
# loser re-register cleanly (the winner's row is now active so the loser's
# UPDATE step expires it before INSERT). Max-retry = 1: two collisions in a
# row = systemic contention; further retries don't materially help.
_REGISTER_MAX_RETRIES = 1
_REGISTER_RETRY_JITTER_LO_S = 0.05  # seconds (50 ms)
_REGISTER_RETRY_JITTER_HI_S = 0.15  # seconds (150 ms)

# Stage 2 — App-side autopoll (BRISEN_LAB_APP_AUTOPOLL_INBOX_1).
# Roles whose Cowork sessions are Director-facing (AH1-App as Director's
# secretary). When BAKER_ROLE matches AND BRISEN_LAB_APP_AUTOPOLL_ENABLED=true,
# the hook drains /msg/director in addition to /msg/{role}.
_DIRECTOR_FACING_ROLES = frozenset({
    "cowork-ah1", "lead", "ah1", "aihead1",
})

# Director's terminal-key 1P reference (mirrors F2 sender-key fetch pattern).
_DIRECTOR_KEY_OP_REF = "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_director/credential"

# Director-inbox body cap (Q4(b) ratified): 8K matches daemon body_preview cap.
# Higher than the existing 140-char self-inbox cap (Q4 rationale: Director
# message density warrants full body; aesthetics secondary).
_DIRECTOR_BODY_FULL_CAP = 8000

# Per-inbox last-seen markers — distinct files so /msg/lead and /msg/director
# advance independently. Resetting one does not over-read the other.
_DIRECTOR_LAST_SEEN_FILENAME = "baker-brisen-lab-lastseen-director-via-{role}.txt"


# ---------------------------------------------------------------------------
# Stdin drain (NEVER raise — SIGPIPE-safe)
# ---------------------------------------------------------------------------

def _drain_stdin() -> dict | None:
    """Read+parse Claude's JSON envelope from stdin. Return None if empty/invalid.

    Claude passes UserPromptSubmit hook a JSON envelope containing at least the
    submitted prompt text. Schema is opaque to this hook; we only need `prompt`.
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Hook output (JSON envelope expected by Claude Code)
# ---------------------------------------------------------------------------

def _emit_context(text: str | None) -> None:
    """Print Claude Code's hookSpecificOutput envelope. Never raises."""
    try:
        if not text:
            return
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": text,
            },
        }))
        sys.stdout.write("\n")
    except Exception:
        pass


def _exit_clean(text: str | None = None) -> None:
    """Single exit path. ALWAYS code 0."""
    _emit_context(text)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _v2_enabled() -> bool:
    """Honor pre-flag-flip safety: skip everything when V2 is disabled.

    Defaults to FALSE (cutover-safe). Daemon-side BRISEN_LAB_V2_ENABLED is the
    authoritative flag; this hook also reads a local mirror so terminal startup
    never depends on a network call to determine state.
    """
    raw = os.environ.get("BRISEN_LAB_V2_ENABLED", "").strip().lower()
    return raw in ("true", "1", "yes", "on")


def _worker_slug() -> str:
    """Caller's terminal slug (lower-cased). Defaults to 'cowork'."""
    role = os.environ.get("BAKER_ROLE", "").strip().lower()
    return role or "cowork"


def _is_literal_terminal_key(val: str | None) -> bool:
    return bool(val) and not val.startswith("op://")


def _terminal_key_cache_path(slug: str) -> str:
    return os.path.join(os.path.expanduser("~"), ".brisen-lab", "keys", slug)


def _read_cached_terminal_key(slug: str) -> str:
    try:
        with open(_terminal_key_cache_path(slug), "r", encoding="utf-8") as f:
            key = f.read().strip()
    except Exception:
        return ""
    return key if _is_literal_terminal_key(key) else ""


def _write_cached_terminal_key(slug: str, key: str) -> None:
    """Best-effort cache seed. Never raises and never logs key material."""
    if not _is_literal_terminal_key(key):
        return
    if not slug or "/" in slug or "\\" in slug:
        return
    try:
        cache_dir = os.path.join(os.path.expanduser("~"), ".brisen-lab", "keys")
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(os.path.dirname(cache_dir), 0o700)
            os.chmod(cache_dir, 0o700)
        except Exception:
            pass
        path = _terminal_key_cache_path(slug)
        tmp = os.path.join(cache_dir, f".{slug}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
            f.write("\n")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        try:
            if "tmp" in locals():
                os.unlink(tmp)
        except Exception:
            pass


def _op_read_terminal_key(op_ref: str, cache_slug: str) -> str:
    try:
        import subprocess
        out = subprocess.run(
            ["op", "read", op_ref],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return ""
        key = out.stdout.strip()
    except Exception:
        return ""
    if _is_literal_terminal_key(key):
        _write_cached_terminal_key(cache_slug, key)
        return key
    return ""


def _resolve_terminal_key_for_slug(slug: str, *env_values: str, fallback_op_ref: str | None = None) -> str:
    """Resolve terminal key with precedence: literal env → cache → op fallback.

    Background: Cowork-App's `settings.local.json` `env` block does NOT
    auto-resolve `op://` references — values arrive in `os.environ` as literal
    refs. Those refs now check the seeded cache before spawning 1Password CLI,
    avoiding GUI authorization prompts on hot prompt-submit paths.

    Returns empty string on any failure (cache miss, op CLI absent,
    unauthenticated, timeout) — preserves the caller's fail-open contract.
    """
    for val in env_values:
        if _is_literal_terminal_key(val):
            return val

    cached = _read_cached_terminal_key(slug)
    if cached:
        return cached

    op_refs: list[str] = []
    for val in env_values:
        if val.startswith("op://") and val not in op_refs:
            op_refs.append(val)
    if fallback_op_ref and fallback_op_ref not in op_refs:
        op_refs.append(fallback_op_ref)
    if not op_refs:
        op_refs.append(f"op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_{slug}/credential")

    for op_ref in op_refs:
        key = _op_read_terminal_key(op_ref, slug)
        if key:
            return key
    return ""


def _terminal_key() -> str:
    """Per-worker key takes precedence; fall back to unsuffixed for backward-compat.

    Wraps both env paths through `_resolve_terminal_key` so values stored as
    `op://` refs in Cowork-App's settings env block are resolved at hook-runtime
    rather than sent literally to the daemon.
    """
    slug = _worker_slug()
    slug_key = f"BRISEN_LAB_TERMINAL_KEY_{slug}"
    return _resolve_terminal_key_for_slug(
        slug,
        os.environ.get(slug_key, "").strip(),
        os.environ.get("BRISEN_LAB_TERMINAL_KEY", "").strip(),
    )


def _brisen_lab_url() -> str:
    return os.environ.get("BRISEN_LAB_URL", "https://brisen-lab.onrender.com").rstrip("/")


def _app_autopoll_enabled() -> bool:
    """Stage 2 kill-switch — BRISEN_LAB_APP_AUTOPOLL_ENABLED. Default false."""
    raw = os.environ.get("BRISEN_LAB_APP_AUTOPOLL_ENABLED", "").strip().lower()
    return raw in ("true", "1", "yes", "on")


def _is_director_facing_role() -> bool:
    """Caller's role is one of the AH1-App-equivalent slugs."""
    return _worker_slug() in _DIRECTOR_FACING_ROLES


def _director_last_seen_path() -> str:
    """Per-role marker for Director-inbox drain. Separate from self-inbox marker."""
    tmp = os.environ.get("TMPDIR", "/tmp").rstrip("/")
    return f"{tmp}/" + _DIRECTOR_LAST_SEEN_FILENAME.format(role=_worker_slug())


def _read_director_last_seen() -> str | None:
    try:
        with open(_director_last_seen_path(), "r", encoding="utf-8") as f:
            ts = f.read().strip()
        return ts or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _write_director_last_seen(ts: str) -> None:
    try:
        with open(_director_last_seen_path(), "w", encoding="utf-8") as f:
            f.write(ts)
    except Exception:
        pass


def _fetch_director_key() -> str | None:
    """Fetch Director's terminal-key. Resolves env value through
    `_resolve_terminal_key`; falls back to the canonical op-ref if env unset.

    Env path: `BRISEN_LAB_TERMINAL_KEY_director`. May be a literal key OR an
    `op://` reference (Cowork-App `settings.local.json` env block stores refs
    literally — see `_resolve_terminal_key` docstring).

    Op fallback: if env unset entirely, try `_DIRECTOR_KEY_OP_REF` directly.

    Returns None on miss — caller fail-opens silent (no Director-inbox drain
    that prompt). Hook discipline: never block startup on Director-inbox flow.
    """
    val = _resolve_terminal_key_for_slug(
        "director",
        os.environ.get("BRISEN_LAB_TERMINAL_KEY_director", "").strip(),
        fallback_op_ref=_DIRECTOR_KEY_OP_REF,
    )
    return val or None


def _last_seen_path() -> str:
    """Per-worker last-seen marker for drain `since` filter.

    Stored in $TMPDIR — a marker timestamp, not a secret. Deleting it just causes
    a one-time over-read of the inbox (idempotent via ack semantics).
    """
    tmp = os.environ.get("TMPDIR", "/tmp").rstrip("/")
    return f"{tmp}/baker-brisen-lab-lastseen-{_worker_slug()}.txt"


# ---------------------------------------------------------------------------
# Auth chain — V0.3.7 single-process keygen + register + sign + exchange
# ---------------------------------------------------------------------------

def _build_signed_payload(worker_slug: str, session_id: str, prompt: str) -> tuple[dict, str]:
    """Per brief §6 H7 §2: payload = {worker_slug, session_id, prompt_hash, ts, nonce}.

    Returns (payload_dict, canonical_json_string_for_signing).
    Canonical JSON: sorted keys, no whitespace — ensures signature reproducible
    across language clients.
    """
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    payload = {
        "worker_slug": worker_slug,
        "session_id": session_id,
        "prompt_hash": prompt_hash,
        "ts": int(time.time()),
        "nonce": str(uuid.uuid4()),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return payload, canonical


def _run_auth_chain(prompt: str) -> str | None:
    """Execute V0.3.7 auth chain. Returns JWT on success, None on any failure.

    Failure = silent (per fail-open contract). Caller's downstream MCP tool will
    surface a daemon 403 if it tries to post ratify_decision without HCT, which
    is the loud-and-recoverable path the brief specifies.
    """
    # Lazy imports — avoid import-time failure if cryptography not installed.
    try:
        import httpx  # type: ignore
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # type: ignore
        from cryptography.hazmat.primitives import serialization  # type: ignore
    except Exception:
        return None

    worker_slug = _worker_slug()
    terminal_key = _terminal_key()
    if not terminal_key:
        return None  # No key configured — fail-open silent

    # Step 1: keygen (process memory only — never written, never logged)
    try:
        privkey = Ed25519PrivateKey.generate()
        pubkey_bytes = privkey.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    except Exception:
        return None

    base = _brisen_lab_url()
    headers = {"X-Terminal-Key": terminal_key, "Content-Type": "application/json"}

    # Step 2: register-session-pubkey → daemon issues fresh session_id.
    # Encoding: brisen-lab daemon requires strict base64 (bus.py:635 — rejects
    # non-base64 with HTTP 400 pubkey_not_base64).
    # Surface 6a: retry once on 409 race-loss (concurrent register from a sibling
    # SessionStart fires within the same UPDATE+INSERT window; the partial UNIQUE
    # index rejected this caller's INSERT). Other non-200 statuses fail-open
    # immediately per V0.3.7 contract.
    register_payload = {
        "pubkey": base64.b64encode(pubkey_bytes).decode("ascii"),
        "worker_slug": worker_slug,
    }
    resp = None
    for attempt in range(_REGISTER_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_REGISTER_TIMEOUT_S) as client:
                resp = client.post(
                    f"{base}/auth/register-session-pubkey",
                    headers=headers,
                    json=register_payload,
                )
        except Exception:
            return None
        if resp.status_code == 200:
            break
        if resp.status_code == 409 and attempt < _REGISTER_MAX_RETRIES:
            # Jitter required: without it, both losers retry in lockstep and
            # collide again deterministically. 50-150ms is large enough to
            # break the tie via Python scheduler granularity.
            time.sleep(random.uniform(
                _REGISTER_RETRY_JITTER_LO_S, _REGISTER_RETRY_JITTER_HI_S
            ))
            continue
        return None
    if resp is None or resp.status_code != 200:
        return None
    try:
        session_id = resp.json().get("session_id")
    except Exception:
        return None
    if not session_id:
        return None

    # Step 3: sign FIRST (consumer-side nonce-ordering discipline mirrors brisen-lab
    # HIGH fix: never burn local nonce before daemon confirms signature)
    payload, canonical = _build_signed_payload(worker_slug, session_id, prompt)
    try:
        signature_bytes = privkey.sign(canonical.encode("utf-8"))
    except Exception:
        try:
            del privkey
        except Exception:
            pass
        return None
    # Drop privkey reference IMMEDIATELY post-sign — before the ~5s
    # human-confirmation HTTP round-trip opens. Narrows the forward-secrecy
    # window from "key alive across HTTP round-trip" to "key alive only during
    # the local sign() call." CPython refcount drops the underlying memory at
    # this point; not a guarantee vs. a determined attacker reading process
    # memory, but closes the gap between brief §6 "key dies with it" claim and
    # actual code behavior.
    try:
        del privkey
    except Exception:
        pass

    # Step 4: exchange for JWT (base64 sig per daemon contract bus.py:718)
    try:
        with httpx.Client(timeout=_HUMAN_CONFIRM_TIMEOUT_S) as client:
            resp = client.post(
                f"{base}/auth/human-confirmation",
                headers=headers,
                json={
                    "session_id": session_id,
                    "payload": payload,
                    "signature": base64.b64encode(signature_bytes).decode("ascii"),
                },
            )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json().get("token")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Drain wiring (Surface 5)
# ---------------------------------------------------------------------------

def _read_last_seen() -> str | None:
    try:
        with open(_last_seen_path(), "r", encoding="utf-8") as f:
            ts = f.read().strip()
        return ts or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _write_last_seen(ts: str) -> None:
    try:
        with open(_last_seen_path(), "w", encoding="utf-8") as f:
            f.write(ts)
    except Exception:
        pass


def _drain_inbox() -> str | None:
    """Drain new inbox messages for this worker. Returns formatted summary or None."""
    try:
        import httpx  # type: ignore
    except Exception:
        return None

    terminal_key = _terminal_key()
    if not terminal_key:
        return None

    worker = _worker_slug()
    # last_seen is a DISPLAY hint only (BUS_READ_UNACKED_SCAN_FIX_1) — NEVER the
    # daemon selection filter. Full-unacked scan: wide window + client-side
    # acknowledged_at==null filter, so boundary/out-of-order unacked never drop.
    last_seen = _read_last_seen()
    params: dict[str, Any] = {"limit": _DRAIN_SCAN_LIMIT}

    base = _brisen_lab_url()
    headers = {"X-Terminal-Key": terminal_key}

    try:
        with httpx.Client(timeout=_DRAIN_TIMEOUT_S) as client:
            resp = client.get(f"{base}/msg/{worker}", params=params, headers=headers)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except Exception:
        return None

    rows = payload if isinstance(payload, list) else (payload.get("messages") or payload.get("rows") or [])
    if not rows:
        return None

    # Select UNACKED only (acknowledged_at==null); then split off wildcard
    # broadcasts (to_terminals==['*']) which 403 on per-terminal ack and would
    # permanently inflate the count (#7011) — surfaced separately, never acked.
    unacked = [r for r in rows if isinstance(r, dict) and not r.get("acknowledged_at")]
    ackable = [r for r in unacked if r.get("to_terminals") != ["*"]]
    residue = [r for r in unacked if r.get("to_terminals") == ["*"]]
    if not ackable and not residue:
        return None

    # Ack each ackable (NM3: sole authoritative path). Per-msg failure isolated.
    newest_ts: str | None = last_seen
    summary_lines: list[str] = []
    try:
        with httpx.Client(timeout=_DRAIN_TIMEOUT_S) as client:
            for row in ackable:
                mid = row.get("id")
                if mid is None:
                    continue
                try:
                    client.post(f"{base}/msg/{mid}/ack", headers=headers)
                except Exception:
                    continue  # per-msg failure does not abort drain
                # Advance the display-hint marker to the newest acked created_at.
                created = row.get("created_at")
                if created and (newest_ts is None or str(created) > str(newest_ts)):
                    newest_ts = str(created)
                # Compose summary line — preview only (daemon caps at 8K); never
                # the raw body (brief §6 forbids raw body for ratify_required).
                # The message id is always listed so no unacked row is elided.
                kind = row.get("kind", "?")
                topic = row.get("topic") or ""
                from_t = row.get("from_terminal", "?")
                preview = row.get("body_preview")
                if not isinstance(preview, str) or not preview:
                    preview = "(preview unavailable)"
                elif len(preview) > 140:
                    preview = preview[:137] + "..."
                summary_lines.append(f"  #{mid} [{kind}] {from_t} → {topic}: {preview}")
    except Exception:
        pass

    if newest_ts:
        _write_last_seen(newest_ts)

    if not summary_lines and not residue:
        return None
    out = "📨 Brisen Lab inbox drained (full-unacked scan):"
    if summary_lines:
        out += "\n" + "\n".join(summary_lines)
    if residue:
        rids = ", ".join(f"#{r.get('id')}" for r in residue)
        out += ("\n  ⚠ broadcast residue (wildcard to=['*'], not seat-ackable): "
                f"{len(residue)} — {rids}")
    return out


def _drain_director_inbox() -> str | None:
    """Stage 2 — drain /msg/director using Director's terminal-key.

    Q3(b): AH1-App as Director's secretary; one window surfaces both inboxes.
    Q4(b): full body (up to 8K) via /event/{id}/full — bypasses 140-char preview cap.
    Q5(a): ratify_required pinned at top of returned summary.

    Acks each consumed message (NM3 — sole authoritative path). Tracks newest
    created_at in a SEPARATE marker file so /msg/lead drain (existing) and
    /msg/director drain advance independently.

    Returns formatted summary or None. Fail-open silent on any error.
    """
    if not _app_autopoll_enabled():
        return None
    if not _is_director_facing_role():
        return None
    director_key = _fetch_director_key()
    if not director_key:
        return None
    try:
        import httpx  # type: ignore
    except Exception:
        return None

    # Full-unacked scan (BUS_READ_UNACKED_SCAN_FIX_1) — since is a display hint
    # only, never the daemon selection filter.
    last_seen = _read_director_last_seen()
    params: dict[str, Any] = {"limit": _DRAIN_SCAN_LIMIT}

    base = _brisen_lab_url()
    headers = {"X-Terminal-Key": director_key}

    try:
        with httpx.Client(timeout=_DRAIN_TIMEOUT_S) as client:
            resp = client.get(f"{base}/msg/director", params=params, headers=headers)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except Exception:
        return None
    rows = payload if isinstance(payload, list) else (
        payload.get("messages") or payload.get("rows") or []
    )
    if not rows:
        return None

    # Full-unacked scan: select acknowledged_at==null; drop wildcard broadcasts
    # (to_terminals==['*']) that 403 on per-terminal ack (#7011).
    ackable = [
        r for r in rows
        if isinstance(r, dict) and not r.get("acknowledged_at")
        and r.get("to_terminals") != ["*"]
    ]
    if not ackable:
        return None

    pinned_lines: list[str] = []
    chronological_lines: list[str] = []
    newest_ts: str | None = last_seen

    try:
        with httpx.Client(timeout=_DRAIN_TIMEOUT_S) as client:
            for row in ackable:
                mid = row.get("id")
                if mid is None:
                    continue

                full_body = None
                try:
                    fr = client.get(f"{base}/event/{mid}/full", headers=headers)
                    if fr.status_code == 200:
                        full_body = fr.json().get("body")
                except Exception:
                    pass

                # Compose + surface BEFORE ack so a transient ack failure does
                # not silently drop a message we already paid the network cost
                # to fetch. NM3 idempotent ack means re-delivery on ack-fail is
                # safe; not advancing newest_ts on ack-fail makes that explicit.
                body = full_body
                if not isinstance(body, str) or not body:
                    body = row.get("body_preview")
                if not isinstance(body, str) or not body:
                    body = "(body unavailable)"
                if len(body) > _DIRECTOR_BODY_FULL_CAP:
                    body = body[:_DIRECTOR_BODY_FULL_CAP - 3] + "..."

                kind = row.get("kind", "?")
                topic = row.get("topic") or ""
                from_t = row.get("from_terminal", "?")
                line = f"  [{kind}] {from_t} → {topic}\n    {body}"

                if kind == "ratify_required":
                    pinned_lines.append(line)
                else:
                    chronological_lines.append(line)

                ack_ok = False
                try:
                    ar = client.post(f"{base}/msg/{mid}/ack", headers=headers)
                    ack_ok = ar.status_code == 200
                except Exception:
                    ack_ok = False

                if ack_ok:
                    created = row.get("created_at")
                    if created and (newest_ts is None or str(created) > str(newest_ts)):
                        newest_ts = str(created)
    except Exception:
        pass

    if newest_ts:
        _write_director_last_seen(newest_ts)

    if not pinned_lines and not chronological_lines:
        return None

    sections: list[str] = []
    if pinned_lines:
        sections.append(
            "🔔 Director-Q (ratify_required) — pending decisions:\n"
            + "\n".join(pinned_lines)
        )
    if chronological_lines:
        sections.append(
            "📨 Director inbox (chronological):\n"
            + "\n".join(chronological_lines)
        )
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _extract_prompt(envelope: dict | None) -> str:
    """Best-effort prompt extraction from Claude's UserPromptSubmit envelope."""
    if not envelope:
        return ""
    for key in ("prompt", "user_prompt", "submitted_prompt", "text"):
        val = envelope.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def main() -> None:
    # Always drain stdin first; never SIGPIPE.
    envelope = _drain_stdin()

    # Pre-flag-flip safety: V2 disabled → no-op silent exit.
    if not _v2_enabled():
        _exit_clean(None)
        return

    prompt = _extract_prompt(envelope)
    worker = _worker_slug()
    parts: list[str] = []

    # Auth chain: only for ratify-authority-bearing roles + only if prompt non-empty.
    if prompt and worker in _AUTH_BEARING_ROLES:
        jwt = _run_auth_chain(prompt)
        if jwt:
            # Emit a marker for the LLM to thread into baker_inbox_post(kind=ratify_decision)
            # if the prompt's tool-chain triggers a ratify_decision. JWT is single-use +
            # 60s TTL — leakage to LLM context is bounded.
            parts.append(
                f"[brisen-lab v2 auth] human_confirmation_token issued for this prompt: "
                f"{jwt}\n  Pass to baker_inbox_post(human_confirmation_token=...) for ratify_decision."
            )

    # Drain side (all roles): pull new inbox + ack consumed.
    drain = _drain_inbox()
    if drain:
        parts.append(drain)

    # Stage 2 — Director-inbox drain (AH1-App as Director's secretary).
    # Gated by BRISEN_LAB_APP_AUTOPOLL_ENABLED + _DIRECTOR_FACING_ROLES.
    director_drain = _drain_director_inbox()
    if director_drain:
        parts.append(director_drain)

    _exit_clean("\n\n".join(parts) if parts else None)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Last-resort guard: ANY uncaught exception → silent exit 0.
        # Hook bug must NEVER block terminal startup (PR #149 discipline).
        sys.exit(0)
