# BRIEF: BRISEN_LAB_CORTEX_DRILLDOWN_1 — make Cortex card drillable with open-ratify-required view

## Context

Director clicked the Cortex card on the Brisen Lab dashboard 2026-05-18 evening — nothing opened. Root cause: `static/app.js:10` declares `SYSTEM_CARDS = ["cortex", "cowork-ah1"]`; the click-handler guard at `static/app.js:703` skips drill-down for any alias in that list (`if (SYSTEM_CARDS.includes(c.dataset.alias)) return;`). With PR #220 + PR #221 + PR #222 shipped (cortex heartbeats now route correctly to `daemon` for phases + `director` for ratify-required), the Cortex card has meaningful state to surface — open ratify-required envelopes — and Director needs to click into it to ratify-or-dismiss without leaving the dashboard. A secondary wire-contract bug (`app.js:502`) means the "Director-consult: N open Qs" banner never increments because it tests `msg.msg_kind === "ratify_required"` while actual envelopes use `topic = "cortex/<m>/ratify-required"`.

This brief = the smallest valuable drill-down (Option C of the AH1/Director planning exchange 2026-05-18). v1 ships open-ratify-required view + counter fix. Recent-cycles + raw-envelopes view deferred to v2 only if Director requests.

## Estimated time: ~45-60 builder-minutes
## Complexity: Low
## Prerequisites
- PR #20 brisen-lab cowork-ah1 visibility merged (b46d46c, 2026-05-18) — confirmed.
- PR #222 baker-master cortex heartbeat recipient fix merged (044c925, 2026-05-18) — confirmed; ratify-required envelopes now flow to `to=["director"]` with `topic="cortex/<matter>/ratify-required"`.
- Greenfield: `git log --oneline --grep="cortex" -i --grep="drilldown" -i` returns no prior implementation (already verified 2026-05-18 by AH1 in EXPLORE step).

---

## Fix 1 — Remove cortex from the non-drillable list

### Problem
The cortex card's click handler is short-circuited by the `SYSTEM_CARDS` guard. Currently both `"cortex"` and `"cowork-ah1"` are excluded. Removing cortex (leave cowork-ah1) is the minimum-blast-radius unlock.

### Current State
`static/app.js` line 10 (verified by `grep -n SYSTEM_CARDS static/app.js`):
```js
const SYSTEM_CARDS = ["cortex", "cowork-ah1"];
```

Guard at line 703 (verified):
```js
document.querySelectorAll(".card").forEach(c => {
  if (SYSTEM_CARDS.includes(c.dataset.alias)) return;  // system cards not drillable
  c.addEventListener("click", () => {
    state.detailAlias = c.dataset.alias;
    renderDetail();
  });
});
```

### Implementation
Edit `static/app.js:10` — remove `"cortex"`, keep `"cowork-ah1"`:
```js
const SYSTEM_CARDS = ["cowork-ah1"];
```

NO change to line 703 — the guard is correct, it just no longer matches cortex.

### Key Constraints
- Do NOT remove `"cowork-ah1"` from `SYSTEM_CARDS`. Cowork-ah1 has its own `renderCoworkCard()` renderer and no drill-down view exists for it — drilling into it would render an empty modal, regressing UX (worse than current).
- Do NOT touch the L703 click-handler wiring — it remains correct.

### Verification
- After deploy, clicking the Cortex card opens the `#terminal-detail` dialog (verify by visual smoke).
- Clicking the Cowork (AH1) card still does nothing (regression check).

---

## Fix 2 — Render open-ratify-required section in cortex detail view

### Problem
The generic `renderDetail()` reads `state.terminals.find(t => t.slug === alias).recent_messages` (per `static/app.js:322`). But `recent_messages` is keyed per-RECIPIENT in `/api/v2/terminals` (verified in `bus.py:1042` — `recent_msgs.get("cortex", [])`). Cortex envelopes are sent FROM cortex TO `daemon`/`director`, so cortex's `recent_messages` array is empty. The generic detail would show "(no bus messages)" — confusing UX worse than non-clickable.

