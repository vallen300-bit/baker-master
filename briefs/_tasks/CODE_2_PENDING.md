---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1.md
trigger_class: TIER_B_FLEET_INFRA
dispatched_at: 2026-05-11
dispatched_by: ai-head-1 (AH1)
target: b2
director_ratification: Director ratified 2026-05-11 in chat ("go ahead") after AID provisioning round-trip exposed V0.2 §#3 wake-mechanism gap; AH1 authored brief V0.1 → V0.2 (reviewer pass folded 4 blockers + 1 token-budget note). Director redirected dispatch B1 → B2 same session ("can you dispatch to b2 instead? b3 is busy"). Director's prior comment "AH2 + B-codes still via Director paste-block (not on bus yet)" relayed from parallel-AH1 instance flagged this as the next-shipping fleet-infra unblock.
priority: P2
phase: 1 of 1 (single PR)
unblocks:
  - Fleet-wide bus-as-default delivery: AH1/AH2/B1-B5/architect/AID/cortex all gain SessionStart inbox drain
  - Director-clipboard-relay becomes fallback only (was primary delivery path for non-active terminals)
  - V0.2 §#3 wake-mechanism pattern (2) ship; pattern (1) tmux-send-keys remains deferred
expected_pr_count: 1 (baker-master, plus user-global hook file + settings.json edit outside the repo)
expected_branch_name: b2/brisen-lab-bus-drain-on-session-start-1
expected_complexity: low-medium (~3-4h)
mandatory_2nd_pass: FALSE  # feature-dev:code-reviewer pass on brief done (4 blockers folded); /security-review NOT mandatory (fleet-internal auth, not user-facing Tier-A); AH2 cross-lane review on PR per autonomy charter §3
last_heartbeat: null
autopoll_eligible: true
---

# CODE_2_PENDING — BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1 — 2026-05-11

**Brief:** `briefs/BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1.md` (READ FIRST — 344 lines, V0.2 post-reviewer-fold, complete embedded hook script + jq splice command + 5-section verification including V0.2 reviewer-fix sanity checks)
**Working dir:** `~/bm-b2`
**Working branch:** `b2/brisen-lab-bus-drain-on-session-start-1`
**Repo:** `vallen300-bit/baker-master`

## Summary

Wire V0.2 §#3 wake-mechanism pattern (2) — SessionStart hook drains V2 bus inbox for the current terminal's BAKER_ROLE slug on every Claude Code session-open, emits unread messages as `additionalContext`. Closes the delivery gap: AH2 + B-codes + AID are all provisioned on the bus (have keys + authority rows), but receivers don't see incoming traffic without an active poll OR a hook drain. AID's first successful round-trip 2026-05-10T22:05Z worked only because AID manually polled.

**2 files to create + 1 user-global edit (NOT in the repo):**

1. **New hook file:** `~/.claude/hooks/session-start-bus-drain.sh` (user-global; NOT inside `baker-master`).
   - Resolves BAKER_ROLE → slug (mirror `scripts/bus_post.sh` ROLE_TO_SLUG).
   - Fetches `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>/credential`.
   - Reads `~/.brisen-lab-bus-last-seen-<slug>.txt` (24h-ago default on first run).
   - GETs `https://brisen-lab.onrender.com/msg/<slug>?since=<last>&limit=50` with `X-Terminal-Key`.
   - Emits formatted summary as `additionalContext` JSON envelope (≤30 messages rendered, overflow noted).
   - Updates state file atomically via `tempfile.mkstemp` + `os.replace()`.
   - Never blocks session start: all error paths emit a short status line + exit 0.

2. **User-global `~/.claude/settings.json` edit:** `jq`-splice the new SessionStart entry alongside the existing Forge hook entry. Do NOT overwrite the file — it has 8 other top-level keys (`permissions`, `model`, `statusLine`, `enabledPlugins`, `extraKnownMarketplaces`, `skipDangerousModePermissionPrompt`, `theme`, `_comment`) that must survive. Exact jq command in brief §Implementation step 2.

3. **In-repo: `tests/test_bus_drain_hook.py`** — unit tests covering the 5 failure paths + happy path. Test scaffolding only (the hook itself is user-global; the test stubs `curl` and `op` via env vars).

## CRITICAL — reviewer-caught issues already folded into V0.2 brief

A `feature-dev:code-reviewer` pass on the brief itself (2026-05-11) caught 4 blockers + 1 token-budget note. ALL FOLDED INTO V0.2. If you encounter:

