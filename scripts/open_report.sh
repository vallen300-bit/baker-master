#!/usr/bin/env bash
# open_report.sh — vetted wrapper: open a researcher's OWN report file in the browser.
#
# RESEARCHER_OPEN_REPORT_WRAPPER_1 (deputy, 2026-07-12; lead dispatch #9194,
# Director-directed). The researcher Bash cage denies raw `open` (URL-opening is the
# prompt-injection surface the cage exists to block), so the researcher cannot show
# Director its own rendered reports. This wrapper is the sanctioned path — allow-listed
# by EXACT canonical path in researcher_bash_cage.sh, same lineage as check_inbox.sh.
#
# STRICT posture (the cage trusts this path's internals):
#   - Opens EXACTLY ONE path arg, and ONLY a regular FILE that resolves (realpath,
#     defeating ../ traversal + symlinks) under one of the researcher's OWN output
#     roots. Anything else → REJECT exit 2.
#   - NEVER opens a URL. Any arg containing "://" is rejected up front. URL-opening
#     stays denied — that is the injection surface (F1: open http://evil → drive-by).
#   - No arg-driven exec: the validated path is passed ONLY to macOS `open`, never eval'd.
#
# Allowed roots (researcher's own delivery + scratch surfaces):
#   /Users/dimitry/baker-vault/wiki/research/   (canonical research deliverables)
#   /Users/dimitry/baker-vault/docs-site/       (rendered docs site, if present)
#   /tmp/research-*/                             (scratch renders; macOS /tmp→/private/tmp)
#
# Usage: open_report.sh <path-to-file-under-an-allowed-root>
set -u

TARGET="${1:-}"
reject() { echo "open_report: REJECTED — $1" >&2; exit 2; }

[ -n "$TARGET" ] || reject "missing file path"
[ "$#" -eq 1 ] || reject "exactly one path arg allowed (got $#)"
# URL guard BEFORE any resolution — no scheme may ever reach `open`.
case "$TARGET" in *"://"*) reject "URLs are not allowed (file paths only)" ;; esac

# Validate + canonicalize inside the trusted wrapper (python realpath + prefix check).
# Prints the canonical path on success (allowed + is a regular file), nothing otherwise.
# `python3 -c` with a single-quoted program (path passed via env, not interpolated) —
# avoids heredoc-in-$() paren-matching quirks on macOS bash 3.2.
SAFE="$(TARGET="$TARGET" python3 -c '
import os, sys
t = os.environ.get("TARGET", "")
if not t or "://" in t:
    sys.exit(0)
rp = os.path.realpath(t)
if not os.path.isfile(rp):
    sys.exit(0)
fixed = ["/Users/dimitry/baker-vault/wiki/research",
         "/Users/dimitry/baker-vault/docs-site"]
for root in fixed:
    r = os.path.realpath(root) + os.sep
    if rp.startswith(r):
        print(rp); sys.exit(0)
tmp_prefix = os.path.realpath("/tmp") + os.sep + "research-"
if rp.startswith(tmp_prefix):
    print(rp); sys.exit(0)
sys.exit(0)
')"

[ -n "$SAFE" ] || reject "path is not an existing file under an allowed researcher output root (wiki/research/, docs-site/, /tmp/research-*/)"

# Open the validated canonical path. `open` runs HERE (trusted internals), not from
# the model's Bash. --  guards against a path that starts with '-'.
exec open -- "$SAFE"
