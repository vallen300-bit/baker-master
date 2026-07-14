#!/usr/bin/env bash
# test_arm_fleet_parity.sh — FLEET_DEPLOY_PARITY_1 Leg A manifest sweep tests.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SWEEP="$ROOT/scripts/arm_fleet_parity.sh"
PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); }
bad() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d -t arm_fleet_parity.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/missing.json" <<'JSON'
{
  "version": 1,
  "host_jobs": [
    {
      "job_label": "com.example.expected",
      "installer": "scripts/installer-that-is-not-installed.sh",
      "worker_src": "scripts/worker-that-is-not-installed.sh",
      "deploy_dir_env": "EXAMPLE_DEPLOY_DIR",
      "expected_interval_s": 60,
      "host_role": "test"
    }
  ],
  "client_scripts": []
}
JSON

bash "$SWEEP" --manifest "$TMP/missing.json" >"$TMP/missing.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "missing manifest job returned rc=0"
grep -q '^RED com.example.expected NOT-INSTALLED installer-missing=' "$TMP/missing.out" \
  && ok || bad "missing manifest job was skipped or not RED"

# Semantic installer uses the same worker/plist parity seam.
SEM_DEPLOY="$TMP/semantic-deploy"
SEM_HOME="$TMP/semantic-home"
SEM_MARKER="$TMP/semantic-marker"
ARM_SEMANTIC_DRYRUN=1 ARM_SEMANTIC_DEPLOY_DIR="$SEM_DEPLOY" \
  ARM_SEMANTIC_MARKER_DIR="$SEM_MARKER" bash "$ROOT/scripts/install_arm_semantic_job.sh" >/dev/null 2>&1
printf '{"schema":"semantic_delivery_verdict_v1","evaluated_at":"%s","semantic_ok":true}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SEM_MARKER/semantic.json"
mkdir -p "$SEM_HOME/Library/LaunchAgents" "$TMP/bin"
cat > "$TMP/bin/launchctl" <<'SH'
#!/usr/bin/env bash
printf '123 0 com.baker.arm-semantic\n'
SH
chmod +x "$TMP/bin/launchctl"
python3 - "$ROOT/scripts/launchd/com.baker.arm-semantic.plist" \
  "$SEM_DEPLOY/arm_semantic_poll.sh" \
  "$SEM_HOME/Library/LaunchAgents/com.baker.arm-semantic.plist" <<'PY'
import sys
tpl, worker, out = sys.argv[1:]
body = open(tpl).read()
for old, new in (
    ("__WORKER_PATH__", worker),
    ("__LABEL__", "com.baker.arm-semantic"),
    ("__CADENCE__", "1800"),
    ("__LOG__", "/tmp/arm-semantic.log"),
    ("__ERRLOG__", "/tmp/arm-semantic.err.log"),
    ("__MARKER_DIR__", "/tmp/semantic-marker"),
    ("__SEAT__", "arm"),
    ("__SEMANTIC_LOG__", "/tmp/semantic.log"),
    ("__KEY__", "test-key"),
):
    body = body.replace(old, new)
open(out, "w").write(body)
PY
PATH="$TMP/bin:$PATH" HOME="$SEM_HOME" ARM_SEMANTIC_DEPLOY_DIR="$SEM_DEPLOY" \
  ARM_SEMANTIC_MARKER_DIR="$SEM_MARKER" bash "$ROOT/scripts/install_arm_semantic_job.sh" --check \
  >"$TMP/semantic-clean.out" 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok || bad "current semantic worker parity did not pass"
grep -q 'RESULT: CLEAN' "$TMP/semantic-clean.out" && ok || bad "semantic parity CLEAN missing"
printf '\n# deliberate parity drift\n' >> "$SEM_DEPLOY/arm_semantic_poll.sh"
PATH="$TMP/bin:$PATH" HOME="$SEM_HOME" ARM_SEMANTIC_DEPLOY_DIR="$SEM_DEPLOY" \
  ARM_SEMANTIC_MARKER_DIR="$SEM_MARKER" bash "$ROOT/scripts/install_arm_semantic_job.sh" --check \
  >"$TMP/semantic-drift.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "semantic worker parity drift returned 0"
grep -q 'deployed worker drifted from repo source' "$TMP/semantic-drift.out" \
  && ok || bad "semantic parity failure not named"

python3 -m json.tool "$ROOT/scripts/arm_fleet_manifest.json" >/dev/null \
  && ok || bad "canonical fleet manifest is invalid JSON"
bash -n "$SWEEP" "$ROOT/scripts/arm_alarm_drift_check.sh" \
  "$ROOT/scripts/arm_cadence_drift_check.sh" && ok || bad "fleet sweep scripts do not parse"

echo "arm fleet parity tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
