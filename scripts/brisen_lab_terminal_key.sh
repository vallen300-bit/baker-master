#!/usr/bin/env bash
# Source-only helper for Brisen Lab terminal-key lookup.
#
# Precedence:
#   1. Literal BRISEN_LAB_TERMINAL_KEY env value supplied by the caller.
#   2. ~/.brisen-lab/keys/<slug> cache file.
#   3. 1Password `op read` fallback; successful reads seed the cache.
#
# Never echo/log key material from this helper except by returning the resolved
# key on stdout to the caller that will put it in the X-Terminal-Key header.

brisen_lab_is_literal_terminal_key() {
  local value="${1:-}"
  [[ -n "$value" && "$value" != op://* ]]
}

brisen_lab_terminal_key_cache_file() {
  local slug="$1"
  printf '%s/.brisen-lab/keys/%s\n' "$HOME" "$slug"
}

brisen_lab_read_cached_terminal_key() {
  local slug="$1"
  local cache_file
  cache_file="$(brisen_lab_terminal_key_cache_file "$slug")"
  [[ -r "$cache_file" ]] || return 1

  local key
  key="$(tr -d '\r\n' < "$cache_file" 2>/dev/null || true)"
  brisen_lab_is_literal_terminal_key "$key" || return 1
  printf '%s\n' "$key"
}

brisen_lab_write_cached_terminal_key() {
  local slug="$1"
  local key="$2"
  brisen_lab_is_literal_terminal_key "$key" || return 1
  [[ "$slug" =~ ^[A-Za-z0-9._-]+$ ]] || return 1

  local cache_dir cache_file tmp
  cache_dir="$HOME/.brisen-lab/keys"
  cache_file="$(brisen_lab_terminal_key_cache_file "$slug")"

  mkdir -p "$cache_dir" 2>/dev/null || return 1
  chmod 700 "$HOME/.brisen-lab" "$cache_dir" 2>/dev/null || true

  tmp="$(mktemp "${cache_dir}/.${slug}.tmp.XXXXXX" 2>/dev/null)" || return 1
  if printf '%s\n' "$key" > "$tmp" 2>/dev/null; then
    chmod 600 "$tmp" 2>/dev/null || true
    mv "$tmp" "$cache_file" 2>/dev/null || {
      rm -f "$tmp" 2>/dev/null || true
      return 1
    }
    chmod 600 "$cache_file" 2>/dev/null || true
    return 0
  fi

  rm -f "$tmp" 2>/dev/null || true
  return 1
}

brisen_lab_read_terminal_key() {
  local slug="$1"
  local env_value="${2:-}"

  if brisen_lab_is_literal_terminal_key "$env_value"; then
    printf '%s\n' "$env_value"
    return 0
  fi

  local cached
  cached="$(brisen_lab_read_cached_terminal_key "$slug" 2>/dev/null || true)"
  if brisen_lab_is_literal_terminal_key "$cached"; then
    printf '%s\n' "$cached"
    return 0
  fi

  command -v op >/dev/null 2>&1 || return 1

  local op_ref key
  if [[ "$env_value" == op://* ]]; then
    op_ref="$env_value"
  else
    op_ref="op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${slug}/credential"
  fi

  key="$(op read "$op_ref" 2>/dev/null || true)"
  brisen_lab_is_literal_terminal_key "$key" || return 1
  brisen_lab_write_cached_terminal_key "$slug" "$key" >/dev/null 2>&1 || true
  printf '%s\n' "$key"
}
