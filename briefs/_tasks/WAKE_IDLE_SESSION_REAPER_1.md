---
status: SCOPING
brief_id: WAKE_IDLE_SESSION_REAPER_1
to: (unassigned — dispatch next session)
from: lead
dispatched_by: lead
authored_at: 2026-06-22
task_class: infra-reliability
repo: brisen-lab (launchd + reaper script) — pattern mirrors baker-codex-reaper
harness_v2: applies
gate_plan: G1 self-test (DRY_RUN logs correct candidates, never kills a busy session) → G2 deputy-codex (false-positive/safety review) → G3 deputy → lead G4 + install → 48h live watch
source_of_truth: this session's 3 wake-trap incidents (lead #3784, b2 #3795, b1 #3918/#3919) + Director GO 2026-06-22
---

# BRIEF (SCOPING) — WAKE_IDLE_SESSION_REAPER_1

## PROBLEM (observed 3× this session)

A wake-spawned agent session stays **alive but idle/stale** and silently squats the wake slot:
1. The duplicate-spawn guard (PR #80/#81) correctly refuses to spawn a 2nd session while one exists.
2. An alive session does NOT auto-poll its bus inbox (no intra-session push).
3. Net: new bus messages to that agent are neither woken-to nor seen — the agent is unreachable until manually cycled.

**Incidents:** lead (#3784 — Director had to paste manually), b2 (#3795 — "didn't wake"), b1 (#3919 — stale 5.5h `claude check bus`, PID 5968, blocking cowork-ah1's PR #82). Each needed a manual SIGTERM + re-ping. Does not scale.

## WHY THE EXISTING REAPER DOESN'T COVER IT

`baker-codex-reaper` (`com.baker.codex-reaper.plist`) reaps **spinning orphans**: NO-TTY + PPID==1 + >90% CPU + age>600s. Today's squatters are the OPPOSITE profile: real TTY, real shell parent, **LOW** CPU (~1-5%), just old + idle. The CPU/orphan gates exclude them. We need a distinct detector.

## ROOT CAUSE

Two individually-correct mechanisms combine into a trap: (a) duplicate-spawn guard + (b) no intra-session push. When a session goes idle-but-alive, both fire and the agent is stranded.

## OPTIONS

1. **Idle-stale wake-session reaper (RECOMMENDED).** launchd watcher mirrors the codex-reaper install pattern; detects stale wake sessions and SIGTERMs them so the next bus message re-spawns fresh. Lowest risk, reuses proven pattern.
2. **Wake-can-poke-existing-session.** Wake handler injects the new message into the live session instead of suppressing. Hard — Claude Code sessions can't be reliably fed external input; high risk.
3. **Per-worker self-poll** (like the lead self-poll built this session). Adds token cost to every session; long sessions die (no self-compaction). Band-aid, not a fix.

## RECOMMENDED DESIGN (Option 1)

**Detection — reap ONLY when ALL hold (busy sessions must fail at least one):**
1. Process is a `brisen-lab-wake-<role>.command` session (or its `claude` child).
2. Age > **THRESH_AGE** (default 90 min — tunable `BAKER_WAKE_REAP_MIN_ETIME`).
3. The role has **unacked inbox messages** on the bus older than **THRESH_UNACK** (default 15 min) — i.e. work is waiting and the session isn't taking it. (Query `GET /msg/<role>` for `acknowledged_at==null` older than threshold.)
4. The role has posted **nothing to the bus** (no ship/heartbeat/ack/gate) in **THRESH_SILENT** (default 20 min) — a working agent emits heartbeats; a stale one is silent.
5. Sustained low CPU on two samples (NOT actively computing) — excludes a session mid-long-task.

The (unacked-inbox-waiting AND bus-silent AND old) triple is the precise squatter signature; a genuinely-busy agent posts heartbeats and acks, failing #3/#4.

**Action on reap:** SIGTERM the session; log to `~/Library/Logs/baker-wake-reaper.log`; then **post a synthetic re-ping** to that role's bus (or rely on the next real message) so a fresh session spawns and drains the backlog. (Killing alone won't re-trigger — a NEW bus event is what wakes; the reaper must emit one or the next sender does.)

**Install (mirror codex-reaper, TCC-safe):**
- Script: `~/Library/Application Support/baker-wake-reaper/reap.sh` (Application Support, NOT Desktop — [[feedback_macos_tcc_launchd_blocks_desktop]]).
- LaunchAgent: `~/Library/LaunchAgents/com.baker.wake-reaper.plist`, `StartInterval` 300s + RunAtLoad; `launchctl bootstrap gui/$(id -u)`.
- Env tunables: `BAKER_WAKE_REAP_MIN_ETIME`, `BAKER_WAKE_REAP_UNACK_AGE`, `BAKER_WAKE_REAP_SILENT`, `DRY_RUN=1`.

**Kill-criteria (safety — when NOT to reap):** any of: role has bus activity within THRESH_SILENT; no unacked inbox (nothing waiting → idle-but-fine); CPU spike (mid-task); session younger than THRESH_AGE. Ship with `DRY_RUN=1` first; promote to live only after the log shows it would have caught the 3 real incidents and zero busy sessions over a 24h dry run.

## ACCEPTANCE CRITERIA

- AC1 DRY_RUN over ≥24h logs every stale-squatter; ZERO false positives on busy sessions (verified vs bus heartbeat timeline).
- AC2 Live reap frees the wake slot AND a fresh session drains the backlog within one wake cycle.
- AC3 Reaper never kills a session that posted to the bus within THRESH_SILENT.
- AC4 Reaper never kills a session with no unacked inbox (idle-but-not-blocking is fine).
- AC5 Replays the 3 recorded incidents (lead/b2/b1) → reaper would have caught all 3.
- AC6 Tunable via env; `DRY_RUN` honored; logs only on action.

## NON-GOALS
1. Do not modify the wake handler / duplicate-spawn guard itself (orthogonal; PR #80/#81 stay).
2. Do not replace the codex-orphan-reaper (different profile; both run).
3. Do not build intra-session push (Option 2) in this brief.

**Status:** SCOPING — ready to dispatch. Builder TBD (b-code); brisen-lab repo. Director GO to scope given 2026-06-22.
