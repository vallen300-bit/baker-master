---
brief_id: BRIEF_AIDENNIS_TERMINAL_INSTALL_WAVE_1
version: 0.1
status: DRAFT
drafted_by: aihead1-app
drafted_at: 2026-05-09
ratification_target: Director (Dimitry Vallen)
trigger_class: TIER_B_AGENT_CAPABILITY_INSTALL_PHASE_1
assignee: AI Dennis-T (self-install, lane-owner)
repos_touched:
  - baker-master (this brief, doc-only PR)
  - baker-vault (4 new SKILL.md files, direct commit per CHANDA Inv 9)
sources:
  - "wiki/research/2026-05-08-aidennis-terminal-scavenged-patterns.md (Researcher v2 §3.1, §3.2, §3.3, §3.8)"
  - "_ops/agents/ai-dennis/CONTRACT.md v1 (3-tier authority + P1-P4 severity, ratified 2026-05-06)"
  - "Anthropic knowledge-work-plugins (operations/runbook + operations/change-request + engineering/incident-response)"
  - "bregman-arie/devops-sre-skills (sev1-first-15-minutes; YAML safety schema)"
prereq_pickers_installed: true
expected_pr_count: 1 (baker-master doc) + direct commits to baker-vault main
---

# BRIEF: AIDENNIS_TERMINAL_INSTALL_WAVE_1 — Foundational ops skills for AI Dennis-T

## Context

AI Dennis-T (AID-T) is the terminal-side picker entrypoint for the IT Shadow Agent (sibling of AH1-T / AH2-T at Director-report level). Picker plumbing was installed 2026-05-08 (`bm-aidennis-t/CLAUDE.md` thin shell + `_ops/skills/aidennis-terminal/` empty dir). One companion skill, `aidennis-edge-scout`, exists at Cowork-side only. The skill catalog needed to operationalise AID-T's CONTRACT.md duties is empty.

Researcher v2 (`wiki/research/2026-05-08-aidennis-terminal-scavenged-patterns.md`) identified 9 directly stealable patterns from Anthropic `knowledge-work-plugins` + bregman-arie `devops-sre-skills`. Wave 1 = the 4 foundational ops stubs. Each subsequent wave (2/3/4) builds on the YAML safety schema and authority-tier discipline established here.

**Personal-hardware + phone scope** (Director ratification 2026-05-08, "Aid in running Baker"): AID-T's brief does not include Dennis Egorenkov-shadow expansion at this stage. AID-T runs on Director's MacBook + Mac Mini Cowork sessions; the skills installed here serve Director's IT-ops needs first.

## Estimated time: ~7 hours (one full work-day, AID-T self-install)
## Complexity: Low (content authoring + git plumbing; no Baker code surface, no DB, no Render env)
## Prerequisites:
- Picker `~/Vallen Dropbox/Dimitry vallen/bm-aidennis-t/` exists with `CLAUDE.md` ✓ verified 2026-05-09
- `~/baker-vault/_ops/skills/aidennis-terminal/` exists (empty dir) ✓ verified 2026-05-09
- Researcher v2 file present at canonical path ✓ verified 2026-05-09
- `it-manager` + `aidennis-edge-scout` skills installed (consistency reference) ✓ verified 2026-05-09

---

## Fix 1: Install `aidennis-terminal/runbook-template`

### Problem
AID-T has no canonical "how to write an IT runbook" template. CONTRACT.md §3.1 lists "writes briefs for IT Workshop (PL + Code) to execute technical changes" but no shared structural pattern. Researcher v2 §3.1 identified Anthropic ops/runbook (template structure) + bregman-arie/devops-sre-skills (YAML safety schema) as the pattern sources; the "painfully specific" rule + "test the runbook" discipline are Researcher v2 Brisen overlays, NOT Anthropic-verbatim — the upstream Anthropic SKILL.md is template-only without the prose discipline. Standing runbook library (DNS cutover, M365 phase, Mac BYOD→corporate, secret rotation, pgbouncer-pool-recovery, EVOK GDAP audit, mac-fleet-patch, phishing-simulation, sev1-first-15, restore-drill-quarterly) is the downstream output — this stub is the meta-template that produces it.

### Implementation
Create file at `~/baker-vault/_ops/skills/aidennis-terminal/runbook-template/SKILL.md`. Symlink `~/.claude/skills/aidennis-terminal/runbook-template` → vault path.

