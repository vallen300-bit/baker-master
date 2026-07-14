#!/usr/bin/env bash
# Run a Codex review command from an ephemeral worktree.
#
# The caller supplies the target ref and optionally asks us to reproduce the
# invoking checkout's tracked/untracked changes. The invoking checkout is never
# used as Codex's cwd, so a review cannot switch its branch or leave artifacts.
#
# Review runs must not overlap another branch-creating operation in the same
# checkout. Cleanup removes local branch refs absent at run start and reports
# each deletion so an unexpected concurrent branch is observable.

set -euo pipefail

REF="HEAD"
COPY_UNCOMMITTED=0
REQUIRE_GIT=0
COMMAND=()

usage() {
    echo "Usage: $0 [--ref REF] [--copy-uncommitted] [--require-git] -- COMMAND [ARGS...]" >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --ref)
            [ "$#" -ge 2 ] || usage
            REF="$2"
            shift 2
            ;;
        --copy-uncommitted)
            COPY_UNCOMMITTED=1
            shift
            ;;
        --require-git)
            REQUIRE_GIT=1
            shift
            ;;
        --)
            shift
            COMMAND=("$@")
            break
            ;;
        *)
            usage
            ;;
    esac
done

[ "${#COMMAND[@]}" -gt 0 ] || usage

REPO=""
if REPO="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    if [ "$REQUIRE_GIT" -eq 1 ]; then
        echo "codex-review-worktree: current directory is not a git repository" >&2
        exit 1
    fi
    TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codex-review-wt.XXXXXX")"
    cleanup_tmp() {
        local status=$?
        trap - EXIT
        rm -rf -- "$TMP_ROOT"
        exit "$status"
    }
    trap cleanup_tmp EXIT
    mkdir -p "$TMP_ROOT/run"
    (
        cd "$TMP_ROOT/run"
        "${COMMAND[@]}"
    )
    exit $?
fi

SNAPSHOT_ROOT=""
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codex-review-wt.XXXXXX")"
WORKTREE="$TMP_ROOT/review"
INITIAL_BRANCHES="$TMP_ROOT/initial-branches"
git -C "$REPO" for-each-ref --format='%(refname)' refs/heads > "$INITIAL_BRANCHES"

cleanup_worktree() {
    local status=$?
    trap - EXIT
    if [ -n "${WORKTREE:-}" ] && [ -d "$WORKTREE" ]; then
        git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
    fi
    while IFS= read -r branch_ref; do
        [ -n "$branch_ref" ] || continue
        if ! grep -Fqx "$branch_ref" "$INITIAL_BRANCHES"; then
            if git -C "$REPO" update-ref -d "$branch_ref"; then
                printf 'codex-review-worktree: removed review-created ref %s\n' \
                    "$branch_ref" >&2
            else
                printf 'codex-review-worktree: could not remove review-created ref %s\n' \
                    "$branch_ref" >&2
            fi
        fi
    done < <(git -C "$REPO" for-each-ref --format='%(refname)' refs/heads)
    git -C "$REPO" worktree prune >/dev/null 2>&1 || true
    rm -rf -- "$TMP_ROOT"
    exit "$status"
}
trap cleanup_worktree EXIT

if [ "$COPY_UNCOMMITTED" -eq 1 ]; then
    SNAPSHOT_ROOT="$TMP_ROOT/snapshot"
    mkdir -p "$SNAPSHOT_ROOT"
    git -C "$REPO" diff --no-ext-diff --binary > "$SNAPSHOT_ROOT/unstaged.patch"
    git -C "$REPO" diff --cached --no-ext-diff --binary > "$SNAPSHOT_ROOT/cached.patch"
    git -C "$REPO" ls-files -z --others --exclude-standard > "$SNAPSHOT_ROOT/untracked.list"
fi

git -C "$REPO" rev-parse --verify "${REF}^{commit}" >/dev/null
git -C "$REPO" worktree add --detach --quiet "$WORKTREE" "$REF"

if [ "$COPY_UNCOMMITTED" -eq 1 ]; then
    if [ -s "$SNAPSHOT_ROOT/cached.patch" ]; then
        git -C "$WORKTREE" apply --index --binary "$SNAPSHOT_ROOT/cached.patch"
    fi
    if [ -s "$SNAPSHOT_ROOT/unstaged.patch" ]; then
        git -C "$WORKTREE" apply --binary "$SNAPSHOT_ROOT/unstaged.patch"
    fi

    while IFS= read -r -d '' relative_path; do
        source_path="$REPO/$relative_path"
        target_path="$WORKTREE/$relative_path"
        [ -e "$source_path" ] || [ -L "$source_path" ] || continue
        mkdir -p -- "$(dirname "$target_path")"
        cp -pR -- "$source_path" "$target_path"
    done < "$SNAPSHOT_ROOT/untracked.list"
fi

(
    cd "$WORKTREE"
    "${COMMAND[@]}"
)
exit $?