- **`KeyError` on `os.environ["SLUG"]` inside the python3 invocation** — the brief's V0.1 draft set env vars on `_emit`'s pipe-tail (a separate subprocess that doesn't inherit them). V0.2 fix: env vars prefixed on the python3 invocation itself; curl response plumbed via `RESP=...` env-var instead of stdin. USE V0.2 SCRIPT VERBATIM.
- **State file written via plain `open(state_file, "w")`** — non-atomic; mid-write kill leaves partial/empty file. V0.2 fix: `tempfile.mkstemp` + `os.replace()`. DO NOT skip.
- **JSON config as a paste-snippet ending with `...`** — V0.1 draft would have clobbered every other top-level key. V0.2 fix: `jq --argjson new ... '.hooks.SessionStart += [$new]'` with backup + validate + atomic swap. USE jq, NOT file overwrite.
- **6s curl + ~3s op read inside 10s hook timeout** — V0.2 fix: `curl --max-time 4`, hook timeout raised to `15`. Both already in brief.
- **Rendering >200 messages → ~70KB additionalContext** — V0.2 fix: curl `limit=50` + rendering hard cap `RENDER_CAP=30`. Overflow note in header.

## Scope discipline (single brief)

This is single-phase. No follow-on briefs in this dispatch. Active-wake for currently-running terminals (V0.2 §#3 pattern 1: tmux send-keys) is **deferred** — flagged as known limitation §2 in brief.

**Do NOT add:**
- Auto-ACK on drain (drain emits as context; receiver explicitly ACKs).
- Per-picker `.claude/settings.json` edits (user-global handles all sessions).
- Changes to `scripts/bus_post.sh` / `bus_post.py` (orthogonal client-side post tooling).
- Any change to `brisen-lab` daemon (`bus.py`, `auth_lab.py`, `db.py` are read-only consumers of existing GET endpoint).

## Ship gate

1. `bash -n ~/.claude/hooks/session-start-bus-drain.sh` — syntax check passes.
2. `pytest tests/test_bus_drain_hook.py -v` — ≥6 tests pass (5 failure paths + 1 happy path).
3. Live end-to-end smoke per brief §Verification step 2 — post from AH1 (`lead`) to `b2`, start fresh `~/bm-b2` session, drain renders in additionalContext within <8s. (Brief uses b1 as the example slug in verification steps — substitute `b2` for your test runs since you're the implementer; either works since the hook is slug-agnostic.)
4. V0.2 reviewer-fix sanity per brief §Verification step 5 — all 4 folds verified live.
5. PR description includes literal `pytest` stdout + literal `bash -n` exit code (no "passes by inspection" — Lesson #8).
6. AH2 cross-lane review per autonomy charter §3 — auth-adjacent change, no `/security-review` mandate.

## Files touched

**Create (in-repo):**
- `tests/test_bus_drain_hook.py`

**Create (user-global, NOT in repo — Director ratifies edit pre-merge):**
- `~/.claude/hooks/session-start-bus-drain.sh`

**Modify (user-global, NOT in repo — Director ratifies edit pre-merge):**
- `~/.claude/settings.json` (jq splice — backup + validate + atomic swap per brief)

**Do NOT touch:**
- `scripts/bus_post.sh` / `bus_post.py` (orthogonal — bus_post is for outbound POST; this hook is for inbound GET).
- Per-picker `.claude/settings.json` (no edit needed; user-global handles all).
- `brisen-lab/` repo (read-only consumer of existing GET /msg/<terminal>).
- `BRISEN_LAB_TERMINAL_KEYS` Render env (already populated for all 13 slugs).
- Other SessionStart hooks (`session-start-role.sh`, Forge hook — both continue firing independently).
- Anything cockpit-Phase-1-related (PR #180 is your prior task; this dispatch is unrelated — separate branch, separate scope).

## Estimated complexity

Low-Medium · ~3-4h · 1 PR (in-repo) + user-global edit (Director-ratified) · Tier-B fleet-infra. No `/security-review` mandate.

## Heartbeat

Update `last_heartbeat: <UTC ISO>` in this mailbox file every 30 min during active work. Standard `b-code-dispatch-coordination.md` §3 protocol. Brief is small enough that 1-2 heartbeats should cover the full cycle.

## Prior CODE_2 task (archive reference)

BRIEF_CORTEX_COCKPIT_SIDEBAR_WIRING — SHIPPED 2026-05-10 / 2026-05-11 (b2 reported SHIPPED in their picker; PR #180 OPEN on `b2/cortex-cockpit-sidebar-wiring`, awaiting AH2 `/security-review` Gate 2 verdict + AH1 merge). PR #180 review/merge runs in parallel with this new dispatch — separate branch, no scope overlap. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
