# BRIEF: WAKE_BACKGROUND_NONINTRUSIVE_1 — agent wakes stop stealing the Director's screen

## Context
Director's screen fills with terminal windows (see 2026-06-20 screenshot: ~10 stacked windows). Root cause: **every addressed bus message wakes the recipient and FOREGROUNDS its Terminal window**, and nothing ever closes them. He shrinks each by hand → crowding. He asked for "a better solution to watch and direct all agents."

The watch surface already exists — the **Brisen Lab dashboard** (agent cards AG-101…AG-205 with live status). The fix is to make wakes **non-intrusive**: agents wake and work in the **background**; a window comes to the **front** only when (a) the Director himself clicks a dashboard card, or (b) an agent hits a real blocker that needs him. Everything else nudges silently.

This is a **design-review brief** — it goes to **Codex Architect (AG-203)** for G0 before any code. Three open design questions are flagged `→ AG-203` at the end; the implementer must confirm the VERIFY items against live code.

Director request 2026-06-20 (cowork-ah1 chat): *"recommend better solution for me to watch and direct all agents… Lead sends bus — recipient agent window opens. Any stays on my screen. I just make them smaller — hence the crowdness."* Greenlit `go`.

### Surface contract
- **Surface:** macOS Terminal window focus behavior on agent wake + the Brisen Lab dashboard as the canonical watch surface. No new dashboard DOM in this brief (watch surface already shipped).
- **Trigger:** server emits `wake_request` (bus auto-wake OR manual `/api/wake`) → `wake-listener.py` → `Brisen Lab Wake.app` AppleScript → Terminal nudge/spawn.
- **States:** (1) session already open → background nudge, no focus steal; (2) session closed + builder slug → background spawn; (3) Director dashboard click → foreground (he asked to look); (4) blocker/escalation topic → foreground (agent needs him); (5) noise kind (ack/heartbeat) → suppressed entirely.
- **Auth/visibility:** unchanged — same WAKEABLE_TERMINALS allowlist + master kill-switch. cowork-ah1 already excluded from Terminal wake (Claude.app instance).
- **No-collateral guarantee:** manual dashboard wake MUST still foreground (do not regress the Director's own "open this agent" click).

## Estimated time: ~3–4h (incl. AppleScript recompile + .app redeploy + tests)
## Complexity: Medium (cross-repo: brisen-lab Python + Mac-side AppleScript + LaunchServices recompile)
## Prerequisites: AG-203 design APPROVE on the 3 open questions below.

---

## Context Contract (Harness V2)
- **Task class:** fleet-infra / developer-tooling (brisen-lab repo + Mac-side wake handler). NOT baker-master.
- **Repos touched:** `bm-b1-brisen-lab` (server `bus.py`, `app.py`, tests); `bm-b2/brisen-lab/tools/wake-handler/wake-handler.applescript` (canonical AppleScript source, mirrored to bm-b1/b3/b4); `~/.brisen-lab/wake-listener.py` (Mac daemon).
- **Deploy path:** server → Render auto-deploy on brisen-lab `main`. AppleScript → `osacompile` into `~/Applications/Brisen Lab Wake.app/Contents/Resources/Scripts/main.scpt` + re-register via `~/.brisen-lab/register-url-handler.sh`. wake-listener.py → restart LaunchAgent `com.baker.wake-listener`.
- **Done rubric:** see §Verification — answered as pass/fail, not "tests passed."
- **Gate plan:** G0 design = AG-203 (this brief). G3 code review = `codex` (independent). Post-deploy AC = `POST_DEPLOY_AC_VERDICT v1` after live proof.
- **Harness-V2:** applies.

---

## Fix 1 — Carry foreground-intent from server to the AppleScript

### Problem
The wake URL is `brisen-lab://wake/<alias>` with no priority/intent. The AppleScript can't tell a Director click from a routine FYI, so it foregrounds everything.

### Current State
- `bm-b1-brisen-lab/bus.py:534-543` emits `wake_request` with `terminal_alias`, `source` ("bus_msg"), `msg_id` — **no foreground flag**.
- `bm-b1-brisen-lab/app.py:498-502` (`/api/wake`, the dashboard-click path) emits `wake_request` with `source` = (VERIFY actual value, likely "manual"/"api").
- `~/.brisen-lab/wake-listener.py:94` shells `subprocess.run(["open", f"brisen-lab://wake/{alias}"], …)` — drops every field except alias.

### Engineering Craft Gates
- **Diagnose:** applies. Feedback loop = post a test bus message + watch whether Terminal jumps to front. Hypotheses ranked in scout map (foreground at lines 270/271 nudge, 328 spawn, 229 error). Regression probe = AppleScript log line "fg=<bool> path=<nudge|spawn>".
- **Prototype:** applies (UI/focus behavior on macOS is the real uncertainty) — see Fix 2, throwaway AppleScript focus-restore spike, delete-or-absorb after AG-203 picks the mechanism.
- **TDD/verification:** applies server-side — `tests/test_bus_autowake*.py` asserts the new `foreground` field value per source/kind. Client AppleScript verified by live probe (no honest unit seam for `open -a`).

### Implementation
1. **Server — add `foreground` to the `wake_request` payload.** In `bus.py` auto-wake emit (around 534-543) and `app.py` `/api/wake` emit (around 498-502), add a computed boolean:
   ```python
   # bus.py — auto-wake (bus_msg source). Foreground when EITHER (a) the recipient
   # is a director-facing role the Director reads live (ROLE-SPLIT, Director-ratified),
   # OR (b) the message is a real "needs-Director" signal. Workers stay background.
   # (Keys off topic-prefix + tier_required + kind=ratify_required per G0 ruling Q3 —
   # the `kind` enum has no blocker/etc.)
   # AUTHORITATIVE SOURCE = the GENERATED WAKEABLE_TERMINALS (agent_identity_generated.py).
   # Builder MUST classify each member of WAKEABLE into VISIBLE or STEALTH at build time;
   # default any unclassified wakeable slug to VISIBLE (foreground = fail to current behavior).
   # Do NOT modify the registry/generator/tests to de-wakeable any slug — out of scope.
   # codex #3765 correction: clerk-haiku IS wakeable (test_agent_identity_generated.py:47)
   # → classified STEALTH (worker). clerk + cortex are NOT in WAKEABLE → not classified.
   VISIBLE_SLUGS = {"lead","deputy","deputy-codex","researcher","codex","codex-arch",
                    "aid","hag-desk","origination-desk","ao-desk","russo-ai"}  # director-facing
   STEALTH_SLUGS = {"b1","b2","b3","b4","CM-1","CM-2","CM-3","CM-4",
                    "hag-filer","clerk-haiku"}  # workers = background
   FG_TOPIC_PREFIXES = ("blocker", "incident", "needs-director", "needs_director")
   _topic = (row.get("topic") or "").lower()
   foreground = (
       recipient in VISIBLE_SLUGS                              # ROLE-SPLIT: heads visible
       or _topic.startswith(FG_TOPIC_PREFIXES)
       or (row.get("kind") or "").lower() == "ratify_required"
       or (row.get("tier_required") or "").lower() == "director_only"
   )  # gate-request alone stays background for STEALTH slugs
   broadcast_fn({
       "kind": "wake_request",
       "terminal_alias": recipient,
       "occurred_at": datetime.now(timezone.utc).isoformat(),
       "source": "bus_msg",
       "msg_id": row["id"],
       "topic": row.get("topic"),
       "msg_kind": row.get("kind"),          # diagnostics only
       "tier_required": row.get("tier_required"),  # diagnostics only
       "foreground": foreground,             # listener decides off THIS bool
   })
   ```
   ```python
   # app.py — manual /api/wake (Director clicked a card): always foreground.
   _broadcast({
       "kind": "wake_request",
       "terminal_alias": alias,
       "occurred_at": datetime.now(timezone.utc).isoformat(),
       "source": "manual",
       "foreground": True,
   })
   ```
2. **wake-listener.py — pass it through the URL.** At `~/.brisen-lab/wake-listener.py:83-94`, read `foreground` from the event and append a query param:
   ```python
   def dispatch_wake(alias, foreground=False):
       fg = "1" if foreground else "0"
       url = f"brisen-lab://wake/{alias}?fg={fg}"
       subprocess.run(["open", url], check=False, capture_output=True, text=True)
   ```
   And at the SSE handler (≈184-187): `dispatch_wake(alias, bool(msg.get("foreground", False)))`.

### Key Constraints
- Default when `fg` is MISSING/invalid = **foreground** (preserve current behavior; an old listener sending a no-query URL ⇒ handler foregrounds — phased-deploy safe). Background happens ONLY via an explicit `fg=0` that the NEW server computed and the listener forwarded. Consistent with the rollback flag (off ⇒ foreground=true) and the Parse-URL invariant below. (codex #3783 Finding 2: brief must pick ONE default — this is it.)
- Do not change `WAKEABLE_TERMINALS` or the master kill-switch logic.

---

## Fix 2 — AppleScript: background by default, foreground only on `fg=1`

### Problem
`wake-handler.applescript` foregrounds on the nudge path (lines 270-271), the spawn path (line 328 `open -a Terminal` inherently activates), and the error path (line 229).

### Current State
- `bm-b2/brisen-lab/tools/wake-handler/wake-handler.applescript:270` `set frontmost of (first window whose id is wId) to true`
- `:271` `set selected of targetTab to true`
- `:328` `do shell script "open -a Terminal " & quoted form of cmdPath`
- `:229` error window `open -a Terminal` (same focus steal)

### Implementation
1. **Parse `fg` from the URL** in `on open location` (after stripping the `brisen-lab://wake/` prefix and the alias): set `wantFg` to true iff query contains `fg=1`.
2. **Nudge path (≈266-296): gate the focus steal.** Keep the `do script "check bus"` injection (the agent must still receive the nudge). Wrap lines 270-271:
   ```applescript
   do script "check bus" in targetTab
   if wantFg then
       set frontmost of (first window whose id is wId) to true
       set selected of targetTab to true
   end if
   -- background nudge: window keeps working, no focus steal
   ```
3. **Spawn path (≈322-328): launch without activation unless `fg`.** `open -a Terminal` always activates Terminal. Two candidate mechanisms — **AG-203 to choose (Q1)**:
   - **(A) Focus-restore:** capture the frontmost app before spawn, spawn, then re-activate the prior app:
     ```applescript
     tell application "System Events" to set priorApp to name of first process whose frontmost is true
     do shell script "open -a Terminal " & quoted form of cmdPath
     if not wantFg then
         delay 0.4
         tell application priorApp to activate
     end if
     ```
   - **(B) No-spawn-on-background:** if `not wantFg` AND no live session found, **do not spawn at all** — let the agent drain its inbox on next manual open / SessionStart. New windows then appear ONLY on a Director click or a foreground topic. (Simpler; risk = a closed builder won't auto-start for background work.)
4. **Error path (≈229): never foreground**, and consider logging to `~/.brisen-lab/wake-listener.stderr.log` instead of popping a Terminal window at all (the "no terminal picker installed for alias code" window in the screenshot is pure noise).

### Key Constraints
- The nudge injection (`do script "check bus"`) must STILL fire in background mode — backgrounding hides the window, it must not skip the wake.
- `fg=1` path must behave exactly as today (Director-click + blocker must foreground).
- After editing the canonical source, recompile + redeploy (see §Deploy) — editing the `.applescript` alone does nothing; the running app uses the compiled `main.scpt`.

---

## Fix 3 — Server topic-gate: suppress pure-noise wakes (conservative)

### Problem
Post-PR #78 there is NO topic-gate — acks and heartbeats wake their recipient. These never need a screen.

### Current State
`bus.py:443-544` auto-wake hook gates on master-switch, per-slug disable, debounce (5s), hourly cap (20), ping-pong loop detect — but **not** on kind/topic (PR #78 removed the over-aggressive #77 gate).

### Implementation
Add a **narrow** suppress set at the top of the recipient loop (before emit), distinct from the foreground set in Fix 1:
```python
# G0 ruling Q2: smallest deny-list. kind=ack is the only suppressed kind;
# heartbeat is a TOPIC PREFIX (not a valid kind today). Do NOT add fyi/dispatch/
# broadcast/gate-request — that was the #78 over-suppression failure.
# Audit per existing schema (db.py:379-381): NULL suppressed_reason = fired,
# non-NULL = skipped. Set a DISTINCT reason before continue (codex #3786 Finding 1).
_kind  = (row.get("kind") or "").lower()
_topic = (row.get("topic") or "").lower()
suppressed_reason = None
if _kind == "ack":
    suppressed_reason = "suppressed_ack"
elif _topic.startswith("heartbeat"):
    suppressed_reason = "suppressed_heartbeat"
if suppressed_reason:
    # Use the EXISTING async helper (codex #3788 nit): bus.py exposes
    # `_audit_wake_event(msg_id, sender_slug, recipient, reason)` — existing suppress
    # branches call `await _audit_wake_event(row["id"], sender_slug, recipient, reason)`.
    await _audit_wake_event(row["id"], sender_slug, recipient, suppressed_reason)  # non-NULL => skipped row
    continue
# (fired wakes fall through and record suppressed_reason=NULL, per the existing path)
```
**#78 lesson (anchor `project_wake_delivery_two_layer_failure_2026-06-18.md`):** the prior gate suppressed too much (fyi/investigation/cleanup) and broke real delivery. Keep this set TINY — ack + heartbeat only. **AG-203 to confirm the set (Q2).**

### Key Constraints
- Suppress is deny-list (tiny), NOT allow-list — anything not explicitly noise still wakes (background, per Fix 1).
- Keep the audit trail: log suppressed wakes so we can prove nothing important was dropped.

---

## Files Modified
- `bm-b1-brisen-lab/bus.py` — `foreground` flag on auto-wake emit; `SUPPRESS_KINDS` gate.
- `bm-b1-brisen-lab/app.py` — `foreground: True` on manual `/api/wake` emit.
- `~/.brisen-lab/wake-listener.py` — pass `foreground` through the `brisen-lab://` URL as `?fg=`.
- `bm-b2/brisen-lab/tools/wake-handler/wake-handler.applescript` — parse `fg`; gate nudge/spawn/error foreground.
- `bm-b1-brisen-lab/tests/test_bus_autowake*.py` — assert `foreground` value per source/kind + suppress set.

## Do NOT Touch
- `WAKEABLE_TERMINALS` / picker alias→cwd map (lines 41-66) — wake routing is correct; only focus behavior changes.
- Master kill-switch / per-slug disable / debounce / hourly cap / ping-pong loop detector — orthogonal, working.
- cowork-ah1 exclusion (AppleScript 186-194) — already correct (Claude.app instance).
- Stale-kill logic (lines 259-264) unless AG-203 says otherwise — out of scope for the focus fix.

## Quality Checkpoints
1. Post a routine bus `msg` to an already-open agent → it drains "check bus" but the window does NOT jump to front.
2. Click the agent's card on the Brisen Lab dashboard → its window DOES come to front (manual wake unregressed).
3. Post a `blocker`-kind message → recipient foregrounds (agent-needs-Director path works).
4. Post an `ack` → no wake at all (suppressed; audit row present).
5. Wake an alias with no picker → no error Terminal window pops (logged instead).
6. Verify on the Director's actual Mac (not just CI) — focus behavior is OS-level.

## Verification
- **Done rubric (answer each pass/fail):**
  1. Routine bus message to a live session → background nudge, zero focus steal? 
  2. Dashboard card click → foreground works?
  3. Blocker topic → foreground works?
  4. ack/heartbeat → suppressed + audited?
  5. Unknown alias → no popped window?
  6. Recompiled `.app` deployed + URL handler re-registered + listener restarted?
- **Server tests:**
  ```bash
  cd ~/bm-b1-brisen-lab && python -m pytest tests/test_bus_autowake*.py -v
  ```
- **Live probe (Director's Mac):** add a temporary log line in the AppleScript (`do shell script "echo fg=" & wantFg & " path=nudge >> ~/.brisen-lab/wake-listener.stderr.log"`), fire each wake type, tail the log, then remove the probe.

## POST_DEPLOY_AC_VERDICT
Emit `POST_DEPLOY_AC_VERDICT v1` to the bus after live proof on the Director's Mac (all 6 done-rubric rows answered).

---

## G0 RULINGS — codex-arch #3586 (LOCKED — implement EXACTLY; supersedes inline snippets where they conflict)

**Verdict:** APPROVE_WITH_REQUIRED_RULINGS. codex-arch verified the live schema and corrected my VERIFY guesses. **These rulings are the source of truth.**

**Schema corrections (use these, not my guesses):**
- `brisen_lab_msg.kind` enum = ONLY `{dispatch, ack, broadcast, ratify_required, ratify_decision}` (db.py:305-308). My proposed kinds (`blocker/escalation/needs_director/gate_request`) DO NOT EXIST — do not key off them.
- There is **no `priority` field**. Available signals: `kind`, `topic` (prefix), `tier_required`. Live topic prefixes include: `gate-request`, `blocker`, `fyi`, `incident`, `request-changes`.
- Manual `/api/wake` currently emits `wake_request` with `terminal_alias` ONLY (app.py:498-502) → must ADD `foreground: true`.
- Bus auto-wake emits with `source/msg_id/topic` (bus.py:586-593) → add computed `foreground`.
- wake-listener opens `brisen-lab://wake/<alias>` only (wake-listener.py:83-95) → append `?fg=`.
- Focus steal confirmed: nudge `frontmost/selected` (wake-handler:267-271), spawn `open -a Terminal` (wake-handler:328).

**Q1 — SPAWN BACKGROUNDING = HYBRID:**
1. Nudge (live session): ALWAYS inject `check bus`; if `fg=0` do NOT set `frontmost`/`selected`; if `fg=1` foreground allowed.
2. Spawn `fg=1`: foreground for all wakeable aliases.
3. Spawn `fg=0` + builder `b1-b4`: MAY spawn, then capture/restore prior frontmost app after ~0.4s (builders must auto-start when closed).
4. Spawn `fg=0` + heads/desks/specialists/codex/researcher: do NOT spawn a window. Log/audit `background_absent_no_spawn`; rely on dashboard stale/open badges + manual card click.
5. Error path: log only; no Terminal error window for background wakes.

**Q2 — SUPPRESS = smallest deny-list:**
1. Suppress autonomous wake for `kind=ack`.
2. `heartbeat` = a topic PREFIX only (not a valid `kind` today) — suppress by topic prefix if it exists.
3. Do NOT suppress `fyi/dispatch/broadcast/gate/gate-request` by content (#78 lesson). Broadcasts to `*` already don't wake (`*` is not a picker slug).

**Q3 — FOREGROUND LOGIC = topic-prefix + tier_required + kind (NOT nonexistent kinds):**
1. Add `foreground` bool to `wake_request`.
2. Manual `/api/wake` → `foreground=true`.
3. Bus auto-wake default → `foreground=false`.
4. Bus auto-wake `foreground=true` ONLY when: topic prefix ∈ {`blocker`, `incident`, `needs-director`/`needs_director`} OR `kind=ratify_required` OR `tier_required=director_only`.
5. `gate-request` STAYS background by default (a B-tier design gate must not steal the screen).
6. Include `msg_kind` + `tier_required` in the SSE `wake_request` for diagnostics, but the listener decides off the explicit `foreground` bool.

**TEST GATES (codex-arch, all must pass live):**
1. Normal dispatch → live non-builder: injects `check bus`, no foreground.
2. Normal dispatch → closed non-builder: no window spawned, records `background_absent_no_spawn`.
3. Normal dispatch → closed b1-b4: spawns + restores prior frontmost app.
4. Manual dashboard click: foregrounds.
5. blocker/incident/needs-director OR ratify_required: foregrounds.
6. fyi/gate-request dispatch: stays background.
7. ack: does not wake.
8. Missing/invalid `fg`: defaults **foreground** (preserve current behavior; phased-deploy safe).

> **NOTE (codex #3786):** these 8 codex-arch gates predate the Director ROLE-SPLIT and are **SUPERSEDED where they conflict** by the role-split + the deputy-codex gate set in §"DEPUTY-CODEX NITS" #6. Specifically: gate 2 (closed non-builder) — a closed **VISIBLE** agent SPAWNS+foregrounds (only closed **STEALTH** workers background-spawn); gate 6 — fyi to a **VISIBLE** recipient foregrounds. Implement the role-split gates as the source of truth.

## ROLE-SPLIT — Director-ratified 2026-06-21 (SUPERSEDES codex-arch Q1#4 + Q3 for the director-facing tier)

The Director reads his director-facing agents live and only wants the **worker** windows quieted. So foreground policy splits by ROLE, not by builder-vs-rest:

- **VISIBLE set** (`lead, deputy, deputy-codex, researcher, codex, codex-arch, aid, hag-desk, origination-desk, ao-desk, russo-ai`): behave **like today** — a message foregrounds the window (spawn + front if closed; bring to front if open). The Director watches these. (`codex-arch` is VISIBLE but the handler intentionally no-ops it — it's a codex app, not a Terminal picker — so "like today" = no Terminal pop. Fine per deputy-codex #3732.)
- **STEALTH set** (`b1-b4, CM-1..4, hag-filer, clerk-haiku`): **background** — live session gets a silent `check bus` nudge (no focus steal); closed worker background-spawns via `open -g` (opens to work, no focus steal). Never clogs the screen. (`clerk-haiku` IS wakeable per codex #3765 — classified worker/STEALTH.)
- **NOT wakeable Terminal targets** (`clerk, cortex`): not in WAKEABLE — do NOT classify or write spawn tests for them. `cowork-ah1` stays a deliberate no-op (Claude.app). The generated WAKEABLE_TERMINALS is the authoritative membership list; classify whatever it contains.
- **Override for everyone:** a high-priority message (topic prefix `blocker`/`incident`/`needs-director`, OR `kind=ratify_required`, OR `tier_required=director_only`) foregrounds regardless of set.
- **Suppress for everyone:** `kind=ack` (+ `heartbeat` topic prefix) → no wake.

**Behavior matrix (routine, non-priority message):**

| Recipient set | Session open | Session closed |
|---|---|---|
| VISIBLE (heads) | nudge + foreground (like before) | spawn + foreground (like before) |
| STEALTH (workers) | nudge, NO focus steal | background-spawn, NO focus steal |

This means codex-arch's ruling Q1#4 ("heads/desks/codex/researcher should NOT spawn") is **overridden** — those are VISIBLE and DO spawn+foreground. The slug sets are an explicit config so the split is tunable without code surgery. cowork-ah1 stays excluded (Claude.app, not a Terminal picker).

## DEPUTY-CODEX NITS — PASS-WITH-NITS #3732 (LOCKED — bake into the builder brief)

Second-pair review verdict: **PASS-WITH-NITS, dispatchable.** Main implementation risk is URL-query parsing/defaults, NOT the role-split concept. Builder must implement all 7:

1. **Background spawn = `open -g -a Terminal <cmdPath>`** (open in background, no focus steal) — selected over the capture-frontmost→reactivate-after-0.4s dance (avoids timing/race + no Accessibility/System Events). Keep plain `open -a Terminal` only for `foreground=true`. Fallback to capture/restore ONLY if smoke shows Terminal ignores `-g` for `.command` files. Evidence: foreground of existing tabs at `wake-handler.applescript:324-329`; spawn at `:430-431`.
2. **Parse the URL query BEFORE alias matching.** Today the handler strips only the prefix (`wake-handler.applescript:232-234`) → without query parsing the alias becomes `b1?fg=0` and hits the unknown-alias error path. **Invariant: missing/invalid `fg` ⇒ `foreground=true`** (preserves current behavior + enables phased deploy). Manual `/api/wake` always emits `foreground=true`; bus auto-wake computes the role-split.
3. **Deploy = Render + two local installs (not just local scripts):**
   - Server/bus changes → brisen-lab **Render deploy/merge** (bus wake payload at `bus.py:586-593` has no `foreground` field today).
   - Local handler → run `tools/wake-handler/build.sh` (osacompiles, signs, registers URL scheme, installs re-register LaunchAgent — `build.sh:16-45,47-69`).
   - Local listener → run `tools/wake-listener/install.sh` (copies `wake-listener.py`, bootout/bootstrap restarts `gui/$UID/com.baker.wake-listener` — `install.sh:26-37`).
4. **Role-split caveats:** `clerk` + `cortex` NOT wakeable (not in WAKEABLE; `test_agent_identity_generated.py:41` locks clerk non-wakeable). `clerk-haiku` IS wakeable (`test_agent_identity_generated.py:47`) → STEALTH worker. `codex-arch` WAKEABLE but handler no-ops it (`wake-handler.applescript:245-251`) — VISIBLE but no Terminal pop = "like today". `ao-desk`/`russo-ai` were unclassified → added to VISIBLE. Default any future unclassified wakeable slug to VISIBLE.
5. **Foreground/suppress as pure helpers:** `foreground = recipient ∈ VISIBLE_SLUGS OR kind==ratify_required OR tier_required==director_only OR topic.startswith(blocker/ | incident/ | needs-director/)`. `suppress = kind==ack OR topic.startswith(heartbeat/)`. Do NOT reintroduce broad topic-priority gating — its removal is documented at `bus.py:82-108` + `test_bus_wake_topic_gate.py:1-13`. Only ack/heartbeat-suppress + high-priority-foreground are added.
6. **Test gates (supersede/extend the 8 above):**
   - *Server pure:* visible→fg true; stealth→false; stealth+ratify_required/director_only/blocker→true; ack + heartbeat→suppress.
   - *Server integration:* `wake_request` payload carries `foreground`; `wake_events` audit records fired/suppressed; `/api/wake`→fg true.
   - *Listener unit:* `dispatch_wake(alias, foreground)` opens `brisen-lab://wake/<alias>?fg=1|0`, preserves `ALLOWED_ALIASES` validation.
   - *Handler compile/static:* `wake/b1?fg=0` parses alias `b1`; background nudge does NOT set frontmost/selected; background spawn uses `open -g`; foreground path = current behavior; missing fg defaults foreground.
   - *Regression:* preserve PR #80 guards — `isAliasLive`, `acquireSpawnLock`, spawn lock, spawn self-delete `rm -f "$0"`.
7. **Rollback flag:** add `BRISEN_LAB_WAKE_ROLE_SPLIT_ENABLED` (default **false/off** until deploy smoke). When off/missing → emit `foreground=true` + skip the ack/heartbeat suppress = fail to current behavior. (`BRISEN_LAB_AUTOWAKE_ENABLED` is the master kill but too blunt for rollback — it kills wakes rather than restoring foreground.)

## CODEX (AG-202) FINDINGS — #3765 (folded; final verify gate)

1. **REQUIRED — clerk-haiku is wakeable (FIXED above).** origin/main `agent_identity_generated.py:18` has `clerk-haiku` in `WAKEABLE_TERMINALS`; `test_agent_identity_generated.py:47` asserts it; generator `generate_agent_identity_artifacts.py:122-126` makes every runtime except service/headless wakeable. So `clerk-haiku` cannot be treated as non-wakeable without registry/generator/test surgery (out of scope). Resolution: `clerk-haiku` → STEALTH (worker). Builder classifies the GENERATED WAKEABLE set; does NOT de-wakeable anything.
2. **SHOULD — audit suppressions PER EXISTING SCHEMA (do not break the NULL-means-fired contract).** `db.py:379-381` + `test_bus_autowake_containment.py:281-306`: a FIRED wake row has `suppressed_reason = NULL`; non-NULL = skipped. So keep `suppressed_reason = NULL` for fired wakes and set a distinct reason ONLY for suppressions: `suppressed_ack`, `suppressed_heartbeat`. The `foreground` decision is observable on the `wake_request` SSE payload — NOT in `suppressed_reason`. If `wake_health` must PERSIST foreground, that is a SEPARATE `foreground` boolean column + migration + tests — OPTIONAL follow-on, explicitly NOT in this MVP. (codex #3783 Finding 1.)
3. **SHOULD — state manual-wake scope (role-split is BUS-ONLY).** The role-split governs **bus auto-wake** foreground computation only. **Manual `/api/wake` (dashboard click) is ALWAYS `foreground=true`** regardless of role — Director explicitly clicked. Dashboard click-wakeability still derives from generated `wakeableTerminals` (`static/app.js:1040`) — unchanged. Master-off still preserves manual `/api/wake` (`test_autowake_master_killswitch.py:393-395`) — unchanged.

## AH1 devil's-advocate (counter-case)
1. **Backgrounding could hide a stuck agent** — if an agent silently errors, no window pops to tell the Director. Mitigation: the dashboard card must show error/stall state (verify it does) before we rely on it.
2. **Focus-restore (option A) is notoriously flaky** — `delay 0.4` races; under load the prior app may not re-activate. Option B sidesteps this entirely; favor it where possible.
3. **"Better way to watch" may be bigger than wakes** — the real ask might be a single tiling cockpit, not 10 windows at all. This brief fixes the intrusion; a follow-on could add a unified multi-agent view. Flag, don't scope-creep here.
4. **Tiny suppress set risks creep** — every future "this is noisy too" tempts adding to SUPPRESS_KINDS until we re-break delivery (the #77 failure). Keep it deny-list-tiny and audited.
