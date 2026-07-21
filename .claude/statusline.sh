#!/usr/bin/env bash
# Baker Claude Code statusline.
# The context-band write is best-effort and additive; the rendered line below
# remains the existing model/context/cost display.

input=$(cat)

CONTEXT_BAND_DIR="${CONTEXT_BAND_DIR:-$HOME/forge-agent/context-band}"
CONTEXT_BAND_THROTTLE_S="${CONTEXT_BAND_THROTTLE_S:-15}"

# Model metadata must be read before the live-band writer runs. The statusline
# JSON's context_window_size is authoritative; model text is fallback only.
model_display=$(printf '%s' "$input" | jq -r '.model.display_name // ""')

context_alias() {
  case "${BAKER_ROLE:-}" in
    lead|ah1|aihead1) printf 'lead\n' ;;
    deputy|deputy-codex|ah2|aihead2) printf 'deputy\n' ;;
    b1) printf 'b1\n' ;;
    b2) printf 'b2\n' ;;
    b3) printf 'b3\n' ;;
    b4) printf 'b4\n' ;;
    *) case "$PWD" in
      */bm-aihead1*) printf 'lead\n' ;;
      */bm-aihead2*) printf 'deputy\n' ;;
      */bm-b1*) printf 'b1\n' ;;
      */bm-b2*) printf 'b2\n' ;;
      */bm-b3*) printf 'b3\n' ;;
      */bm-b4*) printf 'b4\n' ;;
      *) printf '\n' ;;
    esac ;;
  esac
}

context_window_tokens() {
  local live_window fallback
  live_window="$(printf '%s' "$input" | jq -r \
    '.context_window.context_window_size // empty' 2>/dev/null || true)"
  case "$live_window" in
    ''|*[!0-9]*) live_window="" ;;
  esac
  if [ -n "$live_window" ] && [ "$live_window" -gt 0 ] 2>/dev/null; then
    printf '%s\n' "$live_window"
    return 0
  fi

  fallback=200000
  case "$model_display" in
    *1M*) fallback=1000000 ;;
  esac
  printf '%s\n' "$fallback"
}

write_live_context_band() {
  local alias pct_raw pct now mtime tmp band window link link_target target_name target_path link_tmp existing_record
  alias="$(context_alias)"
  [ -n "$alias" ] || return 0
  pct_raw="$(printf '%s' "$input" | jq -r \
    '.context_window.used_percentage // empty' 2>/dev/null || true)"
  [ -n "$pct_raw" ] || return 0
  pct="$(awk -v value="$pct_raw" 'BEGIN {
    if (value !~ /^[0-9]+([.][0-9]+)?$/) exit 1
    if (value < 0) value = 0
    if (value > 100) value = 100
    printf "%.0f", value
  }' 2>/dev/null || true)"
  [ -n "$pct" ] || return 0

  mkdir -p "$CONTEXT_BAND_DIR" 2>/dev/null || return 0
  now="$(date +%s 2>/dev/null || printf '0')"
  mtime="$(stat -f %m "$CONTEXT_BAND_DIR/$alias.current" 2>/dev/null || \
    stat -c %Y "$CONTEXT_BAND_DIR/$alias.current" 2>/dev/null || printf '0')"
  if [ "$mtime" -gt 0 ] 2>/dev/null && [ $((now - mtime)) -lt "$CONTEXT_BAND_THROTTLE_S" ] 2>/dev/null; then
    return 0
  fi

  if [ "$pct" -lt 70 ]; then
    band="ok"
  elif [ "$pct" -lt 85 ]; then
    band="soft"
  else
    band="hard"
  fi
  window="$(context_window_tokens)"
  link="$CONTEXT_BAND_DIR/$alias.current"
  link_target="$(readlink "$link" 2>/dev/null || true)"
  case "$link_target" in
    ""|*[!A-Za-z0-9._-]*)
      link_target=""
      ;;
  esac
  if [ -n "$link_target" ]; then
    target_name="$link_target"
    target_path="$CONTEXT_BAND_DIR/$target_name"
  else
    target_name="${alias}.$(uuidgen 2>/dev/null || printf '%s-%s' "$$" "$now").json"
    target_path="$CONTEXT_BAND_DIR/$target_name"
  fi

  tmp="$(mktemp "$CONTEXT_BAND_DIR/.${alias}.json.tmp.XXXXXX" 2>/dev/null || true)"
  [ -n "$tmp" ] || return 0
  existing_record='{}'
  if [ -f "$target_path" ]; then
    existing_record="$(jq -c 'if type == "object" then . else {} end' \
      "$target_path" 2>/dev/null || printf '{}')"
  fi
  jq -cn \
    --argjson existing "$existing_record" \
    --argjson context_percent "$pct" \
    --arg band "$band" \
    --argjson window_tokens "$window" \
    '$existing + {
      context_percent: $context_percent,
      band: $band,
      measured: true,
      window_tokens: $window_tokens
    }' >"$tmp" 2>/dev/null || {
      rm -f "$tmp" 2>/dev/null || true
      return 0
    }
  mv -f "$tmp" "$target_path" 2>/dev/null || {
    rm -f "$tmp" 2>/dev/null || true
    return 0
  }

  if [ -z "$link_target" ]; then
    link_tmp="$(mktemp "$CONTEXT_BAND_DIR/.${alias}.current.link.tmp.XXXXXX" 2>/dev/null || true)"
    [ -n "$link_tmp" ] || return 0
    rm -f "$link_tmp" 2>/dev/null || true
    ln -s "$target_name" "$link_tmp" 2>/dev/null || {
      rm -f "$link_tmp" 2>/dev/null || true
      return 0
    }
    mv -f "$link_tmp" "$link" 2>/dev/null || rm -f "$link_tmp" 2>/dev/null || true
  fi
}

