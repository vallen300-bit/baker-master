#!/usr/bin/env python3
"""PROBE-ONLY — composer Enter-swallow residual reproduction (diagnose brief
COMPOSER_ENTER_SWALLOW_RESIDUAL_DIAG_1, lead #12696).

NOT a production module. NOT wired into the controller, the bridge, or any
scheduler. It exists to reproduce, deterministically and with pane-capture
evidence, the residual "text lands in the composer, Enter is swallowed, message
parks unsubmitted" bug on an ephemeral probe seat (b3/b4 only).

What it shows (final PTY hop — shared by ALL injection paths, because the
cockpit_mux + bridge agent + ttyd are byte-transparent, see the diag report):

  A  plain coalesced  text + CR in ONE write            -> SUBMITS  (no bug)
  B  bracketed-paste payload ending in newline, no CR   -> PARKS    (the bug)
  C  a separate bare Enter (own write) on parked text   -> SUBMITS  (recovery)

Case B is the residual path: a browser/ttyd PASTE wraps content in
ESC[200~ ... ESC[201~ (xterm bracketed paste, which Claude Code enables via
DECSET 2004). A newline INSIDE the bracket is literal — it does not submit — and
if the paste carries a trailing newline and no separate Enter follows, the line
parks. Same failure family as WAKE_COMPOSER_SUBMIT_FIX_1 (burst text+Enter) and
the wake-handler AppleScript banner-park (fixed with a 2nd empty `do script`).

SAFETY
  * Refuses any seat except b3/b4 (ephemeral probe seats).
  * Default is --dry-run: it prints the exact byte sequences without touching
    tmux. Pass --live to actually inject.
  * --live submits benign probe text to a real Claude seat; the caller is
    expected to interrupt (Esc) any run it triggers. Never point it at a
    Director-facing desk.

Usage:
  python3 scripts/composer_residual_probe.py --seat b4            # dry-run
  python3 scripts/composer_residual_probe.py --seat b4 --live A   # run case A
  python3 scripts/composer_residual_probe.py --seat b4 --live B   # run case B
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

ALLOWED_SEATS = {"b3", "b4"}
SETTLE_S = 1.2

# Byte sequences per case. \x1b[200~ / \x1b[201~ are the xterm bracketed-paste
# start/end markers; a browser/ttyd paste emits exactly these around the payload.
CASES = {
    "A": ("plain coalesced text+CR (one write) -> expect SUBMIT",
          "PROBE_A_coalesced_ignore_this\r"),
    "B": ("bracketed paste, payload ends in newline, NO separate CR -> expect PARK",
          "\x1b[200~PROBE_B_bracketed_paste_trailing_newline\n\x1b[201~"),
}


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def capture(seat: str) -> str:
    return _tmux("capture-pane", "-t", seat, "-p").stdout


def inject_literal(seat: str, payload: str) -> None:
    # -l = literal: the exact bytes go to the pane in a single write, modelling a
    # coalesced ttyd WS INPUT frame (the bridge forwards bytes 1:1).
    _tmux("send-keys", "-t", seat, "-l", payload)


def inject_bare_enter(seat: str) -> None:
    # A Return as its OWN write (not part of a paste bracket) — the recovery hop.
    _tmux("send-keys", "-t", seat, "Enter")


def run_case(seat: str, case: str) -> None:
    desc, payload = CASES[case]
    print(f"[case {case}] {desc}")
    print(f"  bytes: {payload!r}")
    print("  --- pane BEFORE ---")
    print("  " + capture(seat).strip().replace("\n", "\n  "))
    inject_literal(seat, payload)
    time.sleep(SETTLE_S)
    print("  --- pane AFTER inject ---")
    print("  " + capture(seat).strip().replace("\n", "\n  "))
    if case == "B":
        print("  [case C] separate bare Enter on the parked text -> expect SUBMIT")
        inject_bare_enter(seat)
        time.sleep(SETTLE_S)
        print("  --- pane AFTER bare Enter ---")
        print("  " + capture(seat).strip().replace("\n", "\n  "))
    print("  NOTE: interrupt any triggered run with Esc; this is a probe seat.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Composer Enter-swallow residual probe (PROBE-ONLY)")
    p.add_argument("--seat", required=True, help="probe seat (b3 or b4 only)")
    p.add_argument("--live", choices=sorted(CASES), help="actually inject this case; omit for dry-run")
    args = p.parse_args(argv)

    if args.seat not in ALLOWED_SEATS:
        print(f"REFUSED: seat {args.seat!r} not in probe set {sorted(ALLOWED_SEATS)}", file=sys.stderr)
        return 2

    if not args.live:
        print("DRY-RUN (no injection). Byte sequences that WOULD be sent:")
        for c, (desc, payload) in CASES.items():
            print(f"  [case {c}] {desc}\n           bytes={payload!r}")
        print("Re-run with --live A or --live B to inject into", args.seat)
        return 0

    run_case(args.seat, args.live)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
