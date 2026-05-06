# BRIEF: BRISEN-LAB-APP-AUTOPOLL-INBOX-1 — App-side autopoll + daemon-layer Director-block (F2-FU-1 bundle)

**Repos:** `vallen300-bit/baker-master` (primary) + `vallen300-bit/brisen-lab` (companion)
**Branches:**
- baker-master: `b<N>/brisen-lab-app-autopoll-inbox-1`
- brisen-lab: `b<N>/brisen-lab-app-autopoll-inbox-1-daemon-block`

**Tier:** **A** — daemon authz surface change (new env-gated reject on POST /msg) + receive-side hook extension touching Director's inbox.

## Context

Director ratified 2026-05-06 sequencing: F2 ship ✅ → **Stage 2 (this brief)** → 1-week burn-in → Stage 3 NOT authorized.

This brief bundles two pieces:
1. **F2-FU-1 (ClickUp 86c9nugcw)** — move Director-recipient block from F2 script-layer (bypassable) to brisen-lab daemon (load-bearing). Env-flag-gated.
2. **App-side autopoll** — AH1-App's UserPromptSubmit hook drains `/msg/director` on top of `/msg/lead`. Director's Cowork session sees Director-facing bus traffic in preamble alongside AH1's own inbox.

Director Q1-Q5 ratified 2026-05-06:
- Q1 **(a)** per-prompt drain (mirrors CLI hook)
- Q2 **(b)** two flags: `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED` (daemon, default=true) + `BRISEN_LAB_APP_AUTOPOLL_ENABLED` (hook, default=false)
- Q3 **(b)** reuse bm-aihead1 picker — hook drains BOTH /msg/lead AND /msg/director
- Q4 **(b)** full body (up to 8K daemon ceiling) for Director-inbox messages — bypass 140-char preview cap
- Q5 **(a)** pin `ratify_required` at top of preamble, others chronological below

