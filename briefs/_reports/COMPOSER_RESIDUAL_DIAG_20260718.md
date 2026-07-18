# COMPOSER_RESIDUAL_DIAG — 2026-07-18

**Brief:** COMPOSER_ENTER_SWALLOW_RESIDUAL_DIAG_1 (lead #12696, @9aba2c57) +
scope-add #12724 (path-5 local-writer inventory) + scope-add #12728 (BENIGN
reframe → send-keys origin-tag convention).
**Type:** Diagnose-first. No production fix in this brief.
**Worker:** b2. **Probe seats:** b3/b4 only. Read-only against the Lab.

---

## Bottom finding

The residual "text lands, Enter swallowed, message parks" bug is **not a
CR-drop in the mux/bridge/ttyd chain**. That chain is byte-transparent
(verified in code). The park is the Claude Code composer's **bracketed-paste
semantics**: a newline delivered *inside* an xterm bracketed-paste envelope
(`ESC[200~ … ESC[201~`) is inserted **literally** and never submits. Only a
carriage return delivered as its **own** PTY write submits.

Path 3 (the new cockpit-in-Lab bridge terminal) is uniquely exposed because it
carries a **human paste** in the browser xterm, and xterm emits bracketed paste
whenever the app has enabled DECSET 2004 — which Claude Code does. Paths 1 and 2
(programmatic wake injectors) are NOT exposed: they inject a fixed `check bus`
template *and* already carry a belt-and-suspenders second bare-Enter submit
(WAKE_COMPOSER_SUBMIT_FIX_1 @3ff85b17; the wake-handler AppleScript's empty
`do script ""`).

This is the **same failure family** as the wake bug, surfacing at a different
trigger: there, a burst-injected Enter was swallowed; here, a paste-wrapped
newline is literal. Both are "a newline that isn't its own clean PTY write does
not submit."

---

## Reproduction matrix (AC1 / AC2)

All cells run live on seat **b4** (Claude Code, Opus 4.8), pane-captured. Case A2
= the reproduction. Timestamps UTC.

| # | Path modelled | Injection (exact bytes) | Verdict | Evidence |
|---|---|---|---|---|
| A | Path 4 direct / coalesced, no bracket | `PROBE_A_coalesced_ignore_this\r` (one PTY write) | **SUBMITS** | 14:09:19Z — pane showed "✻ Zesting…", composer cleared |
| A2 | **Path 3 browser paste** | `ESC[200~PROBE_A2_bracketed_paste_with_trailing_newline\n ESC[201~` (no separate CR) | **PARKS** | 14:09:57Z — `❯ PROBE_A2_bracketed_paste_with_trailing_newline` sat in the input box, unsubmitted |
| C | Recovery hop | bare `Enter` (own write) on the A2-parked text | **SUBMITS** | 14:10:08Z — pane showed "✽ Whirlpooling…", composer cleared |

Interpretation:
- **A vs A2** isolates the cause to the **bracketing**, not the coalescing: the
  same text+newline submits when raw, parks when paste-wrapped.
- **C** confirms the recovery is a separate Enter — exactly the wake-fix pattern.

### Path-by-path verdicts (AC1)

1. **Path 1 — cockpit controller wake (`send_wake`, tmux send-keys).**
   `SUBMITS`. Injects `check bus #<id> <topic>` via `send-keys -l`, then settle +
   bare Enter + a second bare Enter (`cockpit_controller.py:564-584`,
   WAKE_COMPOSER_SUBMIT_FIX_1). Two separate-write Returns → never parks.
   Evidence: code + case A (coalesced text+CR submits) + case C (bare Enter
   submits).
2. **Path 2 — Wake.app / wake-handler AppleScript `do script`.**
   `SUBMITS` (template only). `do script "check bus"` then an empty
   `do script ""` (lone CR) to submit; its own comments record the identical
   park under a context banner and the empty-`do script` fix
   (`wake-handler-PATCHED-20260625.applescript:364-396`). Terminal tabs are
   mostly gone post-tmux-cutover. Evidence: source.