### Current State
`static/app.js:307-341` — `renderDetail()` body (verified):
```js
function renderDetail() {
  const dlg = document.getElementById("terminal-detail");
  const alias = state.detailAlias;
  document.getElementById("detail-title").textContent =
    TERMINAL_LABELS[alias] || "";
  const body = document.getElementById("detail-events");
  clear(body);

  // Bus inbox section — synchronous read from cached terminals payload.
  const busSection = el("section", { cls: "detail-bus-section" });
  busSection.appendChild(el("h3", { cls: "detail-section-title", text: "Bus inbox" }));
  const busList = el("div", { cls: "detail-bus-list" });
  busSection.appendChild(busList);
  body.appendChild(busSection);

  const cardData = (state.terminals || []).find(t => t && t.slug === alias);
  const msgs = cardData ? (cardData.recent_messages || []) : [];
  if (msgs.length === 0) {
    busList.appendChild(el("div", { cls: "bus-empty", text: "(no bus messages)" }));
  } else {
    for (const m of msgs) {
      const row = el("div", {
        cls: "bus-row" + (m.acked ? " bus-row-acked" : " bus-row-unacked"),
      });
      row.appendChild(el("span", { cls: "bus-id", text: "#" + m.id }));
      // ... rows ...
    }
  }
  // Forge events section ...
}
```

Bus-message ingestion at `static/app.js:488-505` (`handleBusMsg`) currently:
- Updates `state.busLast[recipient]` per recipient (line 491)
- Increments `state.cortex.open_director_qs` ONLY when `msg.msg_kind === "ratify_required"` (line 502 — broken, see Fix 3)
- Does NOT buffer cortex sent envelopes anywhere accessible to `renderDetail()`

### Implementation

#### Step 2.a — Add a client-side cortex sent-envelope buffer

In `static/app.js`, modify `state` initializer at lines 39-44 (verified):
```js
  cortex: {        // synthesized state from bus envelopes
    open_director_qs: 0,
    last_phase: null,
    last_phase_ts: 0,
    last_cost: null,
    openRatify: new Map(),    // NEW — keyed by msg id; value = { topic, body, created_at, matter }
  },
```

In `handleBusMsg(msg)` at line 488, add tracking inside the existing `if (msg.from === "cortex" || …)` block. Replace lines 497-505 with:
```js
  if (msg.from === "cortex" || (msg.topic && msg.topic.startsWith("cortex/"))) {
    if (msg.topic && msg.topic.includes("/cycle-phase/")) {
      state.cortex.last_phase = msg.topic.split("/").pop();
      state.cortex.last_phase_ts = Date.now();
    }
    // Fix 3 (counter bug) — see Fix 3 section for rationale.
    if (msg.topic && msg.topic.endsWith("/ratify-required") && msg.id != null) {
      const matter = (msg.topic.split("/")[1]) || "";
      state.cortex.openRatify.set(msg.id, {
        id: msg.id,
        topic: msg.topic,
        body: msg.body || "",
        created_at: msg.created_at || null,
        matter,
      });
      state.cortex.open_director_qs = state.cortex.openRatify.size;
    }
  }
```

#### Step 2.b — Branch renderDetail() to a custom cortex view

In `static/app.js`, at the TOP of `renderDetail()` (immediately after `clear(body);` — line ~313), add a cortex-only branch BEFORE the existing Bus-inbox section:
```js
  if (alias === "cortex") {
    renderCortexDetail(body);
    return;
  }
```

