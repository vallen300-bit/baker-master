---
status: draft
drafted_at: 2026-04-27
drafted_by: AI Head A (Build-lead)
director_ratification: "yees" + "ratified all" (chat 2026-04-27)
ratification_anchors:
  - 8 open Qs all defaults locked (Q1=900s, Q2=both, Q3=multi-stage, Q4=both, Q5=60min, Q6=LWW, Q7=B2+B3 only, Q8=window-scoped)
  - paste-block elimination for overnight autonomy
spec_source: in-chat plan + ratification (no _ops/ideas/ artefact — direct AI-Head dialog)
api_version_check_date: 2026-04-27
fallback_note: autopoll is opt-in via env flag (B_CODE_AUTOPOLL_ENABLED, default false). Cold-start paste-block (Lesson #48) remains operational outside autopoll windows.
---

# BRIEF: B_CODE_AUTOPOLL_1 — Eliminate paste-block chokepoint via /loop autopoll on mailbox state machine

## Context

Lesson #48 codified that B-codes (B1–B5) do not poll — they wake on Director-relayed paste-blocks. Operationally this means mailbox writes go dormant whenever Director is offline (sleep, travel, meetings). Overnight autonomy is structurally blocked.

Director ratified 2026-04-27 ("yees" → 8 open Qs defaults locked) to introduce **autopoll mode** as a window-scoped exception: B-codes self-wake via Claude Code `/loop` + `ScheduleWakeup` during a defined overnight window (07:00 UTC stop deadline), claim mailbox dispatches via state-machine transition, ship per existing dispatch protocol, and Slack-push every state transition for morning Director review.

This brief is **process + protocol + small Python helper**. No production feature code touched.

## Estimated time: ~4–6h
## Complexity: Low–Medium
## Prerequisites: none (no upstream brief blocks this)

---

## Fix/Feature 1: Mailbox state-machine frontmatter

### Problem

`briefs/_tasks/CODE_*_PENDING.md` files today carry freeform body text. State (OPEN / claimed / completed) is conveyed in prose ("COMPLETE — PR #68 review …") with no parseable contract. Autopoll requires a machine-readable state field so B-codes can claim atomically.

### Current state

`briefs/_tasks/README.md:1-44` documents Director-paste-driven flow. No frontmatter convention. Compare current `briefs/_tasks/CODE_3_PENDING.md` (2026-04-26 BAKER_MCP_EXTENSION_1 dispatch — body-only).

### Implementation

Add YAML frontmatter to every `CODE_*_PENDING.md` going forward (existing files updated as part of this brief; new dispatches use it natively). Schema:

```yaml
---
status: OPEN | IN_PROGRESS | BLOCKED-AI-HEAD-Q | BLOCKED-DIRECTOR-Q | COMPLETE | RETIRED
brief: briefs/BRIEF_<NAME>.md          # required if status != RETIRED
trigger_class: LOW | MEDIUM | HIGH     # per b1-situational-review-trigger
dispatched_at: 2026-04-27T18:30:00Z    # ISO8601 UTC
dispatched_by: ai-head-a | ai-head-b
claimed_at: null | <ISO8601>           # set by B-code on IN_PROGRESS transition
claimed_by: null | b1 | b2 | b3 | b4 | b5
last_heartbeat: null | <ISO8601>       # B-code writes every major step (~10–15 min cadence)
blocker_question: null | <text>        # set when status = BLOCKED-*-Q
ship_report: null | briefs/_reports/B<N>_<name>_<date>.md  # set on COMPLETE
autopoll_eligible: true | false        # if false, requires paste-block (cold-start mode)
---
```

State transitions (only legal flows):

```
OPEN → IN_PROGRESS               (B-code claims)
IN_PROGRESS → BLOCKED-AI-HEAD-Q  (B-code surfaces Tier-A-scope ambiguity)
IN_PROGRESS → BLOCKED-DIRECTOR-Q (B-code surfaces true Director Q)
IN_PROGRESS → COMPLETE           (PR shipped + ship-report written)
BLOCKED-AI-HEAD-Q → IN_PROGRESS  (AI Head answered, B-code resumes)
BLOCKED-DIRECTOR-Q → IN_PROGRESS (Director answered, B-code resumes)
IN_PROGRESS → OPEN               (stale-claim recovery — AI Head loop resets > 60 min stale)
COMPLETE → RETIRED               (post-merge §3 hygiene, optional)
```

### Key constraints

- Frontmatter MUST be YAML between `---` delimiters at top of file. Body follows after second `---`.
- B-codes parse via `yaml.safe_load`, NOT eval. (Standard `pyyaml` already in requirements.)
- All transitions atomic via `git pull --rebase && write file && git add briefs/_tasks/CODE_N_PENDING.md && git commit && git push`. Last-writer-wins on conflict (Q6 ratified) — B-code retries on next wake.
- `autopoll_eligible: false` falls back to paste-block (Lesson #48 still applies for cold-start dispatches).

### Verification

- `pytest tests/test_autopoll_state.py -v` — frontmatter round-trip, illegal transition rejection, body preservation.
- Manual: add frontmatter to `CODE_3_PENDING.md` (currently active BAKER_MCP_EXTENSION_1 dispatch); verify `python3 -c "from scripts.autopoll_state import read_state; print(read_state('briefs/_tasks/CODE_3_PENDING.md'))"` returns expected dict.

---

## Fix/Feature 2: `scripts/autopoll_state.py` helper module

### Problem

Without a shared parser/writer, every B-code and AI Head re-implements YAML frontmatter handling — drift risk, no test coverage.

### Current state

No autopoll state helper exists. `briefs/_tasks/` is convention-only.

### Implementation

Create `scripts/autopoll_state.py` (~80 LOC) with these public functions:

```python
"""Autopoll state-machine helper for briefs/_tasks/CODE_N_PENDING.md.

Frontmatter contract per BRIEF_B_CODE_AUTOPOLL_1. All transitions go
through transition_state(); no direct frontmatter writes.
"""
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VALID_STATUSES = {
    "OPEN", "IN_PROGRESS",
    "BLOCKED-AI-HEAD-Q", "BLOCKED-DIRECTOR-Q",
    "COMPLETE", "RETIRED",
}

LEGAL_TRANSITIONS = {
    "OPEN":               {"IN_PROGRESS"},
    "IN_PROGRESS":        {"BLOCKED-AI-HEAD-Q", "BLOCKED-DIRECTOR-Q", "COMPLETE", "OPEN"},
    "BLOCKED-AI-HEAD-Q":  {"IN_PROGRESS"},
    "BLOCKED-DIRECTOR-Q": {"IN_PROGRESS"},
    "COMPLETE":           {"RETIRED"},
    "RETIRED":            set(),
}


def read_state(path: str | Path) -> dict:
    """Parse frontmatter dict from a CODE_N_PENDING.md file."""
    text = Path(path).read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")
    return yaml.safe_load(text[4:end]) or {}


def transition_state(path: str | Path, *, to: str, **fields) -> None:
    """Atomically transition mailbox state. Raises on illegal transition.

    Caller is responsible for git add/commit/push after.
    """
    if to not in VALID_STATUSES:
        raise ValueError(f"invalid status: {to}")
    p = Path(path)
    text = p.read_text()
    end = text.find("\n---\n", 4)
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5:]

    current = fm.get("status")
    if current and to not in LEGAL_TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal transition: {current} → {to}")

    fm["status"] = to
    fm.update(fields)

    if to == "IN_PROGRESS" and "claimed_at" not in fields:
        fm["claimed_at"] = datetime.now(timezone.utc).isoformat()

    new_text = "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + body
    p.write_text(new_text)


def heartbeat(path: str | Path) -> None:
    """B-code writes during long-running execution (~10-15 min cadence)."""
    p = Path(path)
    text = p.read_text()
    end = text.find("\n---\n", 4)
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5:]
    fm["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
    p.write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + body)


def find_stale_claims(tasks_dir: str | Path, max_age_minutes: int = 60) -> list[Path]:
    """Return CODE_N_PENDING.md paths with IN_PROGRESS but heartbeat > max_age."""
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_minutes * 60
    stale = []
    for p in Path(tasks_dir).glob("CODE_*_PENDING.md"):
        try:
            fm = read_state(p)
        except ValueError:
            continue
        if fm.get("status") != "IN_PROGRESS":
            continue
        hb = fm.get("last_heartbeat")
        if not hb:
            continue
        ts = datetime.fromisoformat(hb).timestamp()
        if ts < cutoff:
            stale.append(p)
    return stale
```

### Key constraints

- Pure-Python; no DB, no external API, no LLM call. Tested standalone.
- `transition_state` is atomic on the file write (single `write_text`); concurrency handled by git rebase-pull on caller side.
- Body preservation MUST be byte-perfect — round-trip test asserts `read → transition → read → body unchanged`.
- No mutation of frontmatter outside `transition_state` / `heartbeat` (use kwargs to update other fields).

### Verification

```bash
cd ~/bm-b<N>
pytest tests/test_autopoll_state.py -v 2>&1 | tail -30
```

≥12 tests covering: frontmatter parse, transition_state legal flow, transition_state illegal-flow rejection, body preservation, claimed_at auto-populate, heartbeat update, find_stale_claims (empty / fresh / stale fixtures), invalid YAML rejection.

---

## Fix/Feature 3: Slack push wiring on every state transition

### Problem

Director loses dispatch eyeball during overnight. Mitigation per Q4 ratification: Slack push every transition.

### Current state

`outputs/slack_notifier.post_to_channel(channel_id: str, text: str) -> bool` at `outputs/slack_notifier.py:111` is the canonical Slack pusher. Director DM is `D0AFY28N030` (referenced at `triggers/audit_sentinel.py:19`, `triggers/ai_head_audit.py:29`, `orchestrator/proactive_pm_sentinel.py:50`). Cockpit channel default `C0AF4FVN3FB` per `config/settings.py:201`.

### Implementation

Extend `scripts/autopoll_state.py` with one helper:

```python
def push_state_transition(
    code_path: str | Path,
    *,
    to: str,
    extra: Optional[str] = None,
) -> None:
    """Slack-push state transition. Best-effort — never raises.

    DM (D0AFY28N030): high-signal events (IN_PROGRESS claim, COMPLETE, BLOCKED-*).
    #baker-overnight (env BAKER_OVERNIGHT_CHANNEL_ID, default C0AF4FVN3FB): every transition.
    """
    import os
    try:
        from outputs.slack_notifier import post_to_channel
    except Exception:
        return  # baker-master not on path (B-code working dir) — OK, AI Head will catch
    fm = read_state(code_path)
    brief = fm.get("brief", "?")
    code = Path(code_path).name
    bn = fm.get("claimed_by") or "?"
    line = f"[{to}] {code} ({bn}) — {brief}"
    if extra:
        line += f" — {extra}"
    high_signal = to in {"IN_PROGRESS", "COMPLETE",
                         "BLOCKED-AI-HEAD-Q", "BLOCKED-DIRECTOR-Q"}
    overnight_channel = os.getenv("BAKER_OVERNIGHT_CHANNEL_ID", "C0AF4FVN3FB")
    post_to_channel(overnight_channel, line)
    if high_signal:
        post_to_channel("D0AFY28N030", line)
```

Caller pattern (B-code):

```python
from scripts.autopoll_state import transition_state, push_state_transition
transition_state("briefs/_tasks/CODE_3_PENDING.md", to="IN_PROGRESS", claimed_by="b3")
push_state_transition("briefs/_tasks/CODE_3_PENDING.md", to="IN_PROGRESS")
```

### Key constraints

- `post_to_channel` already non-fatal (returns False on error per `outputs/slack_notifier.py:142-144`). Wrap import in try/except for B-code dirs that don't have `outputs/` on path — silent skip is fine; AI Head's loop will catch anyway.
- DM messages MUST be ≤3000 chars (slack_notifier already truncates per `outputs/slack_notifier.py:134`).
- `BAKER_OVERNIGHT_CHANNEL_ID` env var Director sets if separate `#baker-overnight` channel created; defaults to `#cockpit` (C0AF4FVN3FB) until Director provisions a dedicated channel.
- No retries, no dedup beyond what `outputs/slack_notifier` already provides — autopoll transitions are inherently rate-limited (~32 wakes/8h × 5 B-codes max).

### Verification

- `pytest tests/test_autopoll_state.py::test_push_state_transition -v` — mock `post_to_channel`, assert called with correct channel + text shape.
- Live smoke test (separate, not in pytest): once deployed, AI Head A flips a `CODE_2_PENDING.md` test row through OPEN→IN_PROGRESS→COMPLETE manually; verify two Slack messages land in DM + cockpit.

---

## Fix/Feature 4: `_ops/processes/b-code-autopoll-protocol.md` — what each B-code does on every wake

### Problem

B-codes need a self-contained protocol they read on every `/loop` wake. They don't have session memory — each wake is a fresh prompt.

### Current state

No protocol doc. Existing `_ops/processes/b-code-dispatch-coordination.md` covers cold-start §2 busy-check (kept as-is, applies outside autopoll window).

### Implementation

Create `_ops/processes/b-code-autopoll-protocol.md` (~150 lines). Skeleton:

```markdown
# B-Code Autopoll Protocol

You are a Code Brisen (B1–B5) running in `/loop` autopoll mode in working dir
`~/bm-bN`. On every wake, execute this protocol exactly.

## Phase 1 — Wake & sync
1. `cd ~/bm-bN && git checkout main && git pull --rebase --quiet`
2. Check stop conditions:
   - `OVERNIGHT_AUTONOMY_UNTIL` env var. If now > deadline → write STOPPED log, exit loop.
   - Idle counter. If 3 consecutive wakes with no fresh dispatch → write STOPPED log, exit.

## Phase 2 — Read mailbox
3. `python3 -c "from scripts.autopoll_state import read_state; \
   print(read_state('briefs/_tasks/CODE_N_PENDING.md'))"`
4. Branch on `status`:
   - `OPEN` + `autopoll_eligible: true` + `dispatched_at` newer than last seen → claim (Phase 3)
   - `IN_PROGRESS` + `claimed_by == bN` → resume; heartbeat then continue work
   - `IN_PROGRESS` + `claimed_by != bN` → leave alone, increment idle counter, reschedule
   - `BLOCKED-AI-HEAD-Q` / `BLOCKED-DIRECTOR-Q` (mine) → check if status flipped back to IN_PROGRESS; if not, idle reschedule
   - `COMPLETE` / `RETIRED` → idle reschedule (no fresh work)

## Phase 3 — Claim
5. `git pull --rebase --quiet` (race protection)
6. `python3 -c "from scripts.autopoll_state import transition_state, push_state_transition; \
   transition_state('briefs/_tasks/CODE_N_PENDING.md', to='IN_PROGRESS', claimed_by='bN'); \
   push_state_transition('briefs/_tasks/CODE_N_PENDING.md', to='IN_PROGRESS')"`
7. `git add briefs/_tasks/CODE_N_PENDING.md && git commit -m "claim(bN): <brief-id>" && git push`
8. If push fails (someone else's commit landed) → re-pull, re-read state. If now IN_PROGRESS by another B-code → idle reschedule.

## Phase 4 — Execute
9. Read brief at `fm["brief"]`. Apply existing dispatch protocol — same as paste-block-driven workflow.
10. Heartbeat every ~10–15 min via `from scripts.autopoll_state import heartbeat; heartbeat(path)`. Keeps stale-claim recovery off your back.

## Phase 5 — Surface blockers
11. If you hit a Tier-A-scope ambiguity (existing helper to use, pattern to follow, file:line clarification): `transition_state(path, to='BLOCKED-AI-HEAD-Q', blocker_question='<text>')`. Push commit. Reschedule wake.
12. If you hit a true Director Q (cost decision, scope question, env var the brief doesn't cover): `transition_state(path, to='BLOCKED-DIRECTOR-Q', blocker_question='<text>')`. Push commit. Reschedule wake.

## Phase 6 — Ship
13. Open PR per existing dispatch protocol. Ship gate: literal pytest output (no "by inspection").
14. `transition_state(path, to='COMPLETE', ship_report='briefs/_reports/...')`. Push commit + push_state_transition. PR title and ship-report path are the headline Director sees.

## Phase 7 — Reschedule
15. `ScheduleWakeup(delaySeconds=900, reason='autopoll wake bN', prompt=...)` to re-enter on next interval. Use the same `/loop` prompt verbatim.
16. End turn.

## Hard rules
- NEVER take Tier B actions in autopoll. Surface to BLOCKED-DIRECTOR-Q.
- NEVER skip ship gate (literal pytest output). Lesson #34/#42/#44 still apply.
- NEVER skip §1 codebase grep (Lesson #47) for new sentinel/capability/pipeline briefs.
- NEVER claim a dispatch you don't have working-dir setup for (e.g., B3 doesn't claim a brief that requires `~/bm-b1` artefacts).
```

### Key constraints

- Doc lives in baker-master repo so B-codes always have it after `git pull`. NOT in baker-vault.
- Versioned via `git log _ops/processes/b-code-autopoll-protocol.md` — any change is a Tier B-grade decision (modifies B-code behavior class).

---

## Fix/Feature 5: `_ops/processes/b-code-autopoll-startup.md` — Director paste-blocks

### Problem

Director needs ONE place that lists the exact paste-block to start each B-code's autopoll loop at the start of overnight.

### Current state

No doc. Director would have to remember syntax.

### Implementation

Create `_ops/processes/b-code-autopoll-startup.md` (~50 lines). Per Q7 ratification (B2 + B3 only first overnight):

````markdown
# B-Code Autopoll — Start of Overnight Window

Paste each block into the named tab once at start of overnight. After that,
B-codes self-wake until `OVERNIGHT_AUTONOMY_UNTIL` deadline (default 07:00 UTC)
or 3 consecutive idle wakes.

## Pre-flight (do this once)
- Set `BAKER_OVERNIGHT_CHANNEL_ID=<channel_id>` env if a dedicated `#baker-overnight`
  channel was created. Otherwise default `#cockpit` (`C0AF4FVN3FB`) is used.
- **Verify `SLACK_BOT_TOKEN` is set in each B-code shell** (autopoll Slack pushes
  read it via `outputs.slack_notifier._get_webclient()`):
  `cd ~/bm-bN && python3 -c "import os; print('OK' if os.getenv('SLACK_BOT_TOKEN') else 'MISSING')"`.
  If MISSING — autopoll silently skips Slack pushes (non-fatal per
  `outputs/slack_notifier.py:142-144`) but morning-Director will lack the
  state-transition log. Source from 1Password CLI (`op read op://baker/SLACK_BOT_TOKEN`)
  or `~/.zshrc` export.
- Verify B-code worktrees clean: `cd ~/bm-bN && git status` returns clean tree.
- Confirm `_ops/processes/b-code-autopoll-protocol.md` is on `main`.

## Paste to: b2

```
You are entering autopoll mode per
_ops/processes/b-code-autopoll-protocol.md. Read that file first; it is
your protocol for every wake. Cap loop at OVERNIGHT_AUTONOMY_UNTIL=07:00 UTC
or 3 consecutive idle wakes, whichever fires first. Wake interval 900s.

cd ~/bm-b2 && git checkout main && git pull -q && \
  cat _ops/processes/b-code-autopoll-protocol.md && \
  cat briefs/_tasks/CODE_2_PENDING.md

Begin Phase 1 of the protocol.
```

## Paste to: b3

```
You are entering autopoll mode per
_ops/processes/b-code-autopoll-protocol.md. Read that file first; it is
your protocol for every wake. Cap loop at OVERNIGHT_AUTONOMY_UNTIL=07:00 UTC
or 3 consecutive idle wakes, whichever fires first. Wake interval 900s.

cd ~/bm-b3 && git checkout main && git pull -q && \
  cat _ops/processes/b-code-autopoll-protocol.md && \
  cat briefs/_tasks/CODE_3_PENDING.md

Begin Phase 1 of the protocol.
```

## Paste to: aihead1 (Build-lead's own loop — stale-claim watchdog)

```
You are AI Head A entering autopoll mode for the night. Every 600s:
1. git pull -q
2. python3 -c "from scripts.autopoll_state import find_stale_claims; \
   for p in find_stale_claims('briefs/_tasks/'): \
   print(f'STALE: {p}')"
3. For each stale claim: transition to OPEN + Slack-push to D0AFY28N030.
4. Scan for status=BLOCKED-AI-HEAD-Q in any mailbox; answer if Tier A scope,
   else escalate to BLOCKED-DIRECTOR-Q.
5. On any PR opened by B-code in autopoll: run /security-review. If clean
   AND PR has APPROVE from AI Head B → merge (Tier A standing). Slack-push.
6. ScheduleWakeup(delaySeconds=600, ...).

Stop conditions: OVERNIGHT_AUTONOMY_UNTIL=07:00 UTC OR Director paste of
"STOP AUTOPOLL".
```

## Manual stop

Paste `STOP AUTOPOLL` into any tab to exit that loop immediately.
````

### Key constraints

- Director copy-paste discipline: the snippets are byte-perfect. Any edit risks B-code interpreting wrong protocol.
- The `aihead1` loop is the watchdog — it MUST run for stale-claim recovery. Do not skip.
- AI Head B (`aihead2`) is NOT yet in autopoll for this first overnight (Q7 — B2 + B3 only). AI Head B stays in cold-start mode for now.

---

## Fix/Feature 6: Lesson #50 — Lesson #48 window-scoped exception

### Problem

Q8 ratification: Lesson #48 (paste-block always) is window-scoped, NOT replaced. Cold-start dispatches outside autopoll still need paste-block. Inside autopoll window, mailbox commit alone is the wake.

### Implementation

Append Lesson #50 to `tasks/lessons.md`:

```markdown
### 50. Autopoll mode supersedes Lesson #48 *only within defined autopoll window* (2026-04-27)

**Rule:** B-codes opted into autopoll (per `_ops/processes/b-code-autopoll-startup.md`) self-wake on mailbox commits during the window — paste-block NOT required for fresh dispatches. Outside the window, Lesson #48 fully applies (paste-block mandatory same turn as dispatch).

**Window definition:** active when (a) Director has pasted the start-protocol per startup doc, AND (b) `OVERNIGHT_AUTONOMY_UNTIL` deadline not yet passed, AND (c) B-code's loop has not exited via idle count or `STOP AUTOPOLL`.

**Frontmatter signal:** mailbox `autopoll_eligible: true` indicates AI Head expects autopoll mode pickup. `autopoll_eligible: false` (default) means cold-start paste-block still required even if window is active.

**Why both modes coexist:** highest-traffic dispatches (overnight build cycles) get autopoll; sensitive dispatches (HIGH trigger class, Director-eyeball needed, ambiguous brief) stay paste-block-driven so Director sees the dispatch live.

**Anchor:** BRIEF_B_CODE_AUTOPOLL_1 (Director ratified 2026-04-27 "ratified all" on 8 open Qs).
```

---

## Files Modified

| Path | New / Update | Why |
|---|---|---|
| `briefs/BRIEF_B_CODE_AUTOPOLL_1.md` | NEW | This brief |
| `scripts/autopoll_state.py` | NEW | State-machine helper (~150 LOC) |
| `tests/test_autopoll_state.py` | NEW | ≥12 pytest tests |
| `_ops/processes/b-code-autopoll-protocol.md` | NEW | B-code wake protocol |
| `_ops/processes/b-code-autopoll-startup.md` | NEW | Director paste-blocks |
| `briefs/_tasks/README.md` | UPDATE | Document state machine |
| `briefs/_tasks/CODE_2_PENDING.md` | UPDATE | Add YAML frontmatter (set status from current body) |
| `briefs/_tasks/CODE_3_PENDING.md` | UPDATE | Add YAML frontmatter (set status from current body) |
| `tasks/lessons.md` | APPEND | Lesson #50 |

## Do NOT Touch

| Path | Why |
|---|---|
| `_ops/processes/b-code-dispatch-coordination.md` | §2 busy-check still applies in cold-start; do NOT replace, only ADD autopoll mode |
| `outputs/slack_notifier.py` | `post_to_channel` already canonical; only IMPORT it from autopoll_state.py — no edits |
| `config/settings.py` | Reuse existing `cockpit_channel_id`; new `BAKER_OVERNIGHT_CHANNEL_ID` is read directly via `os.getenv` (no settings module change) |
| `briefs/_tasks/CODE_1_PENDING.md` / `CODE_4_PENDING.md` / `CODE_5_PENDING.md` | Stale dispatches; do not retrofit frontmatter (those B-codes not in first autopoll cohort per Q7) |
| Any production Cortex / capability / sentinel code | This brief is process + protocol only |
| `triggers/embedded_scheduler.py` | No new APScheduler job — autopoll runs in B-code Claude Code session via `/loop`, not Render-side cron |

## Quality Checkpoints

1. `pytest tests/test_autopoll_state.py -v` ≥12 tests green (literal stdout in ship report)
2. `python3 -c "import py_compile; py_compile.compile('scripts/autopoll_state.py', doraise=True)"` exits 0
3. `python3 -c "from scripts.autopoll_state import read_state; print(read_state('briefs/_tasks/CODE_3_PENDING.md'))"` returns dict with `status` key after frontmatter retrofit
4. `_ops/processes/b-code-autopoll-protocol.md` exists, ≥7 phase sections present
5. `_ops/processes/b-code-autopoll-startup.md` exists, includes paste-blocks for `b2`, `b3`, `aihead1`
6. `tasks/lessons.md` ends with Lesson #50 (`grep -c "^### 50\." tasks/lessons.md` returns 1)
7. `scripts/autopoll_state.py` zero DB writes (`grep -E "psycopg|conn|cursor|store_back" scripts/autopoll_state.py` returns nothing)
8. `scripts/autopoll_state.py` zero secret references (`grep -iE "password|token|secret|api.key" scripts/autopoll_state.py` returns nothing — only `os.getenv("BAKER_OVERNIGHT_CHANNEL_ID")` is acceptable since it's a public channel ID)
9. PR description includes: (a) Lesson #50 quote, (b) confirmation Lesson #48 NOT removed, (c) Q1–Q8 default values listed
10. `/security-review` on PR before merge (mandatory per AI Head SKILL.md)

## Verification (post-merge, dry-run before first overnight)

```bash
# AI Head A executes ONE manual cycle on a test mailbox before Director starts
# overnight window — proves the wiring works end-to-end before B-codes
# actually depend on it.

cd ~/bm-b1
git pull -q

# 1. Create test mailbox row (do NOT use a real B-code's mailbox)
cat > /tmp/CODE_TEST_PENDING.md <<EOF
---
status: OPEN
brief: briefs/BRIEF_B_CODE_AUTOPOLL_1.md
trigger_class: LOW
dispatched_at: 2026-04-27T20:00:00Z
dispatched_by: ai-head-a
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: true
---

# CODE_TEST — autopoll dry-run
EOF

# 2. Test transitions
python3 <<EOF
from scripts.autopoll_state import read_state, transition_state, heartbeat, find_stale_claims
import json

# Read
print("OPEN state:", json.dumps(read_state("/tmp/CODE_TEST_PENDING.md")))

# Claim
transition_state("/tmp/CODE_TEST_PENDING.md", to="IN_PROGRESS", claimed_by="b3")
print("After claim:", json.dumps(read_state("/tmp/CODE_TEST_PENDING.md")))

# Heartbeat
heartbeat("/tmp/CODE_TEST_PENDING.md")

# Ship
transition_state("/tmp/CODE_TEST_PENDING.md", to="COMPLETE", ship_report="briefs/_reports/test.md")
print("After complete:", json.dumps(read_state("/tmp/CODE_TEST_PENDING.md")))

# Stale claim detection
print("Stale claims:", find_stale_claims("/tmp/", max_age_minutes=0))
EOF

# 3. Slack push smoke (only if Director authorizes Tier B)
# python3 -c "from scripts.autopoll_state import push_state_transition; push_state_transition('/tmp/CODE_TEST_PENDING.md', to='COMPLETE', extra='dry-run smoke test')"
# Verify message appears in #cockpit + Director DM.

# 4. Cleanup
rm /tmp/CODE_TEST_PENDING.md
```

## Cost & Operational Risk

- Wake interval 900s × 2 B-codes (B2 + B3) × 8h = ~64 wakes total. Each wake = ~1 cache miss (>5 min TTL boundary). Tractable.
- AI Head A's watchdog loop: 600s interval × 8h = 48 wakes. Same B-code-Claude-instance prompt cache replay cost.
- Slack push: ~32 messages/8h to #cockpit + ~16 high-signal to Director DM. Well under any Slack rate limit; under invariant S4 cap.
- Failure modes:
  - B-code crashes mid-claim → stale heartbeat → AI Head resets to OPEN at 60 min → Slack push surfaces. Worst case: brief sits idle 60 min before next attempt.
  - Git push race on claim → last-writer-wins → losing B-code re-pulls and finds IN_PROGRESS by other B-code → idle reschedule. Clean.
  - `outputs.slack_notifier` import fails in B-code working dir → silent skip (try/except). AI Head's loop catches state transitions independently.
  - `OVERNIGHT_AUTONOMY_UNTIL` env not set → loop runs indefinitely. Mitigation: protocol Phase 1 defaults to 07:00Z if env unset.

## Rollback

If autopoll behaves badly mid-overnight: Director pastes `STOP AUTOPOLL` into any tab → B-code exits loop. AI Head A receives Slack push, manually completes any in-flight claims (transitions to OPEN or COMPLETE as appropriate), reverts to cold-start mode.

For permanent rollback: revert this brief's PR. Lesson #48 reverts to mandatory always (current state).

---

## Code Brief Standards compliance (per AI Head SKILL.md)

| # | Standard | This brief |
|---|---|---|
| 1 | API version/endpoint | Slack `chat_postMessage` via `slack_sdk.WebClient` (already in stack); `ScheduleWakeup` Claude Code primitive (loop tool) |
| 2 | Deprecation check date | 2026-04-27 (frontmatter) |
| 3 | Fallback | `B_CODE_AUTOPOLL_ENABLED` not required (no env gate); whole feature is opt-in via paste-block start. Cold-start mode (Lesson #48) is the fallback. |
| 4 | Migration-vs-bootstrap DDL | N/A — no DB writes |
| 5 | Ship gate | Literal `pytest tests/test_autopoll_state.py -v` output in ship report |
| 6 | Test plan | ≥12 tests in `test_autopoll_state.py` covering frontmatter parse / write / round-trip / illegal-transition rejection / stale-claim detection / Slack push mock |
| 7 | file:line citations | Verified: `outputs/slack_notifier.py:111`, `:115` (D0AFY28N030 ref), `:142-144` (non-fatal contract); `config/settings.py:201`; `triggers/audit_sentinel.py:19`; `briefs/_tasks/README.md:1-44` |
| 8 | Singleton pattern | N/A — no SentinelStoreBack/Retriever instantiation |
| 9 | Post-merge script handoff | N/A — no embedding/ingestion script run from working tree |
| 10 | Pattern-2 invocation-path audit (Amendment H) | N/A — not a capability touch (`capability_sets` untouched) |
