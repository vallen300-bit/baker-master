# B4 ship report — WAKE_INJECT_SUBMIT_FIX_2 (P1)

- **Brief:** WAKE_INJECT_SUBMIT_FIX_2 @cda17e3f (bus #12874, lead)
- **Report topic:** `gates/wake-inject-submit-fix-2`
- **Date:** 2026-07-18
- **PRs:** baker-master **#600** (D1/D2/D3-tag/D4) · brisen-lab **#156** (D3 dispatch log)
- **Branches:** `b4/wake-inject-submit-fix-2` (both repos, off origin/main)

## Done rubric

Live wake nudges could park unsent in the tmux composer even after FIX_1. This
adds a post-inject verify-and-recover on the live path + a fail-loud flag on an
unrecoverable park + universal `[wake]` origin tagging + a PTY regression that
pins the submit rule. Reported below AC-by-AC with evidence.

## Scope decision (surfaced to lead, not averaged)

The brief named `brisen-lab/tools/wake-listener/wake-listener.py` as the delivery
path. Reality: `wake-listener.py` only **dispatches** (`open brisen-lab://wake/<alias>`) —
it writes no composer text. The **live** machine wake-injection path on this host
is `scripts/cockpit_controller.py` `send_wake` (tmux `send-keys`) — that is the
"tmux send-keys wake caller" D1 also names, and the path that produced the b3
park. So D1/D2/D4 land in baker-master; the wake-handler AppleScript path is
legacy Terminal-tab (mostly gone post-cutover) and already carries its own
double-`do script` submit fix, so it was left untouched. `wake-listener.py` gets
the D3 durable attribution log (its role in the chain). Flagged to lead in the
start note (bus #12880).

## Acceptance criteria

- **AC1 — machine nudge submits ≤5s on an idle seat.** Deferred to the live
  post-deploy AC on a real seat (cannot be asserted in unit tests). The write
  pattern (text + separate bare CR) is unchanged from FIX_1 and is proven to
  submit at the PTY layer (AC4).
- **AC2 — recovery fires exactly once; unrecoverable park raises the bus flag.**
  PASS (tests). `test_send_wake_recovers_a_parked_nudge` (boxed → one recovery
  Enter → clear → `verified: recovered`, no flag); `test_send_wake_unrecoverable_park_fails_loud`
  (stays boxed → exactly one recovery Enter → `verified: park_unrecovered` +
  `_post_park_flag` fires); `test_send_wake_unreadable_pane_takes_no_action`
  (rc≠0 capture → `verified: unknown`, no recovery, no flag).
- **AC3 — human-typed composer text is never auto-submitted or tagged.** PASS by
  construction: `send_wake` only tags/verifies its own machine nudge (needle =
  `check bus #<id>`); it never reads or touches human-composed input. The
  AppleScript/human-paste auto-submit is explicitly out of scope (diag §12728).
- **AC4 — regression red on old write pattern, green on new.** PASS.
  `tests/test_composer_pty_submit.py` drives bytes through a real kernel PTY
  (raw mode) against a ComposerModel of the diag rule: bracketed-newline PARKS
  (`test_bracketed_paste_newline_parks`, `test_coalesced_newline_in_paste_is_the_regression_guard`),
  separate bare CR SUBMITS (`test_separate_bare_cr_submits`,
  `test_wake_inject_writes_pattern_submits`).

## Deliverables

- **D1** — text write + separate bare CR (already conformant; `wake_inject_writes`
  states it, PTY test proves it submits).
- **D2** — `_verify_wake_submit`: force redraw (`C-l`), capture pane, `_composer_holds`
  check; one recovery Enter on park; `_post_park_flag` (durable local record +
  best-effort bus post to lead `fleet/wake-inject-park`) on unrecoverable park;
  no action on unreadable pane.
- **D3** — `[wake]` prefix on every machine nudge (`WAKE_ORIGIN_TAG`); durable
  audit via `_audit_wake` (cockpit) + append-only `~/.brisen-lab/wake-dispatch.log`
  (wake-listener).
- **D4** — PTY-level regression (above).

## Park-detection validation (de-risk)

`_composer_holds` distinguishes parked (needle shares a line with a composer
marker — prompt glyph `U+276F` or box border `U+2502`) from submitted (plain `> `
line, no marker). The marker set was **validated against the live deployed Claude
Code composer** via a read-only `tmux capture-pane` of the b4 seat (the composer
input line renders `U+276F` + space; box borders `U+2500`/`U+2502`) — not a guess.
Open item for live AC: confirm on the actual b3 probe seat that a real park is
detected and recovered end-to-end (the one thing unit tests can't cover).

## Test evidence

```
# baker-master
$ python3 -m pytest tests/test_cockpit_wake.py tests/test_composer_pty_submit.py -q
27 passed, 2 warnings in 0.77s

# brisen-lab (dummy TEST_DATABASE_URL to bypass the DB-gated autouse skip; tests touch no DB)
$ python3 -m pytest tests/test_wake_listener_dispatch_log.py tests/test_wake_listener_health.py \
    tests/test_wake_alias_allowlist.py tests/test_wake_handler_no_retired_slugs.py -q
30 passed in 0.10s
```

Note: some unrelated brisen-lab tests fail to *collect* locally on Python 3.9
(`db.py` uses 3.10+ `X | None` union syntax via `bus.py`); pre-existing, CI runs
3.11+. My change touches neither `db.py` nor `bus.py`.

## Gate plan

Codex bus-seat gate on both PRs → lead merges → live AC on this host (fire a real
wake at idle b3, observe submit + `[wake]` prefix in scrollback; then busy-seat
non-interleave) → 24h park-free observation → POST_DEPLOY_AC_VERDICT on
`gates/wake-inject-submit-fix-2`. b2 (diag author) FYI on the topic.

---

## POST-DEPLOY LIVE AC (2026-07-18, after codex PASS #12921 + merge of #600/#156)

Deployed controller confirmed synced (key funcs byte-identical to merged main;
`_composer_holds` / `_verify_wake_submit` / `_tmux_write_args` / `wake_inject_writes`
all IDENTICAL md5). Live probe run on seat b3 (lead-designated probe seat).

- **AC1 — idle-seat submit: PASS.** b3 composer cleared → fired `send_wake` → returned
  `sent=True, line='[wake] check bus #12653 fleet/wake-probe', verified='submitted'`.
  Pane after: composer empty (`❯ `), b3 generating (`✳ Dilly-dallying…`). Tagged
  nudge visible in scrollback: `❯ [wake] check bus #12653 fleet/wake-probe`.
- **AC2 — busy-seat non-interleave: PASS.** `send_wake` on a working seat →
  `{sent: False, skipped: 'working'}`. The wake_skip_reason guard blocks injection
  into a generating composer, so no mid-line interleave is possible.
- **AC3 — concurrent human text guard: PASS.** b3's live composer held an UNTAGGED
  `check bus` line; `_composer_holds(pane, '[wake] check bus #12653 fleet/wake-probe')`
  = **False** (no recovery would fire), while a tagged boxed control = True. An
  untagged human draft is never auto-submitted — the codex #12917 breach is closed.
- **AC4 — dispatch attribution log: PASS.** `~/.brisen-lab/wake-dispatch.log` carries
  organic post-deploy entries (codex/b4/deputy/lead/codex), each with
  `{ts, origin:wake, alias, foreground, result:ok}` — who/what/when/open-result.

**Caveat (fail-loud, for the 24h watch):** the stale-render caveat is REAL and was
reproduced live — `capture-pane -p` returned a stale composer render after edits
even following a `C-l`, until fresh keystrokes forced a repaint. In AC1 the verify
path (`C-l` + 1.0s settle + capture) read correctly, but if false parks / false
recoveries appear during the watch, the `WAKE_VERIFY_SETTLE_S` margin or an extra
repaint before capture is the first tuning knob. Also note: `send_wake`'s injection
appends to whatever is already in the composer, so a wake fired while a human draft
sits unsent would still concatenate+submit — out of this brief's scope (guarded by
is_working for the generating case; the origin-tag chokepoint follow-up #12795
addresses the broader attribution surface).

**Verdict: 4/4 AC PASS.** Director manual copy-paste arc closed pending the 24h
park-free observation.
