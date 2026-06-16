# Baker CEO Cockpit - Design System V6

Inherits from shared design source:

`/Users/dimitry/baker-vault/wiki/design/design-v2.md`

Selected pattern:

`Pattern C - Baker Operational Dashboard`

## Purpose

Baker is a live operational cockpit for the Director. It must make current state, critical work, promised work, meetings, freshness, and next action easy to scan without turning the interface into a decorative cockpit.

## Direction

- Operational, calm, precise, and trustworthy.
- Dark neutral base remains primary for now.
- Blue is the compact metadata/action accent.
- Red, amber, and green are semantic only.
- Cards use Brisen Lab-style tactile depth.
- Card action rows stay short; secondary actions move behind `...`.

## Primary Tokens

| Token | Value | Role |
|---|---|---|
| `--bg` | `#0D1117` | Page field |
| `--bg-subtle` | `#10151C` | Sidebar and anchored chrome |
| `--bg2` | `#1B222D` | Inputs and raised sub-surfaces |
| `--card` | `#171D26` | Cards and panels |
| `--border` | `rgba(140,154,170,0.24)` | Hairline grouping |
| `--text` | `#EEF2F6` | Primary text |
| `--text2` | `#B9C0C8` | Supporting text |
| `--text3` | `#8B949E` | Metadata, still accessible |
| `--blue` | `#58A6FF` | Focus, metadata, primary affordance |
| `--amber` | `#D29922` | Warning/deadline |
| `--green` | `#2BD964` | Healthy/complete |
| `--red` | `#F85149` | Critical/error |

## Component Rules

- Navigation controls are buttons or links with visible focus.
- Main content exposes a `main` landmark.
- Desktop cards use inset top highlight, bottom lip, and cast shadow.
- Mobile home is the same cockpit information architecture in one column: briefing status, Travel, Critical, Promised To Do, Meetings, then Cortex/system status.
- Mobile action cards show a top-right `...` menu; only the primary action remains visible.
- Mobile must allow zoom and keep muted text above accessibility contrast thresholds.
- Empty, loading, error, stale, success, and disabled states must be visible as text, not color only.

## Non-Goals

- Do not rewrite Baker API behavior in a design pass.
- Do not make Baker look like AIology or AI Hotel.
- Do not reintroduce luxury/champagne as the main identity.
