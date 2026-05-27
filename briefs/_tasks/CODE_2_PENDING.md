---
dispatch: TEMPLATES_GALLERY_BAKER_INSTALL_1
to: b2
from: lead
dispatched_by: lead
status: IN_PROGRESS
dispatched_at: 2026-05-27T14:45:00Z
authored: 2026-05-27
target_repo: baker-master
estimated_time: 1-2h
complexity: Low
reply_to: lead
priority: tier-a
anchor: bus #1253 (hag-desk dispatch, Director-ratified 2026-05-27)
brief_path: briefs/BRIEF_TEMPLATES_GALLERY_BAKER_INSTALL_1.md
staged_html: /Users/dimitry/baker-vault/_ops/agents/hagenauer-desk/staging/templates-gallery-index.html
parallel_brief: TEMPLATES_GALLERY_LAB_INSTALL_1 (b4, brisen-lab — runs in parallel; no file overlap)
prior_mailbox_state: superseded — RECHARGE_REPORT_SCAFFOLD_SCHEMA_VALIDATOR_1 shipped (PR #267 merged 2026-05-27)
---

# B2 dispatch — TEMPLATES_GALLERY_BAKER_INSTALL_1

## TL;DR
Install hag-desk's already-styled Templates Gallery page into `baker-master/docs-site/templates/`, register it in both manifests (`docs-site/index.json` + `outputs/static/presentations.json`), and add an external-link nav entry in the Baker dashboard left sidebar between Documents and Dossiers.

Read full brief at `briefs/BRIEF_TEMPLATES_GALLERY_BAKER_INSTALL_1.md`.

## Companion
b4 ships the Lab dashboard link in parallel (brisen-lab repo). Both ships pair in the hag-desk ack reply.

## Reply target
Bus-post `lead` on ship with PR # + merge SHA + live `https://brisen-docs.onrender.com/templates/` probe result.
