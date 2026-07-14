#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
HELPER="${CODEX_REVIEW_WORKTREE_HELPER:-$ROOT/scripts/codex-review-worktree.sh}"
WRAPPER="${CODEX_VERIFY_WRAPPER:-$ROOT/scripts/codex-verify}"
INSTALLER="$ROOT/scripts/install-codex-verify.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codex-review-test.XXXXXX")"
trap 'rm -rf -- "$TEST_ROOT"' EXIT

REPO="$TEST_ROOT/repo"
REMOTE="$TEST_ROOT/remote.git"
mkdir -p "$REPO"
git init -q --bare "$REMOTE"
git -C "$REPO" init -q
git -C "$REPO" config user.email test@example.invalid
git -C "$REPO" config user.name "Codex Test"
printf 'base\n' > "$REPO/sample.txt"
git -C "$REPO" add sample.txt
git -C "$REPO" commit -qm base
git -C "$REPO" branch -M main
git -C "$REPO" remote add origin "$REMOTE"
git -C "$REPO" push -q -u origin main

FAKE_BIN="$TEST_ROOT/bin"
OUT="$TEST_ROOT/out"
mkdir -p "$FAKE_BIN" "$OUT"
cat > "$FAKE_BIN/codex" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "login" ]; then
    echo "Logged in"
    exit 0
fi
printf 'pwd=%s\n' "$PWD" > "$CODEX_OUT/review.txt"
printf 'root=%s\n' "$(git rev-parse --show-toplevel)" >> "$CODEX_OUT/review.txt"
printf 'branch_before=%s\n' "$(git branch --show-current)" >> "$CODEX_OUT/review.txt"
printf 'status_before=%s\n' "$(git status --porcelain | tr '\n' '|')" >> "$CODEX_OUT/review.txt"
git checkout -qb codex-review-test
printf 'branch_after=%s\n' "$(git branch --show-current)" >> "$CODEX_OUT/review.txt"
touch codex-left-an-artifact.txt
if [ "${CODEX_EXIT:-0}" -ne 0 ]; then
    exit "$CODEX_EXIT"
fi
EOF
chmod +x "$FAKE_BIN/codex"

run_wrapper_args() {
    mkdir -p "$TEST_ROOT/tmp" "$TEST_ROOT/home"
    CODEX_OUT="$OUT" \
    CODEX_REVIEW_WORKTREE_HELPER="$HELPER" \
    PATH="$FAKE_BIN:$PATH" \
    HOME="$TEST_ROOT/home" \
    TMPDIR="$TEST_ROOT/tmp" \
    "$WRAPPER" "$@"
}

run_wrapper() {
    run_wrapper_args --review --uncommitted
}

assert_source_state() {
    test "$(git -C "$REPO" branch --show-current)" = "main"
    test "$(git -C "$REPO" status --porcelain)" = "$EXPECTED_STATUS"
    test "$(git -C "$REPO" worktree list | wc -l | tr -d ' ')" = "1"
test -z "$(git -C "$REPO" branch --list codex-review-test)"
}

cd "$REPO"
git config core.hooksPath /dev/null

INSTALL_DIR="$TEST_ROOT/install"
CODEX_VERIFY_INSTALL_DIR="$INSTALL_DIR" "$INSTALLER"
cmp "$ROOT/scripts/codex-review-worktree.sh" "$INSTALL_DIR/codex-review-worktree.sh"
cmp "$ROOT/scripts/codex-verify" "$INSTALL_DIR/codex-verify"

run_wrapper
grep -q 'branch_before=' "$OUT/review.txt"
! grep -q 'branch_before=main' "$OUT/review.txt"
grep -q 'branch_after=codex-review-test' "$OUT/review.txt"
EXPECTED_STATUS=""
assert_source_state

printf 'dirty\n' >> "$REPO/sample.txt"
printf 'untracked\n' > "$REPO/untracked.txt"
EXPECTED_STATUS="$(git -C "$REPO" status --porcelain)"
run_wrapper
grep -q 'sample.txt' "$OUT/review.txt"
grep -q 'untracked.txt' "$OUT/review.txt"
assert_source_state

run_wrapper_args --review --base main
grep -q '^status_before=$' "$OUT/review.txt"
assert_source_state

TARGET_COMMIT="$(git -C "$REPO" rev-parse HEAD)"
run_wrapper_args --review --commit "$TARGET_COMMIT"
grep -q '^status_before=$' "$OUT/review.txt"
assert_source_state

set +e
CODEX_EXIT=17 \
CODEX_OUT="$OUT" \
CODEX_REVIEW_WORKTREE_HELPER="$HELPER" \
PATH="$FAKE_BIN:$PATH" \
HOME="$TEST_ROOT/home" \
TMPDIR="$TEST_ROOT/tmp" \
"$WRAPPER" --review --uncommitted
status=$?
set -e
test "$status" = "17"
assert_source_state
test -z "$(find "$TEST_ROOT/tmp" -mindepth 1 -maxdepth 1 -type d -name 'codex-review-wt.*' -print)"

echo "PASS: codex review worktree isolation success, dirty-state reproduction, and failure cleanup"
