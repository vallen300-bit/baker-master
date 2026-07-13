#!/usr/bin/env python3
"""CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1 (E3) — worker-side GO-reroute gate.

STRUCTURAL enforcement of the standing rule "route a GO/confirm ask on already-
dispatched work to your superior, not the Director" (route-cues-to-superior). Prompt
text decays hours into a session; this gate is a deterministic guard in the bus-post
path that reroutes such a message to the sender's `reports_to` BEFORE it reaches the
Director.

CONSERVATIVE by binding rider (lead dispatch #10036). The reroute fires ONLY when a
message is:
  1. addressed to the Director,
  2. from a seat that HAS a superior (reports_to != Director — top-level seats never
     reroute),
  3. a GO / confirm / permission ask (GO_RE),
  4. about ALREADY-DISPATCHED work — it references a job/PR/brief (JOBREF_RE),
  5. AND carries NO protected signal (PROTECTED_RE): a ratify_required, a Tier-B/C
     prerogative, or a genuine business decision (money / counterparty / external
     send / sign / scope). Any protected hit → NEVER reroute (those legitimately go
     to the Director). Safety-first: the protected veto beats every positive signal.

Fail-loud: a reroute is LOGGED (stderr + a logfile) and cc'd to lead. Env kill switch
`BAKER_GO_REROUTE_DISABLED` (truthy) bypasses the gate entirely.

The decision function `decide_reroute` is PURE (registry injected) so the mandatory
false-positive tests exercise it directly (tests/test_go_reroute_gate.py).
"""
import os
import re
import sys
import time

# GO / confirm / permission ask. Tight — anchored tokens, not any occurrence of "go".
GO_RE = re.compile(
    r"(?:(?<![a-z])go\?)"                 # "go?" not preceded by a letter
    r"|🟢\s*go"                            # green-circle GO cue
    r"|👉\s*you"                           # the "your turn" cue
    r"|\bconfirm\b"
    r"|\bpermission\b"
    r"|\bgreen[-\s]?light\b"
    r"|\bmay i\b"
    r"|\bshould i (?:start|proceed|go|merge|push|ship)\b"
    r"|\bready to start\b"
    r"|\bawait(?:ing)? (?:your )?go\b"
    r"|\bok to (?:start|proceed|merge|go|ship)\b",
    re.IGNORECASE,
)

# Already-dispatched-work reference: a job/PR/brief/dispatch token. This is the
# "already-dispatched job_ref" constraint that keeps the gate conservative — a bare
# "GO?" with no referenced work is NOT rerouted.
JOBREF_RE = re.compile(
    r"(?:#\d+)"                           # bus/PR message id "#9033"
    r"|(?:/jobs/\d+)"                     # queue job ref
    r"|\bjob[_\s-]?ref\b"
    r"|\bjob\s+\d+\b"
    r"|\bpr\s*#?\d+\b"
    r"|\bdispatch(?:ed)?\b"
    r"|\bbrief\b"
    r"|[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+){2,}",  # an ALLCAPS_BRIEF_ID token
)

# PROTECTED — a message that legitimately goes to the Director. ANY hit vetoes the
# reroute. Covers ratify_required, Tier-B/C prerogatives, and business decisions
# (money / counterparty / external-send / signing / scope / timeline).
PROTECTED_RE = re.compile(
    r"\bratif"                            # ratify / ratification / ratify_required
    r"|\btier[-\s]?b\b|\btier[-\s]?c\b"
    r"|\bdirector[_\s-]?only\b"
    r"|\bprerogative\b"
    r"|[€$£]|\bchf\b|\beur\b|\busd\b"     # money
    r"|\bsell\b|\bbuy\b|\bacquire\b|\bcounterpart"
    r"|\bexternal (?:send|email|message)\b"
    r"|\bwire\b|\bsign\b|\bsignature\b"
    r"|\bbudget\b|\bpricing\b|\bvaluation\b|\boffer\b",
    re.IGNORECASE,
)


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def decide_reroute(recipient, body, sender_reports_to, disabled=False):
    """Pure decision. Returns (target_or_None, reason).

    target_or_None: the superior slug to reroute to, or None (no reroute).
    reason: a short machine string for the log / tests.
    """
    if disabled:
        return None, "kill_switch"
    if (recipient or "").strip().lower() != "director":
        return None, "not_director_recipient"
    sup = (sender_reports_to or "").strip()
    if not sup or sup.lower() == "director":
        # Top-level seat (reports to Director) — GO asks to the Director are its
        # legitimate channel; nothing to reroute to.
        return None, "sender_is_top_level"
    text = body or ""
    if PROTECTED_RE.search(text):
        # Protected veto beats every positive signal (ratify / Tier-B/C / business).
        return None, "protected_veto"
    if not GO_RE.search(text):
        return None, "no_go_pattern"
    if not JOBREF_RE.search(text):
        # A GO with no referenced already-dispatched work — conservative: do not
        # reroute (could be a fresh question the Director genuinely needs).
        return None, "no_jobref"
    return sup, "reroute_go_on_dispatched_work"


def resolve_reports_to(sender_slug, agents=None):
    """Look up the sender's `reports_to` from the compiled agent registry."""
    if agents is None:
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from orchestrator.agent_identity_data import AGENTS  # noqa: PLC0415
            agents = AGENTS
        except Exception:
            return None
    s = (sender_slug or "").strip()
    sl = s.lower()
    for ag in agents:
        if ag.get("slug", "").lower() == sl:
            return ag.get("reports_to")
        for alias in ag.get("aliases", ()) or ():
            if str(alias).lower() == sl:
                return ag.get("reports_to")
    return None


def _log_reroute(sender, target, reason, body):
    line = (f"[go-reroute] sender={sender} director->{target} reason={reason} "
            f"ts={int(time.time())} body={ (body or '')[:120]!r}")
    print(line, file=sys.stderr, flush=True)
    try:
        logdir = os.environ.get("BAKER_GO_REROUTE_LOG_DIR") or os.path.join(
            os.path.expanduser("~"), ".brisen-lab")
        os.makedirs(logdir, exist_ok=True)
        with open(os.path.join(logdir, "go-reroute.log"), "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass  # logging is best-effort; never break the post


def main(argv):
    """CLI: go_reroute_gate.py <recipient> <body> <sender>.

    Prints the FINAL recipient slug to stdout (rerouted target, or the original
    recipient unchanged). bus_post.sh captures stdout as the recipient. Reroutes are
    logged to stderr + logfile. `cc lead` is inherent: every current rerouting seat
    reports to lead, so the reroute target IS lead; when a future seat reports to a
    non-lead superior the caller still cc's lead (bus_post.sh)."""
    if len(argv) < 4:
        # Missing args — fail safe (no reroute): echo the recipient unchanged.
        if len(argv) >= 2:
            print(argv[1])
        return 0
    recipient, body, sender = argv[1], argv[2], argv[3]
    disabled = _truthy(os.environ.get("BAKER_GO_REROUTE_DISABLED"))
    sup = resolve_reports_to(sender)
    target, reason = decide_reroute(recipient, body, sup, disabled=disabled)
    if target:
        _log_reroute(sender, target, reason, body)
        print(target)
    else:
        print(recipient)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
