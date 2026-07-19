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
  const connEl = document.getElementById("conn");
  const veilEl = document.getElementById("veil");
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

  function renderSummary(labOk = null) {
    if (!layout) return;
    const cards = layout.plates.flatMap((plate) => plate.cards);
    // COCKPIT_REVAMP_HEADER_1: the oversized digit block (Seats/Attention/Terminals)
    // was removed per spec item 6 — live counts stay in the green header line.
    if (rosterNoteEl) rosterNoteEl.textContent = cards.length + " seats · grouped by operating role";
    if (syncNoteEl) {
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

  async function poll() {
    try {
      const r = await fetch(url("/api/agents"), FETCH_OPTS);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
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
      connEl.textContent = "live · " + driveable + " with terminal / " + total + " seats";
      connEl.className = "conn ok";
      renderSummary(labOk);
      render();
      syncPanelGo();             // reflect needs_go changes while the panel is open
      if (openMsgSlug) renderMsgSummary(openMsgSlug);   // D9 — live-refresh open panel
    } catch (e) {
      // Feed stale/dead — the ONE health line turns red (spec item 6, .feed-dead).
      connEl.textContent = "feed offline — " + e.message;
      connEl.className = "conn feed-dead";
      renderSummary(false);
    }
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
    const row = stateBySlug.get(slug) || {};
    const msgs = Array.isArray(row.unacked_messages) ? row.unacked_messages : [];
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

  // COCKPIT_CARD_CLICK_WAKE_INJECT_1 — an explicit Director click (card open or the
  // drawer Nudge button) force-pushes the composed "check your bus" nudge into the
  // seat's terminal. force=1 bypasses the controller seat-floor (human intent wins);
  // origin=cockpit_click gets the richer nudge line + a wake_audit origin tag.
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
    nudgeSeat(slug, name);       // explicit-click wake (force + origin, toasted)
    termMount.textContent = "";
    const frame = el("iframe", { id: "termframe", src: url("/term/" + slug + "/"),
                                 title: name + " terminal" });
    termMount.appendChild(frame);
    veilEl.classList.add("open");
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
    veilEl.classList.remove("open");
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
    const unacked = Array.isArray(row.unacked_messages) ? row.unacked_messages : [];
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
    msgTitle.textContent = name + " [" + slug + "] messages";
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

  // Shared `#id · topic · from` summary formatter — the ONE source of truth for
  // both the card message-panel Copy and the terminal-drawer Copy (no duplicated
  // line-building logic between the two).
  function formatUnackedSummary(title, unacked) {
    const rows = Array.isArray(unacked) ? unacked : [];
    const lines = rows.map((m) =>
      "#" + String((m && m.id) || "?") + "  " + String((m && m.topic) || "(no topic)") +
      "  from " + String((m && m.from_terminal) || "?"));
    return String(title || "") + "\n" +
      (lines.length ? lines.join("\n") : "(no unacknowledged messages)");
  }

  // Run a Copy button: format the open seat's unacked rows, copy, flash feedback.
  async function runCopy(btn, title, unacked) {
    if (!btn) return;
    const payload = formatUnackedSummary(title, unacked);
    btn.disabled = true;
    const ok = await copyToClipboard(payload);
    btn.disabled = false;
    btn.textContent = ok ? "copied ✓" : "copy failed";
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { btn.textContent = "Copy"; }, 1800);
  }

  function unackedFor(slug) {
    const row = stateBySlug.get(slug) || {};
    return Array.isArray(row.unacked_messages) ? row.unacked_messages : [];
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
  // on one screen. Each row is a fixed 5-column CSS grid (dot · identity · unread
  // · ctx · control) so every row's columns align table-style across all plates.
  //   D2: the ctx cell renders on EVERY row (em-dash placeholder when null).
  //   D3: the control cell renders on EVERY row (Start / GO / status chip) —
  //       never conditionally absent.
  // All content is built via textContent / DOM nodes (no innerHTML), so
  // agent-supplied strings can never inject markup.

  // D2 — context meter on every row. Driveable seat with a numeric context_pct
  // → mini bar + label; anything else (status-only, down, telemetry-less) → an
  // em-dash placeholder. Never blank, never hidden.
  function ctxCell(meta, row) {
    const pct = (meta.driveable && row && typeof row.context_pct === "number")
      ? Math.max(0, Math.min(100, row.context_pct)) : null;
    if (pct === null) {
      return el("span", { class: "r-ctx r-ctx-null", text: "—",
                          title: "no context telemetry" });
    }
    // SEVERITY-BY-VALUE (lead ruling #12977): the fill width still tracks pct, but
    // the gradient is scaled to span one FULL track so its colour reads the true
    // value (not the fill's own width). background-size % is relative to the fill
    // box, and the fill is pct% of the track, so a scale of (10000/pct)% makes the
    // gradient box exactly one track wide → colour at the fill edge == severity(pct).
    const scale = pct > 0 ? (10000 / pct) : 100;
    return el("span", { class: "r-ctx", title: "context window " + Math.round(pct) + "% used" }, [
      el("span", { class: "ctxbar" }, [el("span", { class: "ctxfill",
        style: "width:" + pct + "%;--ctx-track-scale:" + scale + "%" })]),
      el("span", { class: "ctxlbl", text: Math.round(pct) + "%" }),
    ]);
  }

  // D3 — state control on every row. Driveable + down → Start; driveable + up +
  // needs_go → GO; otherwise a live status chip (running / unread / idle /
  // offline / no-signal for driveable seats, or the kind for status-only). The
  // chip is never omitted, so the control column is uniform.
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

  function stateControl(meta, row, up) {
    if (!meta.status_only) {
      if (!up) {
        return el("button", { class: "rbtn start", type: "button", text: "▶ Start",
          title: "Start " + (meta.display_name || meta.slug),
          onclick: (ev) => { ev.stopPropagation(); doStart(meta.slug, ev.currentTarget); } });
      }
      if (row && window.goAffordanceVisible(row)) {
        return el("button", { class: "rbtn go", type: "button", text: "GO ⏎",
          title: "Answer GO for " + (meta.display_name || meta.slug),
          onclick: (ev) => { ev.stopPropagation(); doGo(meta.slug, ev.currentTarget); } });
      }
    }
    return el("span", { class: "chip", text: statusChipText(meta, row, up) });
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

    // Col 2 — identity (name + slug, + kind badge for service/headless).
    const idKids = [
      el("span", { class: "r-name", text: meta.display_name || meta.slug }),
      el("span", { class: "r-slug", text: meta.slug }),
    ];
    if (meta.badge) idKids.push(el("span", { class: "r-kind", text: meta.kind }));

    // Col 3 — unread badge + oldest age (empty spacer keeps the column aligned).
    // D9: shown whenever the seat has unacked messages, including App cards
    // (which are not session_up but do carry a bus identity).
    let unread;
    if (row && row.unacked_count > 0) {
      unread = el("span", { class: "r-unread" }, [
        el("span", { class: "unread", text: String(row.unacked_count) }),
        el("span", { class: ageClass(row.oldest_unacked_age_sec || 0),
                     text: window.formatUnreadAge(row.oldest_unacked_age_sec || 0) }),
      ]);
    } else {
      unread = el("span", { class: "r-unread r-unread-empty" });
    }

    const c = el("div", { class: cls.join(" "), "data-slug": meta.slug }, [
      el("span", { class: "r-dot" }),
      el("span", { class: "r-id" }, idKids),
      unread,
      ctxCell(meta, row),          // D2 — every row
      stateControl(meta, row, up), // D3 — every row
    ]);

    // D9 — two card modes, ZERO dead clicks. A tmux-backed (driveable) seat
    // opens its terminal (unchanged); an App-resident card opens the bus-message
    // panel (same data + section shape as the Lab "Production & Lab" component).
    const name = meta.display_name || meta.slug;
    let open;
    if (!meta.status_only) {
      open = () => {
        const r = stateBySlug.get(meta.slug) || {};
        if (!r.session_up) { toast(name + " is down — press Start first"); return; }
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

  function render() {
    if (!layout) return;
    const frag = document.createDocumentFragment();
    // Plate groupings survive as slim section headers (D1); rows list under each.
    layout.plates.forEach((plate) => {
      const list = el("div", { class: "rows" }, plate.cards.map(card));
      frag.appendChild(el("div", { class: "plate" }, [
        el("h2", {}, [document.createTextNode(plate.label),
          el("span", { class: "count", text: plate.cards.length })]),
        list,
      ]));
    });
    gridEl.textContent = "";
    gridEl.appendChild(frag);
    renderSummary();
  }

  async function doGo(slug, btn) {
    if (btn) btn.disabled = true;
    const ok = await post("/api/sessions/" + slug + "/go", "GO → " + slug);
    if (btn) { btn.disabled = false; if (ok) { btn.classList.add("flash-ok"); setTimeout(() => btn.classList.remove("flash-ok"), 900); } }
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
  veilEl.addEventListener("click", closeTerm);
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

  async function boot() {
    try {
      const r = await fetch(url("/cockpit_layout.json"), FETCH_OPTS);
      if (!r.ok) throw new Error("layout HTTP " + r.status);
    layout = await r.json();
    } catch (e) {
      connEl.textContent = "layout load failed — " + e.message;
      connEl.className = "conn feed-dead";
      return;
    }
    render();                    // paint immediately from layout (metadata)
    renderSummary();
    await poll();                // then hydrate with live state
    pollTimer = setInterval(poll, POLL_MS);
  }

  boot();
})();
