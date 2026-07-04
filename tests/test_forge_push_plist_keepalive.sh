#!/usr/bin/env bash
# BRISEN_LAB_FORGE_TELEMETRY_DURABILITY_1 (T3) — assert the forge-snapshot-push
# launchd plist template carries the self-resume keys, so a reboot/login/crash
# never leaves the pusher silently dead (outage 2026-07-04). AC5 asserts plist
# keys; the live reboot test is lead's. Substitution (__FORGE_KEY__ /
# __WORKER_PATH__) does not touch these keys, so asserting on the template is
# faithful to what launchctl loads. Uses plistlib so we validate parsed values,
# not brittle text matches.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$REPO_ROOT/scripts/launchd/com.baker.forge-snapshot-push.plist"

[[ -f "$PLIST" ]] || { echo "FAIL: plist template missing at $PLIST" >&2; exit 1; }

python3 - "$PLIST" <<'PY'
import plistlib, sys

with open(sys.argv[1], "rb") as fh:
    pl = plistlib.load(fh)

# Case 1 — RunAtLoad true (resume on reboot/login once loaded).
assert pl.get("RunAtLoad") is True, f"RunAtLoad must be True, got {pl.get('RunAtLoad')!r}"
print("PASS: Case 1 — RunAtLoad is True.")

# Case 2 — KeepAlive present + truthy (resume on crash). Accept either the literal
# `true` (brief-specified) or the crash-only dict form {SuccessfulExit: False}
# (the flagged StartInterval-preserving alternative) — both self-resume.
ka = pl.get("KeepAlive")
if ka is True:
    print("PASS: Case 2 — KeepAlive is True (continuous self-resume).")
elif isinstance(ka, dict) and ka.get("SuccessfulExit") is False:
    print("PASS: Case 2 — KeepAlive is crash-only {SuccessfulExit: False}.")
else:
    print(f"FAIL: Case 2 — KeepAlive must self-resume, got {ka!r}", file=sys.stderr)
    sys.exit(1)

# Case 3 — Label + program args intact (didn't corrupt the template).
assert pl.get("Label") == "com.baker.forge-snapshot-push", "Label drifted"
assert pl.get("ProgramArguments"), "ProgramArguments missing"
print("PASS: Case 3 — Label + ProgramArguments intact.")
PY

echo "ALL PASS: forge-push plist self-resume keys present."