## Estimated time: ~2.5h
## Complexity: Medium
## Prerequisites:
- F2 merged ✅ (baker-master 2e8d3b07, brisen-lab fb3061af)
- AUTHZ_FACTORY_1 merged ✅ (PR #5 dc13d20)
- Director's terminal-key already in 12-slug registry: `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_director/credential`

---

## Goal

Replace the Director ↔ AH1 paste-block loop with bus traffic:

**Before (current):**
- AI Heads → Director: paste-block in chat
- Director → AI Heads: paste-block in chat

**After (Stage 2 enabled):**
- AI Heads → Director: `bus_post.sh director "..."` → daemon accepts (block lifted) → row in /msg/director → AH1-App hook drains on next prompt → Director sees in preamble
- Director → AI Heads: still typed prompt to AH1-App (unchanged — Director triggers; Stage 2 does NOT automate Director's outbound)

**Director's role shifts from copy-paste-carrier to wake-poker.** Stage 3 (workers self-wake) remains UNAUTHORIZED.

---

## Implementation

### Part 1 — brisen-lab daemon-layer Director-recipient block (companion PR)

#### `bus.py` — extend POST /msg/{terminal} handler

Add an env-gated check inside `_post_msg_inner` BEFORE the INSERT. Place after `to_terminals` validation (currently bus.py:189-190), before tier classification:

```python
# F2-FU-1: daemon-layer Director-recipient block.
# Default = blocked. Flip BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=false on Render
# to allow Director-recipient bus traffic (Stage 2 autopoll lane).
# Defense-in-depth: even if the F2 client-side script is bypassed (curl direct),
# daemon enforces the gate.
if "director" in to_terminals:
    blocked_env = os.environ.get(
        "BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "true"
    ).strip().lower()
    if blocked_env not in ("false", "0", "no", "off"):
        raise HTTPException(
            status_code=403,
            detail="director_recipient_blocked",
        )
```

**Add `import os` to bus.py imports** (currently absent — verified at bus.py:24-43).

**Why default=true:** the env flag must be EXPLICITLY flipped on Render to enable Director-recipient. Default-blocked closes the silent-drop hazard during the burn-in window between brief merge and Director's first flip.

**Why "default true" via string parse vs missing-env:** `os.environ.get(KEY, "true")` returns "true" when the env var isn't set, matching the safe default. Treating any value other than {false, 0, no, off} as blocked also defends against typos — `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=False` (Python-style) still blocks until lowercased to "false".

#### NEW: `tests/test_director_recipient_block.py`

8 tests, mirroring the 9-test inbox authz pattern in `tests/test_inbox_read_authz.py`. Use `monkeypatch.setenv` to flip the flag per test.

```python
"""F2-FU-1 — daemon-layer Director-recipient block on POST /msg/{terminal}.

Closes the F2 script-bypass hole: F2 bus_post.sh/py reject director-recipient
client-side, but daemon accepted to=["director"] silently. Stage 2 moves the
gate to daemon (defense-in-depth) and gates it via env flag for kill-switch
control during 1-week burn-in.

8-test list:
  1 — POST /msg/lead with to=["director"] when block=true → 403 director_recipient_blocked
  2 — POST /msg/lead with to=["director"] when block=false → 200 (unblocked path)
  3 — POST /msg/lead with to=["director","lead"] when block=true → 403 (multi-recipient any-director rejects)
  4 — POST /msg/lead with to=["lead"] when block=true → 200 (non-director regression — must still work)
  5 — POST /msg/director with to=["director"] when block=true → 403 (path-param case)
  6 — Default state (env UNSET) → blocked (safe default)
  7 — block=False (Python-style title case) → still blocked (lowercased compare)
  8 — block=0 → unblocked (numeric falsy parse)
"""
from __future__ import annotations

import pytest


def _post(client, terminal, sender_key, **kw):
    return client.post(
        f"/msg/{terminal}",
        headers={"X-Terminal-Key": sender_key},
        json=kw,
    )


def test_director_recipient_blocked_when_flag_default(client, monkeypatch):
    """1 — default behavior (env unset) blocks director recipient."""
    monkeypatch.delenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", raising=False)
    r = _post(client, "lead", "lead-key",
              kind="dispatch", body="ping director", to=["director"],
              topic="test/director-block/1")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "director_recipient_blocked"


def test_director_recipient_unblocked_when_flag_false(client, monkeypatch):
    """2 — env=false allows director recipient."""
    monkeypatch.setenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "false")
    r = _post(client, "lead", "lead-key",
              kind="dispatch", body="ping director", to=["director"],
              topic="test/director-block/2")
    assert r.status_code == 200, r.text
    assert "message_id" in r.json()


def test_director_in_multi_recipient_blocked(client, monkeypatch):
    """3 — director in to=[multi] still blocked when block=true."""
    monkeypatch.setenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "true")
    r = _post(client, "lead", "lead-key",
              kind="dispatch", body="multi", to=["director", "lead"],
              topic="test/director-block/3")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "director_recipient_blocked"


def test_non_director_recipient_unaffected(client, monkeypatch):
    """4 — to=[lead] (no director) succeeds with block=true (regression)."""
    monkeypatch.setenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "true")
    r = _post(client, "lead", "dir-key",
              kind="dispatch", body="non-director", to=["lead"],
              topic="test/director-block/4")
    assert r.status_code == 200, r.text


def test_director_path_param_blocked(client, monkeypatch):
    """5 — POST /msg/director (path) with to=[director] blocked."""
    monkeypatch.setenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "true")
    r = _post(client, "director", "dir-key",
              kind="dispatch", body="self-post", to=["director"],
              topic="test/director-block/5")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "director_recipient_blocked"


def test_default_unset_blocks(client, monkeypatch):
    """6 — env entirely unset → default blocked (cutover-safe)."""
    monkeypatch.delenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", raising=False)
    r = _post(client, "lead", "lead-key",
              kind="dispatch", body="default", to=["director"],
              topic="test/director-block/6")
    assert r.status_code == 403, r.text


def test_titlecase_false_still_blocks(client, monkeypatch):
    """7 — env="False" (Python title-case) still blocks (lowercased compare)."""
    monkeypatch.setenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "False")
    r = _post(client, "lead", "lead-key",
              kind="dispatch", body="typo", to=["director"],
              topic="test/director-block/7")
    # "False".lower() == "false" → unblocked. Verify the lower() in code path.
    # If this fails (i.e. "False" still blocks), the .lower() is missing.
    assert r.status_code == 200, (
        f"Title-case 'False' must be parsed as falsy. Body: {r.text}"
    )


def test_numeric_zero_unblocks(client, monkeypatch):
    """8 — env="0" parses as falsy → unblocked."""
    monkeypatch.setenv("BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED", "0")
    r = _post(client, "lead", "lead-key",
              kind="dispatch", body="zero", to=["director"],
              topic="test/director-block/8")
    assert r.status_code == 200, r.text
```

**Note on test fixture access to env-flag in daemon process:** the `client` fixture (pytest fastapi.testclient) runs the app in-process, so `monkeypatch.setenv` flows through to the handler's `os.environ.get`. No additional fixture needed.

---

### Part 2 — baker-master App-side autopoll hook (primary PR)

#### `.claude/hooks/user-prompt-submit-confirm.py` — extend with Director-inbox drain

Add three new helpers + integrate into `main()`. The existing `_drain_inbox()` (lines 327-405) drains `/msg/{worker_slug}` — keep unchanged. Add `_drain_director_inbox()` for the parallel Director-inbox drain.

**New constants** (after line 67):

```python
# Stage 2 — App-side autopoll (BRISEN_LAB_APP_AUTOPOLL_INBOX_1).
# Roles whose Cowork sessions are Director-facing (AH1-App as Director's
# secretary). When BAKER_ROLE matches AND BRISEN_LAB_APP_AUTOPOLL_ENABLED=true,
# the hook drains /msg/director in addition to /msg/{role}.
_DIRECTOR_FACING_ROLES = frozenset({
    "lead", "ah1", "aihead1",
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
```

**New helpers** (after `_brisen_lab_url()` at line 148):

```python
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
    """Fetch Director's terminal-key. Tries env first, then op CLI fallback.

    Env path: BRISEN_LAB_TERMINAL_KEY_director (set on AH1-App's shell).
    Op fallback: 1Password CLI (mirrors F2 bus_post.sh policy ii). Op CLI is
    optional — if not installed/authenticated, fall back to env-only.

    Returns None on miss — caller fail-opens silent (no Director-inbox drain
    that prompt). Hook discipline: never block startup on Director-inbox flow.
    """
    env_key = os.environ.get("BRISEN_LAB_TERMINAL_KEY_director", "").strip()
    if env_key:
        return env_key
    # Op CLI fallback (best-effort; may be absent/unauthenticated)
    try:
        import subprocess
        out = subprocess.run(
            ["op", "read", _DIRECTOR_KEY_OP_REF],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            key = out.stdout.strip()
            if key:
                return key
    except Exception:
        pass
    return None
```

**New `_drain_director_inbox()` function** (after existing `_drain_inbox()` at line 405):

```python
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

    last_seen = _read_director_last_seen()
    params: dict[str, Any] = {"limit": 50}
    if last_seen:
        params["since"] = last_seen

    base = _brisen_lab_url()
    headers = {"X-Terminal-Key": director_key}

    # Drain inbox listing (preview-capped 8K body_preview from daemon).
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

    # Q5(a): partition ratify_required vs others. Pin ratify_required to top.
    pinned_lines: list[str] = []
    chronological_lines: list[str] = []
    newest_ts: str | None = last_seen

    try:
        with httpx.Client(timeout=_DRAIN_TIMEOUT_S) as client:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mid = row.get("id")
                if mid is None:
                    continue

                # Q4(b): fetch full body via /event/{id}/full (preview is 8K-capped
                # but truncated for ratify_required structured payloads). Director's
                # signal-density preference > network round-trip cost.
                full_body = None
                try:
                    fr = client.get(f"{base}/event/{mid}/full", headers=headers)
                    if fr.status_code == 200:
                        full_body = fr.json().get("body")
                except Exception:
                    pass

                # Ack regardless of /event fetch outcome (NM3 idempotent).
                try:
                    client.post(f"{base}/msg/{mid}/ack", headers=headers)
                except Exception:
                    continue  # per-msg failure does not abort drain

                # Track newest created_at for next-prompt since filter
                created = row.get("created_at")
                if created and (newest_ts is None or str(created) > str(newest_ts)):
                    newest_ts = str(created)

                # Compose line. Body source priority:
                #  1. /event/{id}/full body (Q4 full-body path)
                #  2. /msg/{terminal} body_preview (fallback if /event 4xx/5xx)
                #  3. placeholder
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
```

**Integrate into `main()`** — add Director-inbox drain after the existing `_drain_inbox()` call (line 449-451). The two drains are independent; both contribute to `parts`:

```python
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
            parts.append(
                f"[brisen-lab v2 auth] human_confirmation_token issued for this prompt: "
                f"{jwt}\n  Pass to baker_inbox_post(human_confirmation_token=...) for ratify_decision."
            )

    # Self-inbox drain (existing — unchanged).
    drain = _drain_inbox()
    if drain:
        parts.append(drain)

    # Stage 2 — Director-inbox drain (AH1-App as Director's secretary).
    # Gated by BRISEN_LAB_APP_AUTOPOLL_ENABLED + _DIRECTOR_FACING_ROLES.
    director_drain = _drain_director_inbox()
    if director_drain:
        parts.append(director_drain)

    _exit_clean("\n\n".join(parts) if parts else None)
```

#### F2 script cleanup — `scripts/bus_post.sh` and `scripts/bus_post.py`

The F2 hard-reject of `recipient=director` is now superseded by daemon-layer block (defense-in-depth at daemon, not script). Keeping the script-layer reject creates two control points; flipping the daemon flag would still leave scripts blocking, defeating the kill-switch.

**Edit `scripts/bus_post.sh`** — REMOVE lines 86-91 (the director-recipient hard exit):

```bash
# REMOVE THIS BLOCK:
# if [ "$RECIPIENT" = "director" ]; then
#     echo "ERROR: director-recipient blocked." >&2
#     ...
#     exit 1
# fi
```

Update the slug allowlist to INCLUDE director:

```bash
# Validate against canonical 12-slug registry.
case "$RECIPIENT" in
    director|cowork-ah1|lead|deputy|architect|b1|b2|b3|b4|b5|cortex|daemon) ;;
    *)
        echo "ERROR: unknown slug: $RECIPIENT" >&2
        echo "  Valid: director cowork-ah1 lead deputy architect b1 b2 b3 b4 b5 cortex daemon" >&2
        exit 1
        ;;
esac
```

**Edit `scripts/bus_post.py`** — REMOVE the director-rejection at line 270-274 + add "director" to `VALID_SLUGS` (line 197-201):

```python
VALID_SLUGS = {
    "director", "cowork-ah1", "lead", "deputy", "architect",
    "b1", "b2", "b3", "b4", "b5",
    "cortex", "daemon",
}
```

Remove the `if "director" in recipients: sys.exit(...)` block.

**Result:** scripts pass director-recipient through to daemon, which enforces the gate. Single control point.

#### Update `tests/test_bus_post.py` (existing F2 tests)

The two F2 tests (1 and 12) that pin "director-recipient blocked at script" must invert — they now pass through to daemon. Tests should verify the script POSTS the request; daemon-block enforcement is covered in brisen-lab tests.

```python
# OLD: test_bus_post_sh_director_blocked → exit 1 with "blocked" stderr
# NEW: test_bus_post_sh_director_passes_through → POST hits stub daemon

def test_bus_post_sh_director_passes_through(stub_daemon, op_mock_path, tmp_path):
    """F2-FU-1: director-recipient is no longer script-blocked. Script POSTS to
    daemon; daemon enforces the env-gated block (covered in brisen-lab tests)."""
    env = {
        **os.environ,
        "PATH": f"{op_mock_path}:{os.environ['PATH']}",
        "BRISEN_LAB_DAEMON_URL": stub_daemon.url,
        "BAKER_ROLE": "AH1",
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT_SH), "director", "test body", "test/topic"],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    # Stub daemon recorded the POST — director-recipient reached the daemon
    assert any(
        req["path"] == "/msg/director"
        for req in stub_daemon.requests
    )


# Same inversion for the .py variant: test_bus_post_py_director_passes_through
```

#### NEW: `tests/test_director_inbox_drain.py`

Hook unit tests. Use stub HTTP server fixture + monkeypatch env. Mirrors F2 `test_bus_post.py` pattern.

```python
"""Stage 2 — App-side Director-inbox drain unit tests.

Tests _drain_director_inbox() in isolation. Stub daemon HTTP server returns
canned /msg/director + /event/{id}/full responses. Op CLI mocked via PATH
prepend with fake `op` shell script.

10 tests:
  1 — autopoll disabled (env=false) → no drain even if role+key set
  2 — non-director-facing role (b1) → no drain regardless of autopoll flag
  3 — Director key missing (env unset, op CLI absent) → fail-open silent
  4 — Director key via env var → drains
  5 — Director key via op CLI fallback (env unset, op present) → drains
  6 — ratify_required pinned at top of summary
  7 — full body fetched via /event/{id}/full (not preview-capped)
  8 — ack POSTed for each consumed message
  9 — last_seen marker file separate from self-inbox marker
 10 — daemon 503 on GET /msg/director → fail-open silent
"""

# Implementation: pytest fixtures for stub HTTP + tmp PATH op-mock + tmpdir
# isolation. Subprocess-invoke the hook with controlled env, then assert on
# stdout (additionalContext envelope) + stub daemon's recorded request log.
```

Test scaffolding mirrors `tests/test_bus_post.py` — same fixtures pattern.

---

## Acceptance criteria

| AC | Test | Status |
|----|------|--------|
| A1 | brisen-lab `pytest tests/test_director_recipient_block.py -v` — 8/8 PASS | ☐ |
| A2 | brisen-lab full `pytest` GREEN (no regression in 22 factory + 9 inbox + 8 new) | ☐ |
| A3 | baker-master `pytest tests/test_director_inbox_drain.py -v` — 10/10 PASS | ☐ |
| A4 | baker-master `tests/test_bus_post.py` — F2 inversion tests PASS (director passes through) | ☐ |
| A5 | shellcheck `scripts/bus_post.sh` clean (post-edit) | ☐ |
| A6 | `python3 -c "import py_compile; py_compile.compile('.claude/hooks/user-prompt-submit-confirm.py', doraise=True)"` clean | ☐ |
| A7 | `python3 -c "import py_compile; py_compile.compile('scripts/bus_post.py', doraise=True)"` clean | ☐ |
| A8 | brisen-lab `python3 -c "import py_compile; py_compile.compile('bus.py', doraise=True)"` clean | ☐ |
| A9 | Manual smoke test (post-merge by AH1-T): with both env flags ON, `BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh director "Stage 2 smoke" "stage2/smoke"` returns 200; AH1-App next prompt surfaces the message in preamble. | ☐ |
| A10 | Manual reverse smoke test (post-merge): with `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=true` (default), same `bus_post.sh director ...` returns 403 director_recipient_blocked. Pin-not-vacuous: confirms daemon block fires. | ☐ |
| A11 | Pin-not-vacuous (autopoll): with `BRISEN_LAB_APP_AUTOPOLL_ENABLED=false`, AH1-App hook does NOT call `/msg/director` (verify via curl-trace or daemon access log). | ☐ |

---

## 5-gate review chain — MANDATORY (per Director directive 2026-05-06)

Run all reviewers in **parallel** in a single message:

1. **AH2 static review** — `feature-dev:code-reviewer` agent — full diff (both repos)
2. **AH2 `/security-review`** — focus areas:
   - Director's terminal-key handling in hook (env vs 1P fetch path; key never logged)
   - daemon env-flag parsing (defaults safe; typos/title-case don't unblock)
   - hook fail-open contract preserved (no new exit-non-zero paths)
   - drain ordering (sig-then-ack mirror; ack-then-fetch acceptable for read-only inbox)
3. **picker-architect review** — design fit:
   - kill-switch flag granularity (one-vs-two ratified by Director Q2(b))
   - per-role marker file naming (collision-safe across roles + kill-switch flips)
   - body-cap policy (8K matches daemon ceiling — no surprise truncation)
   - F2 script cleanup tradeoff (single control point vs defense-in-depth)
4. **feature-dev:code-reviewer 2nd-pass** — after any review-driven changes
5. **AH1-T merges** — squash + delete branches + PL ship-report

Tag PRs with `tier-a-authz`. Cross-link companion PRs in both bodies.

---

## Files modified

### baker-master (primary PR)

| File | Change |
|------|--------|
| `.claude/hooks/user-prompt-submit-confirm.py` | EXTEND — Director-inbox drain helpers + integration in `main()` |
| `scripts/bus_post.sh` | EDIT — remove director hard-reject; add director to allowlist |
| `scripts/bus_post.py` | EDIT — remove director hard-reject; add to VALID_SLUGS |
| `tests/test_director_inbox_drain.py` | NEW — 10 hook unit tests |
| `tests/test_bus_post.py` | EDIT — invert tests 1 + 12 (director-passes-through) |

### brisen-lab (companion PR)

| File | Change |
|------|--------|
| `bus.py` | EDIT — env-gated Director-recipient block in `_post_msg_inner` |
| `tests/test_director_recipient_block.py` | NEW — 8 tests |

---

## Do NOT touch

- `authz.py` — daemon authz factory unchanged. Director-block is a recipient-list filter, not an authz policy.
- `auth_lab.py` — no key-store changes.
- Existing `_drain_inbox()` for self-inbox — Director-inbox drain is a parallel new function; do NOT merge into one.
- `BRISEN_LAB_V2_ENABLED` — orthogonal master switch; do NOT couple Stage 2 flags to it.
- AH2 / B-code orientation files — vault-side per CHANDA Inv 9. AH1-T handles separately if needed.
- Director's outbound flow (Director → AH1) — Stage 2 only automates AH1 → Director; Director's outbound stays prompt-typed (no Stage 3).

---

## Quality checkpoints

1. After code edits in each repo, run syntax checks (A6/A7/A8)
2. `shellcheck scripts/bus_post.sh` clean (A5)
3. `pytest -v` GREEN in both repos (A1-A4)
4. Hook integration smoke (local): export `BRISEN_LAB_APP_AUTOPOLL_ENABLED=true` + valid Director key in env; run hook with empty stdin; verify exit 0 + no error output
5. Daemon env-flag parse: spin up local brisen-lab with `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=false`; confirm POST /msg/director with to=[director] returns 200
6. Per-inbox marker isolation: drain /msg/lead and /msg/director in same hook run; verify two distinct files in $TMPDIR
7. Post-merge smoke (A9) + reverse smoke (A10) + pin-not-vacuous (A11)

---

## Rollback plan

**Both flags are kill-switches by design:**
- `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=true` (Render env on brisen-lab) → daemon rejects all to=[director] posts. No bus traffic reaches Director's inbox.
- `BRISEN_LAB_APP_AUTOPOLL_ENABLED=false` (AH1-App's shell env, e.g., unset in `.zshrc`) → hook does NOT drain /msg/director. Director's inbox accumulates silently (visible only via dashboard / direct curl).

**Rollback drill:**
1. Misbehavior detected (e.g., Director-Q surfacing wrong content) → flip `BRISEN_LAB_APP_AUTOPOLL_ENABLED=false` in AH1-App's shell, restart Cowork. ~30s recovery.
2. Daemon-side leak (e.g., bus.py block bypass discovered) → flip `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=true` on Render. Auto-restart on env update; ~2-3 min recovery.
3. Full revert (last resort): revert both PRs (brisen-lab + baker-master). Daemon and hook return to F2-state.

**Burn-in: 1 week. If stable, retain. If not, evaluate per Director directive — Stage 3 (worker self-wake) NOT authorized regardless.**

---

## Lessons applied

- **Two-flag kill-switch (Q2(b))**: daemon and hook concerns separated; either can flip independently.
- **Default-safe env parse**: missing env defaults to BLOCKED; typo-tolerant via .lower() check on falsy values.
- **Per-inbox marker isolation**: /msg/lead and /msg/director have distinct last-seen files. Resetting one doesn't over-read the other.
- **/event/{id}/full for body bypass**: existing daemon endpoint reused for Q4(b) full-body fetch; no daemon endpoint expansion.
- **Single control point (script cleanup)**: F2 script-layer hard-reject removed; daemon is the load-bearing gate. Drift between layers is now structurally impossible.
- **Pin-not-vacuous tests (A10/A11)**: explicit verification that flags actually gate behavior — would fail if env-parse defaulted to unblocked or if hook ignored autopoll flag.
- **Two-repo split with cross-link**: baker-master and brisen-lab PRs each link the other. Reviewer chain runs separately; AH1-T merges brisen-lab FIRST (daemon must be ready before hook tries to use Director-recipient flow).

---

## Ship sequencing

1. **Merge brisen-lab companion PR FIRST.** Daemon ships with default-blocked behavior — no behavioral change to existing F2 (which already script-rejected director-recipient).
2. **Merge baker-master primary PR.** Hook + script changes ship with autopoll flag default-OFF — no behavioral change.
3. **Director flips `BRISEN_LAB_APP_AUTOPOLL_ENABLED=true`** in AH1-App shell. Hook starts drain attempts on /msg/director; daemon responds 200 with empty list (until step 4 lands). No traffic flows.
4. **Director flips `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=false`** on Render brisen-lab. Daemon now accepts to=[director]. AH1/AH2 begin posting Director-facing via bus_post.sh. AH1-App hook drains and surfaces.
5. **1-week burn-in**. If stable, Stage 2 retained. Stage 3 (worker self-wake) explicitly out of scope.

---

**Branch (primary):** `b<N>/brisen-lab-app-autopoll-inbox-1` in `vallen300-bit/baker-master`
**Branch (companion):** `b<N>/brisen-lab-app-autopoll-inbox-1-daemon-block` in `vallen300-bit/brisen-lab`
**Mailbox:** `briefs/_tasks/CODE_<N>_PENDING.md`
**Closes:** ClickUp 86c9nugcw (F2-FU-1 daemon Director-block)
**Customer:** Director (App-side autopoll usability) + future automation work that needs Director-bound bus traffic.
