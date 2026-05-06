# BRIEF: BRISEN-LAB-V2-BRIDGE-F2 — outbound auto-post script for AI Heads

**Repo:** `vallen300-bit/baker-master` (NOT brisen-lab — pure client-side helper)
**Branch:** `b2/brisen-lab-v2-bridge-f2`
**Tier:** **B** (no daemon-side code change; no new auth surface; client-side helper script + convention update)

## Context

Director ratified 2026-05-06:
- **OPTION A** — outbound auto-post for AI Heads. Closes the Director-as-relay loop for inter-worker dispatches.
- **Policy (ii)** — 1Password-fetch sender's key on demand at every post (no env-var dependency). Mirrors the hook's PR #163 op-CLI fallback pattern. ~200ms per call acceptable for low-frequency dispatch traffic.

After F2 ships, AH1/AH2 invoke a Bash helper that POSTs directly to the bus instead of producing paste-blocks for B-code / cross-AH-Head messages. Director-facing chat **stays paste-blocks** — F2 explicitly rejects `recipient=director` to prevent silent drops into Director's bus inbox before Stage 2 autopoll lands.

Sequence (Director-locked 2026-05-06): F2 ship → Stage 2 brief (App-side autopoll) → 1-week burn-in → Stage 3 (true autonomy) re-evaluated only if Stage 2 stable.

