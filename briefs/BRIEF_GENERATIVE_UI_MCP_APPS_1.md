# BRIEF — Generative UI for Baker via MCP Apps

**Status:** Direction note / pre-ratification. Engineering-weighted (Step 2). Drafted for a second-pair-of-eyes review (Codex) before any build.
**Date:** 2026-06-20
**Owner:** AI Head A (with Director)
**Origin:** Director question 2026-06-20 — "can we co-create / improvise on a shared UI, like jazz?" Anchored to the talk *Beyond Components: Designing Generative UI for MCP Apps* — Ruben Casas, Postman (AI Engineer), https://youtu.be/hCMrEfPG2Yg

---

## 1. Plain-English summary (Director)

Today Baker answers in text. The idea: let the model *write the interface itself, live* — a small interactive panel (a deadline board, a matter timeline, a decision card with buttons) generated on the fly instead of pre-built screens. You react, it re-renders. That back-and-forth is the "jazz": shared sheet music (the UI), you set direction, Baker plays it back, you bend it.

Two horizons:
- **Now (zero build):** improvise on claude.ai Artifacts to find what's worth keeping.
- **Next (this note):** bake generative UI *into Baker* so it's permanent and wired to your data, riding the emerging **MCP Apps** standard — because Baker already speaks MCP.

This note is mostly about the "Next" engineering.

---

## 2. Why this is tractable for Baker specifically

Baker is already an MCP server: `baker_mcp/baker_mcp_server.py` (official `mcp` Python SDK, low-level `Server`, ~24 tools, each returning `list[TextContent]`). MCP Apps is precisely an extension of that return path — a tool can additionally return a **UI resource** (an HTML/JS template addressed by a `ui://` resource URI) that an MCP-Apps-capable host renders in a sandboxed iframe, with a `postMessage` bridge back to the server for actions.

So the seam already exists. The work is: (a) emit UI resources alongside text, (b) sandbox + secure them, (c) decide static-template vs model-generated HTML.

**Key architectural fact:** the *renderer is the host, not Baker.* Baker hands back UI; Claude desktop/web (or ChatGPT, or — later — our own cockpit acting as a host) draws it. This means our delivery surface question (§5) is as important as the server work.

---

## 3. Spec status — read before building (flag for Codex)

The space is young and the naming is unsettled. Two threads to disambiguate:
- **MCP Apps** — the term used in the talk; the official MCP interactive-UI direction (SEP under the modelcontextprotocol org).
- **MCP-UI** — the community library/spec (mcpui.dev) that several hosts already implement.

Both center on the same primitives: `ui://` resources, an iframe sandbox, and a host↔server `postMessage` channel. **Do not pin Baker to a moving target.** First engineering task is to confirm current spec/version + which hosts actually render it as of 2026-06, then decide whether to (a) adopt the official SEP, (b) use MCP-UI as the pragmatic shim, or (c) wait. This is the #1 question for the second reviewer.

---

## 4. Static templates vs fully generative HTML

The talk's thesis is "let the model write the frontend." Two flavors, different risk profiles:

| Mode | What it is | Pro | Con |
|---|---|---|---|
| **Templated UI resources** | Hand-authored HTML templates filled with tool data | Deterministic, auditable, cacheable, safe | Not really "improvised"; back to components |
| **Model-generated HTML** | Model authors the panel markup live per request | True jazz; flexible | Injection/secret-leak surface; non-deterministic; perf/cost |

Per project rule *"use AI for judgment, not deterministic work"*: the **data and actions must be deterministic**; only the **presentation** should be model-authored. Recommended target: model generates *layout/markup*, but it binds to a fixed, validated data payload and a fixed allow-listed action set — never free-form code that touches secrets or makes its own network calls.

---

## 5. Delivery-surface options

1. **Baker MCP server emits UI resources → rendered in an external host (Claude/ChatGPT).**
   - Pro: rides the standard; least custom code; works wherever Baker's MCP server is mounted.
   - Con: dependent on host support + spec stability; UI lives in someone else's chrome.