```markdown
---
name: aidennis-terminal-runbook-template
description: |
  Template + discipline for writing AID-T operational runbooks — recurring IT-ops tasks (DNS cutover, M365 phase migration, Mac BYOD→corporate flip, secret rotation, pgbouncer pool recovery, EVOK GDAP audit). Each runbook is a step-by-step procedure with exact CLI commands, expected stdout, failure paths, and rollback. YAML safety header encodes Tier-A/B/C authority per CONTRACT.md §4.
  MANDATORY TRIGGERS: aidennis-terminal-runbook-template, write a runbook, draft IT runbook, runbook for, codify procedure, document IT process.
  Use this skill when AID-T needs to capture a recurring IT-ops procedure from tribal knowledge into a repeatable file. Output lands in `~/baker-vault/_ops/runbooks/<slug>.md`.
safety:
  default_mode: read_only
  forbidden: []
  requires_confirmation_for:
    - vault.commit
source: |
  Pattern inspired by Anthropic knowledge-work-plugins/operations/skills/runbook (template structure, published-as-reference) + bregman-arie/devops-sre-skills (YAML safety schema, MIT).
  "Painfully specific" rule + "test the runbook" rule = Researcher v2 §3.1 Brisen overlays (not Anthropic-verbatim — verified against upstream 2026-05-09).
---

# AID-T Runbook Template

You are writing an operational runbook for a recurring IT task. The runbook must be executable by anyone (Director, Dennis Egorenkov, IT PL, IT Code) without further context.

## Painfully-specific rule (Researcher v2 §3.1 Brisen overlay)

"Run the script" is NOT a step. "Run `python sync.py --prod --dry-run` from `~/baker-vault/_ops/scripts/` and confirm stdout starts with `[dry-run-ok]`" IS a step. Apply this rule on every runbook — every step must have:

- Exact CLI command (copy-pasteable)
- Working directory
- Expected stdout signature (the first decisive line)
- Failure path (what to do if stdout differs)
- Rollback (if step is destructive)

## Template structure

Output runbook to `~/baker-vault/_ops/runbooks/<slug>.md` using this exact frontmatter + section layout:

```yaml
---
runbook_id: <slug>
status: draft | live | retired
authority_tier: 1 | 2 | 3   # per CONTRACT.md §4
last_verified: YYYY-MM-DD
last_verified_by: <agent or human name>
trigger: <when this runbook fires>
prereqs: <what must be true before step 1>
estimated_duration: <minutes>
---

# Runbook: <human-readable title>

## Trigger
When does this runbook fire? (cron / manual / incident-driven)

## Prerequisites
- [ ] Prereq 1 (with verification command)
- [ ] Prereq 2

## Steps

### Step 1 — <imperative title>
**Command:** `<exact command>`
**Working dir:** `<path>`
**Expected stdout:** `<first decisive line>`
**Failure path:** <what to do if stdout differs>
**Rollback:** <command, or "not destructive — no rollback needed">

### Step 2 — ...

## Verification (post-completion)
- [ ] Verification command 1 + expected output
- [ ] Verification command 2 + expected output

## Failure modes (catalog)
| Symptom | Cause | Fix |
|---|---|---|

## Change log
| Date | Change | By |
|---|---|---|
```

## Authority-tier rule (steal verbatim from CONTRACT.md §4)

Every runbook MUST declare `authority_tier` in frontmatter:
- **Tier 1** — auto-execute (routine, reversible, low-risk; AID-T runs without confirmation)
- **Tier 2** — recommend + wait (medium-stakes; needs Director or Dennis E. approval before execute)
- **Tier 3** — escalate to Director (irreversible, budget, vendor, security; AID-T does NOT act)

A runbook with destructive steps (DNS cutover, secret rotation, env-var delete) is automatically Tier 2 or Tier 3.

## Test-the-runbook rule (Researcher v2 §3.1 Brisen overlay)

Before marking a runbook `status: live`, AID-T must have someone unfamiliar with the procedure follow it end-to-end. Fix where they get stuck. "Live" means: it has been executed at least once by a human-in-the-loop, by AID-T at least once with Director observing, or both.

## Standing runbook library (Wave 1+ fills these)

**Note**: "skills" live at `_ops/skills/aidennis-terminal/<name>/SKILL.md` (these are reusable templates Wave 1 installs); "runbooks" live at `_ops/runbooks/<slug>.md` (these are concrete operational procedures the runbook-template skill produces — Wave 1+ output). Different folders, different artefacts. Wave 1 = skills only.

Output paths AID-T should populate over Waves 1-4:

- `_ops/runbooks/dns-cutover-mx.md` — Tier 3
- `_ops/runbooks/m365-phase-1.md` through `m365-phase-7.md` — Tier 2/3 per phase
- `_ops/runbooks/mac-byod-to-corporate.md` — Tier 2
- `_ops/runbooks/secret-rotation.md` — Tier 2
- `_ops/runbooks/pgbouncer-pool-recovery.md` — Tier 1 (`DISCARD ALL` sweep; non-destructive)
- `_ops/runbooks/evok-gdap-audit.md` — Tier 1 (read-only)
- `_ops/runbooks/mac-fleet-patch.md` — Tier 2
- `_ops/runbooks/phishing-simulation.md` — Tier 2
- `_ops/runbooks/incident-sev1-first-15.md` — see `aidennis-terminal-sev1-first-15-min` skill
- `_ops/runbooks/restore-drill-quarterly.md` — Tier 2
```

### Key Constraints
- DO NOT inline non-Researcher-v2 patterns. Wave 1 = direct-steal only; novel Brisen patterns belong in Wave 4.
- DO NOT add `tools_allowed` block (the upstream bregman-arie schema has it; Brisen does not yet have a sandbox enforcing it). Reserve for v2 hardening.
- DO NOT include real Render service IDs / API keys in any runbook example. Use placeholders.
- Source attribution line is mandatory (Researcher §8 open-Q ratified).

