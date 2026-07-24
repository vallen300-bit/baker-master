# CHECKPOINT — FUND_AGENT_SEAT_INSTALL_1

**Owner:** deputy (AH2) · **Brief:** `briefs/_tasks/FUND_AGENT_SEAT_INSTALL_1.md`
**Written:** 2026-07-24 (CTX-BAND order lead #15740; ~31% context remaining)
**Phase:** deputy build slice essentially complete; **awaiting deputy-codex round-3 verdict** (thread #15733 / lead #15742). No further build action my side unless codex finds more.

---

## ONE-LINE STATE
All three repo legs committed + pushed; 27-case cage suite PASSES 0 failures; cage now vault-versioned (deviation RATIFIED by lead #15742). Waiting on deputy-codex round-3 gate.

## THREE BRANCH SHAs (all pushed to origin — verified)
1. **baker-master** — branch `deputy/fund-seat-install-1` @ **ca3bc06b5** (HEAD==origin ✓). Bus identity + generator + drain fixture + cockpit manifest/layout + forge test.
2. **brisen-lab** — clone `~/bm-deputy-brisen-lab`, branch `deputy/fund-seat-install-1` @ **0f9a51e** (origin up-to-date ✓). Server rows: agent_identity_generated (py+js), test_a3_a8_a9_bus.py (+35), wake-handler.applescript, wake-listener identity.
3. **baker-vault** — branch `deputy/fund-findings-dir-1` @ **81fb726** (was c089c99; origin ✓). Cage VERSIONED (durability) — see below. Registry AG-406 already on vault main @cf9a938 (status `planned` — do NOT flip; ARM stamp closes).

## RATIFIED DEVIATION (lead #15742, from my #15741)
Picker cage `~/bm-the-fund/.claude` has no `.git` → picker wipe silently un-cages the seat (deputy-codex P2 #15737). FIX: cage source-of-truth now **versioned in vault** @c089c99 under `wiki/matters/oskolkov/04_working_brief/fund-agent-cage/` + `install_fund_cage.sh` (default = (re)install cage into picker + run 27-case suite; `--check` = drift-detect live picker vs vault source). Lead: "durability wins; drift-detector exactly right; do NOT revert to picker-only." Brief stands amended to vault-canonical cage @c089c99 + install_fund_cage.sh deploy path.

## CAGE FILES — ON-DISK PATHS
**Live picker (deployed, working copy):** `~/bm-the-fund/`
- `CLAUDE.md` (persona-pack-only Tier-0 session contract; no charter/CONTEXT refs)
- `.claude/hooks/fund_read_cage.sh`, `fund_write_cage.sh`, `fund_bash_cage.sh` (PreToolUse allowlist)
- `.claude/fund_memory_append.sh` (append-only helper)
- `.claude/settings.json` (hook wiring)
- `.claude/tests/cage_negative_tests.sh` — **the 27-case suite** (run: `bash ~/bm-the-fund/.claude/tests/cage_negative_tests.sh`; last run = 0 failures)
- `inbox/README.md` (artifact drop dir)

**Vault-versioned source (durable mirror) @c089c99:** `~/baker-vault/wiki/matters/oskolkov/04_working_brief/fund-agent-cage/`
- `CLAUDE.md`, `README.md`, `inbox-README.md`, `install_fund_cage.sh` (151 lines / 4 files)
- NOTE: this vault branch mirrors the picker layout; if picker & vault drift, `install_fund_cage.sh --check` reconciles.

## 27-CASE TEST — CURRENT VERDICT
`~/bm-the-fund/.claude/tests/cage_negative_tests.sh` — **27 cases, TOTAL FAILURES: 0** (re-run @ checkpoint time). Covers: symlink escape, `../` traversal, var/brace indirection, command-substitution, chaining, interpreters (python urllib), network — all BLOCKED (exit 2); two sanctioned helpers + own-path reads ALLOWED (exit 0); charter/CONTEXT reads + non-append memory writes BLOCKED.

## FIX ROUNDS (deputy-codex gate history)
- R1 P1 #15730 → cage_negative_tests.sh authored (escape-probe hardening).
- R2 P2 #15737 → cage versioned in vault @c089c99 — **but INCOMPLETE:** commit shipped only 4 doc/script files; the 6 load-bearing `.claude/` files were silently dropped by the vault `.gitignore` (swallows `.claude/`). `--check` from clean extract returned rc=1.
- R3 P1 #15745 → **FIXED @81fb726.** `git add -f` the 6 files (fund_read/write/bash_cage.sh + fund_memory_append.sh + settings.json + cage_negative_tests.sh), byte-identical to picker. Clean-extract → `--check` rc=0 + 27-case 0-fail. Wiped-picker recovery works. **Count pushback:** suite is 27 cases NOT 34 (codex miscount); README '27-case' kept correct. Re-posted deputy-codex #15746; **awaiting re-verdict.**

## RESUME INSTRUCTIONS (successor)
1. Drain deputy bus — check for deputy-codex round-3 verdict (thread #15733) + any lead follow-up.
2. If codex **PASS** → post ship-confirm to lead; lead owns Tier-B local rows (Row 2 zshrc, 3 Terminal profile, 8 1P key, 9 Render env) + E2E + tmux session; ARM 14-row stamp @ `wiki/_fleet/audits/` + registry flip `planned→active` close the three-signature gate.
3. If codex **FAIL** → fix on the SAME three branches above (re-cut clean off origin/main only if base-contaminated — see librarian P1-1 lesson). Re-run 27-case suite; re-post to deputy-codex (restate lane on re-dispatch — known drift).
4. Do NOT flip registry AG-406; do NOT touch persona-pack / charter / memory content (cowork's lane — wire paths only).
5. Lead Tier-B rows still owed (from brief 14-row map): Rows 2,3,8,9 + tmux/ttyd session install (`install_cockpit_ttyd.sh the-fund`).

## GUARDRAILS
- Persona-pack-only cage is THE load-bearing rule — seat must NEVER load charter/CONTEXT/decision-logs (a read-all seat discovers it is fictional → objections stop being honest). Cage wins over any conflicting install row.
- No email (structural block), comms whitelist = bus + Director only.
- Base for any fix: both repos origin/main; cite repo+branch+sha (never PR#) to codex.