2. **Cockpit-native generative panel** (baker-master.onrender.com, FastAPI + vanilla JS): a server endpoint where Claude emits validated HTML that the cockpit renders in a sandboxed iframe.
   - Pro: ours end-to-end, wired to our data/auth, no dependency on external host rollout.
   - Con: we build the renderer + sandbox ourselves; doesn't ride the standard.
3. **Both, sharing one UI-resource contract** — server produces the same `ui://` payload; cockpit becomes an MCP *host* that renders it. Most work, best long-term.

---

## 6. Phased engineering plan

- **Phase 0 — Spike (1–2 days, throwaway, flagged off).** Pick one read-only tool (`baker_deadlines`). Return a templated UI resource in addition to `TextContent`. Render it in one MCP-Apps-capable host. Goal: prove the seam end-to-end, measure host support. No generative HTML yet.
- **Phase 1 — UI-resource contract + sandbox.** Define the `ui://` payload schema, iframe `sandbox` attributes, strict CSP, and the `postMessage` action bridge. Hard rule: **no secrets, no `X-Baker-Key`, no raw PII in emitted HTML**; actions go back through existing audited tool calls (`baker_actions` ledger), never new endpoints.
- **Phase 2 — Generative presentation.** Allow model-authored markup bound to a validated data payload + allow-listed actions. Add HTML sanitization + a render-time validator. Cache per (tool, args) where stable.
- **Phase 3 — Cockpit as host.** Implement option 5.2/5.3: cockpit renders the same contract natively, plugged into Baker auth + data.

Each phase ships behind a flag, read-only first, write-actions last and audited.

---

## 7. Risks / hard rules to honor

- **Security:** HTML/JS injection, secret leakage, exfiltration via model-authored markup. Mitigate: sandboxed iframe, strict CSP, sanitize, no secrets in payload, no arbitrary fetch. Tier-A merges must pass `/security-review` (Lesson #52).
- **Auth:** `X-Baker-Key` / `ALLOWED_ORIGINS` model must not be weakened by an embedded UI surface.
- **Determinism:** data + actions deterministic; only presentation generative (§4).
- **Fault tolerance:** all DB/API calls in try/except — a broken panel must degrade to text, never crash the tool.
- **No auto-send / no out-of-scope writes:** UI buttons route through existing audited, permission-gated tools only.
- **Spec churn:** §3 — pin a version, don't chase.

---

## 8. Open questions for the second reviewer (Codex)

1. **Spec readiness:** As of 2026-06, is the official MCP Apps SEP stable + rendered by enough hosts to build Phase 0 on, or do we start on MCP-UI as a shim and migrate? Which exactly?
2. **Surface:** Ride external hosts (§5.1) first, or invest in cockpit-native (§5.2) so we're not gated on host rollout?
3. **Generative boundary:** Is "model authors markup, fixed data + allow-listed actions" (§4) the right safety line, or too permissive / too strict?
4. **Sandbox model:** iframe + `postMessage` + CSP — any sharper pattern you'd insist on for an LLM-authored DOM?
5. **State model:** turn-taking (you nudge → re-render) vs. real-time shared state — is real-time worth the websocket/CRDT complexity for v1, or explicitly out of scope?

---

## 9. Recommendation

Build in this order, low-commitment first:
- **Step A (no engineering):** improvise on claude.ai Artifacts now to discover the 2–3 panels actually worth having.
- **Step B (Phase 0 spike):** prove the MCP-Apps seam on `baker_deadlines`, read-only, flagged off — *after* Codex answers Q1 (spec readiness).
- **Hold** Phases 2–3 until the spike + Codex review confirm the spec is stable and a surface is chosen.

Rationale: the seam is real and cheap to prove; the standard is not yet stable, so we de-risk with a throwaway spike and a second opinion before committing real build.
