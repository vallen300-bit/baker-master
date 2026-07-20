#!/usr/bin/env bash
# install_forge_agent.sh — install / verify the Brisen Lab forge-agent session
# liveness layer (heartbeat ticker + SessionStart/turn hooks + bus drain/ack)
# on a host.
#
# WHY THIS EXISTS (WAKE_HOST_AFFINITY_1 follow-up, 2026-07-05): the forge-agent
# scripts historically had NO source-of-truth in the repo and NO installer —
# they were hand-placed on the Director's laptop (see
# _ops/processes/brisen-lab-session-start-hook.md). The Mac Mini (the designated
# desk SPAWN host) was never provisioned, so NO session on it ever spawned a
# heartbeat ticker; isAliasLive (the wake-handler's same-host anti-duplicate
# guard) was permanently blind there, and a desk double-spawned + stalled
# overnight. This installer makes the provisioning repeatable + drift-detectable
# so that failure mode cannot recur silently.
#
# MODES:
#   install (default)  — deploy scripts, wire hooks, add env. Idempotent.
#   --check            — non-mutating drift check (for cron). Exit 0 clean,
#                        non-zero on any drift, with a per-item report.
#
# HOST CLASS (the laptop-vs-spawn-host distinction, codified per lead 2026-07-05
# #5624): the forge+bus hook set is installed on BOTH classes. Director-facing
# ENFORCEMENT hooks (recommendation-check / laconic-reminder / etc.) belong ONLY
# on the interactive laptop and are NEVER installed on a headless spawn host —
# they would fire uselessly against non-Director-facing desk/worker output.
#   --headless / --laptop override auto-detection (hostname *mac-mini* =>
#   headless). A ~/.brisen-lab/host-class file ("headless"/"laptop") wins over
#   both.
#
# CONTRACT: never partially wire settings.json (atomic temp+replace, backup
# first). FORGE_KEY is read from env or 1Password — never hardcoded in the repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORGE_SRC_DIR="${SCRIPT_DIR}/forge-agent"
FIXTURES_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/tests/fixtures"

# Canonical deploy targets. Overridable (FORGE_AGENT_HOME / CLAUDE_HOME) for
# tests so a dry-run install never touches the real ~/.claude or ~/forge-agent.
FORGE_HOME="${FORGE_AGENT_HOME:-$HOME/forge-agent}"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
HOOKS_DIR="${CLAUDE_DIR}/hooks"
SETTINGS="${CLAUDE_DIR}/settings.json"
ZSHRC="${FORGE_AGENT_ZSHRC:-$HOME/.zshrc}"
HOST_CLASS_FILE="${BRISEN_LAB_HOST_CLASS_FILE:-$HOME/.brisen-lab/host-class}"
LAB_URL_DEFAULT="https://brisen-lab.onrender.com"

# Deployed forge scripts (canonical source -> deploy basename).
FORGE_SCRIPTS=(session-start-hook.sh heartbeat-ticker.sh turn-start-hook.sh turn-stop-hook.sh \
  codex-worktree.sh lifecycle-watch.sh)
# Bus hooks: canonical source is tests/fixtures/ (already tracked); deployed to
# ~/.claude/hooks/.
BUS_HOOKS=(session-start-bus-drain.sh stop-bus-ack.sh)

MODE="install"
CLASS_OVERRIDE=""
for arg in "$@"; do
  case "$arg" in
    --check)    MODE="check" ;;
    --install)  MODE="install" ;;
    --headless) CLASS_OVERRIDE="headless" ;;
    --laptop)   CLASS_OVERRIDE="laptop" ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown arg: $arg (use --check / --headless / --laptop)" >&2; exit 2 ;;
  esac
done

# --- host class resolution -------------------------------------------------
resolve_host_class() {
  if [[ -n "$CLASS_OVERRIDE" ]]; then echo "$CLASS_OVERRIDE"; return; fi
  if [[ -r "$HOST_CLASS_FILE" ]]; then
    local c; c="$(tr -d '[:space:]' < "$HOST_CLASS_FILE" | tr '[:upper:]' '[:lower:]')"
    case "$c" in headless|laptop) echo "$c"; return ;; esac
  fi
  local hn; hn="$(hostname 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  if [[ "$hn" == *mac-mini* || "$hn" == *macmini* ]]; then echo "headless"; else echo "laptop"; fi
}
HOST_CLASS="$(resolve_host_class)"

