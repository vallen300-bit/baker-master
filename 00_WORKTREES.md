# 00 — Worktrees & Session Labels

**Purpose:** reference card for Director's multi-window Claude setup (Terminal CLI **and** Claude Code App). Tells you which window/tab maps to which role and working directory.

**When to read:** whenever you're unsure what a window is, or when setting up a new window for a specific role.

**Last updated:** 2026-04-29 — split Terminal vs App AI Head rows after Director verified App AI Heads live in Dropbox-synced project root, not `~/Desktop/baker-code`.

---

## Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Baker multi-window setup                         │
│                     (Director's MacBook)                            │
└─────────────────────────────────────────────────────────────────────┘

  ROLE                       SURFACE     COMMAND / OPEN                          DIRECTORY
  ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  Research Agent             App         Cowork Code App pane (no CLI)            (no worktree — Cowork session)
                                  (RA = Lab + orchestration; writes to _ops/ideas/) — RETIRED 2026-04-28T07:00Z

  AI Head A (Terminal)       Terminal    cd ~/Desktop/baker-code && aihead1       ~/Desktop/baker-code
  AI Head B (Terminal)       Terminal    cd ~/Desktop/baker-code && aihead2       ~/Desktop/baker-code
                                  (Tier 2 flat layout — terminal-side checkout)

  AI Head A (App)            App         Open project in Claude Code App          ~/Vallen Dropbox/Dimitry vallen/Baker-Project
  AI Head B (App)            App         Open project in Claude Code App          ~/Vallen Dropbox/Dimitry vallen/Baker-Project
                                  (Dropbox-synced, cross-device; auto-memory at
                                   ~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/
                                   — shared by all App AI Heads in this project)

  Code Brisen B1             Terminal    cd ~/bm-b1 && b1                         ~/bm-b1
  Code Brisen B2 (Terminal)  Terminal    cd ~/bm-b2 && b2                         ~/bm-b2
  Code Brisen B2 (App)       App         Open project in Claude Code App          ~/bm-b2
  Code Brisen B3             Terminal    cd ~/bm-b3 && b3                         ~/bm-b3
  Code Brisen B4             Terminal    cd ~/bm-b4 && b4                         ~/bm-b4
                                  (each B-code: its own clone, independent context, branch isolation for builds)

  (dormant)                              staged, not active                       ~/bm-b5
```

---

## Terminal vs App — when to use which

**Terminal AI Heads** (`~/Desktop/baker-code`)
- Tier 2 flat layout. Local-only. Fastest.
- Use for: in-session orchestration when Director is at the laptop.

**App AI Heads** (`~/Vallen Dropbox/Dimitry vallen/Baker-Project`)
- Dropbox-synced — cross-device continuity (laptop ↔ phone ↔ another machine).
- Auto-memory shared between A and B App instances when both opened in this project root.
- Use for: long-running orchestration, cross-device pickup, parallel App-side AI Head A + B that share auto-memory.

**Code Brisens (B1–B4)** stay in their own clones (`~/bm-b{N}`) regardless of Terminal vs App — branch isolation is the whole point of the worktree pattern. B2 currently runs in App (per topology refresh 2026-04-28T08:35Z) but still in `~/bm-b2`.

---

## Rules of thumb

- **Planning / dispatching / brief writing** = AI Head lane → `~/Desktop/baker-code` (Terminal) **or** `~/Vallen Dropbox/Dimitry vallen/Baker-Project` (App)
- **Implementing a brief / writing code** = Code Brisen lane → `~/bm-b{N}` (always — Terminal or App)
- Each terminal tab's title (set by functions in `~/.zshrc`) tells you which role that window holds — look at the tab bar.
- App tabs: project picker (top-left in App) shows the working directory — that's the role tell.

---

## Session start sequence (every new window)

**Terminal:**
1. Open new terminal tab.
2. Type the command for the role you want (from the Map above).
3. Wait for Claude Code prompt.
4. Paste the role-specific handover note as your first message.
5. Claude resumes where the last instance of that role left off.

**App:**
1. Open Claude Code App → top-left project picker → "Add project" / browse.
2. Paste the absolute path for the role:
   - AI Head A or B → `/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project`
   - B2 App → `/Users/dimitry/bm-b2`
3. New chat in that project.
4. Paste the role-specific handover note as your first message.
5. After compaction: project sticks; `/clear` then re-paste the orientation handover.

---

## Live-check command

Run any time you're unsure what's where:

```bash
ls -d ~/Desktop/baker-code ~/bm-b* 2>/dev/null
```

Expected output:
```
/Users/dimitry/Desktop/baker-code
/Users/dimitry/bm-b1
/Users/dimitry/bm-b2
/Users/dimitry/bm-b2-venv
/Users/dimitry/bm-b3
/Users/dimitry/bm-b4
/Users/dimitry/bm-b5
```

---

## Functions in `~/.zshrc`

Installed 2026-04-24:

```bash
function aihead1() { printf "\033]0;AI Head A\007"; claude "$@"; }
function aihead2() { printf "\033]0;AI Head B\007"; claude "$@"; }
function b1()      { printf "\033]0;Code Brisen B1\007"; claude "$@"; }
function b2()      { printf "\033]0;Code Brisen B2\007"; claude "$@"; }
function b3()      { printf "\033]0;Code Brisen B3\007"; claude "$@"; }
function b4()      { printf "\033]0;Code Brisen B4\007"; claude "$@"; }
```

Each sets the terminal tab title, then launches Claude Code.

## Adding a new role

Append one function to `~/.zshrc` using the same pattern:

```bash
function ROLE_NAME() { printf "\033]0;LABEL_SHOWN_IN_TAB\007"; claude "$@"; }
```

Then `source ~/.zshrc`. If you want the function to always start in a specific dir, make it `cd DIR && claude "$@"` instead.

**Candidates to add later** (not yet configured):
- `aidev` — Baker codebase development
- `biz` — Business analysis (deal analyst / sales / asset mgmt)
- `dennis` — AI Dennis (IT shadow agent)

**Note on Research Agent:** RA does **not** get a CLI function. It lives as a persistent pane in the Cowork Code App (Opus 4.7, 1M context, Extra-High effort) — see `_ops/agents/research-agent/OPERATING.md` §Live paste-target labels.

---

## Three authorities (banked 2026-04-25)

- **Dispatch authority** = writes B-code mailbox + sends wake-paste → **AI Head only**
- **Orchestration authority** = tracks cross-team state, surfaces collisions → **RA**
- **Ratification authority** = approves scope, sets priorities, authorizes Tier B → **Director**

RA may recommend "fan out 4 in parallel"; AI Head decides yes/no and pulls trigger; Director ratifies scope upstream. Don't conflate.
