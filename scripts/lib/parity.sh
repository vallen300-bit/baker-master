#!/usr/bin/env bash
# parity.sh — shared portable digest helpers for fleet parity checks.

_sha256() {
  local path="${1:-}"
  [[ -f "$path" ]] || return 1
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    echo "parity: neither shasum nor sha256sum is available" >&2
    return 1
  fi
}

_sha256_stream() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    echo "parity: neither shasum nor sha256sum is available" >&2
    return 1
  fi
}