3. **Path 3 — cockpit-in-Lab bridge terminal (browser xterm → Lab WS → mux →
   bridge agent → laptop ttyd → tmux).** `PARKS` on paste. The mux + bridge
   agent are byte-transparent (`cockpit_bridge_agent.py:361-389` forwards WS
   payloads 1:1, TEXT decoded utf-8 and re-sent, BINARY passed through; no CR
   rewrite). The frontend is stock ttyd embedded in an iframe
   (`cockpit_static/cockpit.js:190`), so Enter = `\r` and paste = bracketed
   paste. Therefore the laptop-end delivery is identical to case A2.
   **Reproduced at the PTY layer (case A2), which is the shared final hop.**
   End-to-end through Render was NOT executed live — see "Not tested" below.
4. **Path 4 — direct local typing into a ttyd/tmux pane.** `SUBMITS`. Char-by-
   char keystrokes each land as their own PTY write; the final Enter is a clean
   `\r`. No bracket envelope. Evidence: case A (and normal daily use — no
   incidents).

### Live corroboration (in the wild, this session)

- **b3** at 14:09Z had `❯ check bus` **parked** in its composer, unsubmitted —
  a wake nudge that did not submit.
- **b4** during the probe window acquired `❯ clean it up, checkout main and pull`
  **parked** (not typed by me; baseline was empty). `Ctrl-U` did not clear it,
  consistent with bracketed-paste-parked content. Flagged to lead (#12782); left
  untouched because `checkout main and pull` could act if submitted.

Both are independent live instances of the same park.

---

## Causal trace (AC3 — reproduced case)

```
Director pastes question into browser xterm (ttyd UI, proxied via /cockpit)
  → xterm bracketed-paste ON (Claude Code sent DECSET ?2004h)
  → xterm sends  ESC[200~ <question><trailing \n> ESC[201~  as ttyd INPUT
  → Lab /cockpit/term/<slug>/ws → cockpit_mux frames  (transparent)
  → bridge agent _ws_lab_to_upstream: bytes forwarded 1:1  (transparent)
  → laptop ttyd → PTY master write
  → Claude Code composer: inserts payload literally, newline-in-bracket = literal
  → NO separate Enter follows  → text PARKS
```

The eaten hop is **none of them** — nothing drops the CR. The park is the
composer treating a bracketed newline as literal. Path 3 exposes it because it is
the only path that delivers a raw human paste with no injected recovery Enter.

---

## Scope-add #12724 — path-5 local-writer inventory

"Every local writer capable of freeform (non-`check bus`) text into a seat's
tmux/Terminal composer."

| Writer | Mechanism | Freeform? | Attributable today? |
|---|---|---|---|
| Cockpit controller `send_wake` | `tmux send-keys -l` | No — fixed `check bus #id topic` template | Yes — `_audit_wake` + fixed prefix |
| Cockpit GO (`/api/sessions/<slug>/go`) | bare `Enter` | No text at all | Yes |
| Wake-handler AppleScript | `do script "check bus"` in Terminal tab | No — fixed template | Partly (Terminal tab, no tag) |
| **Any local process/human — `tmux send-keys -t <seat> -l "<arbitrary>"`** | tmux | **YES — unconstrained** | **NO — no auth, no source tag** |
| **Any local caller — `osascript … do script "<arbitrary>" in <tab>`** | AppleScript/Terminal | **YES** | **NO** |
| `osascript … System Events keystroke "<arbitrary>"` | AppleScript | YES | NO — but Accessibility-grant-gated (wake-handler avoids it, err 1002) |
| **Local ttyd WS INPUT** (`ws://127.0.0.1:<port>/ws`, basic-auth `6470:6470`) | ttyd protocol | **YES** | **NO — shared cred, no per-caller tag** |
| Direct keyboard into a ttyd browser tab / tmux pane | human | YES | NO (real keyboard) |

The BENIGN incident #12700 (`status update in an hour` in lead's composer,
"sibling Cowork session typed it") is the `tmux send-keys -l` row: any Cowork
Claude/agent on this laptop can write arbitrary text into any seat's composer
with zero attribution. That is the recurrence risk, not a hostile actor.

