#!/usr/bin/env bash
# test_auth_source_fetch.sh — suite for the researcher authenticated-source reader.
#
# RESEARCHER_TRANCHE3_11_AUTH_SOURCE_ACCESS_1 (b2, 2026-07-12; codex design-verify #9391).
# The DENY/arg cases are deterministic (structural URL gate runs BEFORE any CDP contact),
# so they assert real exit codes with no browser. The ALLOW path drives the port-9222
# debug Chrome over CDP, so it runs only as an integration check when 9222 is reachable
# (skipped otherwise — never a false FAIL in CI).
set -u
SCRIPT="$(dirname "$0")/../auth_source_fetch.sh"
[ -x "$SCRIPT" ] || { echo "FAIL [setup]: script missing/not executable at $SCRIPT" >&2; exit 1; }

PASS=0; FAIL=0; SKIP=0

# expect_rc <expected-rc> <name> <args...>
expect_rc() {
    local expected="$1" name="$2"; shift 2
    bash "$SCRIPT" "$@" >/dev/null 2>&1
    local actual=$?
    if [ "$expected" = "$actual" ]; then echo "PASS: $name (exit $actual)"; PASS=$((PASS+1))
    else echo "FAIL: $name (expected $expected, got $actual)" >&2; FAIL=$((FAIL+1)); fi
}

# expect_reason <substr> <name> <args...> — assert stderr carries the reason token
expect_reason() {
    local sub="$1" name="$2"; shift 2
    local err; err="$(bash "$SCRIPT" "$@" 2>&1 >/dev/null)"
    case "$err" in
        *"$sub"*) echo "PASS: $name (reason: $sub)"; PASS=$((PASS+1)) ;;
        *) echo "FAIL: $name (expected reason $sub, got: $err)" >&2; FAIL=$((FAIL+1)) ;;
    esac
}

echo "== arg guards (no arg-driven exec; exactly one positional URL) =="
expect_rc 1 "no args"                      # usage error
expect_rc 1 "two args"       a b
expect_rc 1 "flag rejected"  --oops
expect_reason "no flags"     "leading-dash rejected as flag not URL"  -https://arxiv.org/x

echo "== structural URL gate (runs before any CDP contact — deterministic) =="
expect_rc     2 "http rejected"                 "http://arxiv.org/abs/1"
expect_reason "scheme_not_https" "http reason"  "http://arxiv.org/abs/1"
expect_rc     2 "ftp rejected"                  "ftp://arxiv.org/x"
expect_reason "userinfo_rejected" "userinfo"    "https://user:pass@arxiv.org/x"
expect_rc     2 "off-allowlist host"            "https://evil.com/x"
expect_reason "domain_not_allowlisted" "evil host reason" "https://evil.com/x"
# suffix-match must NOT be fooled by a look-alike host (endswith '.arxiv.org' only)
expect_rc     2 "lookalike host rejected"       "https://arxiv.org.evil.com/x"
expect_reason "domain_not_allowlisted" "lookalike reason" "https://arxiv.org.evil.com/x"

echo "== ALLOW path (integration — needs the port-9222 debug Chrome) =="
if curl -s --max-time 4 "http://127.0.0.1:9222/json/version" >/dev/null 2>&1; then
    out="$(bash "$SCRIPT" "https://arxiv.org/abs/1706.03762" 2>/dev/null)"; rc=$?
    if [ "$rc" = "0" ] && printf '%s' "$out" | grep -qi "Attention Is All You Need"; then
        echo "PASS: allow-listed arxiv read returns rendered body text (exit 0)"; PASS=$((PASS+1))
    else
        echo "FAIL: allow-listed read (rc=$rc, ${#out} bytes)" >&2; FAIL=$((FAIL+1))
    fi
else
    echo "SKIP: port-9222 debug Chrome not reachable — ALLOW-path integration skipped"; SKIP=$((SKIP+1))
fi

echo "---"
echo "auth_source_fetch tests: $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" = "0" ]