### Verification
- File exists at `~/baker-vault/_ops/skills/aidennis-terminal/runbook-template/SKILL.md`.
- Symlink exists: `~/.claude/skills/aidennis-terminal/runbook-template` → vault path.
- `head -1 ~/.claude/skills/aidennis-terminal/runbook-template/SKILL.md` returns `---`.
- Frontmatter `safety.default_mode: read_only` present.
- Skill auto-discovers in next Cowork session (mirror of `it-manager` install).

---

## Fix 2: Install `aidennis-terminal/change-request`

### Problem
Brisen has no canonical change-request format. DNS / Conditional Access / Render env-var / secret rotation / new MCP install / SaaS procurement / M365 license / Cloudflare WAF — each surfaces ad-hoc in chat or email. Researcher v2 §3.2 identified Anthropic ops/change-request as direct-steal with the assess-plan-execute-sustain framework.

### Implementation
Create file at `~/baker-vault/_ops/skills/aidennis-terminal/change-request/SKILL.md`. Symlink `~/.claude/skills/aidennis-terminal/change-request` → vault path.

```markdown
---
name: aidennis-terminal-change-request
description: |
  Generates an AID-T change request — assess-plan-execute-sustain framework, with Brisen-specific approver matrix (Director Tier 3 / Dennis E. advisory / AID-T requester). Used for any IT change with material impact: DNS records, Conditional Access policies, Render env-vars, production secret rotation, new MCP install, SaaS subscription procurement, M365 license SKU change, Cloudflare WAF rules.
  MANDATORY TRIGGERS: aidennis-terminal-change-request, change request, change-request, IT change, propose IT change, request approval for, draft CR, propose change.
  Output lands in `~/baker-vault/_ops/change-requests/YYYY-MM-DD-<slug>.md`.
safety:
  default_mode: read_only
  forbidden:
    - secrets.write
    - vcs.rewrite_history
  requires_confirmation_for:
    - vault.commit
    - render.env_put
    - render.deploy_cancel
source: |
  Anthropic knowledge-work-plugins/operations/skills/change-request (published-as-reference).
  Communication principles + assess-plan-execute-sustain framework stolen verbatim.
---

# AID-T Change Request

Apply the assess-plan-execute-sustain framework. Communication principles (steal verbatim from Anthropic source):

> Explain the **why** before the **what**.
> Communicate early and often.
> Use multiple channels.
> Acknowledge what's being lost, not just what's being gained.
> Provide a clear path for questions and concerns.

## When to invoke

Mandatory for any of these:
- DNS record change on `brisengroup.com` / `brisen-infra.com` / `theailogy.{ai,com}` (any MX/CNAME/TXT)
- Conditional Access policy add / modify / delete
- Render env-var add / rename / delete (any service)
- Production secret rotation that affects active sessions
- New MCP install (anywhere in Director's session graph)
- New SaaS subscription procurement
- M365 license SKU change (E2 add-on, P1 add-on, etc.)
- Cloudflare WAF rule change

## Output template (steal verbatim, fill in)

```markdown
## Change Request: <Title>
**Requester:** AI Dennis Terminal | **Date:** YYYY-MM-DD | **Priority:** Critical | High | Medium | Low

### Description
<What is changing and why — 2-4 sentences>

### Business Justification
<Why — cost / compliance / security / efficiency. Anchor to a concrete trigger (incident, audit finding, vendor renewal, new requirement).>

### Impact Analysis
| Area | Impact | Details |
|---|---|---|
| Users | H/M/L/None | <who is affected, how many> |
| Systems | H/M/L/None | <what systems> |
| Processes | H/M/L/None | <what workflows change> |
| Cost | H/M/L/None | <€ impact, one-time + recurring> |

### Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| <risk 1> | H/M/L | H/M/L | <mitigation> |

### Implementation Plan
| Step | Owner | Timeline |
|---|---|---|
| <step 1> | <owner> | <when> |

### Rollback Plan
- **Trigger:** <when to roll back>
- **Steps:** <how>
- **Verification:** <how to confirm rollback succeeded>

### Approvals Required
| Approver | Role | Status |
|---|---|---|
| Dimitry Vallen | Director (Tier 3) | Pending |
| Dennis Egorenkov | IT Admin (advisory) | Pending |
| AI Dennis Terminal | Requester | Submitted |

### Status
Draft | Pending Approval | Approved | In Progress | Complete | Rolled Back
```

## Tier discipline (steal verbatim)

AID-T cannot move past `Status: Draft → Pending Approval` without a Tier 2/3 approver acting (Director or Dennis Egorenkov). For Tier 3 changes (CONTRACT.md §4), Director approval is mandatory; Dennis E. advisory only.

## Communication channels

- **Primary:** drop CR file in `_ops/change-requests/YYYY-MM-DD-<slug>.md` + paste-block to Director in chat.
- **Secondary:** ClickUp Handoff Notes (workspace 24385290, list 901521475044) — prefix `AI Dennis → Director: CR-<slug>`.
- **For Dennis Egorenkov advisory:** email or ClickUp comment per his preference (NOT WhatsApp; Dennis E. is email-first).

## Acknowledge-the-loss rule

Per Anthropic source: "Acknowledge what's being lost, not just what's being gained." Every CR must explicitly name what we lose by making the change. Examples:
- DNS cutover loses email-deliverability headroom during TTL bake.
- New MCP install loses one slot on the curated MCP allowlist.
- M365 SKU upgrade loses €X/seat/month flexibility.

This forces honest pricing of the change.
```

