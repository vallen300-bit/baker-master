# Fleet session-start load audit — 2026-07-16

> **Binding ruling:** lead bus #11951. The seat manifest is Table 0 and
> supersedes the brief's imprecise '12-row map' wording.

## Table 0 — Seat manifest

Identity generator entries observed: **42** (brief/ruling expected 38; drift: +4).
Every generated row is classified exactly once. AC1/AC3 denominators are
`MEASURE-terminal` + `MEASURE-app`; Codex and no-session rows are excluded.

| Role | Class | Picker path | State |
|---|---|---|---|
| `lead` | `MEASURE-terminal` | `/Users/dimitry/bm-aihead1` | OK |
| `cowork-ah1` | `MEASURE-app` | `/Users/dimitry/bm-aihead1` | OK |
| `deputy` | `MEASURE-terminal` | `/Users/dimitry/bm-aihead2` | OK |
| `deputy-codex` | `N/A-codex` | `/Users/dimitry/bm-aihead2` | N/A |
| `aid` | `MEASURE-terminal` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-aidennis-t` | OK |
| `b1` | `MEASURE-terminal` | `/Users/dimitry/bm-b1` | OK |
| `b2` | `MEASURE-terminal` | `/Users/dimitry/bm-b2` | OK |
| `b3` | `MEASURE-terminal` | `/Users/dimitry/bm-b3` | OK |
| `b4` | `MEASURE-terminal` | `/Users/dimitry/bm-b4` | OK |
| `researcher` | `MEASURE-terminal` | `/Users/dimitry/bm-researcher` | OK |
| `codex` | `N/A-codex` | `/Users/dimitry/baker-vault` | N/A |
| `codex-arch` | `N/A-codex` | `/Users/dimitry/baker-vault` | N/A |
| `clerk` | `MEASURE-terminal` | `/Users/dimitry/bm-clerk` | OK |
| `clerk-haiku` | `MEASURE-terminal` | `/Users/dimitry/bm-clerk` | OK |
| `russo-ai` | `MEASURE-terminal` | `/Users/dimitry/bm-russo-ai` | OK |
| `deep55` | `N/A-no-session` | `N/A` | N/A |
| `ben` | `MEASURE-app` | `/Users/dimitry/bm-ben` | OK |
| `librarian` | `MEASURE-terminal` | `/Users/dimitry/bm-librarian` | OK |
| `arm` | `MEASURE-terminal` | `/Users/dimitry/bm-arm` | OK |
| `publisher` | `MEASURE-terminal` | `/Users/dimitry/bm-publisher` | OK |
| `designer` | `MEASURE-terminal` | `/Users/dimitry/bm-designer` | OK |
| `hag-desk` | `MEASURE-terminal` | `/Users/dimitry/bm-hag-desk` | OK |
| `origination-desk` | `MEASURE-terminal` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-origination-desk` | OK |
| `ao-desk` | `MEASURE-terminal` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ao-desk` | OK |
| `movie-desk` | `MEASURE-terminal` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-movie-desk` | OK |
| `baden-baden-desk` | `MEASURE-terminal` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-baden-baden-desk` | OK |
| `brisen-desk` | `MEASURE-terminal` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-brisen-desk` | OK |
| `cowork-bb-desk` | `MEASURE-app` | `/Users/dimitry/BB` | OK |
| `cowork-ao-desk` | `MEASURE-app` | `/Users/dimitry/AO` | OK |
| `cowork-movie-desk` | `MEASURE-app` | `/Users/dimitry/MOVIE` | OK |
| `cowork-hag-desk` | `MEASURE-app` | `/Users/dimitry/Hagenauer` | OK |
| `cowork-origination-desk` | `MEASURE-app` | `/Users/dimitry/Origination` | OK |
| `cowork-researcher` | `MEASURE-app` | `/Users/dimitry/Researcher` | OK |
| `cowork-arm` | `MEASURE-app` | `/Users/dimitry/ARM` | OK |
| `cowork-russo-ai` | `MEASURE-app` | `/Users/dimitry/Russo` | OK |
| `cowork-librarian` | `MEASURE-app` | `/Users/dimitry/Librarian` | OK |
| `cowork-aid` | `MEASURE-app` | `/Users/dimitry/AID` | OK |
| `CM-1` | `MEASURE-terminal` | `/Users/dimitry/bm-CM-1` | OK |
| `CM-2` | `MEASURE-terminal` | `/Users/dimitry/bm-CM-2` | OK |
| `CM-3` | `MEASURE-terminal` | `/Users/dimitry/bm-CM-3` | OK |
| `CM-4` | `MEASURE-terminal` | `/Users/dimitry/bm-CM-4` | OK |
| `hag-filer` | `MEASURE-terminal` | `/Users/dimitry/bm-hag-filer` | OK |