# --- sanity: canonical sources present -------------------------------------
for s in "${FORGE_SCRIPTS[@]}"; do
  [[ -f "${FORGE_SRC_DIR}/${s}" ]] || { echo "FATAL: canonical forge script missing: ${FORGE_SRC_DIR}/${s}" >&2; exit 2; }
done
for h in "${BUS_HOOKS[@]}"; do
  [[ -f "${FIXTURES_DIR}/${h}" ]] || { echo "FATAL: canonical bus hook missing: ${FIXTURES_DIR}/${h}" >&2; exit 2; }
done

_sha() { shasum "$1" 2>/dev/null | awk '{print $1}'; }

# The forge+bus hook wiring, as a JSON fragment merged into settings.json. Uses
# absolute deployed paths so the wiring is host-correct.
emit_hook_fragment() {
  python3 - "$FORGE_HOME" "$HOOKS_DIR" <<'PY'
import json, sys
forge, hooks = sys.argv[1], sys.argv[2]
def g(cmd, timeout=None, matcher=None):
    h = {"type": "command", "command": cmd}
    if timeout is not None: h["timeout"] = timeout
    grp = {"hooks": [h]}
    if matcher is not None: grp["matcher"] = matcher
    return grp
frag = {
    "SessionStart": [
        g(f"{forge}/session-start-hook.sh", timeout=10),
        g(f"{hooks}/session-start-bus-drain.sh", timeout=15),
    ],
    "UserPromptSubmit": [
        g(f"{forge}/turn-start-hook.sh", matcher="*"),
    ],
    "Stop": [
        g(f"{forge}/turn-stop-hook.sh", matcher="*"),
        g(f"{hooks}/stop-bus-ack.sh", timeout=10),
    ],
}
print(json.dumps(frag))
PY
}

# Director-facing ENFORCEMENT hook command substrings that must NOT appear on a
# headless host. Codifies the laptop-vs-spawn-host distinction.
DIRECTOR_ONLY_SUBSTRINGS=(recommendation-check end-cue-check fail-loud-check \
  synthesis-vs-taxonomy standing-rules-scan stakeholder-authority-trigger \
  contract-gate-trigger strategic-mode-router authority-profile-preload \
  pre-send-checklist annotate-pending-checker laconic-reminder)

# ===========================================================================
# CHECK MODE — non-mutating drift detection (cron-safe)
# ===========================================================================
if [[ "$MODE" == "check" ]]; then
  drift=0
  report() { printf '  [%s] %s\n' "$1" "$2"; }
  echo "forge-agent drift-check (host-class=$HOST_CLASS, home=$FORGE_HOME)"

  # 1. Deployed forge scripts match canonical AND are executable. A content
  #    match with a lost +x bit is silent death (the hook simply never runs), so
  #    -x is validated alongside the shasum (codex G3 #5629 finding 1).
  for s in "${FORGE_SCRIPTS[@]}"; do
    if [[ ! -f "${FORGE_HOME}/${s}" ]]; then report FAIL "missing deployed ${FORGE_HOME}/${s}"; drift=1
    elif [[ "$(_sha "${FORGE_HOME}/${s}")" != "$(_sha "${FORGE_SRC_DIR}/${s}")" ]]; then
      report FAIL "drift ${s} (deployed != canonical)"; drift=1
    elif [[ ! -x "${FORGE_HOME}/${s}" ]]; then report FAIL "${s} not executable (-x lost)"; drift=1
    else report OK "${s}"; fi
  done
  # 2. Deployed bus hooks match canonical AND are executable.
  for h in "${BUS_HOOKS[@]}"; do
    if [[ ! -f "${HOOKS_DIR}/${h}" ]]; then report FAIL "missing deployed ${HOOKS_DIR}/${h}"; drift=1
    elif [[ "$(_sha "${HOOKS_DIR}/${h}")" != "$(_sha "${FIXTURES_DIR}/${h}")" ]]; then
      report FAIL "drift ${h} (deployed != canonical fixture)"; drift=1
    elif [[ ! -x "${HOOKS_DIR}/${h}" ]]; then report FAIL "${h} not executable (-x lost)"; drift=1
    else report OK "${h}"; fi
  done
  # 3. Env present in zshrc.
  for v in FORGE_KEY LAB_URL; do
    if grep -qE "^export ${v}=" "$ZSHRC" 2>/dev/null; then report OK "env ${v}"; else report FAIL "env ${v} missing from ${ZSHRC}"; drift=1; fi
  done
  # 4. Hooks wired in settings.json (+ headless purity).
  if [[ ! -f "$SETTINGS" ]]; then report FAIL "settings.json missing: $SETTINGS"; drift=1; else
    verdict="$(FORGE_HOME="$FORGE_HOME" HOOKS_DIR="$HOOKS_DIR" HOST_CLASS="$HOST_CLASS" \
      DIRECTOR_ONLY="${DIRECTOR_ONLY_SUBSTRINGS[*]}" python3 - "$SETTINGS" <<'PY'
