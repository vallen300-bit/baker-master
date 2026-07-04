# BRISEN_LAB_FORGE_TELEMETRY_DURABILITY_1

**Repo:** `brisen-lab` (base `main` @a7b78f9) · **Worker:** b1 · **Dispatcher:** lead (AH1)
**Recommended effort:** high (touches terminal-card render semantics + a scheduled server alarm; false-alarm discriminator logic is correctness-critical)
**Origin:** forge-pusher outage analysis 2026-07-04 — lead #5239 + cowork-ah1 #5240 (agreed path, lead #5246). The laptop `com.baker.forge-snapshot-push` launchd job died silently; dashboard kept showing green `has_telemetry` cards for hours. Root-cause class: **sticky boolean instead of derived freshness** — `has_telemetry=True` is a cached claim about the past rendered as present truth. Any client-push design fails again (sleep, Cowork worktree wipe, launchd unload, key rotation); the durable fix is server-side.

---

## Tasks (3 layers, cheapest first)

### T1 (P0) — Server render: derive staleness at read time
Terminal cards must go **grey/stale when `now - daemon_last_seen > 10 min`** (env `FORGE_TELEMETRY_STALE_MIN`, default 10), regardless of the stored `has_telemetry` flag. Recompute at render/API-read time — stop trusting the sticky boolean (ignore it or recompute it in `/api/v2/terminals`). A dead pusher must show honestly within minutes, forever.

### T2 (P0) — Server alarm via existing scheduler
Hook the existing TTL-sweep / fleet-refresh scheduled cadence (do NOT add a new scheduler): if fleet-wide `max(daemon_last_seen)` across laptop-hosted terminals is stale, post a `kind=alert` bus message to `lead`.
**Sleep-false-positive discriminator (required):** alarm ONLY if (a) bus events from laptop-hosted terminals occurred INSIDE the stale window (activity proves the laptop awake while the pusher is silent), OR (b) staleness > 24h continuous. Asleep laptop = no sessions = no alarm.
Rate-limit: max 1 alert per stale episode (don't re-alert every sweep tick; clear on freshness recovery).

### T3 (P1) — Client plist hardening
`com.baker.forge-snapshot-push` plist (in baker-master `scripts/` or wherever `install_forge_push.sh` sources it — locate it): add `KeepAlive=true` + `RunAtLoad=true`. Commit the plist + a one-line install command to a how-to note. Foot-gun warning in the how-to: install ONLY from a Terminal session — Cowork overlay wipes `~/Library` writes within ~15s (lived incident 2026-07-04). If the plist lives in baker-master not brisen-lab, do T3 as a separate small baker-master PR on branch `b1/forge-push-keepalive-1`.

## Constraints
- Additive + reversible. No schema drops; if T1 needs a migration it must be idempotent.
- All DB calls in try/except.
- Reject the Mini-relocation idea if you're tempted — analyzed and rejected (#5240): Mini was never a forge host; asleep laptop = nothing to report anyway.
- Tests first: T1 staleness derivation + T2 discriminator are pure-logic — unit-test both before wiring.

## Acceptance criteria (= definition of done from #5240)
1. Kill the pusher manually ⇒ cards grey within ≤10 min (T1).
2. Same episode with in-window bus activity ⇒ exactly ONE `kind=alert` bus msg to lead (T2).
3. Stale window with NO in-window laptop bus activity and <24h ⇒ NO alarm (sleep discriminator test).
4. Freshness recovery ⇒ cards green again, alert state cleared.
5. Reboot/login ⇒ pusher self-resumes with zero manual steps (T3 — assert plist keys; live reboot test is lead's).
6. Existing tests green; new unit tests for AC1-AC4 logic.
7. Live post-deploy AC verdict on the bus per `post-deploy-ac-bus-gate` before DONE (T1/T2 deploy with brisen-lab).

## Notes for worker
- `daemon_last_seen` already exists server-side (surfaced in `/api/v2/terminals`) — this brief derives from it, no new client fields.
- You shipped the dashboard fixlist (#5215) — card render code is fresh for you.
- Laptop-hosted terminal set: derive from `agent_identity_generated.py` host metadata if present; else hardcode the alias list with a comment pointing at the registry (surface which in ship report).
- Branch: `b1/forge-telemetry-durability-1`. PR to `main`, ship report + gate verdicts to lead on bus.