## Measurement method

- **Skills:** user-global `~/.claude/skills/*/SKILL.md` frontmatter plus
picker `.claude/skills/*/SKILL.md` frontmatter, counted additively.
- **CLAUDE.md chain:** existing `CLAUDE.md` files from picker to home,
deduplicated by resolved path, plus user-global `~/.claude/CLAUDE.md`.
- **Role hook:** local `.claude/role-context/<role>.md` plus route-cues;
the deputy hook also appends the laconic register.
- **Tier 0:** role orientation plus `ai-head/SKILL.md` for AH seats.
- **Window:** picker `settings.json` `rollover_window_tokens`, otherwise
the declared 200,000-token default. This is a byte proxy, not a live meter.
- **Conversion:** `bytes / 4` estimated tokens; percentage is
`bytes / 4 / window_tokens * 100`.

## Table 1 — Baseline source bytes

| Role | Class | Skills FM | CLAUDE chain | Hook | Tier 0 | Before bytes | Before % | Window |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `lead` | `MEASURE-terminal` | 130,167 | 23,023 | 10,636 | 26,395 | 190,221 | 4.76% | 1,000,000 |
| `cowork-ah1` | `MEASURE-app` | 130,167 | 19,244 | 13,073 | 7,214 | 169,698 | 4.24% | 1,000,000 |
| `deputy` | `MEASURE-terminal` | 106,211 | 19,244 | 19,110 | 16,429 | 160,994 | 4.02% | 1,000,000 |
| `aid` | `MEASURE-terminal` | 125,405 | 13,549 | 14,836 | 0 | 153,790 | 19.22% | 200,000 |
| `b1` | `MEASURE-terminal` | 106,211 | 23,023 | 12,070 | 14,422 | 155,726 | 3.89% | 1,000,000 |
| `b2` | `MEASURE-terminal` | 106,211 | 23,023 | 12,070 | 14,422 | 155,726 | 3.89% | 1,000,000 |
| `b3` | `MEASURE-terminal` | 106,211 | 23,023 | 12,070 | 14,422 | 155,726 | 3.89% | 1,000,000 |
| `b4` | `MEASURE-terminal` | 106,211 | 23,023 | 12,070 | 15,539 | 156,843 | 3.92% | 1,000,000 |
| `researcher` | `MEASURE-terminal` | 119,197 | 6,803 | 14,836 | 25,015 | 165,851 | 20.73% | 200,000 |
| `clerk` | `MEASURE-terminal` | 106,614 | 8,237 | 8,400 | 0 | 123,251 | 15.41% | 200,000 |
| `clerk-haiku` | `MEASURE-terminal` | 106,614 | 8,237 | 8,400 | 0 | 123,251 | 15.41% | 200,000 |
| `russo-ai` | `MEASURE-terminal` | 106,211 | 4,563 | 8,400 | 0 | 119,174 | 14.90% | 200,000 |
| `ben` | `MEASURE-app` | 125,557 | 13,903 | 14,836 | 0 | 154,296 | 19.29% | 200,000 |
| `librarian` | `MEASURE-terminal` | 106,211 | 6,269 | 8,400 | 8,410 | 129,290 | 0.03% | 100,000,000 |
| `arm` | `MEASURE-terminal` | 106,211 | 5,405 | 8,400 | 7,482 | 127,498 | 3.19% | 1,000,000 |
| `publisher` | `MEASURE-terminal` | 106,211 | 3,572 | 8,400 | 1,442 | 119,625 | 14.95% | 200,000 |
| `designer` | `MEASURE-terminal` | 106,211 | 3,626 | 8,400 | 1,224 | 119,461 | 14.93% | 200,000 |
| `hag-desk` | `MEASURE-terminal` | 117,052 | 9,980 | 14,836 | 0 | 141,868 | 3.55% | 1,000,000 |
| `origination-desk` | `MEASURE-terminal` | 128,732 | 6,828 | 14,836 | 0 | 150,396 | 3.76% | 1,000,000 |
| `ao-desk` | `MEASURE-terminal` | 128,683 | 6,381 | 14,836 | 0 | 149,900 | 3.75% | 1,000,000 |
| `movie-desk` | `MEASURE-terminal` | 128,650 | 7,350 | 14,836 | 0 | 150,836 | 3.77% | 1,000,000 |
| `baden-baden-desk` | `MEASURE-terminal` | 129,334 | 7,493 | 14,836 | 0 | 151,663 | 3.79% | 1,000,000 |
| `brisen-desk` | `MEASURE-terminal` | 128,803 | 7,830 | 14,836 | 0 | 151,469 | 18.93% | 200,000 |
| `cowork-bb-desk` | `MEASURE-app` | 106,211 | 5,250 | 8,400 | 0 | 119,861 | 14.98% | 200,000 |
| `cowork-ao-desk` | `MEASURE-app` | 106,211 | 9,294 | 8,400 | 3,784 | 127,689 | 15.96% | 200,000 |
| `cowork-movie-desk` | `MEASURE-app` | 106,211 | 8,302 | 8,400 | 4,263 | 127,176 | 15.90% | 200,000 |
| `cowork-hag-desk` | `MEASURE-app` | 106,211 | 6,551 | 8,400 | 0 | 121,162 | 15.15% | 200,000 |
| `cowork-origination-desk` | `MEASURE-app` | 106,211 | 6,473 | 8,400 | 2,837 | 123,921 | 15.49% | 200,000 |
| `cowork-researcher` | `MEASURE-app` | 106,211 | 6,056 | 8,400 | 27,712 | 148,379 | 18.55% | 200,000 |
| `cowork-arm` | `MEASURE-app` | 106,211 | 5,586 | 8,400 | 9,958 | 130,155 | 16.27% | 200,000 |
| `cowork-russo-ai` | `MEASURE-app` | 106,211 | 5,729 | 8,400 | 2,647 | 122,987 | 15.37% | 200,000 |
| `cowork-librarian` | `MEASURE-app` | 106,211 | 5,638 | 8,400 | 11,048 | 131,297 | 16.41% | 200,000 |
| `cowork-aid` | `MEASURE-app` | 106,211 | 5,975 | 8,400 | 0 | 120,586 | 15.07% | 200,000 |
| `CM-1` | `MEASURE-terminal` | 106,211 | 5,956 | 9,902 | 0 | 122,069 | 15.26% | 200,000 |
| `CM-2` | `MEASURE-terminal` | 106,211 | 5,959 | 9,902 | 0 | 122,072 | 15.26% | 200,000 |
| `CM-3` | `MEASURE-terminal` | 106,211 | 5,959 | 9,902 | 0 | 122,072 | 15.26% | 200,000 |
| `CM-4` | `MEASURE-terminal` | 106,211 | 5,959 | 10,024 | 0 | 122,194 | 15.27% | 200,000 |
| `hag-filer` | `MEASURE-terminal` | 114,535 | 23,023 | 10,742 | 0 | 148,300 | 3.71% | 1,000,000 |

