// DASHBOARD_CARD_WORKSTATE_CLARITY_1 — pure glance-state resolver.
//
// The dot is the ONE work-state signal (the competing data-pending navy card
// chrome is retired). Priority (first match wins):
//   NEEDS_GO (highest) — latest assistant line asks Director "GO?".
//   WORKING          — fresh forge heartbeat (≤120s); suppresses NEW glow.
//   NEW              — unacked bus msg AND not working (keeps the App-agent glow).
//   UNKNOWN          — no telemetry ever for this alias (App agents: lead/Cowork
//                      emit no forge heartbeat) → NEVER assert IDLE or WORKING.
//   DONE             — just shipped (cardState green within GREEN_WINDOW).
//   IDLE             — telemetry-capable agent, no work, not just-shipped.
//
// Pure (no DOM, no globals) and dual-exported (browser global + CommonJS) so
// tests/test_glance_state_resolver.js can exercise it directly. Loaded via its
// own <script> before app.js, which reads it as a global.
function resolveGlanceState({ unacked, isWorking, hasTelemetry, isDoneGreen, needsGo }) {
  if (needsGo === true) return "NEEDS_GO";
  if (isWorking === true) return "WORKING";
  if (unacked > 0) return "NEW";
  if (!hasTelemetry) return "UNKNOWN";  // telemetry-UNKNOWN: never false IDLE
  return isDoneGreen ? "DONE" : "IDLE";
}

// COCKPIT_REVAMP_COLORS_1 (spec @d5e25efa item 3, Director-ratified 2026-07-19) —
// FINAL cockpit state palette. Pure row → one-of-six st-* class resolver.
//   st-running     bright green    is_working
//   st-go          bright blue     needs_go             (pulsating)
//   st-unread-old  bright red      unread > 600s
//   st-unread      muted amber     unread 0–600s        (from second zero)
//   st-offline     muted red       up but no signal     (pulsating)
//   st-idle        muted grey      everything else / not-started
// Precedence: running > GO > unread-old > unread > offline > idle — a working seat
// with unread mail reads running green; GO outranks unread; unread outranks offline.
// QUIET-WHEN-HEALTHY (spec item 7): a cleanly not-started seat (session down) stays
// muted grey, NOT offline-red — its Start button is the affordance; offline-red is
// reserved for a seat that is UP but silent (terminal down / no telemetry while
// expected up), which is the "no-signal + offline combined" case that needs eyes.
var UNREAD_OLD_S = 600; // >10 min unread flips muted-amber → bright red (named, not magic)
function resolveStateClass(row, sessionUp) {
  var r = row || {};
  if (r.is_working === true) return "st-running";
  if (r.needs_go === true) return "st-go";
  var unacked = Math.floor(Number(r.unacked_count)) || 0;
  if (unacked > 0) {
    var age = Number(r.oldest_unacked_age_sec) || 0;
    return age > UNREAD_OLD_S ? "st-unread-old" : "st-unread";
  }
  if (sessionUp === true && (r.ttyd_up === false || r.has_telemetry === false)) return "st-offline";
  return "st-idle";
}

// D5 amber-state predicate: a seat shows the AMBER "unread" card state when it
// has unacked bus messages and is NOT working (and not awaiting GO — needs_go
// owns the green state). This is exactly resolveGlanceState === "NEW", exposed
// as its own pure predicate so the cockpit and its tests can gate on it.
function amberState(row) {
  if (!row) return false;
  return resolveGlanceState({
    unacked: row.unacked_count || 0,
    isWorking: row.is_working === true,
    hasTelemetry: row.has_telemetry === true,
    isDoneGreen: false,
    needsGo: row.needs_go === true,
  }) === "NEW";
}

// GO delivers a bare Enter into the seat's tmux session. That is only safe when
// the seat is actually awaiting a GO ("GO?" confirmation) — otherwise Enter
// lands in a normal prompt. Every GO affordance (card face AND terminal panel)
// gates on this one predicate so the two can never drift apart again.
function goAffordanceVisible(row) {
  return !!(row && row.needs_go === true);
}

function formatUnreadAge(ageSeconds) {
  const seconds = Number(ageSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3_600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3_600)}h`;
  return `${Math.floor(seconds / 86_400)}d`;
}

function buildUnreadCopyPayload(alias, badge, rows = []) {
  const data = badge || {};
  const count = Math.floor(Number(data.unacked_count));
  if (!Number.isFinite(count) || count <= 0) return "";

  const oldest = formatUnreadAge(data.oldest_unacked_age_sec);
  const countLabel = count === 1 ? "message" : "messages";
  const lines = [
    `TO: ${String(alias)} — ${count} unacked bus ${countLabel}, oldest ${oldest}`,
  ];
  const messageRows = Array.isArray(rows) ? rows : [];
  if (messageRows.length > 0) {
    for (const row of messageRows) {
      const topic = String((row && row.topic) || "(no topic)");
      const age = String((row && row.age) || oldest);
      lines.push(`- ${topic} — ${age}`);
    }
  } else {
    const topics = Array.isArray(data.topics) ? data.topics : [];
    for (const topic of topics) {
      lines.push(`- ${String(topic || "(no topic)")} — ${oldest}`);
    }
  }
  lines.push(`Read /msg/${String(alias)} with the full unacked filter and act.`);
  return lines.join("\n");
}

if (typeof window !== "undefined") {
  window.resolveGlanceState = resolveGlanceState;
  window.resolveStateClass = resolveStateClass;
  window.UNREAD_OLD_S = UNREAD_OLD_S;
  window.goAffordanceVisible = goAffordanceVisible;
  window.amberState = amberState;
  window.formatUnreadAge = formatUnreadAge;
  window.buildUnreadCopyPayload = buildUnreadCopyPayload;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { resolveGlanceState, resolveStateClass, UNREAD_OLD_S, goAffordanceVisible, amberState, formatUnreadAge, buildUnreadCopyPayload };
}