import json, os, sys
d = json.load(open(sys.argv[1]))
hooks = d.get("hooks", {})
# Path-form normalization: Claude Code expands $HOME / ${HOME} / ~ at runtime,
# so a hook wired as "$HOME/forge-agent/turn-start-hook.sh" is EQUIVALENT to the
# absolute "/Users/x/forge-agent/turn-start-hook.sh". Compare normalized forms
# or a legit $HOME-form wiring false-positives as missing (laptop drift alarm).
HOME = os.environ.get("HOME", "")
def norm(c):
    c = (c or "").replace("${HOME}", HOME).replace("$HOME", HOME)
    return os.path.expanduser(c)
def cmds(ev): return [norm(h.get("command","")) for g in hooks.get(ev,[]) for h in g.get("hooks",[])]
forge, hd = os.environ["FORGE_HOME"], os.environ["HOOKS_DIR"]
need = {
    "SessionStart": [f"{forge}/session-start-hook.sh", f"{hd}/session-start-bus-drain.sh"],
    "UserPromptSubmit": [f"{forge}/turn-start-hook.sh"],
    "Stop": [f"{forge}/turn-stop-hook.sh", f"{hd}/stop-bus-ack.sh"],
}
missing = [f"{ev}:{c}" for ev, cs in need.items() for c in cs if norm(c) not in cmds(ev)]
for m in missing: print("FAIL missing-wire " + m)
if os.environ["HOST_CLASS"] == "headless":
    subs = os.environ["DIRECTOR_ONLY"].split()
    allc = [c for ev in hooks for g in hooks[ev] for h in g.get("hooks",[]) for c in [h.get("command","")]]
    for c in allc:
        if any(s in c for s in subs):
            print("FAIL director-hook-on-headless " + c)
if not missing:
    print("OK wiring")
PY
)"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      case "$line" in
        OK*)   report OK "settings.json ${line#OK }" ;;
        FAIL*) report FAIL "settings.json ${line#FAIL }"; drift=1 ;;
      esac
    done <<< "$verdict"
  fi

  if [[ "$drift" -eq 0 ]]; then echo "RESULT: clean"; exit 0
  else echo "RESULT: DRIFT DETECTED — run: bash $(basename "${BASH_SOURCE[0]}") (host-class=$HOST_CLASS)"; exit 1; fi
fi

# ===========================================================================
# INSTALL MODE
# ===========================================================================
echo "forge-agent install (host-class=$HOST_CLASS)"

# FORGE_KEY: env, else 1Password. LAB_URL: env, else default.
if [[ -z "${FORGE_KEY:-}" ]]; then
  if command -v op >/dev/null 2>&1; then
    FORGE_KEY="$(op read 'op://Baker API Keys/FORGE_KEY (brisen-lab)/credential' 2>/dev/null || true)"
  fi
fi
[[ -n "${FORGE_KEY:-}" ]] || { echo "FATAL: FORGE_KEY not in env and 1Password fetch failed. Set FORGE_KEY and retry." >&2; exit 2; }
LAB_URL="${LAB_URL:-$LAB_URL_DEFAULT}"

# 1. Deploy forge scripts.
mkdir -p "$FORGE_HOME/active"
[[ -f "$FORGE_HOME/sessions.json" ]] || echo '{}' > "$FORGE_HOME/sessions.json"
for s in "${FORGE_SCRIPTS[@]}"; do
  cp "${FORGE_SRC_DIR}/${s}" "${FORGE_HOME}/${s}"; chmod +x "${FORGE_HOME}/${s}"
