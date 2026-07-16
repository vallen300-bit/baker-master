# Cockpit manifest reconciliation (FLEET_TMUX_LAUNCH_1, join v1.3.2 / #12093)

> GENERATED artifact — do not hand-edit. Reconcile-to-exactly-one: a profile
> resolves iff its literal BAKER_ROLE/FORGE_TERMINAL markers (≤1 wrapper hop,
> NO cwd parsing) map to exactly one registry slug. Zero/conflict/multiple =
> unresolved -> fix that seat's zsh function markers at source, never a table.

- Eligible seats (active + runtime terminal-*): **26**
- Resolved into manifest: **26**
- Unresolved eligible seats: **0**

## Resolved seats

| port | slug | alias | Terminal profile |
|---|---|---|---|
| 7600 | lead | `aihead1` | AI 1 LEAD |
| 7602 | deputy | `aihead2claude` | AI Head B (Claude) |
| 7603 | deputy-codex | `aihead2` | DEPUTY CODEX |
| 7605 | aid | `aidennist` | AID |
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

## Unresolved eligible seats (fix the zsh function markers)

_none — all eligible seats resolved deterministically._

## Per-profile provenance (reviewer line-read — #12093 delta 3)

| profile | alias | wrapper hop | markers found | matched slug | verdict |
|---|---|---|---|---|---|
| AI 1 LEAD | `aihead1` | — | BAKER_ROLE=lead, FORGE_TERMINAL=lead | lead | resolved |
| AI Head B (Claude) | `aihead2claude` | — | BAKER_ROLE=deputy, FORGE_TERMINAL=deputy | deputy | resolved |
| AID | `aidennist` | — | BAKER_ROLE=aid, FORGE_TERMINAL=ai_dennis_t | aid | resolved |
| AO Desk | `aodesk` | — | BAKER_ROLE=ao-desk, FORGE_TERMINAL=ao-desk | ao-desk | resolved |
| ARM | `arm` | — | BAKER_ROLE=arm, FORGE_TERMINAL=arm | arm | resolved |
| B1 | `b1` | — | BAKER_ROLE=B1, FORGE_TERMINAL=b1 | b1 | resolved |
| B2 | `b2` | — | BAKER_ROLE=B2, FORGE_TERMINAL=b2 | b2 | resolved |
| B3 | `b3` | — | BAKER_ROLE=B3, FORGE_TERMINAL=b3 | b3 | resolved |
| B4 | `b4` | — | BAKER_ROLE=B4, FORGE_TERMINAL=b4 | b4 | resolved |
| B5 | `b5` | — | BAKER_ROLE=B5, FORGE_TERMINAL=b5 | b5 | resolved |
| BEN | `ben` | — | BAKER_ROLE=BB_FINANCE, FORGE_TERMINAL=ben | — | unresolved: CONFLICT — markers point at ['bb-finance', 'ben'] |
| Baden-Baden Desk | `badenbadendesk` | — | BAKER_ROLE=BADEN_BADEN_DESK, FORGE_TERMINAL=baden-baden-desk | baden-baden-desk | resolved |
| Brisen Desk | `brisendesk` | — | BAKER_ROLE=brisen-desk, FORGE_TERMINAL=brisen-desk | brisen-desk | resolved |
| CM-1 | `cm1` | — | BAKER_ROLE=CM-1, FORGE_TERMINAL=CM-1 | CM-1 | resolved |
| CM-2 | `cm2` | — | BAKER_ROLE=CM-2, FORGE_TERMINAL=CM-2 | CM-2 | resolved |
| CM-3 | `cm3` | — | BAKER_ROLE=CM-3, FORGE_TERMINAL=CM-3 | CM-3 | resolved |
| CM-4 | `cm4` | — | BAKER_ROLE=CM-4, FORGE_TERMINAL=CM-4 | CM-4 | resolved |
| Clerk | `clerk` | — | BAKER_ROLE=clerk, FORGE_TERMINAL=clerk | clerk | resolved |
| Clerk Qwen3 | `clerkqwenterm` | — | — | — | unresolved: zero identity markers (BAKER_ROLE/FORGE_TERMINAL) |
| Codex 5.5 | `cvi` | — | FORGE_TERMINAL=codex | codex | resolved |
| DEPUTY CODEX | `aihead2` | aihead2codex | BAKER_ROLE=deputy-codex, FORGE_TERMINAL=deputy-codex | deputy-codex | resolved |
| Deep55 | `deep55picker` | — | — | — | unresolved: zero identity markers (BAKER_ROLE/FORGE_TERMINAL) |
| Hag Desk | `hagenauerdesk` | — | BAKER_ROLE=hag-desk, FORGE_TERMINAL=hag-desk | hag-desk | resolved |
| Hag Filer | `hagfiler` | — | BAKER_ROLE=hag-filer, FORGE_TERMINAL=hag-filer | hag-filer | resolved |
| LIBRARIAN | `librarian` | — | BAKER_ROLE=librarian, FORGE_TERMINAL=librarian | librarian | resolved |
| MOVIE Desk | `moviedesk` | — | BAKER_ROLE=MOVIE_DESK, FORGE_TERMINAL=movie-desk | movie-desk | resolved |
| Origination Desk | `originationdesk` | — | BAKER_ROLE=ORIGINATION_DESK, FORGE_TERMINAL=origination-desk | origination-desk | resolved |
| Publisher | `publisher` | — | BAKER_ROLE=publisher, FORGE_TERMINAL=publisher | publisher | resolved |
| Researcher | `researcher` | — | BAKER_ROLE=researcher, FORGE_TERMINAL=researcher | researcher | resolved |
| Russo AI | `russoai` | — | BAKER_ROLE=russo-ai, FORGE_TERMINAL=russo-ai | russo-ai | resolved |
| UI Designer | `designer` | — | BAKER_ROLE=designer, FORGE_TERMINAL=designer | designer | resolved |