### Key Constraints
- DO NOT pre-populate Director's name in approver field as `Approved`. Always `Pending`.
- DO NOT include actual Render service IDs in template examples. Placeholders only.
- DO NOT bypass the CR for "small" DNS changes. The brief lists the gates exhaustively; if the change touches any of them, CR is mandatory.
- The Acknowledge-the-loss section is non-optional. AID-T must not omit it to make the CR feel "lighter."

### Verification
- File exists at `~/baker-vault/_ops/skills/aidennis-terminal/change-request/SKILL.md`.
- Symlink exists.
- `grep -c "Acknowledge what's being lost" ~/.claude/skills/aidennis-terminal/change-request/SKILL.md` returns ≥ 1.
- Approver matrix shows `Dimitry Vallen | Director (Tier 3) | Pending` (3 columns, exact match).

---

## Fix 3: Install `aidennis-terminal/incident-response`

### Problem
CONTRACT.md §6 KPI #2 requires "zero missed P1/P2 incidents per quarter; false-positive rate <15%." CONTRACT.md §4 has a one-line P1-P4 reference for response-speed only (P1 immediate / P2 same session / P3 this week / P4 backlog) — no impact-criteria matrix and no operational lifecycle. Researcher v2 §3.3 carries the four-phase lifecycle (TRIAGE → COMMUNICATE → MITIGATE → POSTMORTEM) from Anthropic engineering/incident-response (verbatim from upstream) AND the Brisen-specific SEV1-4 impact criteria (Production Baker down / M365 lockout / etc.) which are Researcher-authored Brisen overlays — not upstream Anthropic verbatim. Wave 1 codifies impact + lifecycle from Researcher v2 §3.3 and cross-references CONTRACT §4 for response speed via an explicit P↔SEV mapping table.

**Note on Researcher v2 status:** the Researcher v2 file is `pending` Director ratification per its frontmatter (line 5). AID-T's Wave 1 install is the first canonical use of these SEV criteria — Director ratifies them implicitly by ratifying the Wave 1 ship-report. If the criteria need adjustment post-install, the change lands in BOTH the Researcher v2 file AND `incident-response/SKILL.md` in the same commit.

### Implementation
Create file at `~/baker-vault/_ops/skills/aidennis-terminal/incident-response/SKILL.md`. Symlink `~/.claude/skills/aidennis-terminal/incident-response` → vault path.

