#!/bin/bash
# =============================================================================
# Mac Mini (Code Brisen) — Claude Code Setup
# Replicates MacBook AI Head environment: Baker MCP + Chrome MCP + 19 agents
# Run this script from the Mac Mini after cloning the baker-code repo.
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

echo "============================================"
echo " Mac Mini — Claude Code Setup for Baker"
echo "============================================"
echo ""

# --- Step 0: Detect environment ---
USER_HOME="$HOME"
CLAUDE_DIR="$USER_HOME/.claude"
CLAUDE_JSON="$USER_HOME/.claude.json"

echo "Home: $USER_HOME"
echo "User: $(whoami)"
echo ""

# --- Step 1: Check Claude Code CLI ---
if command -v claude &>/dev/null; then
    log "Claude Code CLI found: $(which claude)"
    claude --version 2>/dev/null || true
else
    warn "Claude Code CLI not found. Installing..."
    if command -v npm &>/dev/null; then
        npm install -g @anthropic-ai/claude-code
        log "Claude Code CLI installed"
    else
        err "npm not found. Install Node.js first: brew install node"
        exit 1
    fi
fi
echo ""

# --- Step 2: Check Python 3.12 ---
PYTHON_BIN=""
if [ -f "/opt/homebrew/bin/python3.12" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.12"
elif command -v python3.12 &>/dev/null; then
    PYTHON_BIN="$(which python3.12)"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="$(which python3)"
    warn "Using python3 instead of python3.12: $PYTHON_BIN"
else
    err "Python 3 not found. Install: brew install python@3.12"
    exit 1
fi
log "Python: $PYTHON_BIN"

# Check MCP server dependencies
$PYTHON_BIN -c "import psycopg2" 2>/dev/null || {
    warn "psycopg2 not installed. Installing..."
    $PYTHON_BIN -m pip install psycopg2-binary 2>/dev/null || $PYTHON_BIN -m pip install psycopg2-binary --user
}
log "psycopg2 available"
echo ""

# --- Step 3: Find Baker MCP server ---
MCP_SERVER=""
DROPBOX_PATHS=(
    "$USER_HOME/Dropbox (Vallen)/Baker-Project/baker-mcp/baker_mcp_server.py"
    "$USER_HOME/Vallen Dropbox/Dimitry vallen/Baker-Project/baker-mcp/baker_mcp_server.py"
    "$USER_HOME/Dropbox-Vallen/Dimitry vallen/Baker-Project/baker-mcp/baker_mcp_server.py"
    "$USER_HOME/Dropbox/Baker-Project/baker-mcp/baker_mcp_server.py"
)
for p in "${DROPBOX_PATHS[@]}"; do
    if [ -f "$p" ]; then
        MCP_SERVER="$p"
        break
    fi
done

if [ -z "$MCP_SERVER" ]; then
    warn "Baker MCP server not found in Dropbox paths."
    warn "Make sure Dropbox is synced. Looked in:"
    for p in "${DROPBOX_PATHS[@]}"; do echo "  - $p"; done
    echo ""
    read -p "Enter Baker MCP server path (or press Enter to skip): " MCP_SERVER
fi

if [ -n "$MCP_SERVER" ]; then
    log "Baker MCP server: $MCP_SERVER"
else
    warn "Baker MCP will need to be configured manually later"
fi
echo ""

# --- Step 4: Check repo ---
REPO_DIR="$USER_HOME/Desktop/baker-code"
if [ -d "$REPO_DIR/.git" ]; then
    log "Repo already cloned at $REPO_DIR"
    cd "$REPO_DIR" && git pull
elif [ -d "$REPO_DIR" ]; then
    warn "$REPO_DIR exists but is not a git repo"
    read -p "Clone into $REPO_DIR? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$REPO_DIR"
        git clone git@github.com:vallen300-bit/baker-master.git "$REPO_DIR"
    fi
else
    log "Cloning baker-master repo..."
    git clone git@github.com:vallen300-bit/baker-master.git "$REPO_DIR"
fi
log "Repo ready at $REPO_DIR"
echo ""

# --- Step 5: Create ~/.claude/settings.json ---
mkdir -p "$CLAUDE_DIR"
cat > "$CLAUDE_DIR/settings.json" << 'SETTINGS_EOF'
{
  "permissions": {
    "allow": [
      "Read",
      "Edit",
      "Bash(npm run *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git commit *)",
      "Bash(git status)",
      "Bash(git push *)",
      "Bash(ls *)",
      "Bash(cat *)",
      "Bash(mkdir *)"
    ],
    "deny": [],
    "defaultMode": "bypassPermissions"
  },
  "model": "opus[1m]",
  "enabledPlugins": {
    "feature-dev@claude-plugins-official": true,
    "pyright-lsp@claude-plugins-official": true,
    "code-review@claude-plugins-official": true,
    "security-guidance@claude-plugins-official": true,
    "hookify@claude-plugins-official": true,
    "claude-code-setup@claude-plugins-official": true,
    "ralph-loop@claude-plugins-official": true,
    "skill-creator@claude-plugins-official": true,
    "agent-sdk-dev@claude-plugins-official": true
  },
  "skipDangerousModePermissionPrompt": true
}
SETTINGS_EOF
log "Created ~/.claude/settings.json (Opus 1M, bypass mode, 9 plugins)"

# --- Step 6: Configure MCP servers in ~/.claude.json ---
# We need to merge mcpServers into existing ~/.claude.json (which has other state too)

# Build the MCP config
MCP_BAKER_JSON=""
if [ -n "$MCP_SERVER" ]; then
    # Escape the path for JSON
    ESCAPED_PATH=$(echo "$MCP_SERVER" | sed 's/"/\\"/g')
    ESCAPED_PYTHON=$(echo "$PYTHON_BIN" | sed 's/"/\\"/g')
    MCP_BAKER_JSON=$(cat << BAKER_EOF
    "baker": {
      "type": "stdio",
      "command": "$ESCAPED_PYTHON",
      "args": [
        "$ESCAPED_PATH"
      ],
      "env": {
        "POSTGRES_HOST": "ep-summer-sun-aih7ha4h.c-4.us-east-1.aws.neon.tech",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "neondb",
        "POSTGRES_USER": "neondb_owner",
        "POSTGRES_PASSWORD": "npg_26tjJyupOSfi",
        "POSTGRES_SSLMODE": "require"
      }
    }
BAKER_EOF
    )
fi

# Use Python to merge MCP servers into existing ~/.claude.json
$PYTHON_BIN << PYEOF
import json, os

claude_json_path = os.path.expanduser("~/.claude.json")
data = {}
if os.path.exists(claude_json_path):
    with open(claude_json_path) as f:
        data = json.load(f)

# Ensure mcpServers key exists
if "mcpServers" not in data:
    data["mcpServers"] = {}

# Add Baker MCP
mcp_server = """$MCP_SERVER"""
python_bin = """$PYTHON_BIN"""
if mcp_server:
    data["mcpServers"]["baker"] = {
        "type": "stdio",
        "command": python_bin,
        "args": [mcp_server],
        "env": {
            "POSTGRES_HOST": "ep-summer-sun-aih7ha4h.c-4.us-east-1.aws.neon.tech",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "neondb",
            "POSTGRES_USER": "neondb_owner",
            "POSTGRES_PASSWORD": "npg_26tjJyupOSfi",
            "POSTGRES_SSLMODE": "require"
        }
    }

# Add Chrome MCP
data["mcpServers"]["chrome"] = {
    "type": "stdio",
    "command": "npx",
    "args": ["chrome-devtools-mcp@latest", "--browserUrl", "http://127.0.0.1:9222"]
}

# Add Render MCP as project-level config
project_key = os.path.expanduser("~/Desktop/baker-code")
if "projects" not in data:
    data["projects"] = {}
if project_key not in data["projects"]:
    data["projects"][project_key] = {}
data["projects"][project_key]["mcpServers"] = {
    "render": {
        "type": "http",
        "url": "https://mcp.render.com/mcp",
        "headers": {
            "Authorization": "Bearer rnd_KfUrD5r1vZKP5Ed9nKPV7bv49ODz"
        }
    }
}
data["projects"][project_key]["hasTrustDialogAccepted"] = True

with open(claude_json_path, "w") as f:
    json.dump(data, f, indent=2)

print("MCP servers configured in ~/.claude.json")
PYEOF

log "MCP servers configured: baker + chrome + render"
echo ""

# --- Step 7: Install skills ---
SKILLS_DIR="$CLAUDE_DIR/skills"
mkdir -p "$SKILLS_DIR"

# ai-engineer
mkdir -p "$SKILLS_DIR/ai-engineer"
cat > "$SKILLS_DIR/ai-engineer/SKILL.md" << 'SKILL_EOF'
---
name: ai-engineer
description: >
  AI/ML engineering specialist for building intelligent systems. Use when working with
  LLMs, embeddings, RAG, fine-tuning, prompt engineering, vector databases, ML pipelines,
  or AI-powered features.
  Triggers: AI, ML, LLM, Claude, GPT, embeddings, RAG, vector, Qdrant, Pinecone,
  fine-tune, prompt, agent, tool use, chain, retrieval, classification, NLP.
---
# AI Engineer Skill
You are an AI/ML engineering specialist. When this skill is triggered:
1. Identify the AI/ML task type (RAG, embeddings, fine-tuning, prompt engineering, etc.)
2. Use best practices for the specific domain
3. Consider cost, latency, and accuracy tradeoffs
4. Recommend appropriate models and embedding dimensions
5. Follow Baker's existing patterns: Voyage AI voyage-3 (1024 dims), Qdrant Cloud, Claude API

## Key patterns in this codebase:
- Embeddings: `tools/embedder.py` using Voyage AI
- Vector store: Qdrant Cloud collections (see CLAUDE.md for list)
- LLM: Claude via Anthropic SDK
- RAG pipeline: `orchestrator/pipeline.py`
- Agent loop: `orchestrator/agent.py`
SKILL_EOF

# backend-architect
mkdir -p "$SKILLS_DIR/backend-architect"
cat > "$SKILLS_DIR/backend-architect/SKILL.md" << 'SKILL_EOF'
---
name: backend-architect
description: >
  Backend architecture specialist for designing and building server-side systems.
  Use when working on APIs, databases, authentication, caching, microservices,
  queues, or any server-side code.
  Triggers: backend, API, database, auth, server, REST, GraphQL, microservice,
  queue, cache, migration, schema, endpoint, middleware, ORM.
---
# Backend Architect Skill
You are a backend architecture specialist. When this skill is triggered:
1. Consider scalability, reliability, and security
2. Follow REST API best practices
3. Use proper database patterns (indexes, transactions, connection pooling)
4. Implement proper error handling and logging
5. Follow Baker's existing patterns: FastAPI, PostgreSQL, async where appropriate

## Key patterns in this codebase:
- API framework: FastAPI (`outputs/dashboard.py`)
- Database: PostgreSQL on Neon (psycopg2)
- Auth: X-Baker-Key header
- Background jobs: APScheduler (`triggers/embedded_scheduler.py`)
SKILL_EOF

# devops-automator
mkdir -p "$SKILLS_DIR/devops-automator"
cat > "$SKILLS_DIR/devops-automator/SKILL.md" << 'SKILL_EOF'
---
name: devops-automator
description: >
  DevOps and infrastructure automation specialist. Use when working with CI/CD,
  Docker, Kubernetes, cloud infrastructure, monitoring, deployment, or
  infrastructure-as-code.
  Triggers: DevOps, CI/CD, Docker, Kubernetes, k8s, deploy, infrastructure,
  Terraform, AWS, GCP, Azure, Render, Vercel, Netlify, monitoring, Grafana,
  Prometheus, pipeline, GitHub Actions, nginx, load balancer.
---
# DevOps Automator Skill
You are a DevOps and infrastructure specialist. When this skill is triggered:
1. Prioritize reliability and observability
2. Use infrastructure-as-code where possible
3. Implement proper secrets management
4. Consider cost optimization
5. Follow Baker's deployment patterns: Render auto-deploy from main

## Key patterns in this codebase:
- Deployment: Render (auto-deploys from main branch)
- Service: baker-master (Pro: 2 CPU / 4 GB)
- Monitoring: Render dashboard + Baker circuit breaker
- Secrets: Render env vars (NEVER use PUT API for env vars)
- DNS: Cloudflare (brisen-infra.com)
SKILL_EOF

# frontend-developer
mkdir -p "$SKILLS_DIR/frontend-developer"
cat > "$SKILLS_DIR/frontend-developer/SKILL.md" << 'SKILL_EOF'
---
name: frontend-developer
description: >
  Frontend engineering specialist for building modern web UIs. Use when working on
  React, Vue, Svelte, CSS, accessibility, responsive design, component architecture,
  state management, or any browser-side code.
  Triggers: frontend, UI, component, React, Vue, CSS, responsive, accessibility,
  a11y, web app, SPA, layout, design system.
---
# Frontend Developer Skill
You are a frontend engineering specialist. When this skill is triggered:
1. Write semantic HTML and accessible interfaces
2. Use modern CSS (flexbox, grid, custom properties)
3. Consider mobile-first responsive design
4. Optimize performance (lazy loading, code splitting)
5. Follow Baker's frontend patterns: vanilla JS, no framework

## Key patterns in this codebase:
- Desktop: `outputs/static/index.html` + `app.js`
- Mobile: `outputs/static/mobile.html` + `mobile.js` + `mobile.css`
- Auth: bakerFetch() wrapper with X-Baker-Key header
- Streaming: SSE (Server-Sent Events) for Scan responses
- Cache busting: ?v=N on CSS/JS includes
SKILL_EOF

# mobile-app-builder
mkdir -p "$SKILLS_DIR/mobile-app-builder"
cat > "$SKILLS_DIR/mobile-app-builder/SKILL.md" << 'SKILL_EOF'
---
name: mobile-app-builder
description: >
  Mobile app development specialist for iOS, Android, and cross-platform apps.
  Use when building React Native, Flutter, Swift, Kotlin, or any mobile application.
  Triggers: mobile, app, iOS, Android, React Native, Flutter, Swift, Kotlin,
  phone, tablet, PWA, app store, push notification, deep link, offline.
---
# Mobile App Builder Skill
You are a mobile app development specialist. When this skill is triggered:
1. Consider platform-specific UX patterns
2. Handle offline scenarios and poor connectivity
3. Implement proper touch targets (48px minimum)
4. Use 100dvh for full viewport height (not 100vh)
5. Follow Baker's mobile patterns: PWA, no native app

## Key patterns in this codebase:
- Mobile PWA: `outputs/static/mobile.html`
- Touch-friendly: 48px minimum targets
- Dark mode: prefers-color-scheme media query
- Push: Web Push API via service worker
- Viewport: 100dvh for iOS Safari compatibility
SKILL_EOF

# rapid-prototyper
mkdir -p "$SKILLS_DIR/rapid-prototyper"
cat > "$SKILLS_DIR/rapid-prototyper/SKILL.md" << 'SKILL_EOF'
---
name: rapid-prototyper
description: >
  Rapid prototyping specialist for building MVPs, proofs of concept, and quick
  demos fast. Use when speed matters more than polish — hackathons, demos,
  validating ideas, or building the simplest thing that works.
  Triggers: prototype, MVP, proof of concept, POC, demo, hackathon, quick, fast,
  throw together, sketch, spike, experiment, validate, just make it work.
---
# Rapid Prototyper Skill
You are a rapid prototyping specialist. When this skill is triggered:
1. Ship fast — working code beats perfect code
2. Use the simplest solution that works
3. Skip unnecessary abstractions
4. Hard-code values that can be configurable later
5. Focus on the happy path first

## Principles:
- Inline styles > CSS framework for one-off pages
- Global state > state management library for prototypes
- console.log > logging framework for debugging
- String concatenation > template engine for simple HTML
- SQLite/JSON file > database for local prototypes
SKILL_EOF

# dropbox-file-delivery
mkdir -p "$SKILLS_DIR/dropbox-file-delivery"
cat > "$SKILLS_DIR/dropbox-file-delivery/SKILL.md" << 'SKILL_EOF'
---
name: dropbox-file-delivery
description: >
  Save files directly to Dimitry's Dropbox by uploading via the Chrome browser to
  dropbox.com. Use this skill whenever Claude creates a deliverable (document,
  spreadsheet, presentation, report, analysis, or any file) that needs to be saved
  to Dropbox.
  Triggers: "save to Dropbox", "put it in Dropbox", "upload to my Dropbox",
  "save the file", or any time Claude produces a file the user will need later.
  Also use when Claude needs to find the right Dropbox folder for a deliverable,
  or when the user asks "where did you save it?"
  IMPORTANT: This skill should be used proactively. Whenever Claude creates a file
  as a final deliverable, it should upload it to Dropbox without being asked, using
  the Chrome browser method described here. The user expects files to land in Dropbox
  automatically.
---
# Dropbox File Delivery via Chrome Browser

## Method: Upload via Chrome MCP to dropbox.com
Use the Chrome MCP tools to navigate to Dropbox and upload files.

## Steps:
1. Create the file locally (e.g., in /tmp/ or the project outputs/ directory)
2. Use Chrome MCP to navigate to https://www.dropbox.com
3. Navigate to the target folder (usually Baker-Feed or the relevant project folder)
4. Use the upload button to upload the file
5. Confirm the upload completed

## Key Dropbox Folders:
- `/Baker-Feed` — Dimitry's main feed folder
- `/Edita-Feed` — Edita's feed folder
- `/Baker-Project/` — Baker system files (shared with Cowork)

## Local Dropbox Sync Path:
`/Users/dimitry/Vallen Dropbox/Dimitry vallen/`

## Alternative: Direct File Copy
If local Dropbox sync is available, you can copy directly:
```bash
cp /path/to/file "/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Feed/"
```
This is faster and more reliable than browser upload.
SKILL_EOF

# skill-installation
mkdir -p "$SKILLS_DIR/skill-installation"
cat > "$SKILLS_DIR/skill-installation/SKILL.md" << 'SKILL_EOF'
---
name: skill-installation
description: >
  How to install new skills so they are automatically picked up by Claude.
  Use this skill whenever creating a new skill, updating an existing skill,
  or when the user asks to save/install/add a skill.
  Triggers: "create a skill", "save this skill", "install skill",
  "add a new skill", "update skill".
---
# Skill Installation Guide

## Where Skills Live
Custom skills are stored in: `~/.claude/skills/`

Structure:
```
~/.claude/skills/
├── ai-engineer/
│   └── SKILL.md
├── backend-architect/
│   └── SKILL.md
└── [other skills]/
    └── SKILL.md
```

## How to Install a New Skill
1. Create the skill folder: `mkdir -p ~/.claude/skills/<skill-name>`
2. Write the SKILL.md file with frontmatter (name, description) and content
3. Skills are picked up automatically — no restart needed

## SKILL.md Format
```markdown
---
name: skill-name
description: >
  When to trigger this skill. Include trigger words.
---
# Skill Title
Instructions for Claude when this skill is activated.
```
SKILL_EOF

log "Installed 8 skills to ~/.claude/skills/"
echo ""

# --- Step 8: Verify agents in repo ---
AGENT_COUNT=$(ls "$REPO_DIR/.claude/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
if [ "$AGENT_COUNT" -ge 19 ]; then
    log "Found $AGENT_COUNT agents in .claude/agents/ (expected 19)"
else
    warn "Found $AGENT_COUNT agents in .claude/agents/ (expected 19)"
fi
echo ""

# --- Step 9: Create project memory directory ---
PROJECT_MEMORY="$CLAUDE_DIR/projects/-Users-$(whoami)-Desktop-baker-code/memory"
mkdir -p "$PROJECT_MEMORY"
if [ ! -f "$PROJECT_MEMORY/MEMORY.md" ]; then
    cat > "$PROJECT_MEMORY/MEMORY.md" << 'MEM_EOF'
# Baker — Code Brisen Memory (Mac Mini)

## My Role: Code Brisen
- I implement briefs from AI Head. I focus on frontend/UX and coding tasks.
- **AI Head** = the MacBook Claude Code instance. Plans, analyzes, writes briefs.
- **Director (Dimitry)** = final authority.
- I have full access to Baker's memory via MCP tools.

## Key Facts
- Baker runs on Render (Pro: 2 CPU / 4 GB) — auto-deploys from main
- BAKER_API_KEY: `bakerbhavanga`
- Render service ID: `srv-d6dgsbctgctc73f55730` (baker-master)

## Coding Rules
- Syntax check all modified files before committing
- Never force push to main (Render auto-deploys)
- Always `git pull` before starting work
- Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
MEM_EOF
    log "Created project memory with starter MEMORY.md"
else
    log "Project memory already exists"
fi
echo ""

# --- Summary ---
echo "============================================"
echo " Setup Complete!"
echo "============================================"
echo ""
echo "  Repo:     $REPO_DIR"
echo "  Agents:   $AGENT_COUNT custom agents"
echo "  Skills:   8 skills installed"
echo "  MCP:      baker + chrome + render"
echo "  Model:    Opus 1M context"
echo "  Mode:     Bypass permissions"
echo ""
echo "Next steps:"
echo "  1. cd $REPO_DIR"
echo "  2. claude      (start Claude Code)"
echo "  3. Test: ask 'What are Baker's active deadlines?'"
echo ""
if [ -z "$MCP_SERVER" ]; then
    warn "Baker MCP not configured — set up Dropbox sync first"
fi
echo "Chrome MCP requires Chrome running in debug mode:"
echo "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\"
echo "    --remote-debugging-port=9222 \\"
echo "    --remote-allow-origins=* \\"
echo "    --user-data-dir=\$HOME/.chrome-debug-profile"
echo ""
