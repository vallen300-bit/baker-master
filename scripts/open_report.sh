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

# Race-free validate-and-snapshot inside the trusted wrapper (codex G3 #9204 HIGH:
# a path-validate-then-open-by-path design is TOCTOU — a symlink swap between the
# check and `open` escapes all roots). This construction has NO check/use gap:
#   1. os.open(target, O_RDONLY | O_NOFOLLOW) — opens ONCE; a symlink at the final
#      component is refused outright.
#   2. fstat the fd — must be a regular file.
#   3. F_GETPATH on the *held fd* gives the canonical path of the inode actually
#      opened; the allowed-root check runs against THAT, not a re-resolved path.
#   4. Snapshot the bytes by reading the SAME fd (never a second open-by-path) into
#      a private mkstemp file (unpredictable name, per-user $TMPDIR).
# `open` then renders the snapshot — the original path is never reopened, so a
# post-validation swap cannot redirect it. Prints the snapshot path on success.
SNAP="$(TARGET="$TARGET" python3 -c '
import os, sys, stat, fcntl, tempfile
t = os.environ.get("TARGET", "")
if not t or "://" in t:
    sys.exit(0)
try:
    fd = os.open(t, os.O_RDONLY | os.O_NOFOLLOW)   # refuse a symlink final component
except OSError:
    sys.exit(0)
try:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        sys.exit(0)
    F_GETPATH = getattr(fcntl, "F_GETPATH", 50)     # macOS: canonical path of the fd
    real = fcntl.fcntl(fd, F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0].decode()
    ok = False
    for root in ("/Users/dimitry/baker-vault/wiki/research",
                 "/Users/dimitry/baker-vault/docs-site"):
        if real.startswith(os.path.realpath(root) + os.sep):
            ok = True; break
    if not ok and real.startswith(os.path.realpath("/tmp") + os.sep + "research-"):
        ok = True
    if not ok:
        sys.exit(0)
    data = b""
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        data += chunk
finally:
    os.close(fd)
sfd, spath = tempfile.mkstemp(suffix=".html", prefix="open_report_")
os.write(sfd, data); os.close(sfd)
print(spath)
')"

[ -n "$SNAP" ] || reject "not an existing regular file under an allowed researcher output root (wiki/research/, docs-site/, /tmp/research-*/), or a symlink was refused"

# Open the private snapshot. `open` runs HERE (trusted internals), not from the
# model's Bash. -- guards a path that starts with '-'. The original path is never
# reopened, so a check/use race cannot redirect this.
exec open -- "$SNAP"