```markdown
---
name: aidennis-terminal-incident-response
description: |
  AID-T's full incident lifecycle skill — TRIAGE / COMMUNICATE / MITIGATE / POSTMORTEM. SEV1-4 impact criteria sourced from Researcher v2 §3.3; response-time mapping cross-references CONTRACT.md §4 P1-P4. Pairs with `aidennis-terminal-sev1-first-15-min` for the acute first 15 minutes; this skill carries the incident through resolution + blameless 5-whys postmortem. Output: `_ops/incidents/YYYY-MM-DD-<slug>.md` (timeline) + `_ops/postmortems/YYYY-MM-DD-<slug>.md` (5-whys).
  MANDATORY TRIGGERS: aidennis-terminal-incident-response, incident, declare incident, IT incident, P1 incident, P2 incident, postmortem, blameless review, 5 whys, incident timeline.
safety:
  default_mode: read_only
  forbidden:
    - vcs.rewrite_history
    - secrets.write
  requires_confirmation_for:
    - vault.commit
    - clickup.task_close
    - render.deploy_cancel
source: |
  Anthropic knowledge-work-plugins/engineering/skills/incident-response (published-as-reference).
  SEV1-4 impact-criteria matrix sourced from Researcher v2 §3.3 verbatim.
  P↔SEV response-time mapping cross-references Brisen CONTRACT.md §4 (canonical for response speed).
---

# AID-T Incident Response

Four-phase lifecycle: TRIAGE → COMMUNICATE → MITIGATE → POSTMORTEM.

## Phase 1: TRIAGE

1. **Assess severity** using the matrix below.
2. **Identify affected systems and users** — be specific (which Render service, which mailbox, which Director session).
3. **Assign roles:**
   - Incident Commander (IC): AID-T (or Director, if Director is engaged on the incident)
   - Comms Lead: AID-T (Director-facing)
   - Operations Lead: IT PL or IT Code session (handed off from AID-T as needed)
4. **Open the timeline file** at `~/baker-vault/_ops/incidents/YYYY-MM-DD-<slug>.md`.

### Severity matrix — impact criteria from Researcher v2 §3.3 (verbatim)

Two compatible classifications: **SEV1-4** (industry-standard impact label) and **P1-P4** (Brisen CONTRACT.md §4 response-speed reference). The two are aligned via the mapping table immediately below; AID-T uses SEV in chat + incident files, P in CONTRACT compliance contexts.

| SEV | Brisen impact criteria | P↔SEV mapping | Response time (CONTRACT §4) |
|---|---|---|---|
| **SEV1** | Production Baker down OR M365 tenant lockout OR active credential exposure | SEV1 ↔ P1 | Immediate, drop everything, Director paged within 5 min |
| **SEV2** | Major capability degraded (Render service flapping, single-mailbox migration broken, WhatsApp routing wrong) | SEV2 ↔ P2 | Same session, within 15 min of detection |
| **SEV3** | Minor issue (one user can't access one system, one feed disabled, one stale env-var) | SEV3 ↔ P3 | This week |
| **SEV4** | Cosmetic (theming drift, dead env-var, small lint failure) | SEV4 ↔ P4 | Backlog / next business day |

**Authority of each column:**
- Impact criteria column → owned by Researcher v2 §3.3 (this skill carries it verbatim).
- P↔SEV mapping column → defined here, in this skill (Wave 1 install).
- Response time column → owned by CONTRACT.md §4 (this skill cross-references; does NOT redefine).

If CONTRACT.md §4 changes response-times, only the right-hand column updates. If Researcher §3.3 is amended, the impact criteria column updates. The mapping column is stable.

## Phase 2: COMMUNICATE

For SEV1/SEV2: draft initial Director update (use `aidennis-terminal-sev1-first-15-min` for the 5-line template).

For SEV3/SEV4: ClickUp Handoff Notes comment is sufficient.

War-room replacement: ClickUp Handoff Notes (workspace 24385290, list 901521475044) + Slack DM to Director if SEV1.

Cadence:
- SEV1: every 15 minutes during incident; final update on resolution.
- SEV2: every 30-60 minutes; final on resolution.
- SEV3/4: at resolution.

## Phase 3: MITIGATE

Document mitigation steps **as you take them**, not after. Timeline file is append-only during the incident.

Format per timeline entry:
```text
HH:MM UTC — <action taken> — <result observed>
```

Confirm resolution: define what "resolved" means BEFORE acting. Examples:
- Baker down: `curl -fsS https://baker-master.onrender.com/healthz` returns 200 for 3 consecutive minutes.
- Mailbox migration broken: target user can send + receive, verified by test message round-trip.
- Credential exposure: credential rotated + old credential confirmed revoked + audit log shows no usage in exposure window.

## Phase 4: POSTMORTEM (blameless)

Mandatory for SEV1 + SEV2. Optional for SEV3 (only if pattern recurs). Skip for SEV4.

Output: `~/baker-vault/_ops/postmortems/YYYY-MM-DD-<slug>.md`.

Template:
```markdown
# Postmortem: <slug>
**Date:** YYYY-MM-DD | **Severity:** SEV1/2 | **Duration:** <minutes>
**IC:** AID-T | **Comms:** AID-T → Director | **Operations:** <handoff target>

## Impact
- Users affected: <count + names>
- Systems affected: <list>
- Counterparty-comm impact: <list of missed/delayed external comms, e.g. Aukera email queue>
- Director-time spent: <minutes>

## Timeline (from incident file)
HH:MM UTC — <event>
HH:MM UTC — <event>
...

## Root cause analysis (5 whys)
- Why did this fail? — <answer>
- Why? — <answer>
- Why? — <answer>
- Why? — <answer>
- Why? — <answer>
**Root cause:** <one-sentence statement>

## What went well
- <thing>

## What went poorly
- <thing>

## Action items
| Action | Owner | Due | Severity if missed |
|---|---|---|---|
| <action> | <owner> | YYYY-MM-DD | P3/P4 |

## Lessons (append to AID-T LONGTERM.md if pattern-bearing)
- <lesson>
```

Action-item tracking: each row → ClickUp task in workspace 24385290 list 901521475047 with `from-postmortem` tag.

## Blameless principle (steal verbatim from Anthropic source)

