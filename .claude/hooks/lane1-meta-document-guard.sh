#!/usr/bin/env bash
# lane1-meta-document-guard.sh — PreToolUse hook blocking silent-files of
# meta-documents (index / catalog / register / log / tracker / status / roster /
# inventory) into Lane 1 `_synthesis/`.
#
# Canonical: ~/baker-vault/_ops/agents/hagenauer-desk/hooks/lane1-meta-document-guard.sh
# Copies (keep byte-identical to canonical; re-sync on any canonical change):
#   - hag-desk:  symlink ~/bm-hag-desk/.claude/hooks/ -> vault canonical; wired in ~/bm-hag-desk/.claude/settings.json
#   - hag-filer + baker-master clones: this OWN tracked copy at .claude/hooks/lane1-meta-document-guard.sh
#     (HAG_FILER_HARNESS_RETROFIT_1 — lead rulings #6549/#6807/#6814: hag-filer gets its OWN copy, never a
#      reference to the desk's checkout = cross-picker coupling). Wired in tracked .claude/settings.json
#      PreToolUse. Self-filters by _synthesis/ path, so it is a no-op for non-hagenauer work in the b1-b4 clones.
#
# Scar: 2026-05-25 hag-desk mis-filed claim-analyst-outputs-index.md into
# wiki/matters/hagenauer-rg7/creditor-claim-filing/_synthesis/ when it should
# have landed in wiki/matters/hagenauer-rg7/curated/. SOP existed; Step 0a
# decline-to-classify safety mechanism existed; both were silent-bypassed.
# Hook enforces the boundary that the SOP only documented.
#
# Filing protocol v2: ~/baker-vault/_ops/agents/hagenauer-desk/filing-protocol.md
#   Lane 1 `_synthesis/` = "Cross-row strategic analysis" — substantive doctrine.
#   Lane 2 `curated/YYYY-MM-DD-<slug>.{md,html,pdf,docx}` = "Dated standalone
#   artefacts" — Director-facing knowledge layer, where meta-catalogs belong.
#
# Fires when:
#   • Tool ∈ {Write, Edit, MultiEdit}
#   • file_path matches `*/_synthesis/<file>.md`
#   • <file> does NOT start with `_` (Lane 1 roster files like `_index.md` and
#     `_dispatch-log.md` ARE legitimate operational artefacts — the underscore
#     prefix is the marker)
#   • <file> matches meta-document pattern:
#       *-index.md / *-catalog.md / *-register.md / *-log.md / *-tracker.md /
#       *-status.md / *-roster.md / *-inventory.md / *-summary.md
#     (substring match, case-insensitive, before the .md)
#
# To bypass legitimately:
#   (a) Rename file with `_` prefix if it IS an operational Lane 1 roster
#       (matches the existing `_index.md` / `_dispatch-log.md` pattern), OR
#   (b) File to Lane 2 `curated/<YYYY-MM-DD>-<slug>-<topic>.md` instead, where
#       meta-documents and dated standalone artefacts belong per protocol v2.
#
# Exit codes (Claude Code PreToolUse contract):
#   0 — pass / not applicable / malformed input (FAIL-OPEN)
#   2 — block; stderr surfaced to Claude as error context
#
# Fail-open posture: any internal error → exit 0 + stderr warning. Gate-logic
# bugs must NEVER block legitimate tool use.

set -u
trap 'echo "WARN [lane1-meta-document-guard]: hook errored unexpectedly, failing open" >&2; exit 0' ERR

PAYLOAD="$(cat)"

# Validate JSON; fail-open if malformed.
if ! printf '%s' "$PAYLOAD" | jq -e . >/dev/null 2>&1; then
    echo "WARN [lane1-meta-document-guard]: malformed JSON on stdin, failing open" >&2
    exit 0
fi

TOOL="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // empty')"
case "$TOOL" in
    Write|Edit|MultiEdit) ;;
    *) exit 0 ;;
esac

FILE_PATH="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // empty')"
[ -z "$FILE_PATH" ] && exit 0

# Path filter: file must live in a `_synthesis/` directory.
# Match anywhere in the path so future matters adopting the 3-lane pattern get
# the same guard rail. Today: only hagenauer-rg7 uses this layout.
if ! printf '%s' "$FILE_PATH" | grep -qE '(^|/)_synthesis/[^/]+\.md$'; then
    exit 0
fi

# Extract just the filename.
FILENAME="$(printf '%s' "$FILE_PATH" | sed 's|.*/||')"

# Bypass: underscore-prefixed files are operational rosters per protocol v2.
if printf '%s' "$FILENAME" | grep -qE '^_'; then
    exit 0
fi

# Meta-document pattern: filename contains one of the meta tokens followed by
# either a separator (._-) or .md end. Case-insensitive substring match —
# captures the shapes hag-desk identified ("meta / catalog / index / tracking
# document"). Leading `-?` deliberately omitted because BSD grep (macOS) parses
# `-` at start of pattern as a flag; substring match without that boundary
# still catches all real cases (`outputs-index.md`, `dispatch-log.md`, etc.).
META_PATTERN='(index|catalog|register|log|tracker|status|roster|inventory|summary|listing)([._-]|\.md$)'

if ! printf -- '%s' "$FILENAME" | grep -qiE -- "$META_PATTERN"; then
    exit 0
fi

# Hit. Block with full advisory.
cat >&2 <<EOF
BLOCKED by lane1-meta-document-guard hook: filename '$FILENAME' suggests a meta-document (index / catalog / register / log / tracker / status / roster / inventory / summary / listing).

Lane 1 \`_synthesis/\` is for substantive cross-row strategic analysis only — open-book mechanics, water-cascade theory, Bauer overlap, cluster substantiation, etc.

Meta-catalogs and author-tracking indices belong in Lane 2 \`curated/\` as dated standalone artefacts (per filing-protocol v2 — ~/baker-vault/_ops/agents/hagenauer-desk/filing-protocol.md).

To proceed, either:
  (a) Rename with leading underscore if this IS a Lane 1 operational roster
      (matches the existing _index.md / _dispatch-log.md pattern in the same folder), OR
  (b) Re-file to Lane 2 curated/ as a dated artefact:
      curated/$(date -u +%Y-%m-%d)-<slug>-<topic>.md

If classification is genuinely ambiguous (Step 0a per filing-protocol v2), surface candidate destinations to Director with probabilities before silent-filing.

Anchor: 2026-05-25 mis-file of claim-analyst-outputs-index.md into _synthesis/ — same-day correction at curated/2026-05-25-claim-analyst-outputs-index.md.
EOF
exit 2
