# Director: Dimitry Vallen — Global Claude Code defaults

@~/.claude/dropbox-tier0.md

# Claude-Code-only defaults below. Portfolio context (people / projects / terms /
# glossary) lives in the Dropbox-root file imported above. The path above is a
# symlink to `/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md` — done via
# symlink (not direct @-path) because Claude Code @import handling of paths
# containing spaces is undocumented; symlink eliminates the unknown.

## Hard rules — universal
- Never force-push `main` / `master`.
- Never commit secrets. Treat `.env`, `*credentials*`, `*secret*` as off-limits.
- Never auto-send external email. Internal auto-send only when authorized in repo CLAUDE.md.
- Never amend published commits — always create a new commit.
- Never bypass hooks (`--no-verify`) without explicit Director ask.
- Destructive ops (`rm -rf`, `git reset --hard`, drop table) — confirm before acting.

## When to use subagents
- **Explore** — codebase searches >3 queries.
- **Plan** — non-trivial implementation that needs an interactive plan-mode session.
- **general-purpose** — open-ended search, parallel independent work.
- **ai-head** — Baker system development, capability framework, prompt engineering, automation design.
- **Specialized** (russo-*, baker-*, claims-analysis, claude-code-guide, feature-dev:*, etc.) — when their trigger keywords match.
- Don't duplicate work — if a subagent is searching, don't search the same thing yourself.

## Communication
- Don't ask for confirmation on routine ops when context is clear.
- (Language preferences live in Tier 0 `## Preferences` block — imported via `@` at top of this file.)

## Git identity
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