Postmortems focus on **systems and processes that allowed the failure**, not on individual decisions. "Why did the on-call human do X?" is the wrong question; "Why was X the easiest path?" is the right one. AI Dennis-T does not name individual humans as root causes.
```

### Key Constraints
- DO NOT skip the 5-whys section even on "obvious" causes. The discipline is the value.
- DO NOT mark a postmortem complete without action-item tracking entries in ClickUp.
- DO NOT name individual humans (Dennis Egorenkov, Director, EVOK staff) as root causes. Systems / processes / incentives only.
- The SEV1-4 impact criteria column is sourced from Researcher v2 §3.3 verbatim — do NOT paraphrase, do NOT add Brisen-novel criteria in Wave 1. The P↔SEV mapping column is defined IN this skill (single source of truth). The response-time column cross-references CONTRACT.md §4 — do NOT redefine response times here. If CONTRACT.md §4 response-time line changes, update the right-hand column only.

### Verification
- File exists at `~/baker-vault/_ops/skills/aidennis-terminal/incident-response/SKILL.md`.
- Symlink exists.
- `grep -c "Production Baker down OR M365 tenant lockout" ~/.claude/skills/aidennis-terminal/incident-response/SKILL.md` returns ≥ 1 (impact-criteria sourced from Researcher v2 §3.3 verbatim).
- `grep -c "SEV1 ↔ P1" ~/.claude/skills/aidennis-terminal/incident-response/SKILL.md` returns ≥ 1 (P↔SEV mapping table present).
- `grep -c "CONTRACT.md §4" ~/.claude/skills/aidennis-terminal/incident-response/SKILL.md` returns ≥ 1 (response-time cross-reference present, not redefined).
- 5-whys template appears in Phase 4 section.
- Blameless principle paragraph present.

---

## Fix 4: Install `aidennis-terminal/sev1-first-15-min`

### Problem
CONTRACT.md §4 declares SEV1 = "drop everything, Director paged" but provides no first-15-minutes muscle-memory protocol. Researcher v2 §3.8 identified bregman-arie/sev1-first-15-minutes as direct-steal — production-grade SRE pattern, paired with the schema that all subsequent AID-T skills should adopt.

### Implementation
Create file at `~/baker-vault/_ops/skills/aidennis-terminal/sev1-first-15-min/SKILL.md`. Symlink `~/.claude/skills/aidennis-terminal/sev1-first-15-min` → vault path.

```markdown
---
name: aidennis-terminal-sev1-first-15-min
description: |
  Acute first-15-minutes runbook for SEV1 incidents. Pairs with `aidennis-terminal-incident-response` (which carries the full lifecycle). Use this skill the moment a SEV1 is declared — declare severity → assign roles → state customer impact → stabilize → start timeline. Adopts bregman-arie schema verbatim (the YAML safety pattern AID-T uses across all Terminal-lane skills).
  MANDATORY TRIGGERS: aidennis-terminal-sev1-first-15-min, sev1, SEV1, P1 incident, drop everything, page director, baker down, tenant lockout, credential exposure.
safety:
  default_mode: read_only
  forbidden:
    - secrets.write
    - vcs.rewrite_history
  requires_confirmation_for:
    - render.deploy_cancel
    - render.env_put
    - cloudflare.waf_add
    - entra.ca_emergency_add
source: |
  bregman-arie/devops-sre-skills/skills/incident/sev1-first-15-minutes/SKILL.md (MIT).
  Initial-update template stolen verbatim. Roles + stabilize-first ordering preserved.
---

# AID-T SEV1 First 15 Minutes

The first 15 minutes of a SEV1 are muscle memory. Don't think; act.

## The 5 acute steps (steal verbatim, ordered)

1. **Declare severity and open an incident channel.** Open `~/baker-vault/_ops/incidents/YYYY-MM-DD-<slug>.md`. First line: `## SEV1 declared HH:MM UTC by <AID-T or Director>`.
2. **Assign roles:**
   - Incident Commander (IC): AID-T (escalates to Director if Director engages)
   - Comms Lead: AID-T (Director-facing, Slack + ClickUp)
   - Operations Lead: IT PL or IT Code (hand off as soon as a code-side action is needed)
3. **State the customer impact in one sentence.** "Director / Brisen team / counterparty <X> is currently experiencing <Y>." If you can't state impact in one sentence, you don't yet have enough information — keep gathering, do NOT freeze.
4. **Stabilize first: stop the bleeding.** In order of preference:
   - Roll back the most recent deploy (Tier 2 — confirm with Director if production-impacting).
   - Disable the failing feature (Tier 1 if reversible env-var; Tier 2 if config change).
   - Shed load (Tier 2 — Cloudflare WAF rule, rate limit, route block).
   Do NOT chase root cause yet. Stabilize first.
5. **Start the timeline.** Append to incident file as you act. Format:
   ```text
   HH:MM UTC — <action> — <result>
   ```

## Decision heuristics (steal verbatim)

- **If impact is unknown:** prioritize measurement and narrowing scope. The first 5 minutes might be entirely "what's broken" before "how do I fix it."
- **If rollback is low-risk and likely effective:** rollback early. Don't wait for root cause.
- **If data integrity is at risk:** freeze writes and escalate to Director immediately. Data corruption is irreversible; downtime is not.

## Director update template (steal verbatim from bregman-arie)

Initial Director update — paste-block to Slack DM + ClickUp Handoff Notes:

```text
Impact: <who/what is affected>
Start: <HH:MM UTC>
Current status: <what we see>
Mitigation in progress: <what we are doing>
Next update: <HH:MM UTC>
```

Cadence: every 15 minutes during the SEV1 until resolution. Final update at resolution.

## Brisen-specific stabilization tools + tier

| Tool | Tier | Notes |
|---|---|---|
| `render.rollback_deploy` | Tier 2 | Confirm with Director |
| `render.env_put` (kill-switch) | Tier 2 | Confirm with Director |
| `cloudflare.waf_add_rule` | Tier 2 | Confirm with Director |
| `entra.ca_emergency_add` | Tier 3 | Director only |
| `whatsapp.disable_via_env` | Tier 1 | Reversible; AID-T can act (precedent: WAHA mis-route 2026-05-08) |

