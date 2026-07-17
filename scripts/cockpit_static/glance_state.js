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
  window.formatUnreadAge = formatUnreadAge;
  window.buildUnreadCopyPayload = buildUnreadCopyPayload;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { resolveGlanceState, formatUnreadAge, buildUnreadCopyPayload };
}
