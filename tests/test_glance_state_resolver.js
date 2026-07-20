// Resolver truth-table for glance_state.js resolveStateClass — the FINAL 6-state
// cockpit palette (COCKPIT_REVAMP_COLORS_HEADER_COPY_1, spec @d5e25efa item 3).
//
// No JS test runner is wired in this repo (pytest-only CI), so this is a
// self-contained node assert file — run with:  node tests/test_glance_state_resolver.js
// Exercises the REAL exported resolver (CommonJS export) so the vectors can never
// drift from the shipped logic. Exit 0 = all pass, non-zero = failure.
//
// Anchor: codex FAIL #13327 P1 — has_telemetry===null on a LIVE seat must resolve
// st-offline (no-signal), not st-idle. Vector T-P1 locks that.
const assert = require("assert");
const { resolveStateClass, UNREAD_OLD_S } = require("../scripts/cockpit_static/glance_state.js");

assert.strictEqual(UNREAD_OLD_S, 600, "UNREAD_OLD_S must be the named 600s threshold");

// [name, row, sessionUp, expected]
const VECTORS = [
  // precedence: running > GO > unread-old > unread > offline > idle
  ["running", { is_working: true, has_telemetry: true }, true, "st-running"],
  ["running beats GO", { is_working: true, needs_go: true }, true, "st-running"],
  ["running beats unread", { is_working: true, unacked_count: 5, oldest_unacked_age_sec: 900 }, true, "st-running"],
  ["GO", { needs_go: true, has_telemetry: true }, true, "st-go"],
  ["GO beats unread", { needs_go: true, unacked_count: 3, oldest_unacked_age_sec: 900 }, true, "st-go"],
  ["unread fresh", { unacked_count: 1, oldest_unacked_age_sec: 120, has_telemetry: true }, true, "st-unread"],
  ["unread from second zero", { unacked_count: 1, oldest_unacked_age_sec: 0, has_telemetry: true }, true, "st-unread"],
  ["unread at 600s boundary is still fresh", { unacked_count: 1, oldest_unacked_age_sec: 600, has_telemetry: true }, true, "st-unread"],
  ["unread old >600s", { unacked_count: 1, oldest_unacked_age_sec: 601, has_telemetry: true }, true, "st-unread-old"],
  ["unread outranks offline", { unacked_count: 1, oldest_unacked_age_sec: 100, ttyd_up: false }, true, "st-unread"],
  ["offline — terminal down", { ttyd_up: false, has_telemetry: true }, true, "st-offline"],
  ["offline — telemetry explicitly false", { has_telemetry: false }, true, "st-offline"],
  // codex FAIL #13327 P1 — the load-bearing regression vector.
  ["T-P1 offline — telemetry null on a live seat", { has_telemetry: null, ttyd_up: true }, true, "st-offline"],
  ["offline — telemetry missing on a live seat", {}, true, "st-offline"],
  ["idle — up, telemetry present, quiet", { has_telemetry: true }, true, "st-idle"],
  // QUIET-WHEN-HEALTHY: a not-started (session-down) seat stays grey, never offline.
  ["not-started — session down, quiet grey", {}, false, "st-idle"],
  ["not-started — down even without telemetry stays idle", { has_telemetry: false }, false, "st-idle"],
  ["null row → idle", null, false, "st-idle"],
];

let failures = 0;
for (const [name, row, up, expected] of VECTORS) {
  const got = resolveStateClass(row, up);
  try {
    assert.strictEqual(got, expected);
    console.log(`  ok   ${name} → ${got}`);
  } catch (_e) {
    failures++;
    console.error(`  FAIL ${name}: expected ${expected}, got ${got}`);
  }
}

if (failures) {
  console.error(`\n${failures}/${VECTORS.length} resolver vectors FAILED`);
  process.exit(1);
}
console.log(`\nall ${VECTORS.length} resolver vectors passed`);