# --- Model (short name) ---
if printf '%s' "$model_display" | grep -qi "opus"; then
  model_short="Opus"
elif printf '%s' "$model_display" | grep -qi "sonnet"; then
  model_short="Sonnet"
elif printf '%s' "$model_display" | grep -qi "haiku"; then
  model_short="Haiku"
else
  model_id=$(printf '%s' "$input" | jq -r '.model.id // ""')
  model_short="${model_id##*-}"
fi

write_live_context_band

# --- Context window usage ---
used_pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty')

if [ -n "$used_pct" ]; then
  used_int=$(printf "%.0f" "$used_pct")

  # Build 10-char bar
  filled=$(( used_int / 10 ))
  empty=$(( 10 - filled ))
  bar=""
  for i in $(seq 1 $filled); do bar="${bar}▓"; done
  for i in $(seq 1 $empty);  do bar="${bar}░"; done

  # Color based on usage
  if [ "$used_int" -lt 50 ]; then
    ctx_color="\033[0;32m"
  elif [ "$used_int" -lt 80 ]; then
    ctx_color="\033[0;33m"
  else
    ctx_color="\033[0;31m"
  fi

  ctx_str="${ctx_color}${bar} ${used_int}%\033[0m"
else
  ctx_str="\033[0;90mctx: --\033[0m"
fi

# --- Session cost (total input + output tokens → rough USD estimate) ---
total_in=$(printf '%s' "$input" | jq -r '.context_window.total_input_tokens  // 0')
total_out=$(printf '%s' "$input" | jq -r '.context_window.total_output_tokens // 0')
model_id_full=$(printf '%s' "$input" | jq -r '.model.id // ""')

# Pricing per 1M tokens (USD) — pick rate based on model
if printf '%s' "$model_id_full" | grep -qi "opus-4"; then
  price_in="15.00"
  price_out="75.00"
elif printf '%s' "$model_id_full" | grep -qi "sonnet-4"; then
  price_in="3.00"
  price_out="15.00"
elif printf '%s' "$model_id_full" | grep -qi "haiku"; then
  price_in="0.80"
  price_out="4.00"
else
  price_in="3.00"
  price_out="15.00"
fi

cost=$(awk -v in_tok="$total_in" -v out_tok="$total_out" \
           -v p_in="$price_in" -v p_out="$price_out" \
       'BEGIN { printf "%.3f", (in_tok * p_in + out_tok * p_out) / 1000000 }')

cost_str="\033[0;97m\$${cost}\033[0m"

# --- Assemble single line ---
cyan="\033[0;36m"
reset="\033[0m"
sep="\033[0;90m │\033[0m"

echo -e "${cyan}${model_short}${reset}${sep} ${ctx_str}${sep} ${cost_str}"
