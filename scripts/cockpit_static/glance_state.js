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
// reserved for a seat that is UP but silent, which is the "no-signal + offline
// combined" case that needs eyes: terminal down (ttyd_up===false) OR no telemetry
// signal at all (has_telemetry is anything other than an explicit true — false,
// null, or missing) while the session is up.
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
  // up-but-silent → offline. has_telemetry must be an explicit true to read idle;
  // null / undefined / false is a live-seat no-signal and resolves offline (pulse).
  if (sessionUp === true && (r.ttyd_up === false || r.has_telemetry !== true)) return "st-offline";
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

// COCKPIT_DRAWER_COPY_BUTTON_FIX_1 — reconcile the unacked rows the cockpit panel
// RENDERS (and the Copy buttons COPY) from the two bus surfaces so they can never
// diverge:
//   • /api/agents   → row.unacked_messages (status shape; can be lean/empty even
//                     when unacked_count > 0 — the "status-only hydration" shape).
//   • /api/messages → per-id detail rows (authenticated; carry body_preview).
// Rules:
//   1. Prefer row.unacked_messages.
//   2. If it is empty but unacked_count > 0, fall back to the already-fetched
//      detail rows still flagged unacked (acked === false) — the messages ARE
//      there, just not in the status payload. Callers pass the IN-MEMORY detail
//      list, so this never refetches and still yields rows / a stable placeholder
//      while /api/messages is unavailable (bus degraded).
//   3. Enrich every returned row with the matching detail's body_preview, so Copy
//      emits id + from + topic + body preview and the render + copy paths share one
//      source. Pure: no DOM, no fetch, no globals.
function reconcileUnacked(row, details) {
  var r = row || {};
  var detailList = Array.isArray(details) ? details : [];
  var byId = {};
  for (var i = 0; i < detailList.length; i++) {
    var d = detailList[i];
    if (d && d.id !== undefined && d.id !== null) byId[String(d.id)] = d;
  }
  var base = Array.isArray(r.unacked_messages) ? r.unacked_messages : [];
  var count = Math.floor(Number(r.unacked_count)) || 0;
  if (!base.length && count > 0) {
    base = detailList.filter(function (d) { return d && d.acked === false; });
  }
  return base.map(function (m) {
    var m0 = m || {};
    var id = m0.id !== undefined && m0.id !== null ? String(m0.id) : null;
    var detail = id && byId[id] ? byId[id] : null;
    var preview = m0.body_preview || (detail && detail.body_preview) || "";
    return {
      id: m0.id !== undefined ? m0.id : (detail ? detail.id : undefined),
      topic: m0.topic || (detail && detail.topic) || null,
      from_terminal: m0.from_terminal || (detail && detail.from_terminal) || null,
      created_at: m0.created_at || (detail && detail.created_at) || null,
      body_preview: preview,
    };
  });
}

// Shared `#id  topic  from` + body-preview formatter — the ONE source of truth for
// both the card message-panel Copy and the terminal-drawer Copy. Emits the full
// rendered row (id + from + topic + body preview) as plain text, and the
// placeholder ONLY when there are genuinely no unacked rows. Pure.
function formatUnackedSummary(title, rows) {
  var list = Array.isArray(rows) ? rows : [];
  var lines = list.map(function (m) {
    var m0 = m || {};
    var head = "#" + String(m0.id !== undefined && m0.id !== null ? m0.id : "?") +
      "  " + String(m0.topic || "(no topic)") +
      "  from " + String(m0.from_terminal || "?");
    var preview = m0.body_preview ? "\n    " + String(m0.body_preview) : "";
    return head + preview;
  });
  return String(title || "") + "\n" +
    (lines.length ? lines.join("\n") : "(no unacknowledged messages)");
}

if (typeof window !== "undefined") {
  window.resolveGlanceState = resolveGlanceState;
  window.resolveStateClass = resolveStateClass;
  window.UNREAD_OLD_S = UNREAD_OLD_S;
  window.goAffordanceVisible = goAffordanceVisible;
  window.amberState = amberState;
  window.formatUnreadAge = formatUnreadAge;
  window.buildUnreadCopyPayload = buildUnreadCopyPayload;
  window.reconcileUnacked = reconcileUnacked;
  window.formatUnackedSummary = formatUnackedSummary;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { resolveGlanceState, resolveStateClass, UNREAD_OLD_S, goAffordanceVisible, amberState, formatUnreadAge, buildUnreadCopyPayload, reconcileUnacked, formatUnackedSummary };
}
