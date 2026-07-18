/* Baker Cockpit — LAB_COCKPIT_PAGE_1.
 *
 * Data model: a generated static layout (cockpit_layout.json — plates + card
 * metadata, mirrors the live Control Room) merged by slug with the controller's
 * live GET /api/agents (session + glance state). Driveable seats open an
 * on-demand iframe to /term/<slug>/ (same origin — one Basic-auth prompt per
 * browser session). Non-driveable active seats (app-*, service, headless) are status-only (no terminal). GO sends
 * Enter to the seat's tmux session; Start (re)creates a downed seat's session.
 *
 * Interaction contract: COCKPIT_CARD_BEHAVIOR_MOCK.html. Glance frames: §5.2 +
 * brisen-lab glance_state.js resolveGlanceState (precedence NEEDS_GO > WORKING
 * > NEW). GO affordance: §5.4. All card content is built via textContent / DOM
 * nodes — no innerHTML, so agent-supplied strings can never inject markup.
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
  const notifyToggle = document.getElementById("notify-toggle");
  const syncNoteEl = document.getElementById("sync-note");
  const rosterNoteEl = document.getElementById("roster-note");
  const statTotalEl = document.getElementById("stat-total");
  const statAttentionEl = document.getElementById("stat-attention");
  const statTerminalsEl = document.getElementById("stat-terminals");
  // D9 — App-resident card bus-message panel.
  const msgVeil = document.getElementById("msgveil");
  const msgPanel = document.getElementById("msgpanel");
  const msgBody = document.getElementById("msg-body");
  const msgTitle = document.getElementById("msg-title");
  const msgCopy = document.getElementById("msg-copy");

  let layout = null;             // { plates: [{label, cards:[...]}, ...] }
  let stateBySlug = new Map();   // slug -> live /api/agents row
  let openSlug = null;           // currently open terminal, or null
  let openMsgSlug = null;        // currently open bus-message panel, or null (D9)
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

  function glanceClass(row) {
    // No live row at all = telemetry never seen for this seat -> UNKNOWN, NOT idle.
    if (!row) return "glance-unknown";
    const g = window.resolveGlanceState({
      unacked: row.unacked_count || 0,
      isWorking: row.is_working === true,
      hasTelemetry: row.has_telemetry === true,
      isDoneGreen: false,               // no DONE signal on this surface
      needsGo: row.needs_go === true,
    });
    if (g === "NEEDS_GO") return "glance-needs-go";      // green tint + GO
    if (g === "WORKING") return "";                       // E6: running = bright, no frame
    if (g === "NEW") return "glance-amber";               // D5/E6: amber = unread
    // UNKNOWN (glance outage or telemetry-less seat) must read distinctly from
    // IDLE — a quiet seat with telemetry vs a seat we have no signal for.
    if (g === "UNKNOWN") return "glance-unknown";
    return "";                          // IDLE
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
    const attention = cards.filter((meta) => {
      const row = stateBySlug.get(meta.slug);
      if (!row) return false;
      return row.needs_go === true || (row.unacked_count || 0) > 0 ||
        row.ttyd_up === false || (!meta.status_only && row.session_up === false);
    }).length;
    const terminals = cards.filter((meta) => meta.driveable).length;
    if (statTotalEl) statTotalEl.textContent = String(cards.length);
    if (statAttentionEl) statAttentionEl.textContent = stateBySlug.size ? String(attention) : "—";
    if (statTerminalsEl) statTerminalsEl.textContent = String(terminals);
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
      // lab_glance_ok=false ⇒ the Lab telemetry source is down; every seat's
      // glance collapses to UNKNOWN. Surface it explicitly, don't read as idle.
      const labOk = data.lab_glance_ok !== false;
      const total = totalCardCount();
      connEl.textContent = "live · " + m.size + " driveable / " + total + " seats" +
        (labOk ? "" : " · ⚠ telemetry offline");
      connEl.className = labOk ? "conn ok" : "conn warn";
      renderSummary(labOk);
      render();
      syncPanelGo();             // reflect needs_go changes while the panel is open
      if (openMsgSlug) renderMsgSummary(openMsgSlug);   // D9 — live-refresh open panel
    } catch (e) {
      connEl.textContent = "offline — " + e.message;
      connEl.className = "conn err";
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
    if (!msgs.length) { termUnacked.hidden = true; return; }
    const head = el("div", { class: "u-head",
      text: msgs.length + " unacked bus message" + (msgs.length === 1 ? "" : "s") });
    const list = el("div", { class: "u-list" }, msgs.map((m) => {
      const ts = m && m.created_at ? Date.parse(m.created_at) : NaN;
      const age = Number.isFinite(ts) ? window.formatUnreadAge((Date.now() - ts) / 1000) : "";
      return el("div", { class: "u-row" }, [
        el("span", { class: "u-id", text: "#" + String((m && m.id) || "?") }),
        el("span", { class: "u-topic", text: String((m && m.topic) || "(no topic)") }),
        age ? el("span", { class: "u-age", text: age }) : null,
      ]);
    }));
    termUnacked.appendChild(head);
    termUnacked.appendChild(list);
    termUnacked.hidden = false;
  }

  // D6 — wake-on-open. Opening a driveable seat that has unacked>0 and is not
  // WORKING (and not needs_go — that is the GO flow) nudges its tmux once. The
  // controller enforces the guards + a 10-min dedupe + audit; the page just asks.
  function maybeWakeOnOpen(slug) {
    const row = stateBySlug.get(slug);
    if (window.amberState(row)) {
      fetch(url("/api/sessions/" + slug + "/wake"), { ...FETCH_OPTS, method: "POST" })
        .catch(() => { /* best-effort nudge; never blocks opening the terminal */ });
    }
  }

  function openTerm(slug, name) {
    openSlug = slug;
    termTitle.textContent = name + " — live terminal";
    syncPanelGo();
    renderPanelUnacked(slug);
    maybeWakeOnOpen(slug);
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
    syncPanelGo();                // openSlug null -> panel GO hidden
    termEl.classList.remove("open");
    veilEl.classList.remove("open");
    termMount.textContent = "";   // remove iframe -> drops the ttyd WS connection
    termUnacked.textContent = ""; termUnacked.hidden = true;
  }

  // ---- D9 bus-message panel (App-resident cards) --------------------------
  // Binds the Lab "Production & Lab" component: header + Unacknowledged(n) /
  // Last message / Acknowledged(count) sections, from the same per-agent bus
  // fields (unacked_messages / last_message / acked_count). DOM-node built —
  // no innerHTML, so agent-supplied strings can never inject markup.
  function msgEnvelope(m, extraCls) {
    const created = m && m.created_at ? Date.parse(m.created_at) : NaN;
    const age = Number.isFinite(created)
      ? window.formatUnreadAge((Date.now() - created) / 1000) : "";
    return el("div", { class: "hrow " + (extraCls || "") }, [
      el("span", { class: "hfrom", text: "from " + String((m && m.from_terminal) || "?") }),
      el("span", { class: "htopic", text: String((m && m.topic) || "(no topic)") }),
      el("span", { class: "hid", text: "#" + String((m && m.id) || "?") }),
      age ? el("span", { class: "hage", text: age }) : null,
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
    else unacked.forEach((m) => s1.appendChild(msgEnvelope(m, "hrow-unacked")));
    msgBody.appendChild(s1);

    msgBody.appendChild(el("section", { class: "hsec" }, [
      el("h3", { class: "hsec-t", text: "Last message" }),
      last ? msgEnvelope(last, last.acked ? "hrow-acked" : "hrow-unacked")
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

  async function doMsgCopy() {
    if (!openMsgSlug) return;
    const row = stateBySlug.get(openMsgSlug) || {};
    const unacked = Array.isArray(row.unacked_messages) ? row.unacked_messages : [];
    const lines = unacked.map((m) =>
      "#" + String((m && m.id) || "?") + "  " + String((m && m.topic) || "(no topic)") +
      "  from " + String((m && m.from_terminal) || "?"));
    const payload = (msgTitle.textContent || openMsgSlug) + "\n" +
      (lines.length ? lines.join("\n") : "(no unacknowledged messages)");
    msgCopy.disabled = true;
    const ok = await copyToClipboard(payload);
    msgCopy.disabled = false;
    msgCopy.textContent = ok ? "copied ✓" : "copy failed";
    clearTimeout(msgCopy._t);
    msgCopy._t = setTimeout(() => { msgCopy.textContent = "Copy"; }, 1800);
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
  function statusChipText(meta, row, up) {
    if (meta.status_only) return meta.kind || "app";
    if (!up) return "down";
    if (row && row.ttyd_up === false) return "offline";
    const g = window.resolveGlanceState ? window.resolveGlanceState({
      unacked: (row && row.unacked_count) || 0,
      isWorking: !!(row && row.is_working),
      hasTelemetry: !!(row && row.has_telemetry),
      isDoneGreen: false,
      needsGo: !!(row && row.needs_go),
    }) : "";
    if (g === "WORKING") return "running";
    if (g === "NEW") return "unread";
    if (g === "UNKNOWN") return "no signal";
    return "idle";
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

    // State classes (color language preserved from the card design): app =
    // status-only, error = ttyd down, up/working, glance frame, or down.
    if (meta.status_only) {
      cls.push("app");
    } else if (up && row && row.ttyd_up === false) {
      cls.push("up", "error");
    } else if (up) {
      cls.push("up");
      const gc = glanceClass(row);
      if (gc) cls.push(gc);
      if (row && row.is_working) cls.push("working");
    } else {
      cls.push("down");
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
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openMsgSlug) closeMsgPanel(); });

  // ---- unread-bus notifications mute toggle (NOTIFY_SLICE) ----------------
  // The controller fires banners even with the page closed; this toggle only
  // reflects + flips the controller's persisted mute flag. localStorage gives an
  // instant default before the controller answers; the controller is authoritative.
  const NOTIFY_MUTE_KEY = "cockpit.notifyMuted";
  let notifyMuted = false;

  function applyNotifyUI() {
    if (!notifyToggle) return;
    notifyToggle.textContent = notifyMuted ? "🔕 Muted" : "🔔 Alerts";
    notifyToggle.setAttribute("aria-pressed", notifyMuted ? "true" : "false");
    notifyToggle.classList.toggle("muted", notifyMuted);
  }

  async function hydrateNotify() {
    // Default from localStorage first (instant), then reconcile with controller.
    try { notifyMuted = localStorage.getItem(NOTIFY_MUTE_KEY) === "1"; } catch (_e) {}
    applyNotifyUI();
    try {
      const r = await fetch(url("/api/notify/state"), FETCH_OPTS);
      if (r.ok) {
        const s = await r.json();
        notifyMuted = !!s.muted;
        try { localStorage.setItem(NOTIFY_MUTE_KEY, notifyMuted ? "1" : "0"); } catch (_e) {}
        applyNotifyUI();
      }
    } catch (_e) { /* offline: keep localStorage default */ }
  }

  async function toggleNotify() {
    const prev = notifyMuted;
    const next = !notifyMuted;
    notifyMuted = next;                       // optimistic UI
    try { localStorage.setItem(NOTIFY_MUTE_KEY, next ? "1" : "0"); } catch (_e) {}
    applyNotifyUI();
    try {
      const r = await fetch(url("/api/notify/mute"), {
        ...FETCH_OPTS, method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ muted: next }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      toast(next ? "Bus alerts muted" : "Bus alerts on", "ok");
    } catch (e) {
      // Persist failed — revert so the toggle never lies about the real state.
      notifyMuted = prev;
      try { localStorage.setItem(NOTIFY_MUTE_KEY, prev ? "1" : "0"); } catch (_e2) {}
      applyNotifyUI();
      toast("Notify toggle failed — " + e.message, "err");
    }
  }

  if (notifyToggle) notifyToggle.addEventListener("click", toggleNotify);

  async function boot() {
    try {
      const r = await fetch(url("/cockpit_layout.json"), FETCH_OPTS);
      if (!r.ok) throw new Error("layout HTTP " + r.status);
    layout = await r.json();
    } catch (e) {
      connEl.textContent = "layout load failed — " + e.message;
      connEl.className = "conn err";
      return;
    }
    render();                    // paint immediately from layout (metadata)
    renderSummary();
    hydrateNotify();             // reflect the controller's mute state on the toggle
    await poll();                // then hydrate with live state
    pollTimer = setInterval(poll, POLL_MS);
  }

  boot();
})();
