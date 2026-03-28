# Baker CEO Cockpit — Design System v5 (Luxury Concierge)

## Brand Essence
Private wealth management meets AI chief of staff.
Think Amex Centurion lounge meets Bloomberg terminal.
Sophisticated, understated, premium.

## Color Palette

### Core Surfaces
| Token | Hex | Usage |
|-------|-----|-------|
| `--bg` | `#0D0F14` | Page background |
| `--bg-subtle` | `#141820` | Sidebar, input backgrounds |
| `--bg2` | `#1A1F28` | Card surfaces, elevated elements |
| `--card` | `#1A1F28` | Cards, panels |
| `--border` | `rgba(201,169,110,0.12)` | All borders |

### Text Hierarchy
| Token | Hex | Usage |
|-------|-----|-------|
| `--text` | `#E8E4DC` | Primary text (cream) |
| `--text2` | `#9B958B` | Secondary text |
| `--text3` | `#6B6560` | Tertiary/muted text |

### Accent — Champagne Gold
| Token | Hex | Usage |
|-------|-----|-------|
| `--blue` | `#C9A96E` | Primary accent (gold) |
| `--blue-hover` | `#B89A5C` | Hover state |
| `--blue-bg` | `rgba(201,169,110,0.10)` | Gold background tint |

### Semantic Colors (Muted)
| Token | Hex | Usage |
|-------|-----|-------|
| `--red` | `#C75050` | Critical, errors |
| `--amber` | `#D4A535` | Warnings, deadlines |
| `--green` | `#5B9A6F` | Success, confirmed |

## Typography

| Role | Font | Weight | Size |
|------|------|--------|------|
| Logo | EB Garamond | 700 | 18px, uppercase, 2px tracking |
| Greeting/Headings | EB Garamond | 700 | 30px |
| Section labels | DM Sans mono | 600 | 11px uppercase |
| Body text | DM Sans | 400 | 13-14px |
| Monospace | SF Mono / Fira Code | — | 10-11px |

## Component Patterns

### Cards
- Background: `var(--card)` (#1A1F28)
- Border: `1px solid var(--border)`
- Border-radius: 14px
- Shadow: `0 2px 8px rgba(0,0,0,0.15)`

### Grid Headers (Landing 2x2)
- Travel: `rgba(201,169,110,0.08)` — gold tint
- Critical: `rgba(199,80,80,0.08)` — red tint
- Promised: `rgba(212,165,53,0.08)` — amber tint
- Meetings: `rgba(91,154,111,0.08)` — green tint

### Buttons
- Primary: gold bg (`var(--blue)`), white text
- Secondary: ghost border, gold text on hover
- Pills: `border-radius: 22px`

### Chat Bubbles
- User: `rgba(201,169,110,0.15)` with gold border
- Baker: `var(--bg-subtle)` with standard border

### Sidebar
- Background: `var(--bg-subtle)` (#141820)
- Active item: gold bg tint + gold text + left border
- Hover: subtle gold tint

## Design Principles
1. Never bright or saturated — always muted, sophisticated
2. Gold accent only on interactive elements and highlights
3. Serif (EB Garamond) for personality, sans (DM Sans) for readability
4. Generous whitespace — let elements breathe
5. Thin borders preferred over heavy shadows
6. Premium restraint — less is more
