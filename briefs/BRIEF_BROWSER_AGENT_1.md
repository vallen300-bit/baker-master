# BRIEF: BROWSER-AGENT-1 — Baker Controls Your Real Browser (CDP/OpenClaw Approach)

## Context
Director asked Baker (via WhatsApp) to go to the Whoop website, find a spare part, and order it. Baker couldn't — he can search the web and read pages, but cannot click, fill forms, or buy things. For a Chief of Staff, this is a basic capability gap.

Director decision: "Give Baker the same power as OpenClaw — connect to my real browser, use my existing sessions. He already has my email, WhatsApp, calendar. One more function gives me 1-2 hours a day of free time."

## Goal
Baker connects to the Director's real Chrome browser via Chrome DevTools Protocol (CDP). He can navigate, click, fill forms, add to cart, and complete purchases — using the Director's existing logged-in sessions (Amazon, PayPal, Whoop, etc.). No separate cloud browser service needed. Zero additional monthly cost.

## Architecture

### The Key Insight: Chrome DevTools MCP Server
Google's official **Chrome DevTools MCP server** (`chrome-devtools-mcp`) already exists as an npm package. It exposes 29 tools via MCP including `click`, `fill`, `fill_form`, `navigate_page`, `type_text`, `take_screenshot`. It connects to a running Chrome instance via CDP — including the Director's real Chrome with all his sessions.

### Two Deployment Options

**Option A: Director's Mac (recommended for now)**
```
Director's Chrome ←CDP→ chrome-devtools-mcp ←MCP→ Claude Code
```
- Baker (via Claude Code) controls Director's Chrome directly
- Director sees everything happening in his browser in real-time
- All existing sessions (PayPal, Amazon, Whoop) available
- Works immediately — Director is sitting at the Mac

**Option B: Always-on (future)**
```
Director's Chrome ←CDP→ chrome-devtools-mcp ←API→ Baker (Render)
```
- Requires Chrome running on a persistent machine (Mac Mini or cloud VM)
- Baker can browse autonomously even when Director is away
- Needs Chrome profile with saved sessions
- More complex setup — defer to later

### Flow: "Order me a Whoop band"

```
Director (WhatsApp): "Go to whoop.com and order me a SuperKnit band, size M"

Baker (via Claude Code or Render):
  1. navigate_page → https://www.whoop.com/shop
  2. click → "Accessories" or "Bands"
  3. click → "SuperKnit Band"
  4. click → size "M"
  5. click → "Add to Cart"
  6. navigate_page → checkout
  7. take_screenshot → confirm cart contents
  8. (PayPal/payment already saved in Chrome profile)
  9. click → "Pay with PayPal"
  10. take_screenshot → confirm order placed

Baker → Director (WhatsApp):
  "Done. Ordered SuperKnit Band (M) — $49 via PayPal.
   Order confirmation #WH-28491. Screenshot attached."
```

### Flow: "Find and book the cheapest Business flight to Vienna"

```
Director: "Find me a Business class flight to Vienna next Thursday, morning departure"

Baker:
  1. navigate_page → google.com/flights
  2. fill_form → from: Zurich, to: Vienna, date: next Thu, class: Business
  3. take_screenshot → results
  4. Analyze: "Swiss LX1572 dep 07:10 arr 08:35 — EUR 389. Austrian OS562 dep 09:25 — EUR 420."
  5. Director confirms: "Book the Swiss one"
  6. navigate_page → swiss.com (already logged in)
  7. Complete booking using saved payment
```

## Implementation

### Part 1: Add Chrome DevTools MCP to Baker

