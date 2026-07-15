# BRIEF: ARM_ALARM_RECIPIENT_SPLIT_1 — per-kind alarm recipient routing

## Context
The ARM out-of-band alarm (`scripts/arm_alarm_check.sh`) delivers every alarm kind to one
recipient (`EMAIL_TO`, default the Director's ops address). Codex review of the bus-watch
ownership SOP (verdict #11671, folded PR #207 @6fa8aa6a) found that arming
`ARM_ALARM_SEMANTIC_ENFORCE=1` would then page the **Director on routine semantic-delivery red**,
violating "Director only on true emergencies." Lead ruled (routing, #11674/#11679): routine
enforced semantic red retargets to **lead**; the Director ops mailbox is reserved for
**bus-down / canary-dead / report-stopped** emergencies. This brief makes the alarm route by kind.
Authored by deputy (AH2) on lead GO #11676; line-read PASS + rider #11679.

## Estimated time: ~1.5h
## Complexity: Low
## Prerequisites: none (self-contained script change; must land before any `ARM_ALARM_SEMANTIC_ENFORCE=1` arming — hard gate)

## Baker Agent Vault Rails
Relevant rails: **verification-surfaces** (out-of-band alarm is a verification surface),
**build-command-center** (fleet reinstall via `install_arm_alarm_job.sh`), **memory-and-lessons**
(fleet-deploy drift lesson). Ignore: standing-contract, bus-and-lanes, skills-and-playbooks,
loop-runner (not touched).

## Context Contract (Harness V2)
- **Repo / file:** baker-master, `scripts/arm_alarm_check.sh` (canonical source; deployed per-host
  to `WORKER_DEPLOY` via `install_arm_alarm_job.sh`, sha256 drift-checked).
- **In scope:** the email recipient resolution inside `arm_alarm_check.sh` + its test + a deploy note.
- **Out of scope / read-only:** the bus DB (no SQL), `install_arm_alarm_job.sh` logic (only re-run it),
  `send_notify` (host-local notification, no recipient), the incident-key state machine, any other seat's files.
- **No new silent paths.** No secrets in code — reference env-var NAMES only.

## Task class (Harness V2)
**Production implementation — delivery-path — HIGH-IMPACT.** Full gate chain applies incl.
mandatory codex verify on the build (Director tiered-SOP ruling #11665).

## Problem
`arm_alarm_check.sh` resolves the email recipient once (`EMAIL_TO="${ARM_ALARM_EMAIL_TO:-dvallen@brisengroup.com}"`, `:81`),
passes that single value into the delivery heredoc (`:254`), and `deliver()` → `send_email` use it
for **every** incident kind (`:311`). There is no way to route semantic red away from the Director
without a code change. Arming ENFORCE on top of this pages the Director on routine red.

## Current State
- Marker kinds read (`:29-33`): `report.json` (`report:*`), `canary.json` (`canary:*`),
  `semantic.json` (`semantic:*`). Incident key = `"<source>:<type>"` (`:47`).
- Delivery is owned by one Python heredoc (`:249`+): `deliver(subject, body)` → `send_email(subject, body)`
  reads `os.environ["EMAIL_TO"]`. The FIRE loop (`:~375`), the RECOVERY loop (`:~400`), and the
  STILL-FAILING branch all call `deliver()` with no per-kind recipient.
- `SEMANTIC_ENFORCE="${ARM_ALARM_SEMANTIC_ENFORCE:-0}"` (`:97`) — semantic paging is currently
  gated OFF; this brief is the prerequisite that lets it be armed safely.

## Engineering Craft Gates
- **Diagnose:** N/A as a bug hunt — root cause already proven from code (single `EMAIL_TO`, three call sites). This is a scoped change, not an investigation.
- **Prototype:** N/A — no design uncertainty; the resolver + fallback shape is specified below.
- **TDD/verification:** APPLIES. Public seam = the alarm's email delivery keyed by incident source. Write the vertical test FIRST (AC2 + AC3) before wiring: a semantic incident's fire **and** recovery **and** still-failing notices all resolve to `ARM_ALARM_EMAIL_TO_SEMANTIC`; with no per-kind env set, every kind resolves to `EMAIL_TO` (byte-identical to today). No mocking of the mailer internals — assert the resolved recipient string the delivery path would use.

## Implementation
Inside the delivery heredoc, add a per-kind recipient resolver and thread the incident's **source**
(the part of the incident key before `:`) into every `deliver()` call.

1. **Resolver** (Python, inside the heredoc — NO apostrophes per the bash-3.2 foot-gun `:246-248`):
   ```python
   # source = the part of the incident key before ":" (e.g. "semantic", "report", "canary")
   def resolve_recipient(source):
       env_key = "ARM_ALARM_EMAIL_TO_" + source.upper()
       to = os.environ.get(env_key, "").strip()
       if to:
           return to, env_key
       return os.environ["EMAIL_TO"], "EMAIL_TO"
   ```
2. **Thread it** — at each delivery site (FIRE, STILL-FAILING, RECOVERY), derive `source` from the
   incident key `ik` (`source = ik.split(":", 1)[0]`), resolve, and pass the recipient into
   `deliver()` / `send_email(subject, body, to)`. Change `send_email` to take an explicit `to`
   argument instead of reading `os.environ["EMAIL_TO"]` directly.
3. **Fail-loud log:** when the resolver falls back to `EMAIL_TO`, append a log line
   (`resolved <ik> -> EMAIL_TO (no <env_key>)`); when it uses a per-kind env, log
   `resolved <ik> -> <env_key>`. Never a silent no-send.
4. **No plist hardcoding** — the production routing map is applied via envs in the launchd plist at
   install (see Verification / deploy note), not baked into the script.

Routing map (production config, applied at install):

| source | class | env | resolves to |
|---|---|---|---|
| `semantic` | routine | `ARM_ALARM_EMAIL_TO_SEMANTIC` | lead |
| `report` | emergency | `ARM_ALARM_EMAIL_TO_REPORT` (or fallback) | Director |
| `canary` | emergency | `ARM_ALARM_EMAIL_TO_CANARY` (or fallback) | Director |
| unmapped/future | emergency-biased | — | `EMAIL_TO` = Director |

## Key Constraints
- **Delivery-truth** (`:242` — state committed only after ≥1 channel delivers) unchanged.
- **Per-incident-key** dedupe / cooldown / bounded-backoff unchanged — recipient is a delivery
  target, not incident-key state.
- **Recipient consistency across the incident lifecycle (lead rider #11679):** FIRE, RECOVERY, and
  STILL-FAILING for the same incident MUST resolve to the same recipient. A semantic recovery email
  to the Director is the same misfire this brief closes.
- **bash-3.2 heredoc:** NO apostrophes inside the `$()` heredoc.
- **`send_notify`** untouched — email channel only.

## Files Modified
- `scripts/arm_alarm_check.sh` — add `resolve_recipient()`, thread per-kind recipient through FIRE/RECOVERY/STILL-FAILING, `send_email(..., to)` signature, fallback log lines.
- `tests/` — add a per-kind recipient test (AC2 + AC3 + lifecycle consistency).

## Do NOT Touch
- `install_arm_alarm_job.sh` (logic) — only re-run it to redeploy; do not change its deploy mechanics.
- The incident-key state machine / dedupe / backoff.
- `send_notify` / the macOS notification channel.
- Any other seat's copy of the script — canonical source is baker-master; distribution is the reinstall.

## Verification
- **Unit/behavior test** (write first): stub `os.environ`, assert `resolve_recipient("semantic")`
  returns the `ARM_ALARM_EMAIL_TO_SEMANTIC` value when set; assert FIRE + RECOVERY + STILL-FAILING
  for a `semantic:*` incident all resolve to that same address; assert with no per-kind envs every
  source resolves to `EMAIL_TO`.
- **Deploy note (AC7):** the production plist sets `ARM_ALARM_EMAIL_TO_SEMANTIC=<lead address>`
  (lead supplies the string). Fleet reinstall = every picker re-runs `bash scripts/install_arm_alarm_job.sh`;
  `--check` must exit 0 (repo sha == deployed) on every host.
- **Deputy live-AC (post-merge, owned by deputy):** seed a semantic red marker + a canary/report red
  on a host with the production envs; confirm the semantic notice lands on lead and the emergency
  notice on Director; confirm a semantic recovery also lands on lead.

## Quality Checkpoints (Acceptance criteria)
- **AC1** Per-kind resolver implemented; `ARM_ALARM_EMAIL_TO_<KIND>` → fallback `EMAIL_TO`; resolved recipient threaded through FIRE + RECOVERY + STILL-FAILING.
- **AC2** With `ARM_ALARM_EMAIL_TO_SEMANTIC=<lead>` set: semantic red → lead (not Director); report/canary red → Director. **Lifecycle consistency (rider #11679):** the RECOVERY and STILL-FAILING notices for that semantic incident resolve to the SAME recipient as the fire (lead), asserted by test.
- **AC3** Backward-compat regression: no per-kind env set ⇒ every kind → `EMAIL_TO` byte-identically to today.
- **AC4** Delivery-truth + dedupe/backoff/cooldown state machine unchanged; existing suite green + new test added.
- **AC5** Fail-loud: unset/blank per-kind env → fallback to `EMAIL_TO` + a log line; never silent no-send.
- **AC6** `install_arm_alarm_job.sh --check` passes after change; brief names fleet reinstall as the deploy action.
- **AC7** Plist/env wiring documented so semantic→lead is applied at install.

## Done rubric / done-state (Harness V2)
DONE = all 7 ACs green **and** codex verify PASS on the diff **and** lead merge **and** fleet
reinstall with `--check` exit 0 on every host **and** deputy live-AC drill confirms semantic→lead /
emergency→Director (incl. a semantic recovery to lead). Only then is the
`ARM_ALARM_SEMANTIC_ENFORCE=1` hard gate cleared. Compile-clean ≠ done (Lesson #8).

## Gate plan (Harness V2)
Author (deputy) → lead line-read [DONE, PASS + rider #11679] → dispatch worker (b4) → build
(TDD: AC2 + AC3 + lifecycle test first) → **codex verify (high-impact, MANDATORY)** → author
rewrite on findings → lead merge → fleet reinstall + `--check` all hosts → deputy live-AC drill →
hard gate cleared.
