# Cockpit manifest reconciliation (FLEET_TMUX_LAUNCH_1, join D / #12080)

> GENERATED artifact — do not hand-edit. Fixing an unresolved seat means
> correcting that seat's zsh function (real source), never a table here.

- Eligible seats (active + runtime terminal-*): **26**
- Resolved into manifest: **25**
- Unresolved eligible seats: **1**

## Resolved

| port | slug | alias | Terminal profile |
|---|---|---|---|
| 7600 | lead | `aihead1` | AI 1 LEAD |
| 7602 | deputy | `aihead2claude` | AI Head B (Claude) |
| 7603 | deputy-codex | `aihead2` | DEPUTY CODEX |
| 7606 | b1 | `b1` | B1 |
| 7607 | b2 | `b2` | B2 |
| 7608 | b3 | `b3` | B3 |
| 7609 | b4 | `b4` | B4 |
| 7611 | researcher | `researcher` | Researcher |
| 7612 | codex | `cvi` | Codex 5.5 |
| 7616 | russo-ai | `russoai` | Russo AI |
| 7619 | librarian | `librarian` | LIBRARIAN |
| 7620 | arm | `arm` | ARM |
| 7621 | publisher | `publisher` | Publisher |
| 7622 | designer | `designer` | UI Designer |
| 7623 | hag-desk | `hagenauerdesk` | Hag Desk |
| 7624 | origination-desk | `originationdesk` | Origination Desk |
| 7625 | ao-desk | `aodesk` | AO Desk |
| 7626 | movie-desk | `moviedesk` | MOVIE Desk |
| 7627 | baden-baden-desk | `badenbadendesk` | Baden-Baden Desk |
| 7628 | brisen-desk | `brisendesk` | Brisen Desk |
| 7640 | CM-1 | `cm1` | CM-1 |
| 7641 | CM-2 | `cm2` | CM-2 |
| 7642 | CM-3 | `cm3` | CM-3 |
| 7643 | CM-4 | `cm4` | CM-4 |
| 7644 | hag-filer | `hagfiler` | Hag Filer |

## Unresolved eligible seats (fix the zsh function)

| slug | display | runtime | why |
|---|---|---|---|
| aid | AID T | terminal-claude | no Terminal profile function body resolved to this slug |

## Unresolved Terminal profiles (informational)

| profile | alias | reason |
|---|---|---|
| AID | `aidennist` | marker 'AI_DENNIS' does not map to any registry slug |
| Deep55 | `deep55picker` | function body carries no BAKER_ROLE/FORGE_TERMINAL/picker-dir marker |