done
echo "  deployed ${#FORGE_SCRIPTS[@]} forge scripts -> $FORGE_HOME"

# 2. Deploy bus hooks.
mkdir -p "$HOOKS_DIR"
for h in "${BUS_HOOKS[@]}"; do
  cp "${FIXTURES_DIR}/${h}" "${HOOKS_DIR}/${h}"; chmod +x "${HOOKS_DIR}/${h}"
done
echo "  deployed ${#BUS_HOOKS[@]} bus hooks -> $HOOKS_DIR"

# 3. Env in zshrc (idempotent; never overwrite an existing export).
touch "$ZSHRC"
if ! grep -qE '^export FORGE_KEY=' "$ZSHRC"; then
  { echo ""; echo "# Brisen Lab forge telemetry (install_forge_agent.sh)"; \
    printf 'export FORGE_KEY=%q\n' "$FORGE_KEY"; } >> "$ZSHRC"
  echo "  appended FORGE_KEY to $ZSHRC"
else echo "  FORGE_KEY already in $ZSHRC (kept)"; fi
if ! grep -qE '^export LAB_URL=' "$ZSHRC"; then
  printf 'export LAB_URL=%q\n' "$LAB_URL" >> "$ZSHRC"
  echo "  appended LAB_URL to $ZSHRC"
else echo "  LAB_URL already in $ZSHRC (kept)"; fi

# 4. Wire hooks into settings.json (backup first, atomic merge, preserve keys).
mkdir -p "$CLAUDE_DIR"
[[ -f "$SETTINGS" ]] || echo '{}' > "$SETTINGS"
cp "$SETTINGS" "${SETTINGS}.bak-$(date +%Y%m%d-%H%M%S)"
FRAG="$(emit_hook_fragment)"
FRAG="$FRAG" SETTINGS="$SETTINGS" HOST_CLASS="$HOST_CLASS" \
  DIRECTOR_ONLY="${DIRECTOR_ONLY_SUBSTRINGS[*]}" python3 - <<'PY'
import json, os, tempfile
sp = os.environ["SETTINGS"]
d = json.load(open(sp))
frag = json.loads(os.environ["FRAG"])
hooks = d.setdefault("hooks", {})
# Normalize $HOME/${HOME}/~ so an existing "$HOME/..."-form hook is recognized as
# the same as the absolute form we emit — else dedup misses it and we append a
# DUPLICATE (a re-install on the laptop, whose turn hooks use $HOME form, would
# double them). Same normalization as --check.
HOME = os.environ.get("HOME", "")
def norm(c):
    c = (c or "").replace("${HOME}", HOME).replace("$HOME", HOME)
    return os.path.expanduser(c)
def cmds(group): return tuple(norm(h.get("command")) for h in group.get("hooks", []))
for ev, groups in frag.items():
    existing = hooks.setdefault(ev, [])
    have = {cmds(g) for g in existing}
    for g in groups:
        if cmds(g) not in have:
            existing.append(g); have.add(cmds(g))
# Headless purity: on a spawn host, Director-facing enforcement hooks are noise
# AND make --check fail. The installer must CONVERGE (codex G3 #5629 finding 2:
# leaving them warns but then --check fails on the same host = unhealable loop),
# so on --headless we STRIP any Director-facing hook entry, dropping groups that
# become empty and events that become empty. Reported, not silent.
if os.environ["HOST_CLASS"] == "headless":
    subs = os.environ["DIRECTOR_ONLY"].split()
    removed = []
    for ev in list(hooks.keys()):
        new_groups = []
        for g in hooks[ev]:
            kept = []
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                if any(s in cmd for s in subs):
                    removed.append(cmd)
                else:
                    kept.append(h)
            if kept:
                ng = dict(g); ng["hooks"] = kept; new_groups.append(ng)
        if new_groups:
            hooks[ev] = new_groups
        else:
            del hooks[ev]
    if removed:
        print("  stripped %d Director-facing hook(s) on headless host: %s"
              % (len(removed), ", ".join(removed)))
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(sp))
with os.fdopen(fd, "w") as f:
    json.dump(d, f, indent=2)
os.replace(tmp, sp)
print("  wired forge+bus hooks into settings.json (events: %s)" % ", ".join(sorted(frag)))
PY

echo "install complete. Verify: bash $(basename "${BASH_SOURCE[0]}") --check"
