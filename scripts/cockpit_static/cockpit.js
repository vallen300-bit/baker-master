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
  const BASE = location.origin;
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

  let layout = null;             // { plates: [{label, cards:[...]}, ...] }
  let stateBySlug = new Map();   // slug -> live /api/agents row
  let openSlug = null;           // currently open terminal, or null
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
      stateBySlug = m;
      // lab_glance_ok=false ⇒ the Lab telemetry source is down; every seat's
      // glance collapses to UNKNOWN. Surface it explicitly, don't read as idle.
      const labOk = data.lab_glance_ok !== false;
      const total = totalCardCount();
      connEl.textContent = "live · " + m.size + " driveable / " + total + " seats" +
        (labOk ? "" : " · ⚠ telemetry offline");
      connEl.className = labOk ? "conn ok" : "conn warn";
      render();
      syncPanelGo();             // reflect needs_go changes while the panel is open
    } catch (e) {
      connEl.textContent = "offline — " + e.message;
      connEl.className = "conn err";
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

  // ---- rendering ----------------------------------------------------------
  function card(meta) {
    const row = meta.driveable ? stateBySlug.get(meta.slug) : null;
    const up = row ? row.session_up === true : false;
    const cls = ["card"];
    let actions = null, unread = null;

    // E6 (Director, binding): NO state text row. State is color + affordance
    // only — dimmed+Start = down, bright = running, amber = unread, green tint +
    // GO = needs GO, red = offline. The only card words are name / slug / unread
    // badge+age / buttons.
    if (meta.status_only) {
      // Status-only (app / service / headless). E1: the recessed background IS
      // the app/terminal distinction; E3: no "APP" marker.
      cls.push("app");
    } else if (up && row && row.ttyd_up === false) {
      cls.push("up", "error");                    // red = offline (no words)
    } else if (up) {
      cls.push("up");                             // bright = running
      const gc = glanceClass(row);
      if (gc) cls.push(gc);                        // amber/green/cyan glance frame
      if (row && row.is_working) cls.push("working");
      // GO on the card face (§5.4) — ONLY when the seat is awaiting a GO.
      if (window.goAffordanceVisible(row)) {
        const goBtn = el("button", { class: "btn go", type: "button", text: "GO ⏎",
          onclick: (ev) => { ev.stopPropagation(); doGo(meta.slug, ev.currentTarget); } });
        actions = el("div", { class: "actions" }, [goBtn]);
      }
      if (row && row.unacked_count > 0) {
        unread = el("div", { class: "state" }, [
          el("span", { class: "unread", text: String(row.unacked_count) }),
          el("span", { class: ageClass(row.oldest_unacked_age_sec || 0),
                       text: window.formatUnreadAge(row.oldest_unacked_age_sec || 0) + " oldest" }),
        ]);
      }
    } else {
      cls.push("down");                           // dimmed + Start = down
      const startBtn = el("button", { class: "btn start", type: "button", text: "▶ Start",
        onclick: (ev) => { ev.stopPropagation(); doStart(meta.slug, ev.currentTarget); } });
      actions = el("div", { class: "actions" }, [startBtn]);
    }

    // E3: no TERMINAL / APP kind word — the background carries that. Only
    // service / headless keep a small badge pill (bg alone can't name them).
    const children = [];
    if (meta.badge) {
      children.push(el("div", { class: "top" }, [el("span", { class: "kind", text: meta.kind })]));
    }
    children.push(el("div", { class: "name", text: meta.display_name || meta.slug }));
    children.push(el("div", { class: "slug", text: meta.slug }));
    // Bottom-pinned group (margin-top:auto): the footer row + the context band.
    const bottom = [];
    // Compaction (Director #12264): unread badge + action button share ONE footer row.
    if (unread || actions) {
      bottom.push(el("div", { class: "footer" }, [unread, actions].filter(Boolean)));
    }
    // D4: context band — driveable seats with a known context_pct only; null →
    // hidden (never blocks render). 3px green→amber→red fill by usage + tiny label.
    if (meta.driveable && row && typeof row.context_pct === "number") {
      const pct = Math.max(0, Math.min(100, row.context_pct));
      bottom.push(el("div", { class: "ctx" }, [
        el("div", { class: "ctxbar" }, [el("div", { class: "ctxfill", style: "width:" + pct + "%" })]),
        el("div", { class: "ctxlbl", text: "ctx " + Math.round(pct) + "%" }),
      ]));
    }
    if (bottom.length) children.push(el("div", { class: "cardbottom" }, bottom));

    const c = el("div", { class: cls.join(" "), "data-slug": meta.slug }, children);
    if (!meta.status_only) {
      c.addEventListener("click", () => {
        const r = stateBySlug.get(meta.slug) || {};
        if (!r.session_up) { toast(meta.display_name + " is down — press Start first"); return; }
        // ttyd down ⇒ the proxy would 502; don't open a dead terminal frame.
        if (r.ttyd_up === false) { toast(meta.display_name + " — terminal server offline"); return; }
        openTerm(meta.slug, meta.display_name || meta.slug);
      });
    }
    return c;
  }

  function render() {
    if (!layout) return;
    const frag = document.createDocumentFragment();
    // grade-{i} drives the D3 stepped near-black plate ladder (6 grades).
    layout.plates.forEach((plate, i) => {
      const grid = el("div", { class: "grid" }, plate.cards.map(card));
      frag.appendChild(el("div", { class: "plate grade-" + i }, [
        el("h2", {}, [document.createTextNode(plate.label),
          el("span", { class: "count", text: plate.cards.length + " seats" })]),
        grid,
      ]));
    });
    gridEl.textContent = "";
    gridEl.appendChild(frag);
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
    hydrateNotify();             // reflect the controller's mute state on the toggle
    await poll();                // then hydrate with live state
    pollTimer = setInterval(poll, POLL_MS);
  }

  boot();
})();
