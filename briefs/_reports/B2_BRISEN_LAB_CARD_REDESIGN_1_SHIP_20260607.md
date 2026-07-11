# B2 SHIP — BRISEN_LAB_CARD_REDESIGN_1

- **Dispatch:** cowork-ah1 #2168 (2026-06-07)
- **Repo:** brisen-lab (`~/bm-b2-brisen-lab`)
- **PR:** https://github.com/vallen300-bit/brisen-lab/pull/68
- **Branch:** `b2/brisen-lab-card-redesign-1` off fresh `origin/main` (90decf0)
- **Status:** MERGED 2026-06-07T10:45:57Z (squash to main, branch deleted; lead #2182). brisen-lab.onrender.com auto-deploys.
- **Gates final:** G3 codex PASS (#2178, commit 242f658) + G2 /security-review PASS (#2181, no exploitable findings).

## What
Front-end-only restyle + restructure of the Production & Lab board to the
Director-ratified locked mockup. No behaviour changes.
- Card: `dot · blue AG-### pill · bold display name · ···` (`···` replaces
  `[history]` text; same class + `data-history-alias` + handler).
- Fleet = 3×2 titled column grid (Orchestrators / Builders / Special Agents ·
  Research & Advisors / ClaimsMax Workers / Core Engine); membership 100%
  registry-`group`-driven; responsive wrap <1030px.
- Option-C bevel cards (248px fleet / 264px matter); matter panels recoloured
  Hagenauer-amber / Origination-red.

## Brief-premise correction (pre-approved lead #2172 + cowork-ah1 #2174)
`agent_registry.yml` has no `group` field (only `scope` + `agent_id`); `scope`
collides on 2 of 6 columns. `app.py`-serves-registry is not prod-viable (no vault
checkout on brisen-lab). So the generator derives the 6-column `group` + emits
`group`+`agentIds` to the JS artifact (`render_python` untouched → `.py` twins +
wake-listener zero-diff); app.js builds columns purely from that. +2-file diff
(generator + regenerated JS) accepted. Long-term: lead queuing a `lab_group`
vault field.

## Files (5)
`static/app.js`, `static/styles.css`, `static/index.html`,
`scripts/generate_agent_identity_artifacts.py`, `static/agent_identity_generated.js`.

## Gates
- node --check OK · py_compile OK · generator `--check` CLEAN.
- `git diff static/glance_state.js` EMPTY (HARD no-touch held).
- JS tests: resolver 8/8, glance-toggle 6/6.
- Identity invariants (drift, CARD_SLUGS⊆index.html, label format) pass.
- AC proof: registry `display_name` edit → artifact label changes, no app.js edit.
- Live render verified vs locked mockup via Chrome; click behaviour intact
  (card-body wakes, `···` opens history, shift-click opens detail).
- **G2 /security-review:** automated skill git-cwd-bound to baker-master worktree
  this session → manual security pass done (no new endpoints/auth/secrets; strict
  createElement+textContent, no innerHTML; generator emits via json.dumps).
  Recommended deputy run `/security-review` on PR #68 for a clean automated artifact.
- **G3 codex:** requested via bus (review/brisen-lab-pr-68, #2175).

## Bus
- Heads-up (premise): #2170 cowork-ah1, #2171 lead. Approvals: #2172 lead, #2174 cowork-ah1.
- Ship: #2176 lead, #2177 cowork-ah1. G3: #2175 codex.

## Known truncation (spec-faithful)
"Codex Reviewer"/"Codex Architect" (registry canonical names, guardrail #3) are
longer than the mockup's "Codex RT/ARCH" labels → ellipsis-truncate (mockup `.nm`
truncates identically), full label recovered on hover. Mockup floor names fit.
