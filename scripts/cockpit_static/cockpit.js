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
  const toastEl = document.getElementById("toast");

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
    if (g === "NEEDS_GO") return "glance-needs-go";
    if (g === "WORKING") return "glance-working";
    if (g === "NEW") return "glance-new";
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

  function openTerm(slug, name) {
    openSlug = slug;
    termTitle.textContent = name + " — live terminal";
    syncPanelGo();
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
  }

  // ---- rendering ----------------------------------------------------------
  function card(meta) {
    const row = meta.driveable ? stateBySlug.get(meta.slug) : null;
    const up = row ? row.session_up === true : false;
    const cls = ["card"];
    let stateText, actions = null, statusOnly = null, unread = null;

    if (meta.status_only) {
      // Any non-driveable active seat: app (app-*), service, headless. Reuse
      // the .app status-only styling; the kind pill + badge carry the family.
      cls.push("app");
      const label = meta.app_seat ? "app seat" : (meta.badge || "status only");
      stateText = label;
      statusOnly = el("div", { class: "statusonly", text: "status only — " + label + ", no terminal" });
    } else if (up && row && row.ttyd_up === false) {
      // tmux session is alive but its ttyd terminal server is unreachable:
      // opening would 502. Show an explicit error state (§7) — no GO, no open.
      cls.push("up", "error");
      stateText = "terminal offline";
    } else if (up) {
      cls.push("up");
      const gc = glanceClass(row);
      if (gc) cls.push(gc);
      if (row && row.is_working) cls.push("working");
      // UNKNOWN telemetry must read differently from a live idle seat.
      stateText = gc === "glance-unknown" ? "session up · no telemetry" : "session up";
      // GO on the card face (§5.4) — ONLY when the seat is actually awaiting a
      // GO. Sending Enter into a non-confirmation prompt is unsafe, so gate
      // strictly on needs_go (shared predicate, see panel GO below).
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
      cls.push("down");
      stateText = "session down";
      const startBtn = el("button", { class: "btn start", type: "button", text: "▶ Start",
        onclick: (ev) => { ev.stopPropagation(); doStart(meta.slug, ev.currentTarget); } });
      actions = el("div", { class: "actions" }, [startBtn]);
    }

    // AG pill dropped (D2). The kind pill (TERMINAL / APP / SERVICE / …) is the
    // only top-row marker now.
    const kind = meta.kind || (meta.status_only ? "APP" : "TERMINAL");
    const top = el("div", { class: "top" }, [
      el("span", { class: "kind", text: kind }),
    ]);
    const nameEl = el("div", { class: "name", text: meta.display_name || meta.slug });
    // Card face must carry the slug alongside display name (scope §5.2) — the
    // slug is the address every bus/tmux action uses, so it belongs on the face.
    const slugEl = el("div", { class: "slug", text: meta.slug });
    const stateEl = el("div", { class: "state" }, [
      el("span", { class: "dot" }), el("span", { text: stateText }),
    ]);

    const children = [top, nameEl, slugEl, stateEl];
    if (statusOnly) children.push(statusOnly);
    // Compaction (Director #12264): the unread badge and the action button share
    // ONE footer row so the crowded state stays 5 rows — the name is never
    // squeezed and the uniform card height stays low.
    if (unread || actions) {
      children.push(el("div", { class: "footer" }, [unread, actions].filter(Boolean)));
    }

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
    await poll();                // then hydrate with live state
    pollTimer = setInterval(poll, POLL_MS);
  }

  boot();
})();
