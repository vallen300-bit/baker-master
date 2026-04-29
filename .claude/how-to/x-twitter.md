---
name: x-twitter-access-via-syndication
description: How to fetch X (Twitter) tweet content when WebFetch on x.com returns 402. Use the syndication endpoint.
when_to_use: User asks to fetch / read / quote a specific tweet by URL or ID.
---

# Fetching X (Twitter) tweet content

**Problem:** `WebFetch` on `https://x.com/USERNAME/status/TWEET_ID` returns **HTTP 402 Payment Required**. X's public API is gated. Nitter mirrors are unreliable (often empty or rate-limited).

**Working pattern (verified 2026-04-28):** use the public syndication endpoint that backs Twitter's embed widget. No auth required.

```
https://cdn.syndication.twimg.com/tweet-result?id={TWEET_ID}&token=a
```

## How to use it

1. Take the tweet URL Director gave you, e.g.
   `https://x.com/realBigBrainAI/status/2048741576961401017?s=20`
2. Extract just the numeric ID from after `/status/` — strip query params.
3. Construct: `https://cdn.syndication.twimg.com/tweet-result?id=2048741576961401017&token=a`
4. `WebFetch` that URL with a prompt asking for the tweet text + media + author.

## What it returns

JSON with the tweet text, author handle + name, posted date, like/reply counts, attached media descriptions, and quoted-tweet content if any.

## Limitations

- Single tweet only — no thread / replies.
- Some quoted tweets return only metadata, not full quoted content. If the user wants the quote, fetch the quoted tweet's ID separately the same way.
- Some media (videos) come back as descriptions only, no playback.
- Rate limits exist but are looser than nitter.

## When to use this vs alternatives

- **First try:** the syndication endpoint above.
- **If it fails for a specific tweet:** try `WebSearch` for a quoted/embedded version of the tweet (often picked up by indexers).
- **For threads / replies:** no good public path; ask Director to paste the relevant content.

## Provenance

Discovered 2026-04-28 during Brisen AI integration research (Dorsey "AI-as-copilot" tweet). x.com returned 402; nitter empty; syndication endpoint returned full content. Used twice in same session for `realBigBrainAI/2048741576961401017` and `DataChaz/2048716448961290347`.
