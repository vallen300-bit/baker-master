---
dispatch: TEMPLATES_GALLERY_LAB_INSTALL_1
to: b4
from: lead
dispatched_by: lead
status: COMPLETE
dispatched_at: 2026-05-27T14:45:00Z
completed_at: 2026-05-27T14:58:40Z
authored: 2026-05-27
target_repo: brisen-lab
workdir: ~/bm-b4-brisen-lab
estimated_time: 30-45min
complexity: Low
reply_to: lead
priority: tier-a
anchor: bus #1253 (hag-desk dispatch, Director-ratified 2026-05-27)
brief_path: briefs/BRIEF_TEMPLATES_GALLERY_LAB_INSTALL_1.md
parallel_brief: TEMPLATES_GALLERY_BAKER_INSTALL_1 (b2, baker-master — runs in parallel; no file overlap)
prerequisite_note: Link target `https://brisen-docs.onrender.com/templates/` returns 404 until parallel brief ships. Ship in parallel; target page lands when companion deploys.
ship_pr: brisen-lab#48 (merged 2026-05-27T14:58:40Z, commit 2a0aa56)
---

# B4 dispatch — TEMPLATES_GALLERY_LAB_INSTALL_1

## TL;DR
Add a third Templates Gallery item to the Brisen Lab left sidebar, positioned directly below the Business button, opening `https://brisen-docs.onrender.com/templates/` in a new tab. Director-explicit placement (bus #1253 + chat 2026-05-27): *"3rd from the left top in the left side bar"*.

Read full brief at `briefs/BRIEF_TEMPLATES_GALLERY_LAB_INSTALL_1.md`.

Workdir: `~/bm-b4-brisen-lab` (brisen-lab clone, NOT the baker-master clone at `~/bm-b4`).

## Companion
b2 ships the gallery page itself + Baker dashboard link in parallel (baker-master repo). Both ships pair in the hag-desk ack reply.

## Reply target
Bus-post `lead` on ship with PR # + merge SHA + Render deploy URL probe result.
