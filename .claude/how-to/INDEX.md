# How-To Index

**Loading model:** this index is auto-loaded into every session via `@.claude/how-to/INDEX.md` in `bm-b1/CLAUDE.md`. Body files below are loaded ONLY when their trigger matches the user's request — read them via the Read tool when needed.

**Trigger contract:** scan this index when the user's ask doesn't match obvious code/repo work. If a hook line matches, Read the linked body file before acting.

## Procedures

- [X / Twitter access](.claude/how-to/x-twitter.md) — `x.com` returns 402. Short tweets: syndication endpoint. Articles + threads + truncated-preview tweets: Chrome MCP via logged-in port-9222 (`navigate_page` + `evaluate_script`)
- [Local research via Gemma 4](.claude/how-to/local-research-gemma.md) — free Ollama @ `localhost:11434`, structured note in ~30-60s, force a confidence section
- [Perplexity Ask API](~/baker-vault/_ops/how-to/perplexity-api.md) — cited synthesis via MCP, ~$0.01-0.05/query, replaces 3-5 chained WebSearch+WebFetch calls. Wired in Researcher + AID-T pickers; others escalate via cross-agent dispatch.
- [Chrome debug port 9222 recovery](.claude/how-to/chrome-debug-recovery.md) — auto-starts at login; if dead, `launchctl kickstart -k gui/$(id -u)/com.baker.chrome-debug`
- [Cheap OCR for desks](~/baker-vault/_ops/how-to/cheap-ocr-desk.md) — `desk-ocr <image>` = free on-device Apple Vision OCR for number-in-image docs. Never feed flat PNGs/charts to Opus vision just to read digits.
- [Bluewin private email read](.claude/how-to/bluewin-read-via-mail-app.md) — dvallen@bluewin.ch in Baker cloud pipeline (baker_email_search source="bluewin", live since 2026-06-09); Mail.app AppleScript for pre-06-09 history
- [Forge snapshot pusher install](.claude/how-to/forge-snapshot-push-install.md) — `FORGE_KEY=… bash scripts/install_forge_push.sh` from a **Terminal** (not Cowork — ~15s ~/Library wipe); KeepAlive-hardened, self-resumes on reboot/crash. Feeds Brisen Lab card telemetry

## Adding a new how-to

1. Create `bm-b1/.claude/how-to/<slug>.md` with frontmatter (name, description, when_to_use)
2. Add one line here under `## Procedures`: `- [Title](.claude/how-to/<slug>.md) — <≤120 char hook>`
3. Keep the hook tight — it's the only thing loaded every session
