# How-To Index

**Loading model:** this index is auto-loaded into every session via `@.claude/how-to/INDEX.md` in `bm-b1/CLAUDE.md`. Body files below are loaded ONLY when their trigger matches the user's request — read them via the Read tool when needed.

**Trigger contract:** scan this index when the user's ask doesn't match obvious code/repo work. If a hook line matches, Read the linked body file before acting.

## Procedures

- [X / Twitter access](.claude/how-to/x-twitter.md) — `x.com` returns 402; use `cdn.syndication.twimg.com/tweet-result?id={ID}&token=a` syndication endpoint
- [Local research via Gemma 4](.claude/how-to/local-research-gemma.md) — free Ollama @ `localhost:11434`, structured note in ~30-60s, force a confidence section
- [Chrome debug port 9222 recovery](.claude/how-to/chrome-debug-recovery.md) — auto-starts at login; if dead, `launchctl kickstart -k gui/$(id -u)/com.baker.chrome-debug`

## Adding a new how-to

1. Create `bm-b1/.claude/how-to/<slug>.md` with frontmatter (name, description, when_to_use)
2. Add one line here under `## Procedures`: `- [Title](.claude/how-to/<slug>.md) — <≤120 char hook>`
3. Keep the hook tight — it's the only thing loaded every session
