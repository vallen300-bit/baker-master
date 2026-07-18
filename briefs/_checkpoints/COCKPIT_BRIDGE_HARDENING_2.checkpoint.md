---
brief_id: COCKPIT_BRIDGE_HARDENING_2
attempt: 1
dispatched_by: lead (bus #12867, P1/P2)
report_topic: gates/cockpit-bridge-hardening-2
repos:
  - brisen-lab b1/cockpit-bridge-hardening-2 @3a19f20d (D1 + D3)
  - baker-master b1/cockpit-bridge-hardening-2 @651b320d (D2 + D4 + runbook; codex #12968 fix)
status: codex BOUNCE #12974 (P2 #12968) RESOLVED — D4 rotation made atomic+non-destructive. New baker-master tip @651b320d pushed. Awaiting lead re-dispatch of codex on exact head -> merge both -> Render deploy -> live AC1-AC5 verdict (post-deploy, lead flips flag).
gate: codex bus-seat gate both tips + /security-review (done, clean) + codex-arch P2 re-verify -> lead merge
---

# COCKPIT_BRIDGE_HARDENING_2 — checkpoint

Brief: `briefs/_tasks/COCKPIT_BRIDGE_HARDENING_2.md` @a17e9288. Source: codex #12861 + codex-arch #12834-36.

## Done (shipped, rebased, pushed)
- **D1 (P1, brisen-lab):** revoke watcher — `revoke_watcher()` (~3s sweep) started in app `_startup()`;
  `CockpitBridge.enforce()` revokes on flag-off OR key-rotation; `revoke()` resets all streams (tears down
  terminal pumps + in-flight HTTP) then closes the agent socket. Runbook `cockpit-cloud-access.md` restored
  to one-step server kill (supersedes lead's interim two-step warning).
- **D3 (P2, brisen-lab):** `_auth_key` stored at attach (`attach(ws, auth_key=presented)` in app.py);
  `_key_rotated()` compares to current env key; watcher drops the socket on rotation.
- **D2 (P2, baker-master):** `resolve_bridge_key()` — removed generic `BRISEN_LAB_TERMINAL_KEY` fallback;
  dedicated `BRISEN_LAB_COCKPIT_BRIDGE_KEY` / cockpit-bridge cache / cockpit-bridge 1P only.
- **D4 (P2, baker-master):** `install_cockpit_ttyd.sh` generates per-seat `credentials.d/<slug>` (0600, random),
  embeds per-plist; `COCKPIT_TTYD_ROTATE=<slug>` atomic single-seat rotation; `COCKPIT_TTYD_PER_SEAT_CREDS=0`
  legacy. Agent `resolve_ttyd_cred_path()` injects per-seat with shared fallback (positional slug parse refuses
  empty/traversal). Controller-owned shared cred (#12074) NOT touched — new namespace.

## Tests (all green)
- brisen-lab: `tests_unit/test_cockpit_bridge.py` + `test_cockpit_mux.py` -> 83 passed (+8 D1/D3).
- baker-master: `tests/test_cockpit_bridge_agent.py` -> 16 passed (+D2/D4); `tests/test_cockpit_ttyd_per_seat_creds.sh` PASS.
- /security-review: clean, no HIGH/MEDIUM.

## codex #12968 fix (this session)
`scripts/install_cockpit_ttyd.sh` `seat_credential()`: replaced the up-front `rm -f "$f"`
on `COCKPIT_TTYD_ROTATE` with a `rotate=1` flag that only SKIPS the reuse branch. The old
cred file is untouched until the single atomic `mv` overwrites it once a fully-validated
replacement exists — any failure before the mv (openssl/mktemp/write) `die`s with the old
cred intact. Added guard #4 to `tests/test_cockpit_ttyd_per_seat_creds.sh` (broken-openssl
probe: old cred survives + stays 0600); verified load-bearing (fails vs old rm -f). Full
script test PASS + `tests/test_cockpit_bridge_agent.py` 16 passed.

## Next concrete step (owner = lead, then B1 post-deploy)
1. Lead: re-dispatch codex on exact head (@3a19f20d + @651b320d) + codex-arch P2 re-verify -> merge both.
2. Lead: Render deploy + flip `COCKPIT_EMBED_ENABLED` for the live AC drill.
3. B1 post-deploy: post AC1-AC5 verdict to gates/cockpit-bridge-hardening-2 (flag-flip severs live socket ≤5s;
   key-rotate drops bridge ≤5s; two seats distinct creds; no-regression grid+terminal screenshot).

## Rebase note
Both branches were based on pre-UI_POLISH main; rebased 2026-07-18 onto latest main — clean auto-merge (my
regions disjoint from UI_POLISH lockout/cookie + LAYOUT_REARRANGE). Force-pushed feature branches (not main).

## Also this session
Query #12956 answered (#12959): the running cockpit-bridge agent PID 56234 is NOT my test rig (leftover from
the earlier flip AC #12690) — told lead safe to bootout. WAKE_LISTENER AC4 24h soak still owed 2026-07-19.