---

## Scope-add #12728 — send-keys origin-tag convention (proposal)

Goal (lead's words): *every programmatically injected composer line carries a
source prefix so freeform seat input is always attributable at a glance.*

**Proposal — one shared injector + a visible tag + a durable log.**

1. **Single chokepoint.** Add `scripts/seat_inject.sh <slug> <source-tag>
   <text>` (probe/ops helper) and forbid raw `tmux send-keys -l`/`do script`
   text injection outside it (grep guard in the pre-commit hook, like the
   existing singleton/env guards). All programmatic writers route through it.
2. **Visible origin prefix.** The injector prepends a bracketed tag to the line:
   `[wake:cockpit] check bus #123`, `[cowork-ah1] status update in an hour`,
   `[seat_inject:b2] …`. The tag is submitted with the message, so it is visible
   in the seat, in the transcript, and to whoever reads the composer. Tag grammar
   `\[[a-z0-9:_-]+\]` at line start; the reading agent treats a leading tag as
   provenance, not instruction.
3. **Durable audit line.** The injector also appends
   `{ts, source, slug, sha1(text)}` to `~/.brisen-lab/seat-injections.log` so an
   untagged/park incident can be attributed post-hoc even if the composer is
   later cleared.
4. **Human paste is out of scope for the tag** (a real keyboard/paste cannot be
   tagged) — which is *why* the durable log matters: an untagged parked line is
   then, by elimination, a human paste, and that itself is the signal.

**Explicitly NOT recommended:** auto-injecting a recovery Enter after a human
bracketed paste to "fix" the park. Programmatic template injection (wake) should
submit and does; a human paste should NOT be auto-submitted — a user pasting a
multi-line draft to edit before sending would have it fired prematurely. Blast
radius too high. The park on human paste is correct terminal behavior; the fix is
attribution + observability, not auto-submit.

---

## Fix direction for the follow-up brief (NOT built here)

1. **Instrumentation (primary).** A cheap "unsent composer" detector: sample the
   seat pane; if a non-empty composer line persists > N seconds with no run
   active, emit a bus signal `composer/parked <slug> <first-40-chars>`. Catches
   the next occurrence attributably regardless of path. Pairs with the
   `seat-injections.log` above to attribute.
2. **Origin-tag convention** (§ above) — recurrence-design deliverable from
   #12728.
3. **Programmatic injectors:** keep the double-submit fix; route all through the
   single `seat_inject.sh` chokepoint so no new injector re-opens the park.
4. **Human paste:** do NOT auto-submit. Optionally a UX hint in the cockpit
   terminal ("unsent text — press Enter") if cheap, but this is Claude-Code-TUI
   territory we don't own.

---

## Not tested / honest gaps (fail-loud)

- **Path 3 end-to-end through Render** (real browser paste via
  `wss://brisen-lab.onrender.com/cockpit/term/b3/ws`) was **NOT run live.** It
  needs the `COCKPIT_ACCESS_TOKEN` (asked lead) + would inject into a live seat
  from a public surface. It is reproduced faithfully at the PTY layer instead,
  and the intermediate hops are proven byte-transparent in code (loopback probe
  10/10, `cockpit_bridge_loopback_probe.py`). If lead wants the literal
  end-to-end cell, provide the token and I will drive a headless `tty`-subprotocol
  WS client against b3's `/cockpit/term/b3/ws`.
- **Path 2 live** not re-run (Terminal tabs mostly gone post-cutover); verdict
  from source + its own regression notes.

## Artifacts

- Probe (PROBE-ONLY, guarded to b3/b4, dry-run default):
  `scripts/composer_residual_probe.py` — compiles clean; dry-run + refuse-guard
  verified.
- Bus thread: `gates/composer-residual-diag-1` (#12759 claim, #12782 interim +
  b4 heads-up).
