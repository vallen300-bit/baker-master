# 00 — Worktrees & Session Labels

**Purpose:** reference card for Director's multi-window Claude CLI setup. Tells you which terminal tab maps to which role and working directory.

**When to read:** whenever you're unsure what a terminal window is, or when setting up a new window for a specific role.

**Last updated:** 2026-04-26.

---

## Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Baker multi-window setup                         │
│                     (Director's MacBook)                            │
└─────────────────────────────────────────────────────────────────────┘

  ROLE              COMMAND                            DIRECTORY
  ─────────────────────────────────────────────────────────────────
  Research Agent    Cowork Code App pane (no CLI)       (no worktree — works in Cowork session)
                        (RA = Lab + orchestration; writes to _ops/ideas/)

  AI Head A         cd ~/Desktop/baker-code && aihead1  ~/Desktop/baker-code
  AI Head B         cd ~/Desktop/baker-code && aihead2  ~/Desktop/baker-code
                        (one persona, two instances; A = Build lead, B = reviewer; share main repo)

  Code Brisen B1    cd ~/bm-b1 && b1                    ~/bm-b1
  Code Brisen B2    cd ~/bm-b2 && b2                    ~/bm-b2
  Code Brisen B3    cd ~/bm-b3 && b3                    ~/bm-b3
  Code Brisen B4    cd ~/bm-b4 && b4                    ~/bm-b4
                        (each its own clone, independent context)

  (dormant)         ~/bm-b5                             staged, not active
```

---

## Rules of thumb

- **Planning / dispatching / brief writing** = AI Head lane → `~/Desktop/baker-code`
- **Implementing a brief / writing code** = Code Brisen lane → `~/bm-b{N}`
- Each terminal tab's title (set by the functions in `~/.zshrc`) tells you which role that window holds — look at the tab bar, know what the window is.

---

## Session start sequence (every new window)

1. Open new terminal tab.
2. Type the command for the role you want (from the Map above).
3. Wait for Claude Code prompt.
4. Paste the role-specific handover note as your first message.
5. Claude resumes where the last instance of that role left off.

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