## Table 2 — Codex and excluded rows

| Role | Class | Footnote |
|---|---|---|
| `deputy-codex` | `N/A-codex` | AGENTS.md bytes: 9,447; Claude skill frontmatter excluded. |
| `codex` | `N/A-codex` | AGENTS.md bytes: 0; Claude skill frontmatter excluded. |
| `codex-arch` | `N/A-codex` | AGENTS.md bytes: 0; Claude skill frontmatter excluded. |
| `deep55` | `N/A-no-session` | Identity row is planned and has no local session launcher. |

## Fail-loud notes

- The generated source currently returns 42 entries, not 38; all 42 are
included above rather than silently dropped.
- The identity generator has no service row in `SNAPSHOT_TERMINALS`; the
planned `deep55` row is the only current `N/A-no-session` classification.
- Percentages are deterministic byte proxies. A fresh session meter is
required to close the live AC after each rollout group.

## Table 3 — Lead-local pilot byte delta

| Surface | Before bytes | Current bytes | Delta |
|---|---:|---:|---:|
| `_ops/agents/aihead1/orientation.md` | 13,061 | 3,332 | -9,729 |
| `_ops/skills/ai-head/SKILL.md` | 13,334 | 3,704 | -9,630 |
| `bm-aihead1/CLAUDE.md` | 20,703 | 16,913 | -3,790 |
| `bm-aihead1/.claude/role-context/lead.md` | 6,436 | 933 | -5,503 |
| `AH1 MEMORY.md` | 26,831 | 4,376 | -22,455 |
| `dropbox-tier0.md` | 11,093 | 11,093 | 0 (fleet stage) |

The lead-local trim is intentionally not the final 6.5% target: the binding
ruling moves global skill redistribution to the coordinated fleet migration.
