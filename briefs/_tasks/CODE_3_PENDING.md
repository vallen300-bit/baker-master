---
status: MERGED
brief_id: BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1
to: b3
from: lead
dispatched_by: lead
dispatched_at: 2026-06-24
reply_target: lead (bus)
branch: b3/baker-dashboard-v2-marketing-noise-filter-1
pr: 420
merge_commit: 5266d9b
merged_at: 2026-06-25
gates: G2 #4197 / G2-light #4214 / G3 #4198 / G3-spot #4215 all PASS; G4 lead /security-review NO FINDINGS
post_deploy: deploy live (health green 07:07Z); Today feed already 0 marketing (verifier refused pre-filter); 5 awaiting candidates self-park; no feed dismissal needed
task_class: bug/quality fix (noise leak) — deterministic title-pattern filter, no LLM, no migration, no endpoint
full_brief: briefs/_tasks/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.md
checkpoint: briefs/_checkpoints/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.checkpoint.md
rollover: ENFORCED — B3 does not compact; checkpoint+respawn per the ON RESUME block below
arc: BAKER_DASHBOARD_V2 (marketing/no-reply/survey noise off Director Today feed)
prior_brief: BAKER_DASHBOARD_V2_INFRA_ALERT_FILTER_1 (shipped 2026-06-24, PR #419, merge 10987cf — superseded in mailbox)
gate_plan: G2 deputy-codex (runtime+threat) -> G3 deputy (review) -> G4 lead /security-review -> merge. Dual-codex on prod PR (mirror #419).
harness_v2: applies — done rubric + POST_DEPLOY_AC_VERDICT v1 required (production-facing selection-quality filter)
---

# DISPATCH — BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1

## ⟳ ON RESUME (rollover — read FIRST if you are a fresh/respawned B3)
This arc is **no-bloat rollover ENFORCED** (Director 2026-06-24). You do NOT compact.
1. Read `briefs/_checkpoints/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.checkpoint.md` — it carries the ONLY 5 things you need (brief, branch/PR/status, last bus IDs/ack, exact next command). **Do not reconstruct old thread history.**
2. Bump the checkpoint `attempt:` counter, commit + push it — **that commit is your claim** (not a bus ack). If `attempt:` was already bumped past what you'd write, another session claimed it → stand down.
3. Run the checkpoint's "exact next command". Then continue normally.
4. While working: the Stop hook warns at ~70% and hard-blocks at ~85%. On warning after a milestone, or ~60–90 min in, REFRESH the checkpoint (5 fields + next command) + push + `BAKER_ROLE=b3 scripts/respawn-request.sh lead BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1 briefs/_checkpoints/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.checkpoint.md <attempt> b3/baker-dashboard-v2-marketing-noise-filter-1 "<state>"`, then exit cleanly.

---

**Read the full brief in full before starting:** `briefs/_tasks/BAKER_DASHBOARD_V2_MARKETING_NOISE_FILTER_1.md`
(self-contained — context, live proof rows, exact patterns, TDD cases, constraints, verification SQL).

## One-paragraph recap
Sibling fast-follow to the infra filter (PR #419). The shared `_is_stoplist_noise` chokepoint is
**already wired** into both bridges by #419 — you only extend the noise *definition*. Add a new
`STOPLIST_MARKETING_PATTERNS` tuple (no-reply / newsletter / survey / promo title regexes) in
`kbl/bridge/alerts_to_signal.py` and fold it into `_STOPLIST_RE`. Plus tests. That is the entire change.

## The change (2 files, additive only)
1. `kbl/bridge/alerts_to_signal.py` — add `STOPLIST_MARKETING_PATTERNS` immediately after
   `STOPLIST_TITLE_PATTERNS`; change the `_STOPLIST_RE = re.compile(...)` line to join
   `STOPLIST_TITLE_PATTERNS + STOPLIST_MARKETING_PATTERNS`. Exact patterns + audit comments in the full brief.
2. `tests/test_bridge_stop_list_additions.py` — add the parametrized positive (drop) + negative
   (pass-through) cases from the full brief, using the **real live prod titles**.

## Hard constraints (full list in brief — these are the load-bearing ones)
- **Do NOT add any `your interest in mandarin` pattern** — that subject carries real inbound MO Residences
  prospect replies (Jernej Omahen, Ines Wöckl). Filtering it kills live sales leads. The negative test
  asserts those stay. Out of scope for v1 (Director business call, parked).
- **Do NOT** add `proactive_pm_sentinel` / `deadline_cadence` to `STOPLIST_SOURCES` — filter by content, not source.
- **Title-only**, `re.IGNORECASE` on the compile (never inline `(?i)` after `|`), high-precision patterns.
- Additive only: do not touch `_is_stoplist_noise` body, `STOPLIST_SOURCES`, the auction case, or `candidate_ingest.py`.

## Done rubric (answer in ship report)
- Task class: deterministic quality filter, no LLM / no migration / no endpoint.
- Unit: `pytest tests/test_bridge_stop_list_additions.py tests/test_bridge_alerts_to_signal.py -v` — all positive drop, all negative pass, no regression.
- Compile clean; bus-post on ship + each gate.
- The one-time dismissal of already-bridged marketing candidates + bridge re-run is an **AH1 post-merge ops step** (NOT yours) — mirrors #419 Fix-3.

## Gate chain (mirror #419)
G2 deputy-codex → G3 deputy → G4 lead `/security-review` → merge. Open PR against main; post PR# on bus to lead.
