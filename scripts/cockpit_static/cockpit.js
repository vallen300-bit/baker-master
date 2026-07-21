/* Baker Cockpit — LAB_COCKPIT_PAGE_1.
 *
 * Data model: a generated static layout (cockpit_layout.json — plates + card
 * metadata, mirrors the live Control Room) merged by slug with the controller's
 * live GET /api/agents (session + glance state). Driveable seats open an
 * on-demand iframe to /term/<slug>/ (same origin — one Basic-auth prompt per
 * browser session). Non-driveable active seats (app-*, service, headless) are status-only (no terminal). GO sends
 * Enter to the seat's tmux session; Start (re)creates a downed seat's session.
 *
 * Interaction contract: COCKPIT_CARD_BEHAVIOR_MOCK.html. Row colors: the FINAL
 * 6-state palette (spec @d5e25efa item 3) via glance_state.js resolveStateClass
 * (precedence running > GO > unread-old > unread > offline > idle). GO affordance:
 * §5.4. All card content is built via textContent / DOM nodes — no innerHTML, so
 * agent-supplied strings can never inject markup.
 */
(() => {
  "use strict";

  const POLL_MS = 4000;
  const POLL_TIMEOUT_MS = 10000;
  const LAYOUT_RETRY_DELAYS_MS = [1500, 4000];
  const LAYOUT_TIMEOUT_MS = 8000;
  const LAYOUT_SELF_HEAL_MS = 60000;
  const FETCH_OPTS = { credentials: "same-origin", cache: "no-store" };
  // location.origin has NO userinfo, so building request URLs from it avoids
  // "Request cannot be constructed from a URL that includes credentials" when
  // the page itself was opened with credentials embedded in the URL.
  // COCKPIT_IN_LAB_BRIDGE_1 (lead ruling #12577, Option A): when this page is
  // proxied inside Brisen Lab under /cockpit/, the Lab injects
  // window.__COCKPIT_BASE__ = location.origin + "/cockpit" so every url() below
  // resolves under the prefix. Local (127.0.0.1:7800) serving leaves it unset, so
  // BASE falls back to location.origin unchanged — the local page is unaffected.
  const BASE = (typeof window !== "undefined" && window.__COCKPIT_BASE__) || location.origin;
  const url = (p) => BASE + (p.charAt(0) === "/" ? p : "/" + p);

  const gridEl = document.getElementById("grid");
  // LAB_UNIFY_THEME_COCKPIT_EXTENSION_1: the top-right #conn health line was
  // removed (Director 2026-07-21); its live/offline signal now renders into the
  // #sync-note surface next to FLEET COCKPIT (see renderSummary).
  // COCKPIT_REVAMP_SPLIT_VIEW_SIDEBAR_1: the terminal is a right-hand pane inside
  // the three-column app shell (no #veil modal). Opening a seat toggles
  // `.pane-open` on the shell, which widens the pane column; the grid stays live.
  const appShellEl = document.getElementById("appShell");
  const sidebarEl = document.getElementById("sidebar");
  const termEl = document.getElementById("term");
  const termMount = document.getElementById("term-mount");
  const termTitle = document.getElementById("term-title");
  const termGo = document.getElementById("term-go");
  const termUnacked = document.getElementById("term-unacked");
  const toastEl = document.getElementById("toast");
  const termCopy = document.getElementById("term-copy");
  const termNudge = document.getElementById("term-nudge");
  const syncNoteEl = document.getElementById("sync-note");
  const rosterNoteEl = document.getElementById("roster-note");
  // D9 — App-resident card bus-message panel.
  const msgVeil = document.getElementById("msgveil");
  const msgPanel = document.getElementById("msgpanel");
  const msgBody = document.getElementById("msg-body");
  const msgTitle = document.getElementById("msg-title");
  const msgCopy = document.getElementById("msg-copy");

  let layout = null;             // { plates: [{label, cards:[...]}, ...] }
  let stateBySlug = new Map();   // slug -> live /api/agents row
  let openSlug = null;           // currently open terminal, or null
  let openName = null;           // display name of the open seat (for the drawer nudge)
  let openMsgSlug = null;        // currently open bus-message panel, or null (D9)
  let messageDetailsBySlug = new Map(); // slug -> message id -> authenticated preview
  let prevUnacked = new Map();   // slug -> last-seen unacked_count (D9 flash-on-new)
  let flashSlugs = new Set();    // slugs whose unacked count rose this poll (D9)
  let pollTimer = null;
  let pollInFlight = null;
  let bootInFlight = null;
  let bootReady = false;
  let layoutHealTimer = null;

  // ---- sidebar view state (COCKPIT_REVAMP_SPLIT_VIEW_SIDEBAR_1, spec item 5) ----
  // Sidebar entries in order. ACTIVE is the default home; ALL is the flat view;
  // the rest are the six operating-role groups in plain words. Reserved for future
  // buttons — nothing else is added here now (candidates parked in the spec).
  const NAV_ORDER = ["ACTIVE", "ALL", "Pilots", "Control Tower", "Engineering",
                     "Support", "Legal/Finance", "Interns"];
  // History (revamp items 8+9) is a distinct bus-derived job/verdict MODE, not a
  // plate-group filter — so it lives OUTSIDE NAV_ORDER (which stays the 8 plate
  // views) and is appended to the sidebar via SIDEBAR_ORDER. It swaps the middle
  // column rather than filtering the grid.
  const HISTORY_VIEW = "History";
  const SIDEBAR_ORDER = NAV_ORDER.concat([HISTORY_VIEW]);
  // Two-letter abbreviations shown when the sidebar collapses to icons on narrow
  // screens (spec item 5 — CSS media query + hover expansion, no JS breakpoints).
  const NAV_ABBR = { "ACTIVE": "AC", "ALL": "ALL", "Pilots": "Pi", "Control Tower": "CT",
                     "Engineering": "En", "Support": "Su", "Legal/Finance": "LF", "Interns": "In",
                     "History": "Hi" };
  // The ONE plate-label → nav-name mapping (spec item 5). Fail-soft: an unknown
  // plate falls back to its raw label so a new plate is never silently dropped.
  const PLATE_TO_NAV = {
    "PILOTS & PILOT TEAMS": "Pilots",
    "Control Tower & VERIFICATION": "Control Tower",
    "ENGINEERING , TECHNICAL & STAFF MANAGEMENT": "Engineering",
    "FLIGHTS SUPPORT & DOMAIN SPECIFIC": "Support",
    "LEGAL ,FINANCIAL , PR, MARKETING & COMMUNICATIONS": "Legal/Finance",
    "INTERNS": "Interns",
  };
  const VIEW_KEY = "cockpit.view";        // persisted across sessions (spec item 5.4)
  let currentView = readStoredView();     // hydrate on load, default ACTIVE
  let expandedGroups = new Set();          // ACTIVE-view groups whose "N quiet" line is expanded

  // ---- History view state (revamp items 8+9) ------------------------------
  // The History view fetches lead's Lab job stream on its OWN 15s cadence (NOT
  // the 4s /api/agents poll) and owns the middle column while active.
  const HISTORY_REFRESH_MS = 15000;
  let historyTimer = null;
  let historyJobs = [];
  let historyStale = false;
  let historyLoaded = false;
  let expandedHistory = new Set();         // job keys expanded inline
  let pendingScrollKey = null;             // job key to scroll into view next paint

  function readStoredView() {
    try {
      const v = localStorage.getItem(VIEW_KEY);
      if (v && SIDEBAR_ORDER.indexOf(v) !== -1) return v;
    } catch (_) { /* storage blocked — fall through to default */ }
    return "ACTIVE";
  }

  // ---- helpers ------------------------------------------------------------
  function el(tag, attrs = {}, children = []) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) n.setAttribute(k, v);
    }
    for (const c of [].concat(children)) if (c) n.appendChild(c);
    return n;
  }

  function messageDetailFor(slug, message) {
    const details = messageDetailsBySlug.get(slug);
    if (!details || !message || message.id === undefined || message.id === null) {
      return null;
    }
    return details.get(String(message.id)) || null;
  }

  function mergeMessageDetails(slug, rows) {
    const details = new Map();
    for (const row of rows || []) {
      if (row && row.id !== undefined && row.id !== null) {
        details.set(String(row.id), row);
      }
    }
    messageDetailsBySlug.set(slug, details);
  }

  async function fetchMessageDetails(slug) {
    try {
      const r = await fetch(url("/api/messages/" + encodeURIComponent(slug)), FETCH_OPTS);
      if (!r.ok) return;
      const data = await r.json();
      if (data && data.available === true && Array.isArray(data.messages)) {
        mergeMessageDetails(slug, data.messages);
        if (openMsgSlug === slug) renderMsgSummary(slug);
        if (openSlug === slug) renderPanelUnacked(slug);
      }
    } catch (_) {
      // Envelope-only rendering is the intentional Lab-outage fallback.
    }
  }

  let toastTimer = null;
  function toast(msg, kind = "") {
    clearTimeout(toastTimer);
    toastEl.textContent = msg;
    toastEl.className = kind;
    toastEl.hidden = false;
    void toastEl.offsetWidth;      // reflow so the transition fires
    toastEl.classList.add("show");
    toastTimer = setTimeout(() => {
      toastEl.classList.remove("show");
      setTimeout(() => { toastEl.hidden = true; }, 220);
    }, 2600);
  }

  // COCKPIT_REVAMP_COLORS_1 — the row's glance color is the FINAL 6-state palette
  // (spec item 3), resolved by the pure glance_state.js resolver so JS and its
  // tests share one source of truth. Returns one st-* class; the CSS owns the color.
  function glanceClass(row, up) {
    return (window.resolveStateClass || (() => "st-idle"))(row, up === true);
  }

  function ageClass(sec) {
    if (sec >= 1800) return "age hot";     // >30 min
    if (sec >= 600) return "age warn";     // >10 min
    return "age";
  }

  function totalCardCount() {
    if (!layout) return 0;
    return layout.plates.reduce((n, p) => n + p.cards.length, 0);
  }

  // The single health line next to FLEET COCKPIT (#sync-note). It ABSORBS the
  // removed top-right #conn (Director 2026-07-21): green with the driveable/seat
  // count while the feed is live, RED (.feed-dead) when the feed is dead, amber
  // (.is-warn) when the feed answered but Lab telemetry is degraded. `health`
  // (when provided by poll) = { live, driveable, total, error }.
  // The health line is now sticky: renderSummary is also called args-less from
  // view/render refreshes (below), and those must NOT wipe the migrated live/
  // offline state. Remember the latest poll probe and reuse it when not passed one.
  let lastHealth = null;
  let lastLabOk = null;
  function renderSummary(labOk = null, health = null) {
    if (!layout) return;
    if (labOk !== null) lastLabOk = labOk; else labOk = lastLabOk;
    if (health !== null) lastHealth = health; else health = lastHealth;
    const cards = layout.plates.flatMap((plate) => plate.cards);
    if (rosterNoteEl) rosterNoteEl.textContent = cards.length + " seats · grouped by operating role";
    if (!syncNoteEl) return;
    if (health && health.live === false) {
      // Feed dead — the ONE health line turns red (migrated .feed-dead semantics).
      syncNoteEl.textContent = "Feed offline — " + (health.error || "unreachable");
      syncNoteEl.className = "summary-status feed-dead";
    } else if (health && health.live === true) {
      // Feed live — the line stays GREEN whenever the feed answers (the original
      // #conn contract: red is reserved for a dead feed). Degraded Lab telemetry
      // (feed answered but lab_glance_ok=false) is surfaced in TEXT, not color, so
      // that signal is not lost with #conn's removal without breaking green=live.
      const bits = "Live · " + health.driveable + " with terminal / " + health.total + " seats";
      syncNoteEl.textContent = labOk === false ? bits + " · telemetry source degraded" : bits;
      syncNoteEl.className = "summary-status";
    } else {
      // No health probe yet (first paint from layout metadata).
      syncNoteEl.textContent = labOk === false ? "Telemetry source offline" :
        (stateBySlug.size ? "Live · refreshed just now" : "Waiting for telemetry");
      syncNoteEl.className = "summary-status" + (labOk === false ? " is-warn" : "");
    }
  }

  // ---- network ------------------------------------------------------------
  async function post(path, label) {
    try {
      const r = await fetch(url(path), { ...FETCH_OPTS, method: "POST" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      toast(label + " ✓", "ok");
      return true;
    } catch (e) {
      toast(label + " failed — " + e.message, "err");
      return false;
    }
  }

  async function fetchWithTimeout(requestUrl, options, timeoutMs, consumeResponse = null) {
    const controller = new AbortController();
    let timedOut = false;
    let timeoutId = null;
    const timeoutPromise = new Promise((_, reject) => {
      timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
        reject(new Error("request timed out after " + timeoutMs + "ms"));
      }, timeoutMs);
    });
    try {
      const requestPromise = fetch(
        requestUrl,
        { ...options, signal: controller.signal },
      ).then((response) => (
        consumeResponse ? consumeResponse(response) : response
      ));
      return await Promise.race([requestPromise, timeoutPromise]);
    } catch (e) {
      if (timedOut) throw new Error("request timed out after " + timeoutMs + "ms");
      throw e;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  function setLayoutStatus(text) {
    if (!syncNoteEl) return;
    syncNoteEl.textContent = text;
    syncNoteEl.className = "summary-status feed-dead";
  }

  async function loadLayoutWithRetry() {
    const maxAttempts = LAYOUT_RETRY_DELAYS_MS.length + 1;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const data = await fetchWithTimeout(
          url("/cockpit_layout.json"),
          FETCH_OPTS,
          LAYOUT_TIMEOUT_MS,
          async (response) => {
            if (!response.ok) throw new Error("layout HTTP " + response.status);
            return response.json();
          },
        );
        return data;
      } catch (e) {
        if (attempt === maxAttempts - 1) throw e;
        setLayoutStatus("Layout load failed — retrying");
        await new Promise((resolve) => setTimeout(
          resolve,
          LAYOUT_RETRY_DELAYS_MS[attempt],
        ));
      }
    }
    throw new Error("layout retry exhausted");
  }

  function clearLayoutSelfHeal() {
    if (layoutHealTimer !== null) {
      clearInterval(layoutHealTimer);
      layoutHealTimer = null;
    }
  }

  function scheduleLayoutSelfHeal() {
    if (layoutHealTimer !== null) return;
    layoutHealTimer = setInterval(() => {
      if (document.visibilityState === "visible" && !bootReady) void boot();
    }, LAYOUT_SELF_HEAL_MS);
  }

  function poll() {
    // A hung fetch must not wedge boot or stack interval requests behind it.
    if (pollInFlight) return pollInFlight;
    pollInFlight = (async () => {
      try {
        const data = await fetchWithTimeout(
          url("/api/agents"),
          FETCH_OPTS,
          POLL_TIMEOUT_MS,
          async (response) => {
            if (!response.ok) throw new Error("HTTP " + response.status);
            return response.json();
          },
        );
        const m = new Map();
        for (const a of (data.agents || [])) m.set(a.slug, a);
        computeFlash(m);              // D9 — flag cards whose unacked count rose
        stateBySlug = m;
        // lab_glance_ok=false ⇒ the Lab telemetry source is down; the summary
        // sync-note surfaces that (renderSummary below). It does NOT dim the header
        // health line: the feed itself answered, so the line stays GREEN (spec item
        // 6 — green whenever the feed is live, red ONLY when the feed is dead).
        const labOk = data.lab_glance_ok !== false;
        const total = totalCardCount();
        // Header health line — plain words, all bright green while the feed is live
        // (spec item 6 / codex #13356: no warn state). Count = layout driveable cards
        // (codex #13286: /api/agents now hydrates ALL cards, so m.size ≠ terminals).
        const driveable = layout
          ? layout.plates.reduce((n, plate) =>
              n + plate.cards.filter((card) => card.driveable).length, 0)
          : 0;
        // Health line (migrated from #conn) renders through the single owner.
        renderSummary(labOk, { live: true, driveable, total });
        render();
        syncPanelGo();             // reflect needs_go changes while the panel is open
        if (openMsgSlug) renderMsgSummary(openMsgSlug);   // D9 — live-refresh open panel
      } catch (e) {
        // Feed stale/dead — the ONE health line turns red (spec item 6, .feed-dead).
        renderSummary(false, { live: false, error: e.message });
      } finally {
        pollInFlight = null;
      }
    })();
    return pollInFlight;
  }

  // ---- terminal overlay ---------------------------------------------------
  // The panel GO is the same unsafe Enter as the card-face GO, so it gates on
  // the SAME predicate — and stays reactive: if the open seat gains/loses
  // needs_go while the panel is up, the button appears/disappears on next poll.
  function syncPanelGo() {
    const show = openSlug !== null &&
      window.goAffordanceVisible(stateBySlug.get(openSlug));
    termGo.hidden = !show;
  }

  // D5 — list the seat's unacked bus messages (id · topic · age) in the panel.
  function renderPanelUnacked(slug) {
    termUnacked.textContent = "";
    const msgs = renderedUnackedRows(slug);
    // Drawer Copy + Nudge appear only when the open seat actually has unacked rows.
    if (termCopy) { termCopy.hidden = !msgs.length; termCopy.textContent = "Copy"; }
    if (termNudge) termNudge.hidden = !msgs.length;
    if (!msgs.length) { termUnacked.hidden = true; return; }
    const head = el("div", { class: "u-head",
      text: msgs.length + " unacked bus message" + (msgs.length === 1 ? "" : "s") });
    const list = el("div", { class: "u-list" }, msgs.map((m) => {
      const ts = m && m.created_at ? Date.parse(m.created_at) : NaN;
      const age = Number.isFinite(ts) ? window.formatUnreadAge((Date.now() - ts) / 1000) : "";
      const detail = messageDetailFor(slug, m);
      return el("div", { class: "u-row" }, [
        el("div", { class: "u-main" }, [
          el("span", { class: "u-id", text: "#" + String((m && m.id) || "?") }),
          el("span", { class: "u-topic", text: String((m && m.topic) || "(no topic)") }),
          age ? el("span", { class: "u-age", text: age }) : null,
        ]),
        detail && detail.body_preview
          ? el("div", { class: "u-preview", text: detail.body_preview })
          : null,
      ]);
    }));
    termUnacked.appendChild(head);
    termUnacked.appendChild(list);
    termUnacked.hidden = false;
  }

  // COCKPIT_CARD_CLICK_WAKE_INJECT_1 — the drawer Nudge button force-pushes the
  // composed "check your bus" nudge into the seat's terminal. Opening a seat
  // detail pane is inspection only. force=1 bypasses the controller seat-floor
  // (human intent wins); origin=cockpit_click gets the richer nudge line + a
  // wake_audit origin tag.
  //
  // Idempotence lives HERE: the controller's force path intentionally bypasses
  // per-message dedupe (merged WAKE_INJECT arc — do-not-touch), so a per-slug
  // debounce coalesces a rapid double-click and it never double-posts.
  //
  // Every outcome is a VISIBLE toast — sent, guarded-skip, or failure — never silent
  // (fail loud). Only seats that actually have unacked mail are nudged; the
  // controller's own guards still refuse a working / needs_go / no-unacked seat.
  const WAKE_CLICK_DEBOUNCE_MS = 4000;
  const lastNudgeAt = new Map();       // slug -> ms of the last click-nudge POST

  function nudgeSeat(slug, name) {
    const row = stateBySlug.get(slug);
    if (!row || !((row.unacked_count || 0) > 0)) return;   // nothing to nudge about
    const now = Date.now();
    if (now - (lastNudgeAt.get(slug) || 0) < WAKE_CLICK_DEBOUNCE_MS) return;  // double-click coalesce
    lastNudgeAt.set(slug, now);
    const label = name || slug;
    fetch(url("/api/sessions/" + slug + "/wake?force=1&origin=cockpit_click"),
          { ...FETCH_OPTS, method: "POST" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((res) => {
        if (res && res.sent) toast("Nudged " + label + " ✓", "ok");
        else toast(label + " — " + ((res && res.skipped) || "not nudged"), "");  // visible notice
      })
      .catch((e) => { toast("Nudge " + label + " failed — " + e.message, "err"); });  // fail loud
  }

  function openTerm(slug, name) {
    openSlug = slug;
    openName = name;
    termTitle.textContent = name + " — live terminal";
    syncPanelGo();
    renderPanelUnacked(slug);
    void fetchMessageDetails(slug);
    termMount.textContent = "";
    const frame = el("iframe", { id: "termframe", src: url("/term/" + slug + "/"),
                                 title: name + " terminal" });
    termMount.appendChild(frame);
    // Open the right pane column (grid stays live in the middle column, no blur).
    appShellEl.classList.add("pane-open");
    termEl.classList.add("open");
    // Focus the terminal so keystrokes land in the session immediately. The
    // ttyd page is same-origin (proxied via the controller), so we can also
    // attach a capture-phase Escape handler INSIDE the iframe — otherwise, once
    // the terminal has focus, the parent document never sees Escape and the
    // mock's "Esc closes" contract breaks. Capture phase runs before xterm's
    // own handlers, so Escape pops back to the grid from within the terminal.
    frame.addEventListener("load", () => {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.addEventListener("keydown", (e) => {
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeTerm(); }
        }, true);
      } catch (_) { /* cross-origin (should not happen for same-origin proxy) */ }
    });
    frame.focus();
  }

  function closeTerm() {
    openSlug = null;
    openName = null;
    syncPanelGo();                // openSlug null -> panel GO hidden
    termEl.classList.remove("open");
    appShellEl.classList.remove("pane-open");   // collapse the pane column back to 0
    termMount.textContent = "";   // remove iframe -> drops the ttyd WS connection
    termUnacked.textContent = ""; termUnacked.hidden = true;
    if (termCopy) { termCopy.hidden = true; termCopy.textContent = "Copy"; }
    if (termNudge) termNudge.hidden = true;
  }

  // ---- D9 bus-message panel (App-resident cards) --------------------------
  // Binds the Lab "Production & Lab" component: header + Unacknowledged(n) /
  // Last message / Acknowledged(count) sections, from the same per-agent bus
  // fields (unacked_messages / last_message / acked_count). DOM-node built —
  // no innerHTML, so agent-supplied strings can never inject markup.
  function msgEnvelope(m, extraCls, slug) {
    const created = m && m.created_at ? Date.parse(m.created_at) : NaN;
    const age = Number.isFinite(created)
      ? window.formatUnreadAge((Date.now() - created) / 1000) : "";
    const detail = messageDetailFor(slug, m);
    return el("div", { class: "hrow " + (extraCls || "") }, [
      el("div", { class: "hmain" }, [
        el("span", { class: "hfrom", text: "from " + String((m && m.from_terminal) || "?") }),
        el("span", { class: "htopic", text: String((m && m.topic) || "(no topic)") }),
        el("span", { class: "hid", text: "#" + String((m && m.id) || "?") }),
        age ? el("span", { class: "hage", text: age }) : null,
      ]),
      detail && detail.body_preview
        ? el("div", { class: "hpreview", text: detail.body_preview })
        : null,
    ]);
  }

  function renderMsgSummary(slug) {
    const row = stateBySlug.get(slug) || {};
    const unacked = renderedUnackedRows(slug);
    const last = row.last_message || null;
    const ackedCount = Number(row.acked_count) || 0;
    msgBody.textContent = "";

    const s1 = el("section", { class: "hsec" },
      [el("h3", { class: "hsec-t", text: "Unacknowledged (" + unacked.length + ")" })]);
    if (!unacked.length) s1.appendChild(el("div", { class: "hempty", text: "(none)" }));
    else unacked.forEach((m) => s1.appendChild(msgEnvelope(m, "hrow-unacked", slug)));
    msgBody.appendChild(s1);

    msgBody.appendChild(el("section", { class: "hsec" }, [
      el("h3", { class: "hsec-t", text: "Last message" }),
      last ? msgEnvelope(last, last.acked ? "hrow-acked" : "hrow-unacked", slug)
           : el("div", { class: "hempty", text: "(no messages)" }),
    ]));

    msgBody.appendChild(el("section", { class: "hsec hsec-compact" }, [
      el("h3", { class: "hsec-t", text: "Acknowledged" }),
      el("div", { class: "hcount", text: ackedCount + " acknowledged message(s)" }),
    ]));
  }

  function openMsgPanel(slug, name) {
    openMsgSlug = slug;
    msgTitle.textContent = slug + " messages";   // slug-only (name === slug now)
    renderMsgSummary(slug);
    msgVeil.classList.add("open");
    msgPanel.classList.add("open");
    void fetchMessageDetails(slug);
  }

  function closeMsgPanel() {
    openMsgSlug = null;
    msgPanel.classList.remove("open");
    msgVeil.classList.remove("open");
    msgBody.textContent = "";
  }

  async function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(text); return true; } catch (_) { /* fall through */ }
    }
    const ta = el("textarea"); ta.value = text; ta.setAttribute("readonly", "");
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand && document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    return ok;
  }

  // Reconciled unacked rows — the ONE source both the panel/drawer renderers AND the
  // Copy buttons draw from, so Copy always copies EXACTLY what is rendered
  // (COCKPIT_DRAWER_COPY_BUTTON_FIX_1). reconcileUnacked handles the status-only
  // hydration shape (/api/agents ships unacked_count>0 with a lean/empty
  // unacked_messages) by falling back to the already-fetched /api/messages detail
  // rows — in memory only, never a refetch, so it still works while /api/messages
  // is unavailable (bus degraded), and enriches each row with its body_preview.
  function renderedUnackedRows(slug) {
    const row = stateBySlug.get(slug) || {};
    const details = messageDetailsBySlug.get(slug);
    const detailList = details ? Array.from(details.values()) : [];
    return window.reconcileUnacked(row, detailList);
  }

  // Run a Copy button: format the open seat's rendered unacked rows, copy, flash
  // feedback. The formatter (glance_state.js) emits the placeholder ONLY when the
  // reconciled list is genuinely empty.
  async function runCopy(btn, title, unacked) {
    if (!btn) return;
    const payload = window.formatUnackedSummary(title, unacked);
    btn.disabled = true;
    const ok = await copyToClipboard(payload);
    btn.disabled = false;
    btn.textContent = ok ? "copied ✓" : "copy failed";
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { btn.textContent = "Copy"; }, 1800);
  }

  function unackedFor(slug) {
    return renderedUnackedRows(slug);
  }

  async function doMsgCopy() {
    if (!openMsgSlug) return;
    await runCopy(msgCopy, msgTitle.textContent || openMsgSlug, unackedFor(openMsgSlug));
  }

  // Terminal-drawer Copy — same helper, scoped to the OPEN seat's unacked rows.
  async function doTermCopy() {
    if (!openSlug) return;
    await runCopy(termCopy, termTitle.textContent || openSlug, unackedFor(openSlug));
  }

  // D9 flash-on-new-message: mark slugs whose unacked count rose since the last
  // poll so render() can flash their cards, then advance the baseline.
  function computeFlash(newMap) {
    flashSlugs = new Set();
    for (const [slug, a] of newMap) {
      const now = (a && a.unacked_count) || 0;
      const before = prevUnacked.has(slug) ? prevUnacked.get(slug) : now;
      if (now > before) flashSlugs.add(slug);
    }
    prevUnacked = new Map();
    for (const [slug, a] of newMap) prevUnacked.set(slug, (a && a.unacked_count) || 0);
  }

  // ---- rendering ----------------------------------------------------------
  // COCKPIT_UI_POLISH_1 (Director #12800): thin Lab-list rows — the whole fleet
  // on one screen. Each row is a fixed 6-column CSS grid (dot · identity · ctx
  // · unread · session · refresh) so every row's columns align table-style.
  //   D2: the ctx cell renders on EVERY row (muted empty track when inactive).
  //   D3: the session cell always renders a status word; the refresh/action cell
  //       stays present at the right edge, with GO + refresh only when driveable.
  // All content is built via textContent / DOM nodes (no innerHTML), so
  // agent-supplied strings can never inject markup.

  function compactContextAge(sec) {
    if (!Number.isFinite(sec) || sec < 0) return "";
    if (sec < 60) return "<1m";
    if (sec < 3600) return Math.floor(sec / 60) + "m";
    if (sec < 86400) return Math.floor(sec / 3600) + "h";
    return Math.floor(sec / 86400) + "d";
  }

  // D2 — context meter on every row. Fresh values show the percentage; stale
  // values lead with their age so the number cannot be mistaken for current.
  function ctxCell(meta, row) {
    const pct = (row && typeof row.context_pct === "number")
      ? Math.max(0, Math.min(100, row.context_pct)) : null;
    const stale = row && row.context_stale === true;
    const ageSec = stale ? Number(row.context_age_sec) : NaN;
    const staleLong = stale && Number.isFinite(ageSec) && ageSec > 3600;
    if (pct === null || staleLong) {
      return el("span", { class: "r-ctx r-ctx-null", title: "no context telemetry" }, [
        el("span", { class: "ctxbar" }),
      ]);
    }
    // SEVERITY-BY-VALUE (lead ruling #12977): the fill width still tracks pct, but
    // the gradient is scaled to span one FULL track so its colour reads the true
    // value (not the fill's own width). background-size % is relative to the fill
    // box, and the fill is pct% of the track, so a scale of (10000/pct)% makes the
    // gradient box exactly one track wide → colour at the fill edge == severity(pct).
    const scale = pct > 0 ? (10000 / pct) : 100;
    const age = stale ? compactContextAge(ageSec) : "";
    const label = stale
      ? (age ? age + " old · " + Math.round(pct) + "%" : "stale · " + Math.round(pct) + "%")
      : Math.round(pct) + "%";
    const bar = el("span", { class: "ctxbar" }, [el("span", { class: "ctxfill",
        style: "width:" + pct + "%;--ctx-track-scale:" + scale + "%" })]);
    return el("span", {
      class: "r-ctx" + (stale ? " ctx-stale" : ""),
      title: stale
        ? (age ? "stale context: " + age + " old · " + Math.round(pct) + "% used"
               : "stale context · " + Math.round(pct) + "% used")
        : "context window " + Math.round(pct) + "% used",
    }, [
      bar,
      el("span", { class: "ctxlbl", text: label }),
    ]);
  }

  // D3 — Session is status-only. Actions live in the rightmost Refresh column.
  const CHIP_LABEL = {
    "st-running": "running", "st-go": "needs GO", "st-unread": "unread",
    "st-unread-old": "unread", "st-offline": "offline", "st-idle": "idle",
  };
  function statusChipText(meta, row, up) {
    if (meta.status_only) return meta.kind || "app";
    if (!up) return "down";
    // Chip label follows the same palette resolver the row color uses, so text
    // and color can never disagree.
    const sc = window.resolveStateClass ? window.resolveStateClass(row, up) : "st-idle";
    return CHIP_LABEL[sc] || "idle";
  }

  const CONTEXT_REFRESH_ARM_MS = 3000;
  const contextRefreshArmed = new Map();

  function clearContextRefreshArms() {
    for (const armed of contextRefreshArmed.values()) clearTimeout(armed.timer);
    contextRefreshArmed.clear();
  }

  function refreshContextButton(meta) {
    return el("button", {
      class: "rbtn refresh-context",
      type: "button",
      text: "⟳",
      title: "Refresh context (/clear)",
      "aria-label": "Refresh context for " + meta.slug,
      onclick: (ev) => {
        ev.stopPropagation();
        refreshContext(meta.slug, ev.currentTarget);
      },
    });
  }

  function sessionControl(meta, row, up) {
    return el("span", { class: "session-cell" }, [
      el("span", { class: "chip", text: statusChipText(meta, row, up) }),
    ]);
  }

  function refreshControl(meta, row, up) {
    const cell = el("span", { class: "refresh-cell" });
    if (meta.status_only || !up) return cell;
    const actions = [];
    if (row && window.goAffordanceVisible(row)) {
      actions.push(el("button", { class: "rbtn go", type: "button", text: "GO ⏎",
        title: "Answer GO for " + meta.slug,
        onclick: (ev) => { ev.stopPropagation(); doGo(meta.slug, ev.currentTarget); } }));
    }
    actions.push(refreshContextButton(meta));
    cell.appendChild(el("span", { class: "control-actions" }, actions));
    return cell;
  }

  function card(meta) {
    // D9: fetch live state for EVERY card (not just driveable) so App-resident
    // agents surface their unacked badge + feed the bus-message panel.
    const row = stateBySlug.get(meta.slug) || null;
    const up = row ? row.session_up === true : false;
    const cls = ["row"];
    if (flashSlugs.has(meta.slug)) cls.push("flash");   // D9 flash-on-new-message

    // State classes: status-only seats keep the recessed "app" chrome; every
    // driveable seat (up OR down) carries exactly one st-* palette class (spec
    // item 3) so its dot + name color reads its true state. up/down stay for the
    // existing geometry/contrast selectors.
    if (meta.status_only) {
      cls.push("app");
    } else {
      cls.push(up ? "up" : "down");
      cls.push(glanceClass(row, up));
    }

    // Col 2 — identity. COCKPIT_SLUG_ONLY_CARDS_1 (Director: "the name is for me,
    // not for agents"): the SLUG renders in the name's slot — .r-name keeps the
    // name's 13px/500 + per-state color — and the separate small .r-slug line is
    // dropped, so each card shows the slug ONCE and no display name is rendered.
    const idKids = [
      el("span", { class: "r-name", text: meta.slug }),
    ];
    if (meta.badge) idKids.push(el("span", { class: "r-kind", text: meta.kind }));

    // Col 3 — oldest unacked age only (empty spacer keeps the column aligned).
    // D9: shown whenever the seat has unacked messages, including App cards
    // (which are not session_up but do carry a bus identity).
    let unread;
    if (row && row.unacked_count > 0) {
      unread = el("span", { class: "r-unread" }, [
        el("span", { class: ageClass(row.oldest_unacked_age_sec || 0),
                     text: window.formatUnreadAge(row.oldest_unacked_age_sec || 0) }),
      ]);
    } else {
      unread = el("span", { class: "r-unread r-unread-empty" });
    }

    const c = el("div", { class: cls.join(" "), "data-slug": meta.slug }, [
      el("span", { class: "r-dot" }),
      el("span", { class: "r-id" }, idKids),
      ctxCell(meta, row),          // D2 — every row
      unread,
      sessionControl(meta, row, up), // D3 — status-only Session cell
      refreshControl(meta, row, up), // D3 — rightmost action cell
    ]);

    // D9 — two card modes, ZERO dead clicks. A tmux-backed (driveable) seat
    // opens its terminal (unchanged); an App-resident card opens the bus-message
    // panel (same data + section shape as the Lab "Production & Lab" component).
    // Slug, not the display name, everywhere the identity is surfaced to agents
    // (drawer header, panel title, toasts) — COCKPIT_SLUG_ONLY_CARDS_1.
    const name = meta.slug;
    let open;
    if (!meta.status_only) {
      open = () => {
        const r = stateBySlug.get(meta.slug) || {};
        if (!r.session_up) { toast(name + " is down — start it in the terminal"); return; }
        // ttyd down ⇒ the proxy would 502; don't open a dead terminal frame.
        if (r.ttyd_up === false) { toast(name + " — terminal server offline"); return; }
        openTerm(meta.slug, name);
      };
    } else {
      open = () => openMsgPanel(meta.slug, name);
    }
    c.setAttribute("role", "button");
    c.setAttribute("tabindex", "0");
    c.addEventListener("click", open);
    c.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
    return c;
  }

  // ---- sidebar navigation + view filtering (spec item 5) ------------------
  // Logical state class for view filtering. Driveable seats resolve via the shared
  // palette resolver; status-only (app) seats have no st-* chrome, so map them for
  // filtering only: unacked mail → attention (amber/red by age), else grey/quiet.
  function cardStateClass(meta, row, up) {
    if (meta.status_only) {
      const n = (row && row.unacked_count) || 0;
      if (n > 0) {
        const age = (row && row.oldest_unacked_age_sec) || 0;
        return age > (window.UNREAD_OLD_S || 600) ? "st-unread-old" : "st-unread";
      }
      return "st-idle";
    }
    return glanceClass(row, up);
  }

  // planView input: each plate → { nav, label, cards:[{slug, stClass, meta}] }.
  function navGroups() {
    if (!layout) return [];
    return layout.plates.map((plate) => {
      const nav = PLATE_TO_NAV[plate.label] || plate.label;
      const cards = plate.cards.map((meta) => {
        const row = stateBySlug.get(meta.slug) || null;
        const up = row ? row.session_up === true : false;
        return { slug: meta.slug, stClass: cardStateClass(meta, row, up), meta };
      });
      return { nav, label: plate.label, cards };
    });
  }

  // Build the 8 sidebar entries once (static order). Active highlight + red
  // attention badges update per render() from the planView badge set.
  function buildSidebar() {
    if (!sidebarEl) return;
    sidebarEl.textContent = "";
    SIDEBAR_ORDER.forEach((nav) => {
      const badge = el("span", { class: "nav-badge", "aria-label": "needs attention" });
      badge.hidden = true;
      const item = el("button", { class: "nav-item", type: "button", "data-view": nav,
        title: nav, onclick: () => setView(nav) }, [
        el("span", { class: "nav-abbr", "aria-hidden": "true", text: NAV_ABBR[nav] || nav.slice(0, 2) }),
        el("span", { class: "nav-label", text: nav }),
        badge,
      ]);
      sidebarEl.appendChild(item);
    });
  }

  function updateSidebar(badges) {
    if (!sidebarEl) return;
    Array.from(sidebarEl.children).forEach((item) => {
      const nav = item.getAttribute("data-view");
      const isActive = nav === currentView;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-current", isActive ? "page" : "false");
      const badge = item.querySelector(".nav-badge");
      if (badge) badge.hidden = !badges[nav];
    });
  }

  function setView(view) {
    if (SIDEBAR_ORDER.indexOf(view) === -1) view = "ACTIVE";
    const leavingHistory = currentView === "History" && view !== "History";
    currentView = view;
    try { localStorage.setItem(VIEW_KEY, view); } catch (_) { /* storage blocked */ }
    if (view === "History") enterHistory();
    else if (leavingHistory) stopHistory();
    render();
  }

  // ---- History view (revamp items 8+9) ------------------------------------
  function enterHistory() {
    renderHistory();                 // paint immediately (loading / last snapshot)
    fetchHistory();                  // refresh now …
    if (historyTimer === null) {     // … then every 15s while the view is active.
      historyTimer = setInterval(fetchHistory, HISTORY_REFRESH_MS);
    }
  }

  function stopHistory() {
    if (historyTimer !== null) { clearInterval(historyTimer); historyTimer = null; }
  }

  async function fetchHistory() {
    try {
      const r = await fetch(url("/api/history?limit=30"), FETCH_OPTS);
      if (!r.ok) throw new Error("history HTTP " + r.status);
      const data = await r.json();
      historyJobs = Array.isArray(data.jobs) ? data.jobs : [];
      historyStale = data.stale === true;
    } catch (_e) {
      historyStale = true;           // keep the last-good jobs, mark them stale
    }
    historyLoaded = true;
    if (currentView === "History") renderHistory();
  }

  function fmtDuration(sec) {
    if (sec === null || sec === undefined || isNaN(sec)) return "—";
    const s = Math.max(0, Math.round(sec));
    return Math.floor(s / 60) + "m " + (s % 60) + "s";
  }

  function elapsedSince(iso) {
    const t = Date.parse(iso);
    if (isNaN(t)) return "—";
    return fmtDuration((Date.now() - t) / 1000);
  }

  function fmtAge(iso) {
    if (!iso) return "—";
    const t = Date.parse(iso);
    if (isNaN(t)) return "—";
    let s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return s + "s ago";
    const m = Math.floor(s / 60);
    if (m < 60) return m + "m ago";
    const h = Math.floor(m / 60);
    if (h < 24) return h + "h ago";
    return Math.floor(h / 24) + "d ago";
  }

  function historyDotClass(j) {
    if (j.outcome === "pass") return "hist-dot-pass";
    if (j.outcome === "fail") return "hist-dot-fail";
    return j.status === "in-flight" ? "hist-dot-live" : "hist-dot-idle";
  }

  // Verdict-strip card (item 9). Click expands + scrolls to the matching row.
  function verdictCard(j) {
    return el("button", { class: "verdict-card vc-" + j.outcome, type: "button",
      title: j.topic || j.key || "", onclick: () => focusHistory(j.key) }, [
      el("span", { class: "verdict-badge vb-" + j.outcome,
        text: j.outcome === "pass" ? "PASS" : "FAIL" }),
      el("span", { class: "verdict-topic", text: j.topic || j.key || "—" }),
      el("span", { class: "verdict-meta",
        text: (j.seat || "—") + " · " + fmtAge(j.ended_at) }),
    ]);
  }

  // One history job row (item 8). All bus-derived text via el's textContent path.
  function historyRow(j) {
    const expanded = expandedHistory.has(j.key);
    const dur = j.status === "in-flight"
      ? elapsedSince(j.started_at) : fmtDuration(j.duration_sec);
    const head = el("button", { class: "hist-row", type: "button",
      "aria-expanded": expanded ? "true" : "false",
      onclick: () => toggleHistory(j.key) }, [
      el("span", { class: "hist-dot " + historyDotClass(j), "aria-hidden": "true" }),
      el("span", { class: "hist-topic", text: j.topic || j.key || "—" }),
      el("span", { class: "hist-seat", text: j.seat || "—" }),
      el("span", { class: "hist-status", text: j.status || "" }),
      el("span", { class: "hist-dur", text: dur }),
      el("span", { class: "hist-age", text: fmtAge(j.ended_at || j.started_at) }),
    ]);
    const wrap = el("div", { class: "hist-wrap", "data-key": j.key }, [head]);
    if (expanded) {
      const ids = Array.isArray(j.msg_ids) ? j.msg_ids.join(", ") : "";
      wrap.appendChild(el("div", { class: "hist-expand" }, [
        el("div", { class: "hist-preview", text: j.last_preview || "(no preview)" }),
        el("div", { class: "hist-ids", text: "msg ids: " + ids }),
      ]));
    }
    return wrap;
  }

  function toggleHistory(key) {
    if (!key) return;
    if (expandedHistory.has(key)) expandedHistory.delete(key);
    else expandedHistory.add(key);
    renderHistory();
  }

  function focusHistory(key) {
    if (!key) return;
    expandedHistory.add(key);        // verdict-card click always opens the row
    pendingScrollKey = key;
    renderHistory();
  }

  function renderHistory() {
    if (currentView !== "History") return;
    const frag = document.createDocumentFragment();

    // Item 9 — verdict strip: most recent ≤8 jobs that carry an outcome.
    const verdictJobs = historyJobs.filter((j) => j && j.outcome).slice(0, 8);
    if (verdictJobs.length) {
      frag.appendChild(el("div", { class: "verdict-wrap" }, [
        el("h2", {}, [document.createTextNode("Gate verdicts")]),
        el("div", { class: "verdict-strip" }, verdictJobs.map(verdictCard)),
      ]));
    }

    // Item 8 — job rows, newest first (backend already sorts).
    const rows = historyJobs.map(historyRow);
    frag.appendChild(el("div", { class: "history-list" }, [
      el("h2", {}, [document.createTextNode("Task history"),
        historyStale ? el("span", { class: "history-stale", text: "stale" }) : null]),
      rows.length
        ? el("div", { class: "history-rows" }, rows)
        : el("div", { class: "view-empty",
            text: historyLoaded ? "No recent jobs." : "Loading…" }),
    ]));

    gridEl.textContent = "";
    gridEl.appendChild(frag);

    if (pendingScrollKey) {
      const wraps = gridEl.querySelectorAll(".hist-wrap");
      for (const w of wraps) {
        if (w.dataset.key === pendingScrollKey) { w.scrollIntoView({ block: "nearest" }); break; }
      }
      pendingScrollKey = null;
    }
  }

  // ACTIVE-view collapsed grey line: "N quiet" (compact form carries the group
  // label, e.g. "Engineering — 5 quiet"). Click toggles inline expansion.
  function quietGroup(g, compact) {
    const expanded = expandedGroups.has(g.nav);
    const text = (compact ? g.label + " — " : "") + g.greyCount + " quiet";
    const line = el("button", { class: "quiet-line" + (compact ? " quiet-compact" : ""),
      type: "button", "aria-expanded": expanded ? "true" : "false",
      onclick: () => toggleQuiet(g.nav) }, [
      el("span", { class: "quiet-caret", "aria-hidden": "true", text: expanded ? "▾" : "▸" }),
      el("span", { class: "quiet-text", text: text }),
    ]);
    const wrap = el("div", { class: "quiet-wrap" }, [line]);
    if (expanded) {
      wrap.appendChild(el("div", { class: "rows quiet-rows" }, g.greyCards.map((c) => card(c.meta))));
    }
    return wrap;
  }

  function toggleQuiet(nav) {
    if (expandedGroups.has(nav)) expandedGroups.delete(nav);
    else expandedGroups.add(nav);
    render();
  }

  function render() {
    if (!layout) return;
    // Grid replacement creates new buttons; never carry a hidden arm token over
    // to a visually fresh button.
    clearContextRefreshArms();
    // View filter is one pure function (glance_state.js planView) so the DOM and
    // its unit vectors share a source. Plates → nav groups → visible plan + badges.
    const plan = window.planView(navGroups(), currentView);
    updateSidebar(plan.badges);

    // History owns the middle column on its own 15s cadence — the 4s poll must
    // NOT repaint (or refetch) it. Keep the sidebar/summary fresh, then bail.
    if (currentView === "History") { renderSummary(); return; }

    const frag = document.createDocumentFragment();
    const isActive = currentView === "ACTIVE";
    plan.groups.forEach((g) => {
      const hasActive = g.activeCards.length > 0;
      // ACTIVE view, a fully-quiet group → one compact "Label — N quiet" line only.
      if (isActive && !hasActive) {
        if (g.greyCount > 0) frag.appendChild(quietGroup(g, true));
        return;
      }
      if (!hasActive && g.greyCount === 0) return;   // nothing to show for this group
      const children = [
        el("h2", {}, [document.createTextNode(g.label),
          el("span", { class: "count", text: g.activeCards.length })]),
        el("div", { class: "rows" }, g.activeCards.map((c) => card(c.meta))),
      ];
      if (isActive && g.greyCount > 0) children.push(quietGroup(g, false));
      frag.appendChild(el("div", { class: "plate" }, children));
    });
    if (!frag.childNodes.length) {
      frag.appendChild(el("div", { class: "view-empty",
        text: "Nothing needs attention — every seat is quiet." }));
    }
    gridEl.textContent = "";
    gridEl.appendChild(frag);
    renderSummary();
  }

  async function doGo(slug, btn) {
    if (btn) btn.disabled = true;
    const ok = await post("/api/sessions/" + slug + "/go", "GO → " + slug);
    if (btn) { btn.disabled = false; if (ok) { btn.classList.add("flash-ok"); setTimeout(() => btn.classList.remove("flash-ok"), 900); } }
  }

  function refreshContext(slug, btn) {
    const armed = contextRefreshArmed.get(slug);
    if (armed && armed.expiresAt > Date.now()) {
      clearTimeout(armed.timer);
      contextRefreshArmed.delete(slug);
      btn.disabled = true;
      post("/api/sessions/" + slug + "/refresh_context", "context refreshed → " + slug)
        .then((ok) => { if (ok) return poll(); })
        .finally(() => {
          btn.disabled = false;
          btn.textContent = "⟳";
          btn.classList.remove("armed");
        });
      return;
    }
    if (armed) clearTimeout(armed.timer);
    btn.textContent = "sure?";
    btn.classList.add("armed");
    const timer = setTimeout(() => {
      if (contextRefreshArmed.get(slug)?.timer !== timer) return;
      contextRefreshArmed.delete(slug);
      btn.textContent = "⟳";
      btn.classList.remove("armed");
    }, CONTEXT_REFRESH_ARM_MS);
    contextRefreshArmed.set(slug, {
      expiresAt: Date.now() + CONTEXT_REFRESH_ARM_MS,
      timer,
    });
  }

  async function doStart(slug, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "starting…"; }
    const ok = await post("/api/sessions/" + slug + "/start", "Start → " + slug);
    if (ok) await poll();                 // flip the card live, no page reload (AC-U2)
    else if (btn) { btn.disabled = false; btn.textContent = "▶ Start"; }
  }

  // ---- wiring -------------------------------------------------------------
  document.getElementById("x").addEventListener("click", closeTerm);
  document.getElementById("x").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") closeTerm(); });
  // Defense in depth: the button is hidden when GO isn't allowed, but re-check
  // the predicate on click so a stale/racy click can never send a bare Enter.
  termGo.addEventListener("click", () => {
    if (openSlug && window.goAffordanceVisible(stateBySlug.get(openSlug))) doGo(openSlug, termGo);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openSlug) closeTerm(); });

  // ---- D9 message-panel wiring --------------------------------------------
  document.getElementById("msg-x").addEventListener("click", closeMsgPanel);
  document.getElementById("msg-x").addEventListener("keydown",
    (e) => { if (e.key === "Enter" || e.key === " ") closeMsgPanel(); });
  msgVeil.addEventListener("click", closeMsgPanel);
  msgCopy.addEventListener("click", doMsgCopy);
  if (termCopy) termCopy.addEventListener("click", doTermCopy);
  // Drawer Nudge — re-push the composed wake into an already-open seat (same call).
  if (termNudge) termNudge.addEventListener("click", () => { if (openSlug) nudgeSeat(openSlug, openName); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openMsgSlug) closeMsgPanel(); });

  // NOTE (COCKPIT_REVAMP_HEADER_1, spec item 6): the header bell (notify-mute
  // toggle) was removed. Banners stay ON; the controller's /api/notify/* endpoints
  // + COCKPIT_NOTIFY_ENABLED env kill switch are untouched (engineer-only path).

  function boot() {
    if (bootReady) return Promise.resolve();
    if (bootInFlight) return bootInFlight;
    bootInFlight = (async () => {
      try {
        layout = await loadLayoutWithRetry();
        clearLayoutSelfHeal();
        buildSidebar();              // 9 static nav entries (badges hydrate on poll)
        render();                    // paint immediately from layout (metadata)
        renderSummary();
        if (currentView === "History") enterHistory();   // restore a persisted History view
        await poll();                // then hydrate with live state
        if (pollTimer === null) pollTimer = setInterval(poll, POLL_MS);
        bootReady = true;
      } catch (e) {
        // Layout failed before we have any layout — renderSummary early-returns
        // without one, so write the health line directly (red).
        setLayoutStatus("Layout load failed — " + e.message);
        scheduleLayoutSelfHeal();
      } finally {
        bootInFlight = null;
      }
    })();
    return bootInFlight;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !bootReady) void boot();
  });

  // LAB_UNIFY_THEME_COCKPIT_EXTENSION_1: live-follow the /v2 theme. The head
  // bootstrap already applied the stored theme before paint; here we re-theme
  // live when the shell toggles. The cockpit runs as a same-origin iframe inside
  // the Lab, so it receives the shell's `storage` event on the labTheme write.
  (function wireTheme() {
    function applyTheme(t) {
      var el = document.documentElement;
      if (t === "light") { el.setAttribute("data-theme", "light"); }
      else { el.removeAttribute("data-theme"); }
    }
    try { applyTheme(localStorage.getItem("labTheme")); } catch (e) { /* storage off */ }
    window.addEventListener("storage", function (e) {
      if (e.key === "labTheme") {
        try { applyTheme(localStorage.getItem("labTheme")); } catch (_) { /* storage off */ }
      }
    });
  })();

  boot();
})();
