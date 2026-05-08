---
name: x-twitter-access
description: How to fetch X (Twitter) tweet + article content. Syndication endpoint for short tweets; Chrome MCP via logged-in debug-port-9222 profile for gated articles + threads.
when_to_use: User asks to fetch / read / quote a specific tweet, X article, or thread by URL or ID.
---

# Fetching X (Twitter) tweet + article content

**Problem:** `WebFetch` on `https://x.com/...` returns **HTTP 402 Payment Required**. X's public API is gated. Nitter mirrors are unreliable.

Two working channels, in order of preference per content type:

## Channel 1 — Syndication endpoint (short tweets)

Quick, no auth. Backs Twitter's public embed widget.

```
https://cdn.syndication.twimg.com/tweet-result?id={TWEET_ID}&token=a
```

**Use when:** tweet text is ≤277 chars (no media-truncation), no X-article attachment, no thread depth needed.

**Steps:**
1. Take the tweet URL Director gave you, e.g. `https://x.com/realBigBrainAI/status/2048741576961401017?s=20`
2. Extract just the numeric ID from after `/status/` — strip query params.
3. `curl -s 'https://cdn.syndication.twimg.com/tweet-result?id=<ID>&token=a' | python3 -c '...'` to parse JSON.

**Returns:** tweet text, author, posted date, counts, attached media descriptions, quoted-tweet preview.

**Limits:**
- Tweet text truncated at 277 chars (`display_text_range`) when there's media or thread continuation
- X **article** body is gated — syndication returns only `preview_text` (~200 chars) and metadata. **Use Channel 2 for full article body.**
- No thread / replies (single tweet only)
- Some videos come back as descriptions, not playback

## Channel 2 — Chrome MCP via logged-in debug-port-9222 (full articles + threads)

**Use when:** Channel 1 returns truncated `preview_text` only / `display_text_range` shows truncation / URL is `/i/article/<ID>` / Director wants thread replies / Channel 1 fails with 403.

**Prerequisite:** Director's Chrome with X session logged in is running at debug port 9222 (auto-starts at login via `com.baker.chrome-debug` LaunchAgent — see `chrome-debug-recovery.md` if dead).

**Steps:**
1. Load Chrome MCP tool schemas via `ToolSearch query="select:mcp__chrome__list_pages,mcp__chrome__navigate_page,mcp__chrome__select_page,mcp__chrome__evaluate_script"`
2. `mcp__chrome__list_pages` — find an X tab already open (any `x.com/...` page works since session cookies are shared)
3. `mcp__chrome__select_page pageId=<that page's id>` — re-use the logged-in tab
4. `mcp__chrome__navigate_page type=url url=<target X URL>` — works for tweets, articles (`/i/article/<ID>`), profiles, threads
5. `mcp__chrome__evaluate_script` with a function like:
   ```javascript
   () => {
     const candidates = ['article', '[data-testid="tweetText"]', '[role="article"]', 'main', '#react-root'];
     for (const sel of candidates) {
       const el = document.querySelector(sel);
       if (el && el.innerText && el.innerText.length > 1000) {
         return { selector: sel, length: el.innerText.length, text: el.innerText };
       }
     }
     return { selector: 'body', length: document.body.innerText.length, text: document.body.innerText.slice(0, 50000) };
   }
   ```

**Returns:** full rendered DOM text — article body, thread replies, image alt-text, all visible content.

**Why this works:** Chrome at port 9222 has Director's logged-in session cookies. Navigation through that profile bypasses X's auth gate.

## Decision tree

| Content type | Channel |
|--------------|---------|
| Single tweet ≤277 chars, no article, no thread | 1 (syndication) |
| Tweet with `/i/article/<ID>` quoted or attached | 2 (Chrome MCP) — syndication only gives preview |
| Long-form thread (2+ replies needed) | 2 (Chrome MCP) |
| Profile / bookmarks page | 2 (Chrome MCP) |
| Tweet with truncated text (look at `display_text_range`) | 2 (Chrome MCP) |

## Channel 3 — Last resort

- **WebSearch** for a quoted/embedded version (some indexers pick up tweets)
- Ask Director to paste content from his logged-in browser

## What NEVER to use

- `WebFetch` on `x.com` directly — always returns 402, anti-bot login wall is NOT a paywall
- Nitter mirrors — empty or rate-limited

## Provenance

- 2026-04-28: syndication endpoint discovered for Dorsey "AI-as-copilot" tweet (Brisen AI integration research)
- 2026-05-08: Chrome MCP path verified for gated X article (Mnilax "9 patterns / 73% wasted" article id `2050246891963654144`) — syndication returned only 196-char preview; Chrome MCP via logged-in tab returned full 15,104-char article body in one `evaluate_script` call.