## Hand-off to incident-response (Phase 2+)

After 15 minutes (or when stabilized, whichever first), hand off to `aidennis-terminal-incident-response` Phase 2 (COMMUNICATE) → Phase 3 (MITIGATE) → Phase 4 (POSTMORTEM).
```

### Key Constraints
- DO NOT chase root cause in the first 15 minutes. Stabilize → then investigate. (Researcher §3.8 verbatim.)
- DO NOT extend SEV1 protocol to SEV2/3/4. Those use the parent `aidennis-terminal-incident-response` skill directly.
- DO NOT include the Director's actual phone or page channel in this file — AID-T pages via Slack DM + ClickUp; physical pager is out-of-scope.
- The 5 acute steps are ordered. Do not reorder.

### Verification
- File exists at `~/baker-vault/_ops/skills/aidennis-terminal/sev1-first-15-min/SKILL.md`.
- Symlink exists.
- `grep -c "Stabilize first: stop the bleeding" ~/.claude/skills/aidennis-terminal/sev1-first-15-min/SKILL.md` returns ≥ 1.
- Initial-update template (5 lines, ending in `Next update: <HH:MM UTC>`) present verbatim.
- File explicitly references CONTRACT.md §4 and the parent `aidennis-terminal-incident-response` skill.

---

## Files Created (4 SKILL.md + 4 symlinks)

- `~/baker-vault/_ops/skills/aidennis-terminal/runbook-template/SKILL.md` (NEW)
- `~/baker-vault/_ops/skills/aidennis-terminal/change-request/SKILL.md` (NEW)
- `~/baker-vault/_ops/skills/aidennis-terminal/incident-response/SKILL.md` (NEW)
- `~/baker-vault/_ops/skills/aidennis-terminal/sev1-first-15-min/SKILL.md` (NEW)
- 4 × symlink `~/.claude/skills/aidennis-terminal/<name>` → vault path. Use absolute path (mirror `it-manager` precedent): `ln -s /Users/dimitry/baker-vault/_ops/skills/aidennis-terminal/<name> /Users/dimitry/.claude/skills/aidennis-terminal/<name>` — NOT the `~` shorthand on disk.

## Files Modified (1)

- `~/baker-vault/_ops/agents/ai-dennis/LONGTERM.md` — append a new section at end of file with literal heading `## 2026-05-09 — Wave 1 skills installed (BRIEF_AIDENNIS_TERMINAL_INSTALL_WAVE_1)`, then 4 bullet lines pointing at the new SKILL.md vault paths. ≤ 10 new lines total. Do NOT rewrite existing content. Do NOT touch OPERATING.md at install — only LONGTERM.md (CONTRACT §3.1 memory-rewrite happens at session-end, not install-end; install logs to LONGTERM only).

## Do NOT Touch

