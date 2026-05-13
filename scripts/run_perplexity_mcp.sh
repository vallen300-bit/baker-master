#!/usr/bin/env bash
# run_perplexity_mcp.sh — start Perplexity Ask MCP server with op-resolved key.
#
# Replaces plaintext PERPLEXITY_API_KEY in .mcp.json files. Pulls the key
# from 1Password at MCP-spawn time so the secret never sits on disk in
# config. Pattern mirrors bus_post.sh + cortex_rollback_v1.sh.
#
# Director-ratified 2026-05-13.
#
# Usage in .mcp.json:
#   "perplexity-ask": {
#     "type": "stdio",
#     "command": "/Users/dimitry/Desktop/baker-code/scripts/run_perplexity_mcp.sh"
#   }
#
# Override: set PERPLEXITY_API_KEY in env before launch to skip op fetch.

set -euo pipefail

if [ -z "${PERPLEXITY_API_KEY:-}" ]; then
    PERPLEXITY_API_KEY="$(op read 'op://Baker API Keys/API Perplexity/credential' 2>/dev/null)" || {
        echo "ERROR: PERPLEXITY_API_KEY not in env and op read failed" >&2
        echo "  Fix: (a) ensure 1Password app is unlocked + CLI biometric integration enabled" >&2
        echo "  Or:  (b) set PERPLEXITY_API_KEY env var before launching Cowork" >&2
        exit 1
    }
fi

export PERPLEXITY_API_KEY
exec npx -y server-perplexity-ask