## Estimated time: ~1.5h
## Complexity: Low
## Prerequisites:
- AUTHZ_FACTORY_1 merged ✅ (PR #5 dc13d20)
- 12 worker keys in 1Password under `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>/credential`
- 1Password CLI installed + authenticated on Director's MacBook (already in use by the receive-side hook)

---

## Goal

Replace this loop:
> AI Head produces paste-block → Director copy/pastes → recipient terminal sees prompt with embedded message

With this loop:
> AI Head invokes `~/.baker-hooks/bus-post.sh <recipient> <body> [topic]` → script fetches sender key from 1P, POSTs JSON dispatch to bus → recipient drains via existing UserPromptSubmit hook on next prompt fired by Director's one-word poke

**Director's role shifts from message-carrier to wake-poker.** Content moves through bus. Director still triggers (Stage 2 will automate even that). Stage 3 (workers self-wake) is NOT in scope.

---

## The 12-slug worker registry (verified 2026-05-06 against `auth_lab._TERMINAL_KEYS` env-loaded JSON)

```
director, cowork-ah1, lead, deputy, architect, b1, b2, b3, b4, b5, cortex, daemon
```

`director` is **explicitly rejected** by the script — Director-facing messages must stay paste-blocks until Stage 2 autopoll wires the App-side hook. All other 11 slugs are valid recipients.

---

## Implementation

### NEW: `scripts/bus_post.sh` (committed in baker-code; symlinked from `~/.baker-hooks/`)

Bash helper. POSIX-portable. shellcheck-clean.

```bash
#!/usr/bin/env bash
# bus_post.sh — AI Head outbound auto-post to Brisen Lab bus.
# Director ratified 2026-05-06 OPTION A + policy (ii): op-fetch sender key on demand.
#
# Usage:
#   bus_post.sh <recipient_slug> <body> [topic]
#
# Env:
#   BAKER_ROLE     — required. Maps to sender slug (AH1/aihead1/lead → lead;
#                    AH2/aihead2/deputy → deputy; B1-B5 → b1-b5; etc.)
#
# Exits non-zero on any failure with descriptive stderr.

set -euo pipefail

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"

# --- arg parsing ---

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ]; then
    echo "Usage: bus_post.sh <recipient_slug> <body> [topic]" >&2
    exit 2
fi

RECIPIENT="$1"
BODY="$2"
TOPIC="${3:-}"

# --- recipient validation ---

# Reject Director recipient — Director-facing → paste-block (not bus until Stage 2).
if [ "$RECIPIENT" = "director" ]; then
    echo "ERROR: director-recipient blocked." >&2
    echo "  Director-facing dispatches must stay paste-blocks until Stage 2 autopoll." >&2
    echo "  See: BRIEF_BRISEN_LAB_V2_BRIDGE_F2.md — Director ratified 2026-05-06 sequencing." >&2
    exit 1
fi

# Validate against canonical 12-slug registry.
case "$RECIPIENT" in
    cowork-ah1|lead|deputy|architect|b1|b2|b3|b4|b5|cortex|daemon) ;;
    *)
        echo "ERROR: unknown slug: $RECIPIENT" >&2
        echo "  Valid: cowork-ah1 lead deputy architect b1 b2 b3 b4 b5 cortex daemon" >&2
        exit 1
        ;;
esac

# --- sender slug from BAKER_ROLE ---

case "${BAKER_ROLE:-}" in
    AH1|aihead1|lead|LEAD)        SENDER=lead ;;
    AH2|aihead2|deputy|DEPUTY)    SENDER=deputy ;;
    B1|b1)                         SENDER=b1 ;;
    B2|b2)                         SENDER=b2 ;;
    B3|b3)                         SENDER=b3 ;;
    B4|b4)                         SENDER=b4 ;;
    B5|b5)                         SENDER=b5 ;;
    architect|ARCHITECT)          SENDER=architect ;;
    cortex|CORTEX)                 SENDER=cortex ;;
    *)
        echo "ERROR: BAKER_ROLE not set or unrecognized: '${BAKER_ROLE:-}'" >&2
        echo "  Valid: AH1, AH2, B1-B5, architect, cortex" >&2
        exit 1
        ;;
esac

# --- 1Password fetch (policy ii) ---

KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SENDER}/credential" 2>/dev/null)" || {
    echo "ERROR: 1Password CLI fetch failed for sender=${SENDER}" >&2
    echo "  Check: op CLI authenticated (op whoami) + key exists at op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SENDER}/credential" >&2
    exit 1
}

if [ -z "$KEY" ]; then
    echo "ERROR: 1Password returned empty key for sender=${SENDER}" >&2
    exit 1
fi

# --- payload construction (Python json.dumps for safe escaping) ---

PAYLOAD="$(python3 -c '
import json, sys
recipient, body, topic = sys.argv[1], sys.argv[2], sys.argv[3]
out = {"kind": "dispatch", "body": body, "to": [recipient], "tier_required": "B"}
if topic:
    out["topic"] = topic
print(json.dumps(out))
' "$RECIPIENT" "$BODY" "$TOPIC")"

# --- POST ---

RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT

HTTP="$(curl -s -o "$RESP_FILE" -w "%{http_code}" \
    -H "X-Terminal-Key: $KEY" \
    -H "Content-Type: application/json" \
    -X POST "$DAEMON_URL/msg/${RECIPIENT}" \
    --data "$PAYLOAD")"

if [ "$HTTP" != "200" ]; then
    echo "ERROR: POST /msg/${RECIPIENT} returned HTTP $HTTP" >&2
    cat "$RESP_FILE" >&2
    echo >&2
    exit 1
fi

cat "$RESP_FILE"
echo
```

### NEW: `scripts/bus_post.py` (companion for richer payloads)

Python helper for cases where shell-quoting bash would be ugly (multiline body, JSON topic, parent_id chains, `to=[multi]` recipients).

```python
#!/usr/bin/env python3
"""bus_post.py — AI Head outbound auto-post (richer payload variant).

Usage:
    bus_post.py --to lead --body "..." [--topic ...] [--parent-id N] [--kind dispatch] [--tier B]
    bus_post.py --to lead,deputy --body "..."  # multiple recipients

Companion to scripts/bus_post.sh. Use the .sh for one-liner dispatches; the
.py when you need parent_id chains, multi-recipient broadcasts, or multiline
bodies that shell-quote awkwardly.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Optional

import urllib.request
import urllib.error

DAEMON_URL = os.environ.get("BRISEN_LAB_DAEMON_URL", "https://brisen-lab.onrender.com")
VALID_SLUGS = {
    "cowork-ah1", "lead", "deputy", "architect",
    "b1", "b2", "b3", "b4", "b5",
    "cortex", "daemon",
}
ROLE_TO_SLUG = {
    "AH1": "lead", "aihead1": "lead", "lead": "lead", "LEAD": "lead",
    "AH2": "deputy", "aihead2": "deputy", "deputy": "deputy", "DEPUTY": "deputy",
    "B1": "b1", "b1": "b1", "B2": "b2", "b2": "b2",
    "B3": "b3", "b3": "b3", "B4": "b4", "b4": "b4", "B5": "b5", "b5": "b5",
    "architect": "architect", "ARCHITECT": "architect",
    "cortex": "cortex", "CORTEX": "cortex",
}


def _resolve_sender() -> str:
    role = os.environ.get("BAKER_ROLE", "")
    if role not in ROLE_TO_SLUG:
        sys.exit(
            f"ERROR: BAKER_ROLE not set or unrecognized: {role!r}. "
            f"Valid: AH1, AH2, B1-B5, architect, cortex"
        )
    return ROLE_TO_SLUG[role]


def _fetch_key(sender: str) -> str:
    ref = f"op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_{sender}/credential"
    try:
        out = subprocess.run(
            ["op", "read", ref],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        sys.exit(f"ERROR: 1Password CLI fetch failed: {e}")
    if out.returncode != 0:
        sys.exit(f"ERROR: 1Password fetch returned non-zero for {sender}: {out.stderr.strip()}")
    key = out.stdout.strip()
    if not key:
        sys.exit(f"ERROR: 1Password returned empty key for {sender}")
    return key


def _post(recipient: str, payload: dict, key: str) -> dict:
    url = f"{DAEMON_URL}/msg/{recipient}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-Terminal-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: POST {url} returned HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: POST {url} failed: {e.reason}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", required=True, help="comma-separated recipient slug(s)")
    ap.add_argument("--body", required=True, help="message body")
    ap.add_argument("--topic", default=None)
    ap.add_argument("--parent-id", type=int, default=None)
    ap.add_argument("--thread-id", default=None)
    ap.add_argument("--kind", default="dispatch",
                    choices=["dispatch", "ack", "broadcast", "ratify_required", "ratify_decision"])
    ap.add_argument("--tier", default="B", choices=["B", "A", "director_only"])
    args = ap.parse_args()

    recipients = [r.strip() for r in args.to.split(",") if r.strip()]
    if "director" in recipients:
        sys.exit(
            "ERROR: director-recipient blocked. Director-facing → paste-block, not bus.\n"
            "  See BRIEF_BRISEN_LAB_V2_BRIDGE_F2.md."
        )
    bad = [r for r in recipients if r not in VALID_SLUGS]
    if bad:
        sys.exit(f"ERROR: unknown slug(s): {bad}. Valid: {sorted(VALID_SLUGS)}")

    sender = _resolve_sender()
    key = _fetch_key(sender)

    # POST per recipient (daemon's POST /msg/{terminal} is single-recipient-pathed
    # but accepts to=[list] in body; we POST to first recipient with full to-list).
    payload: dict = {
        "kind": args.kind,
        "body": args.body,
        "to": recipients,
        "tier_required": args.tier,
    }
    if args.topic is not None:
        payload["topic"] = args.topic
    if args.parent_id is not None:
        payload["parent_id"] = args.parent_id
    if args.thread_id is not None:
        payload["thread_id"] = args.thread_id

    result = _post(recipients[0], payload, key)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

### Permissions + symlink

```bash
chmod +x scripts/bus_post.sh scripts/bus_post.py
ln -sf "$(pwd)/scripts/bus_post.sh" ~/.baker-hooks/bus_post.sh
ln -sf "$(pwd)/scripts/bus_post.py" ~/.baker-hooks/bus_post.py
```

The `~/.baker-hooks/` symlink mirrors the existing `user-prompt-submit-confirm.py` symlink pattern (committed Block A path-stability convention).

---

## Tests

### NEW: `tests/test_bus_post.py`

Pytest. Subprocess-invokes both scripts. No network — uses `BRISEN_LAB_DAEMON_URL` override pointing at a stub HTTP server fixture.

Tests to write:

| # | Subject | Expected |
|---|---------|----------|
| 1 | bus_post.sh director "x" | exit 1, stderr "director-recipient blocked" |
| 2 | bus_post.sh nonexistent-slug "x" | exit 1, stderr "unknown slug" |
| 3 | bus_post.sh (no args) | exit 2, stderr "Usage:" |
| 4 | bus_post.sh b2 "x" with BAKER_ROLE unset | exit 1, stderr "BAKER_ROLE not set" |
| 5 | bus_post.sh b2 "x" with BAKER_ROLE=GARBAGE | exit 1, stderr "unrecognized" |
| 6 | bus_post.sh b2 "hello" with stub daemon returning 200 | exit 0, stdout = stub-returned JSON |
| 7 | bus_post.sh b2 "hello" with stub daemon returning 503 | exit 1, stderr "HTTP 503" |
| 8 | bus_post.sh b2 "hello" with stub daemon unreachable (bad URL) | exit 1, stderr error |
| 9 | bus_post.sh b2 "hello with \"quotes\" + \$vars" | payload JSON correctly escapes body |
| 10 | bus_post.sh b2 "x" topic/with/slashes | payload includes topic correctly |
| 11 | bus_post.py --to lead,deputy --body "..." | payload to=["lead","deputy"], not single |
| 12 | bus_post.py --to director --body "x" | exit, "director-recipient blocked" |
| 13 | bus_post.py --to b2 --body "x" --parent-id 42 | payload includes parent_id=42 |
| 14 | bus_post.py --to b2 --body "x" --kind broadcast --tier A | payload kind=broadcast tier=A |
| 15 | bus_post.py with BAKER_ROLE missing | sys.exit, "BAKER_ROLE not set" |

**Note for tests 6–8 (stub daemon):** use `http.server.BaseHTTPRequestHandler` in a pytest fixture; bind `BRISEN_LAB_DAEMON_URL=http://localhost:<port>` for the subprocess invocation; tests don't need real bus connectivity.

**Note for 1P fetch:** tests 6/7/8/11/13/14 mock the `op` CLI by prepending a tmp dir with a fake `op` shell script (`echo "fake-key"`) onto `PATH`. This avoids real 1P reads in CI.

### Smoke test (manual, post-merge by AH1-T)

After PR merge, AH1-T runs (in its own `bm-aihead1` shell):

```bash
BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh b2 "F2 smoke test from AH1-T at $(date -u +%FT%TZ)" "v2-bridge/f2/smoke"
```

Expected: HTTP 200 + JSON `{"message_id": N, "thread_id": "...", "posted_at": "..."}`. AH1-T then verifies via `curl -H "X-Terminal-Key: $LEAD_KEY" https://brisen-lab.onrender.com/msg/b2 | jq` that the message appears in B2's inbox.

---

## Architect-item-5 fold (CallerContext bool-predicates) — *included* per AH1-T disposition

Adds bool-predicate companions on `CallerContext` (architect Item 5 from PR #5 review, ClickUp 86c9nr9dw).

In `authz.py` (brisen-lab repo), append to `CallerContext`:

```python
def is_party_to_message(self, msg_row: dict) -> bool:
    if self.is_director:
        return True
    if self.slug == msg_row.get("from_terminal"):
        return True
    if self.slug in (msg_row.get("to_terminals") or []):
        return True
    return False

def is_recipient_of_message(self, msg_row: dict) -> bool:
    if self.is_director:
        return True
    return self.slug in (msg_row.get("to_terminals") or [])
```

These are non-raising mirrors of `require_party_to_message` / `require_recipient_of_message`. F2 doesn't directly need them (the script doesn't call the factory), but the architect flagged Item 5 as "fold to F2" per AH1-T disposition. Keep the fold light — 2 methods, ~10 lines.

**Important:** this fold is in the **brisen-lab repo** (authz.py), NOT baker-master. Means PR for F2 spans 2 repos:
1. `vallen300-bit/baker-master` — script + tests + orientation updates (primary PR)
2. `vallen300-bit/brisen-lab` — authz.py CallerContext bool-predicates (small companion PR)

**Repo branch naming:**
- baker-master: `b2/brisen-lab-v2-bridge-f2`
- brisen-lab: `b2/brisen-lab-v2-bridge-f2-authz-bools`

Reviewer chain runs separately on each PR. AH1-T merges baker-master FIRST (script can ship without the bool methods); brisen-lab follow-on can land independently. If brisen-lab PR runs into review issues, baker-master ships standalone — bool predicates can wait.

### NEW: `tests/test_authz_factory.py` extension (brisen-lab repo)

Append after the existing 22 tests:

```python
def test_caller_context_is_party_to_message_director_true():
    ctx = CallerContext(slug="director", is_director=True)
    assert ctx.is_party_to_message(
        {"from_terminal": "lead", "to_terminals": ["cowork-ah1"]}) is True


def test_caller_context_is_party_to_message_outsider_false():
    ctx = CallerContext(slug="b1", is_director=False)
    assert ctx.is_party_to_message(
        {"from_terminal": "lead", "to_terminals": ["cowork-ah1"]}) is False


def test_caller_context_is_recipient_of_message_match_true():
    ctx = CallerContext(slug="lead", is_director=False)
    assert ctx.is_recipient_of_message({"to_terminals": ["lead"]}) is True


def test_caller_context_is_recipient_of_message_outsider_false():
    ctx = CallerContext(slug="lead", is_director=False)
    assert ctx.is_recipient_of_message({"to_terminals": ["cowork-ah1"]}) is False
```

22 → 26 tests. Keep `test_authz_factory.py` count consistent.

---

## Convention update

### UPDATE: `_ops/agents/aihead1/orientation.md` + `_ops/agents/aihead2/orientation.md`

Add a section near the top:

```markdown
## Bus-direct dispatch (Director ratified 2026-05-06 OPTION A)

For inter-worker dispatches (to b1-b5, deputy/AH2, architect, cortex, cowork-ah1):
INVOKE: `~/.baker-hooks/bus_post.sh <recipient> <body> [topic]`
NOT: produce a paste-block for Director to relay.

Director-facing chat (questions, ratifications, ship-reports addressed to Director):
STAYS: paste-blocks. The script blocks recipient=director until Stage 2 autopoll.

For richer payloads (multi-recipient, parent_id chains, multiline body):
INVOKE: `~/.baker-hooks/bus_post.py --to <slug[,slug]> --body "..." [--topic ...] [--parent-id N]`

The script fetches your sender key from 1P on every call (Director ratified policy ii).
~200ms per call; acceptable for low-frequency dispatch.
```

(Identical block in both files; AH1 uses BAKER_ROLE=AH1 → sender slug "lead", AH2 uses BAKER_ROLE=AH2 → sender slug "deputy". Single source of truth in orientation; no per-AH-Head divergence.)

### UPDATE: `_ops/skills/ai-head/SKILL.md`

Add a single-line reference under the existing "PL ship-report contract" section:

```markdown
**Inter-worker dispatch:** invoke `~/.baker-hooks/bus_post.sh` (or .py for richer payloads). Director-facing chat stays paste-blocks. See `_ops/agents/aihead*/orientation.md` for full convention.
```

---

## Acceptance criteria

| AC | Test | Status |
|----|------|--------|
| A1 | shellcheck `scripts/bus_post.sh` — clean | ☐ |
| A2 | `python3 -c "import py_compile; py_compile.compile('scripts/bus_post.py', doraise=True)"` | ☐ |
| A3 | `pytest tests/test_bus_post.py -v` — 15 tests PASS | ☐ |
| A4 | Symlinks `~/.baker-hooks/bus_post.sh` + `~/.baker-hooks/bus_post.py` exist + `chmod +x` | ☐ |
| A5 | Manual smoke test (post-merge by AH1-T): `BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh b2 "F2 smoke" "v2-bridge/f2/smoke"` returns HTTP 200 + valid JSON | ☐ |
| A6 | director-recipient block verified — `bus_post.sh director "x"` exits 1 with explicit stderr | ☐ |
| A7 | Orientation files updated for AH1 + AH2 (identical block) + ai-head SKILL.md reference | ☐ |
| A8 | (brisen-lab repo, separate PR) authz.py CallerContext bool-predicates added; 4 new tests PASS; ClickUp 86c9nr9dw closed | ☐ |
| A9 | brisen-lab full pytest still PASSES (no regression in existing 22 factory tests + 9 inbox tests) | ☐ |

---

## 5-gate review chain — MANDATORY (per Director directive 2026-05-06)

Run all reviewers in **parallel** in a single message:

1. **AH2 static review** — `feature-dev:code-reviewer` agent — full diff (both repos)
2. **AH2 `/security-review`** — focus: 1P fetch, key handling, recipient validation, daemon URL injection, payload-construction injection
3. **picker-architect review** — design fit (script-vs-tool tradeoff, env-var policy, brisen-lab fold-in scoping)
4. **feature-dev:code-reviewer 2nd-pass** — after any review-driven changes
5. **AH1-T merges** — squash + delete branch + PL ship-report

Tag PR with `tier-b-tooling`. Link the brisen-lab companion PR in the baker-master PR body.

---

## Files modified

### baker-master (primary PR)

| File | Change |
|------|--------|
| `scripts/bus_post.sh` | NEW — Bash helper |
| `scripts/bus_post.py` | NEW — Python richer-payload variant |
| `tests/test_bus_post.py` | NEW — 15 subprocess + stub-daemon tests |
| `_ops/agents/aihead1/orientation.md` | UPDATE — bus-direct convention block |
| `_ops/agents/aihead2/orientation.md` | UPDATE — same block |
| `_ops/skills/ai-head/SKILL.md` | UPDATE — single-line reference |

### brisen-lab (companion PR — optional, can ship later)

| File | Change |
|------|--------|
| `authz.py` | EXTEND — `is_party_to_message()` + `is_recipient_of_message()` bool-predicates on CallerContext |
| `tests/test_authz_factory.py` | EXTEND — 4 new tests (22 → 26) |

## Do NOT touch

- `brisen-lab/bus.py` — daemon endpoints unchanged. The script is a pure client.
- `.claude/hooks/user-prompt-submit-confirm.py` — receive-side hook is a separate lane.
- Director-facing paste-block patterns — those STAY until Stage 2 autopoll lands.
- `~/.zshrc` launchers — they currently set `BRISEN_LAB_TERMINAL_KEY` env. F2 deliberately does NOT use that env var (Director ratified ii). Migrating launchers OUT of env-var-set is OUT OF SCOPE — separate hygiene brief later if Director wants full env-var purge.

## Quality checkpoints

1. After code edits, `shellcheck scripts/bus_post.sh` clean
2. `python3 -c "import py_compile; py_compile.compile('scripts/bus_post.py', doraise=True)"` clean
3. `pytest tests/test_bus_post.py -v` GREEN (15/15)
4. Symlinks installed: `ls -la ~/.baker-hooks/bus_post.*` shows both
5. Manual smoke test post-merge — see A5
6. brisen-lab companion PR (if shipped same session): full pytest GREEN

## Lessons applied

- **Function-signature verification**: every code snippet read from actual `auth_lab.py` / `bus.py` / existing hooks before writing
- **In-place brief amendments**: any review fixes fold IN-PLACE at original sections, not append-only
- **Tier discipline**: Tier B because no daemon code change + no new auth surface (the script just CALLS existing auth-gated endpoints with valid keys); /security-review still runs because of 1P key handling sensitivity
- **Director-recipient block** prevents silent drops into Director's bus inbox before Stage 2 autopoll wires the App-side hook (Lesson #PROTECT-DIRECTOR-LANE)
- **Pin-not-vacuous tests**: AC A6 verifies the director-block is enforced — would fail if someone accidentally removed the case statement
- **Two-repo split**: baker-master script ships independently of the brisen-lab bool-predicate fold; companion PR not blocking

---

**Branch (primary):** `b2/brisen-lab-v2-bridge-f2` in `vallen300-bit/baker-master`
**Branch (companion):** `b2/brisen-lab-v2-bridge-f2-authz-bools` in `vallen300-bit/brisen-lab` (optional, can lag)
**Mailbox:** `briefs/_tasks/CODE_2_PENDING.md`
**Closes:** ClickUp 86c9nr9dw (architect Item 5 fold) on companion PR merge.
**Customer:** Stage 2 brief (App-side autopoll) — will leverage the same op-fetch + 12-slug-registry conventions.