- `_ops/skills/aidennis-edge-scout/` — out of scope; existing Cowork-side-only skill stays where it is.
- `_ops/skills/it-manager/SKILL.md` — separate skill, separate authority. Do NOT consolidate.
- `_ops/agents/ai-dennis/CONTRACT.md` — canonical authority doc; this brief reads from it, does not modify it.
- `bm-aidennis-t/CLAUDE.md` — picker file; updated 2026-05-09 (PR #177 propagation). Wave 1 does not require picker changes.
- `briefs/_tasks/CODE_<N>_PENDING.md` — this brief is AID-T self-install lane, not B-code dispatch.
- `baker-master` Python code — zero code surface in Wave 1.

## Quality Checkpoints

After install, AID-T verifies in this order:

1. **File existence:** `ls ~/baker-vault/_ops/skills/aidennis-terminal/*/SKILL.md` returns 4 files.
2. **Symlink correctness:** `ls -la ~/.claude/skills/aidennis-terminal/` shows 4 symlinks pointing into the vault.
3. **YAML parse:** for each file, `python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]).read().split('---')[1])" <path>` exits 0.
4. **Schema discipline:** each file has `safety.default_mode` set; each has a `source:` attribution block.
5. **Skill discovery:** AID-T opens a fresh Cowork session and confirms the 4 skills appear in the available-skills list (alongside `aidennis-edge-scout` + `it-manager`).
6. **Source-of-truth discipline:** incident-response SEV1-4 impact-criteria matrix sourced from Researcher v2 §3.3 verbatim; P↔SEV mapping table cross-references CONTRACT §4 response-speed line (not a redefinition). Verify via `grep` triple: `Production Baker down OR M365 tenant lockout` (≥1), `SEV1 ↔ P1` (≥1), `CONTRACT.md §4` (≥1) — all three present in `incident-response/SKILL.md`.
7. **Trigger phrase smoke (best-effort, non-blocking):** open a new session, mention "draft IT runbook"; if `runbook-template` is suggested by Cowork, log it. If not, file as a Wave 2 follow-up — do NOT block Wave 1 ratification on this. Cowork skill auto-discovery is description-matched and not deterministic.
8. **Brief commit gate:** baker-master PR for this brief merged AND baker-vault commits pushed AND Director ratifies smoke test before Wave 1 closes.

## Post-install — write Wave 1 ship-report

AID-T writes `~/baker-vault/_ops/agents/ai-dennis/wave1-install-ship-report.md` with:
- Files created (paths)
- Verification results (literal command + output)
- Time-spent vs. estimate (calibration data)
- Any deviations from this brief (with reason)
- Recommendation: ratify Wave 1 → dispatch Wave 2, OR fold corrections + re-test.

Paste-block to Director on completion. Wave 2 dispatch waits on Director ratification.

## Risks + lessons applied

| Risk | Lesson source | Mitigation in this brief |
|---|---|---|
| Skill files installed Cowork-only, lost on Mac wipe | aidennis-edge-scout precedent (vault-canonical missed in v1) | Vault-canonical with Cowork symlink; mirrors `it-manager` |
| YAML schema drift between AID-T skills | bregman-arie schema not adopted = no cross-skill discipline | Schema embedded verbatim in every Wave 1 file; Wave 2+ inherits |
| Brief assumes Anthropic source files unchanged since Researcher scrape | Researcher v2 §8 verified files 2026-05-08 | Source URLs in attribution lines; AID-T re-checks at install if URL drifts |
| Author drifts from "direct-steal" → "improvement" | "Wave 1 = scavenge, Wave 4 = invent" discipline | Constraint sections explicitly forbid novel patterns in Wave 1 |
| Picker still empty / orientation Tier 2 doesn't list new skills | bm-aidennis-t/CLAUDE.md Tier 1 routing table | Out of scope — picker tier-2 update is separate post-Wave-1 commit |

## Cost impact

- $0 marginal (no API calls, no external services).
- AID-T self-install time: ~7 hours of Cowork-session work (one full work-day).
- Director time: ~30 min total (review brief + ratify Wave 1 ship-report).

## Blast radius

- **If a SKILL.md is malformed:** Cowork rejects skill at session start; AID-T continues without that one skill. Reversible by fix + re-symlink. Low blast.
- **If symlink target wrong:** skill not discoverable. Reversible. Low blast.
- **If frontmatter triggers conflict with existing skills:** session manager picks one based on first-match. Test by trigger-phrase verification (Quality Checkpoint #7).
- **If vault commit pushes broken markdown:** Render mirror ingests it but no runtime impact (vault is read-mostly for skill content). Reversible.

No production-Baker risk. No Render env-var risk. No external counterparty risk.

## Open Q for Director (before AID-T self-install starts)

1. **Wave 2 trigger:** does Director want Wave 1 ship-report → ratify → Wave 2 brief drafted automatically by AH1-App, or hold Wave 2 until next Director-initiated execution window?
   - *Recommendation*: hold Wave 2 until Director-initiated. Lets the Wave 1 stubs prove the pattern before adding more.
2. **CHANDA Inv 9 vault commit:** AID-T self-install commits 4 files directly to baker-vault `main`. Confirm vault main is the right target (not a feature branch + PR).
   - *Recommendation*: direct to main (same pattern as ai-dennis OPERATING.md / LONGTERM.md edits). No vault-side PR for skill content.
3. **Researcher v2 quote re-verification at install time:** Researcher v2 §3.1 contains a "painfully specific" quote attributed to Anthropic ops/runbook that is Brisen-authored, not upstream verbatim (caught in this brief's reviewer pass; F1 fix folded). Should AID-T re-verify upstream Researcher quotes against actual upstream source files at install time as a standing rule for Waves 2-4?
   - *Recommendation*: yes — AID-T runs `gh api` fetches against the cited upstream paths at install start, flags any divergence in the Wave ship-report. One-time cost ~10 min per Wave; eliminates "Researcher said it's verbatim" cascading errors.

**Removed**: prior Open Q #2 ("license attribution wording") — already shipped with `Source: <repo>/<path> (license)` format in all 4 Wave 1 SKILL.mds; ratification implicit on Wave 1 merge per Researcher §8 recommendation.

---

## Reference: Wave 1 → Wave 4 install plan (from Researcher v2 §6)

| Wave | Stubs | Effort | Status |
|---|---|---|---|
| **Wave 1** | runbook-template, change-request, incident-response, sev1-first-15-min | ~7 hours | **THIS BRIEF** |
| Wave 2 | risk-assessment, vendor-review, compliance-tracking, status-report, process-doc | ~11 hours | brief drafted post-Wave-1 ratification |
| Wave 3 | nist-csf-assessment, cis-controls-gap, golden-signals-slo, gdpr-status, m365-hardening-maester, m365-assess | ~3 work-days | brief drafted post-Wave-2 ratification |
| Wave 4 | secret-scan, mcp-audit, render-env-rotate, pgbouncer-pool-recovery, evok-gdap-audit, ollama-health, dns-renewal-calendar, dmarc-report-parser, capacity-plan, acronis-sla-monitor, mca-changelog-watch, embeddings-rbac-audit, cyber-insurance-compliance, harden365-baseline | ~5 work-days | brief drafted post-Wave-3 ratification |

This brief covers Wave 1 only. Each subsequent Wave will get its own brief once predecessor Wave is ratified live.

---

**End of brief.**