Then add a new `renderCortexDetail(body)` function (suggest placement: immediately after `renderDetail()` ends, before `renderCoworkCard()` at line ~252; final placement up to b1):
```js
function renderCortexDetail(body) {
  // Section 1: open ratify-required (highest priority)
  const ratifySection = el("section", { cls: "detail-ratify-section" });
  ratifySection.appendChild(el("h3", {
    cls: "detail-section-title",
    text: "Open ratify-required (" + state.cortex.openRatify.size + ")",
  }));
  const list = el("div", { cls: "detail-ratify-list" });
  ratifySection.appendChild(list);
  body.appendChild(ratifySection);

  const rows = Array.from(state.cortex.openRatify.values())
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
    .slice(0, 25);

  if (rows.length === 0) {
    list.appendChild(el("div", { cls: "ratify-empty", text: "(no open ratify-required envelopes)" }));
    return;
  }

  for (const r of rows) {
    const row = el("div", { cls: "ratify-row", attrs: { "data-msg-id": String(r.id) } });
    row.appendChild(el("span", { cls: "ratify-id", text: "#" + r.id }));
    row.appendChild(el("span", { cls: "ratify-matter", text: r.matter || "(unknown)" }));
    row.appendChild(el("span", {
      cls: "ratify-age",
      text: r.created_at ? timeAgo(r.created_at) : "",
    }));
    // Body excerpt — first 100 chars, plain text (XSS-safe: el() uses textContent).
    const excerpt = (r.body || "").slice(0, 100);
    row.appendChild(el("span", { cls: "ratify-body", text: excerpt }));

    // Action buttons
    const actions = el("span", { cls: "ratify-actions" });
    const cycleIdMatch = (r.body || "").match(/cycle_id=([0-9a-f-]+)/);
    const cycleId = cycleIdMatch ? cycleIdMatch[1] : null;

    const openBtn = el("button", {
      cls: "ratify-btn ratify-btn-open",
      text: "Open in baker-master",
    });
    if (cycleId) {
      openBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        window.open(
          "https://baker-master.onrender.com/api/cortex/gate/decide?cycle_id=" + encodeURIComponent(cycleId),
          "_blank",
          "noopener,noreferrer"
        );
      });
    } else {
      openBtn.disabled = true;
      openBtn.title = "No cycle_id in body — cannot open";
    }
    actions.appendChild(openBtn);

    const dismissBtn = el("button", {
      cls: "ratify-btn ratify-btn-dismiss",
      text: "Dismiss as probe",
    });
    dismissBtn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      dismissBtn.disabled = true;
      dismissBtn.textContent = "Dismissing...";
      try {
        const resp = await fetch("/msg/" + r.id + "/ack", { method: "POST" });
        if (!resp.ok) {
          dismissBtn.disabled = false;
          dismissBtn.textContent = "Dismiss as probe";
          console.warn("[cortex-detail] ack failed", resp.status);
          return;
        }
        // Live DOM update: remove this row + decrement counter + re-render card (no full reload).
        state.cortex.openRatify.delete(r.id);
        state.cortex.open_director_qs = state.cortex.openRatify.size;
        row.remove();
        // Update section header count
        const header = ratifySection.querySelector(".detail-section-title");
        if (header) header.textContent = "Open ratify-required (" + state.cortex.openRatify.size + ")";
        // Re-render the card to update the Director-consult banner immediately.
        renderCortexCard();
        // If list now empty, show empty placeholder.
        if (state.cortex.openRatify.size === 0) {
          list.appendChild(el("div", { cls: "ratify-empty", text: "(no open ratify-required envelopes)" }));
        }
      } catch (err) {
        dismissBtn.disabled = false;
        dismissBtn.textContent = "Dismiss as probe";
        console.warn("[cortex-detail] ack threw", err);
      }
    });
    actions.appendChild(dismissBtn);
    row.appendChild(actions);

    list.appendChild(row);
  }
}
```