**For Claude Code (Director's Mac — Option A):**

Add to the project's `.claude/settings.local.json`:

```json
{
  "mcpServers": {
    "baker": { ... existing baker MCP ... },
    "chrome": {
      "command": "npx",
      "args": ["chrome-devtools-mcp@latest", "--autoConnect"]
    }
  }
}
```

That's it. Claude Code now has 29 browser tools alongside Baker's 21 tools.

**Prerequisites on Director's Mac:**
1. Chrome M144+ (check `chrome://version`)
2. Enable at `chrome://inspect/#remote-debugging`
3. First connection: Chrome shows permission dialog → Director clicks "Allow"
4. Chrome shows "controlled by automated test software" banner during session

### Part 2: New Agent Tool for Render (Baker server-side)

For when Baker needs to browse autonomously (WhatsApp requests, scheduled tasks):

**File: `orchestrator/agent.py`**

Add tool #19 `browse_website`:

```python
{
    "name": "browse_website",
    "description": (
        "Control the Director's Chrome browser to navigate websites, click buttons, "
        "fill forms, add items to cart, and complete purchases. Uses the Director's "
        "existing logged-in sessions (Amazon, PayPal, Swiss, etc.).\n\n"
        "Available actions: navigate_page, click, fill, fill_form, type_text, "
        "press_key, take_screenshot, hover, upload_file, wait_for.\n\n"
        "Use for: ordering products, booking flights/hotels, checking account dashboards, "
        "filling forms, price comparison on live sites.\n\n"
        "The Director can see everything you do in real-time in his Chrome."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "click", "fill", "fill_form", "type_text",
                         "screenshot", "press_key", "hover", "wait", "evaluate"],
                "description": "Browser action to perform",
            },
            "url": {
                "type": "string",
                "description": "URL to navigate to (for navigate action)",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector or text content to target (for click/fill/hover)",
            },
            "value": {
                "type": "string",
                "description": "Text value to type/fill",
            },
            "form_data": {
                "type": "object",
                "description": "Key-value pairs for fill_form action: {field_selector: value, ...}",
            },
        },
        "required": ["action"],
    },
}
```

**File: `triggers/browser_cdp_client.py` (NEW)**

```python
"""
Baker CDP Browser Client — connects to Director's Chrome via DevTools Protocol.

Two modes:
  - Local: Connect to Chrome on Director's Mac (ws://localhost:9222)
  - Remote: Connect to Chrome on Mac Mini via SSH tunnel or direct IP

Uses python-cdp or PyChromeDevTools for the WebSocket connection.
"""

class CDPBrowserClient:
    """Control Director's Chrome via Chrome DevTools Protocol."""

    def __init__(self, ws_url="ws://localhost:9222"):
        self.ws_url = ws_url

    async def navigate(self, url: str) -> dict: ...
    async def click(self, selector: str) -> dict: ...
    async def fill(self, selector: str, value: str) -> dict: ...
    async def fill_form(self, fields: dict) -> dict: ...
    async def type_text(self, text: str) -> dict: ...
    async def screenshot(self) -> str: ...  # returns base64
    async def evaluate(self, js: str) -> dict: ...
    async def wait_for(self, selector: str, timeout: int = 10) -> dict: ...
```

### Part 3: Capability Assignment

Add `browse_website` to these capabilities:
- `research` — product research, price comparison, competitor sites
- `profiling` — company research on live websites
- `it` — SaaS dashboards, Microsoft 365 admin, service status
- `communications` — checking online content before drafting
- `asset_management` — property portals, insurance dashboards
- `russo_ai` — banking portals, tax authority sites

### Part 4: Screenshot → WhatsApp

When Baker takes a screenshot during browsing, attach it to the WhatsApp response so the Director sees what Baker is doing.

**File: `triggers/waha_client.py`**
- Already supports media sending via WAHA
- Baker can send screenshot as image message

## Setup on Director's Mac

### One-time setup (5 minutes):

```bash
# 1. Install the Chrome DevTools MCP server
npm install -g chrome-devtools-mcp

# 2. Enable Chrome remote debugging
# Open Chrome → navigate to chrome://inspect/#remote-debugging
# Toggle "Enable remote debugging"

# 3. Update Claude Code MCP config (already done if using baker-code project)
```

### How Director starts a browser session:

```bash
# 1. Open Chrome normally (it's already running)
# 2. Start Claude Code
cd ~/Desktop/baker-code
claude

# 3. Ask Baker to do something
"Go to whoop.com and order me a SuperKnit band size M"
```

Chrome shows a permission dialog on first connection → click Allow.
Director sees Baker navigating his Chrome in real-time.

## Cost

**$0/month.** Chrome DevTools Protocol is free. No cloud browser service needed.

The only cost is the Claude API usage for the agent loop (~$0.10-0.30 per browsing task depending on complexity).

## Files to Create/Modify

| # | File | What |
|---|------|------|
| 1 | `.claude/settings.local.json` | Add chrome-devtools-mcp server config |
| 2 | `orchestrator/agent.py` | Add `browse_website` tool #19 |
| 3 | `triggers/browser_cdp_client.py` | NEW — CDP client for Render-side browsing |
| 4 | `orchestrator/capability_registry.py` | Add tool to 6 capability slugs |

## Phased Rollout

**Phase 1 (now — 30 minutes):**
- Add `chrome-devtools-mcp` to Claude Code MCP config
- Baker can browse via Claude Code on Director's Mac
- Director sees everything in real-time
- Works for "right now" requests

**Phase 2 (next session):**
- Add `browse_website` tool #19 to agent framework
- Baker on Render can browse via CDP connection to Mac Mini
- Works for WhatsApp requests when Director is away
- Needs persistent Chrome + SSH tunnel or Tailscale

**Phase 3 (future):**
- Saved browser profiles for common sites
- Multi-step task memory ("last time you ordered this size M")
- Shopping list queue ("order these 5 things when prices drop below X")

## Risks

- **Chrome permission prompt**: Director must click "Allow" once per session. Minor friction.
- **"Controlled by automated test software" banner**: Always visible during CDP sessions. Some sites may detect this.
- **Accidental clicks**: Baker could click the wrong button. Mitigation: Baker takes a screenshot before any irreversible action (purchase, delete) and confirms with Director.
- **Session timeout**: If Chrome closes, Baker loses connection. Non-fatal — just reconnect.

## What This Unlocks

With full browser access, Baker becomes a true digital executive assistant:
- Order products, spare parts, gifts
- Book flights, hotels, restaurants
- Check bank balances, make transfers (with Director confirmation)
- Fill government forms, submit tax filings
- Manage subscriptions (renew, cancel, upgrade)
- Research competitors by navigating their actual products
- Monitor dashboards (property management, investment platforms)

**The same thing a human PA does — but 24/7 and instant.**
