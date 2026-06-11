#!/usr/bin/env bash
# Stop hook: ack RENDERED Brisen Lab bus messages for the current terminal's
# BAKER_ROLE slug at the end of every assistant turn.
#
# Canonical source: tests/fixtures/stop-bus-ack.sh in baker-master.
# Deployed as user-global at ~/.claude/hooks/stop-bus-ack.sh. Drift detectable:
#   diff ~/.claude/hooks/stop-bus-ack.sh tests/fixtures/stop-bus-ack.sh
#
# V2 — ACK-ONLY-WHAT-RENDERS (2026-06-11, PINNED §OPEN-2 fix):
# V1 acked ALL unacked messages (up to 60) at turn end, including messages the
# agent never saw — the session-start drain renders at most RENDER_CAP=30, and
# mid-session arrivals are never auto-rendered. Result 2026-06-10: 6 ship
# reports auto-acked unseen; badge looked clean; reports nearly lost.
#
# V2 contract: ack ONLY message ids present in the rendered-ID ledger
# ~/.brisen-lab-bus-rendered-<slug>.txt, written by:
#   - session-start-bus-drain.sh (ids it emits into additionalContext), and
#   - check-<slug>-inbox.sh poll scripts (ids they print to the agent).
# Unrendered messages stay UNACKED — the daemon badge stays a true "you have
# unread work" signal. Manual raw-curl reads are NOT ledgered: the agent acks
# those itself per the ack-on-read hard rule (fleet-wide, 2026-06-11, 874eb38).
#
# Ledger lifecycle: append-only by writers; this hook prunes ids that are no
# longer unacked (acked here, acked manually, or expired) and caps the file at
# the newest 500 ids. Fetch failure → ledger untouched, retry next turn.
#
# Contract: never block turn end. Exit 0 on every path. Bounded wall-clock
# (~4s fetch + parallel acks) to stay well under the Stop-hook timeout.

# Drain stdin (Claude passes JSON; we don't consume it).
cat >/dev/null 2>&1 || true

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"

# --- resolve sender slug from BAKER_ROLE ---
#
# SCOPE: ORCHESTRATOR ROLES ONLY (lead / deputy / cowork-ah1). These drain the
# bus every session, so auto-acking rendered messages at turn-end keeps their
# badge a true signal.
#
# B-CODES / DESKS / WORKERS ARE DELIBERATELY EXCLUDED. They CONSUME dispatches by
# reading their UNACKED inbox — auto-acking would clear a dispatch from their view
# before they claim it. Regression caught 2026-06-03: this hook (then user-global,
# all-roles) acked b1's incoming dispatch at b1's turn-end, making b1's bus look
# "clean" and reinforcing a false "idle / no pending work" conclusion. A b-code
# acks a dispatch only when IT claims the work, never automatically.
case "${BAKER_ROLE:-}" in
    AH1|aihead1|lead|LEAD)              SLUG=lead ;;
    AH1-APP|cowork-ah1|COWORK-AH1)      SLUG=cowork-ah1 ;;
    AH2|aihead2|deputy|DEPUTY)          SLUG=deputy ;;
    *)
        # B-codes, desks, workers, architect, researcher, cortex, aid, or no
        # BAKER_ROLE → silent no-op. They are NOT auto-acked (see SCOPE above).
        exit 0
        ;;
esac

LEDGER_FILE="${HOME}/.brisen-lab-bus-rendered-${SLUG}.txt"

# Fast path: no ledger → nothing was rendered → ack nothing.
[ -s "$LEDGER_FILE" ] || exit 0

# --- fetch terminal key from 1Password ---
KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SLUG}/credential" 2>/dev/null)"
if [ -z "$KEY" ]; then
    exit 0
fi

# --- ack ledgered ids that are still unacked; prune ledger (parallel, bounded) ---
DAEMON_URL="$DAEMON_URL" SLUG="$SLUG" KEY="$KEY" LEDGER_FILE="$LEDGER_FILE" python3 -c '
import json, os, sys, tempfile, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

daemon = os.environ["DAEMON_URL"]
slug = os.environ["SLUG"]
key = os.environ["KEY"]
ledger_file = os.environ["LEDGER_FILE"]
hdr = {"X-Terminal-Key": key}

# Read rendered-ID ledger (dedup, preserve order).
try:
    with open(ledger_file) as f:
        raw = [ln.strip() for ln in f]
except OSError:
    sys.exit(0)
seen = set()
ledger_ids = []
for s in raw:
    if s.isdigit() and int(s) not in seen:
        seen.add(int(s))
        ledger_ids.append(int(s))
if not ledger_ids:
    sys.exit(0)

# GET inbox (unread filter + generous limit). The daemon ignores order params and
# caps server-side; we client-filter on acknowledged_at to find true unacked.
url = "{}/msg/{}?unread=true&limit=2000".format(daemon, slug)
try:
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=4) as r:
        data = json.loads(r.read().decode())
except Exception:
    sys.exit(0)  # fetch failed -> ledger untouched, retry next turn

msgs = data if isinstance(data, list) else data.get("messages", data.get("events", []))
unacked_ids = {m["id"] for m in msgs if isinstance(m, dict) and m.get("id") is not None
               and not m.get("acknowledged_at")}

# Ack ONLY rendered ids that are still unacked. Bound: 60 per turn.
to_ack = [i for i in ledger_ids if i in unacked_ids][:60]

acked_ok = set()
def ack(mid):
    try:
        req = urllib.request.Request("{}/msg/{}/ack".format(daemon, mid),
                                     headers=hdr, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=3) as r:
            if r.status == 200:
                acked_ok.add(mid)
    except Exception:
        pass

if to_ack:
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(ack, to_ack))

# Prune ledger: keep only ids still unacked after this run (ack failed or
# beyond the 60-bound). Ids already acked (here or elsewhere) drop out.
remaining = [i for i in ledger_ids if i in unacked_ids and i not in acked_ok][-500:]
try:
    state_dir = os.path.dirname(ledger_file) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".brisen-lab-bus-rendered-tmp-", dir=state_dir)
    with os.fdopen(fd, "w") as f:
        f.write("".join("{}\n".format(i) for i in remaining))
    os.replace(tmp_path, ledger_file)
except OSError:
    pass  # stale ledger re-prunes next turn; acks are idempotent
' 2>/dev/null || true

exit 0