### Key Constraints
- Use `el()` helper (line 52 — verified) for ALL DOM construction. It applies `textContent` (XSS-safe) — never use `innerHTML` (Lesson #43 phantom-helper risk + XSS). Confirmed `el()` exists.
- Use `clear()` helper (line 63 — verified) only for the body wipe. Cortex detail re-renders by closing + reopening (existing pattern), NOT by clearing mid-life.
- Use `timeAgo(iso)` helper (line 67 — verified) for ALL relative timestamps.
- Do NOT add a new server endpoint in v1. The client-side buffer (Step 2.a) handles this end-to-end.
- Do NOT auto-clear `state.cortex.openRatify` on page reload — it rehydrates from SSE replay (server snapshots historical events on connect). If rehydration doesn't include them, the empty state is a known v1 limitation; addressed in v2.
- Live DOM update on dismiss (Lesson: "Triage updates invisible" — dismiss must remove row + decrement count + re-render card BEFORE any modal-close, not on next reload).

### Verification
Manual smoke after deploy:
1. Fire a Cortex cycle (any matter) — `curl -X POST https://baker-master.onrender.com/api/cortex/trigger -H "X-Baker-Key: $BAKER_KEY" -H "Content-Type: application/json" -d '{"matter_slug":"mrci","triggered_by":"director_manual","director_question":"v1 drilldown smoke"}'`. Cycle should land `tier_b_pending` ~75-120s; a `cortex/<matter>/ratify-required` envelope arrives.
2. Open dashboard. Cortex card shows "Director-consult: 1 open Q" badge.
3. Click cortex card. Modal opens with "Open ratify-required (1)" section + one row.
4. Click "Open in baker-master" — opens baker-master URL in new tab with the cycle_id query string.
5. Click "Dismiss as probe" — row removes instantly, header counter decrements to 0, modal stays open showing "(no open ratify-required envelopes)", card's Director-consult badge disappears (live, no reload).
6. Click cowork-ah1 card — nothing happens (regression check passes).
7. Click any other card (lead/deputy/b1/b2/b3/b4) — generic Bus-inbox + Activity modal opens (no regression).

---

## Fix 3 — Counter wire-contract bug

### Problem
`static/app.js:502` increments `state.cortex.open_director_qs` ONLY when `msg.msg_kind === "ratify_required"`. Real envelopes (PR #220 + PR #221 + PR #222) carry `kind: "dispatch"` and `topic: "cortex/<matter>/ratify-required"`. The `msg_kind` field is never present, so the counter never increments. The "Director-consult: N open Qs" banner has been silently dead since PR #220 merged.

### Current State
`static/app.js:497-505` (verified):
```js
  if (msg.from === "cortex" || (msg.topic && msg.topic.startsWith("cortex/"))) {
    if (msg.topic && msg.topic.includes("/cycle-phase/")) {
      state.cortex.last_phase = msg.topic.split("/").pop();
      state.cortex.last_phase_ts = Date.now();
    }
    if (msg.msg_kind === "ratify_required") {     // ← never matches
      state.cortex.open_director_qs += 1;
    }
  }
```

### Implementation
Already folded into Fix 2 (Step 2.a). The replacement block in Step 2.a derives `open_director_qs` from `openRatify.size` and tests `msg.topic.endsWith("/ratify-required")` — both correct against the live wire contract verified in production envelope #494 (matter=mrci, 2026-05-18 evening).

No SEPARATE diff for Fix 3 — it lands inside Fix 2.

### Key Constraints
- Counter MUST be `openRatify.size` (not a free-running increment) so the dismiss path can decrement it correctly.
- Topic test MUST be `.endsWith("/ratify-required")` (with hyphen), NOT `.endsWith("/ratify_required")` (underscore) — verified against envelope #494 topic.

### Verification
1. With dashboard open, fire a fresh ratify-required envelope (Cortex cycle). Card shows "Director-consult: 1 open Q" within ~1-2s (SSE latency).
2. Dismiss via Fix 2 button. Banner disappears live.
3. Hard-reload page after dismiss. Banner stays absent (no stale increment). [Limitation: if server replays acked envelopes through SSE on reload, banner may briefly flash — known v1 limitation per Key Constraints in Fix 2.]

---

## Fix 4 — Cache-bust + CSS additions

### Problem
- `static/index.html:7` has `?v=7` on styles.css; `:76` has `?v=9` on app.js. Per Lesson #4, BOTH must bump on any CSS or JS change to avoid stale-cache regression on iOS PWA + desktop browsers.
- The new ratify-section + ratify-row + button classes referenced in Fix 2 don't exist in `styles.css`.

### Current State
`static/index.html` (verified):
```html
  <link rel="stylesheet" href="/static/styles.css?v=7">
  ...
  <script src="/static/app.js?v=9"></script>
```

### Implementation

#### 4.a — Bump cache-bust

`static/index.html:7`:
```html
<link rel="stylesheet" href="/static/styles.css?v=8">
```

`static/index.html:76`:
```html
<script src="/static/app.js?v=10"></script>
```

#### 4.b — Add CSS classes

Append to `static/styles.css` (after the existing detail-section classes — exact placement at b1's discretion):
```css
/* BRISEN_LAB_CORTEX_DRILLDOWN_1 — open ratify-required section */
.detail-ratify-section { margin-bottom: 1.5rem; }
.detail-ratify-list { display: flex; flex-direction: column; gap: 0.5rem; }
.ratify-row {
  display: grid;
  grid-template-columns: 60px 100px 80px 1fr auto;
  gap: 0.5rem;
  align-items: center;
  padding: 0.5rem 0.75rem;
  background: var(--card-bg, #1c1f24);
  border-radius: 4px;
  font-size: 0.85rem;
}
.ratify-id { font-family: monospace; color: var(--muted, #888); }
.ratify-matter { font-weight: 600; }
.ratify-age { color: var(--muted, #888); font-size: 0.8rem; }
.ratify-body { color: var(--text, #ddd); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ratify-actions { display: flex; gap: 0.5rem; }
.ratify-btn {
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
  border: 1px solid var(--border, #444);
  background: transparent;
  color: var(--text, #ddd);
  border-radius: 3px;
  cursor: pointer;
}
.ratify-btn:hover:not(:disabled) { background: var(--hover-bg, #2a2e35); }
.ratify-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ratify-btn-dismiss { border-color: var(--warn, #c97f4a); }
.ratify-empty { color: var(--muted, #888); font-style: italic; padding: 0.5rem; }
```

### Key Constraints
- Use CSS variables (`var(--card-bg)`, etc.) where they exist in the codebase. If b1 finds a different set of variables in `styles.css`, swap to those — the literal hex fallbacks are conservative defaults.
- Do NOT introduce a new CSS file or new `<link>` in index.html — append to the existing `styles.css`.

### Verification
- After deploy on a Director iOS PWA AND a desktop Chrome, hard-reload the page. New CSS applies (ratify section has spacing, buttons have hover state). If iOS PWA shows old style, the cache-bust failed — check `index.html` got the `?v=8 / v=10` bump.

---

## Files Modified
- `static/app.js` — Fix 1 (L10, remove cortex from SYSTEM_CARDS), Fix 2 (state init L39-44 + handleBusMsg L497-505 + renderDetail L307-313 + new renderCortexDetail function ~50 LOC), Fix 3 (folded into Fix 2)
- `static/index.html` — Fix 4.a (cache-bust bump styles `?v=7→v=8`, app `?v=9→v=10`)
- `static/styles.css` — Fix 4.b (append ~22 LOC for ratify-section + ratify-row + buttons + empty state)

## Do NOT Touch
- `static/app.js` cowork-ah1 renderer (`renderCoworkCard` ~L253) — out of scope, do not regress
- `bus.py`, `app.py`, `authz.py`, `auth_lab.py` — server stays as-is in v1 (the client-side buffer handles the data need; if v2 ever ships, server endpoint extension goes there)
- `baker-master` entirely — zero coupling
- Any other terminal card renderer
- The `SYSTEM_CARDS` array's `"cowork-ah1"` entry — cowork-ah1 stays non-drillable (no detail view exists for it)

## Quality Checkpoints
1. **Cache-bust bumped** — both styles `?v=8` AND app `?v=10` in index.html. Hard-reload on iOS PWA verifies (Lesson #4).
2. **No new `innerHTML`** — all DOM via `el()` helper (XSS-safe; verified `el()` exists at L52). Phantom-helper risk: do NOT reference `_escHtml()` or similar (Lessons table — known phantom).
3. **Dismiss button live-updates DOM** — row removes, counter decrements, card re-renders, NO modal close, NO page reload (Lesson: "Triage updates invisible").
4. **Regression check** — clicking lead/deputy/b1/b2/b3/b4 cards opens generic detail (unchanged). Clicking cowork-ah1 still does nothing.
5. **Fix 3 counter validated against live envelope #494** — topic format confirmed `cortex/mrci/ratify-required` (hyphen, not underscore). Brief writer (AH1) owns this assertion — if envelope shape differs in production, brief is wrong.
6. **Ack endpoint auth** — `POST /msg/<id>/ack` requires Policy.AUTH_ONLY (verified in `bus.py:446`); the dashboard's same-origin session cookie carries auth. Director must be the recipient OR Director (line 467-468 — director_recipient OK). Confirm Director's session is active when smoking.
7. **No new endpoint added on brisen-lab server** — verified by `grep -n "@app.\|@router\." brisen-lab-staging/*.py | wc -l` BEFORE vs AFTER (count should match).
8. **No `--no-verify`, no force-push, no secret in code** — standard contract.

## Verification SQL (server-side smoke, optional)
Run from the lab Postgres to confirm the test envelope #494 (or its tomorrow-equivalent) exists with the expected topic format:
```sql
SELECT id, from_terminal, to_terminals, topic, kind,
       (acknowledged_at IS NOT NULL) AS acked
FROM brisen_lab_msg
WHERE from_terminal = 'cortex'
  AND topic LIKE 'cortex/%/ratify-required'
ORDER BY id DESC
LIMIT 5;
```

Expected: rows with `kind = 'dispatch'`, `topic = 'cortex/<matter>/ratify-required'` (hyphen), `to_terminals = {director}` (post-PR-#222 fixes).

---

## Ship gate

- PR opened against brisen-lab main from branch `b1/cortex-drilldown-1`.
- Trigger class: LOW — UI-only change; no auth/DB/external surface; ≤120 LOC across 3 files. AH2 Gate 1 (cross-lane static) required; Gate 2 (/security-review) SKIP-eligible per brief — no auth/DB change, XSS guarded by `el()` helper, no new endpoint, no secret handling (matches PR #20 brisen-lab precedent).
- Commit identity: `Code Brisen #1 <b1@brisengroup.com>`.
- Standard contract: no `--no-verify`, never bypass hooks.
- Bus-post `ship/brisen-lab-cortex-drilldown-1` to `lead` on PR open. AH1 (lead) merges under standing Tier A on green verdict.

## Out of scope (do NOT include — v2 territory)

- "Recent cycles" section grouped by cycle_id (parse from envelope body) — defer to v2 brief if Director wants it after v1 lands.
- "Raw envelopes" fallback list — same, v2.
- Server-side endpoint `recent_sent` for cortex slug in `/api/v2/terminals` — not needed in v1; if v2 lands, that's where it goes.
- Slack / WhatsApp push for ratify-required — separate brief tracked from 2026-05-18 discussion ("route ratify-required to phone").
- Making cowork-ah1 drillable — separate brief if Director ever wants it.
- Auto-ratify / auto-dismiss — Director-only authority; do not automate.

---

**Anchor:** Director observation 2026-05-18 evening — *"When I click on Cortex, nothing opens up"* + AH1 EXPLORE pass discovering (a) `SYSTEM_CARDS` guard at L703, (b) wire-contract bug at L502 (`msg_kind` vs `topic` mismatch), (c) `recent_messages` per-recipient schema that makes generic detail view useless for cortex. Director approved Option C (smallest valuable ship) 2026-05-18 evening — open-ratify-required view + counter fix + cache-bust, no server change, recent-cycles defer to v2.
