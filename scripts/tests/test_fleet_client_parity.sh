#!/usr/bin/env bash
# test_fleet_client_parity.sh — FLEET_DEPLOY_PARITY_1 Leg B regression suite.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHECKER="$ROOT/scripts/fleet_client_parity.sh"
PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); }
bad() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d -t fleet_client_parity.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

ORIGIN="$TMP/origin.git"
REPO="$TMP/repo"
git init -q --bare "$ORIGIN"
git init -q "$REPO"
git -C "$REPO" config user.email test@example.invalid
git -C "$REPO" config user.name parity-test
mkdir -p "$REPO/scripts"
cat > "$REPO/scripts/bus_post.sh" <<'SH'
#!/usr/bin/env bash
# CLIENT_STARTED_EMISSION_1
exit 0
SH
cat > "$REPO/scripts/arm_fleet_manifest.json" <<'JSON'
{
  "version": 1,
  "host_jobs": [],
  "client_scripts": [
    {
      "path": "scripts/bus_post.sh",
      "capability_marker": "CLIENT_STARTED_EMISSION_1",
      "distributed_to": ["test-seat"]
    }
  ]
}
JSON
chmod +x "$REPO/scripts/bus_post.sh"
git -C "$REPO" add scripts
git -C "$REPO" commit -q -m initial
git -C "$REPO" branch -M main
git -C "$REPO" remote add origin "$ORIGIN"
git -C "$REPO" push -q -u origin main
git -C "$REPO" fetch -q origin main

# Current checkout: CLEAN.
FLEET_CLIENT_REPO="$REPO" FLEET_CLIENT_MANIFEST="$REPO/scripts/arm_fleet_manifest.json" \
  FLEET_CLIENT_SKIP_FETCH=1 bash "$CHECKER" --no-fetch --capability-probe >"$TMP/clean.out" 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok || bad "current client copy returned rc=$rc"
grep -q '^CLEAN scripts/bus_post.sh$' "$TMP/clean.out" && ok || bad "current copy not CLEAN"

# A committed local pre-capability copy is stale against origin/main and should
# explain the capability failure in human terms.
printf '# stale pre-started client\n' > "$REPO/scripts/bus_post.sh"
git -C "$REPO" add scripts/bus_post.sh
git -C "$REPO" commit -q -m stale-client
FLEET_CLIENT_REPO="$REPO" FLEET_CLIENT_MANIFEST="$REPO/scripts/arm_fleet_manifest.json" \
  FLEET_CLIENT_SKIP_FETCH=1 bash "$CHECKER" --no-fetch --capability-probe >"$TMP/stale.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "stale client returned rc=0"
grep -q '^STALE scripts/bus_post.sh ' "$TMP/stale.out" && ok || bad "stale copy not reported"
grep -q 'missing the started-emit capability' "$TMP/stale.out" \
  && ok || bad "capability probe did not name started-emit"

# Roll-up: an unconfirmable seat is RED and blocks the aggregate.
FLEET_CLIENT_REPO="$REPO" FLEET_CLIENT_MANIFEST="$REPO/scripts/arm_fleet_manifest.json" \
  FLEET_CLIENT_SKIP_FETCH=1 bash "$CHECKER" --rollup --no-fetch \
  --manifest "$REPO/scripts/arm_fleet_manifest.json" \
  --seat missing="$TMP/does-not-exist" >"$TMP/rollup.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "unconfirmable seat roll-up returned rc=0"
grep -q '^RED missing missing-or-unreachable-seat-repository=' "$TMP/rollup.out" \
  && ok || bad "unconfirmable seat was not RED"

echo "fleet client parity tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
