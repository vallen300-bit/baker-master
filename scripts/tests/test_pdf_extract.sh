#!/usr/bin/env bash
# test_pdf_extract.sh — suite for scripts/pdf_extract.sh (researcher local-PDF v1).
#
# RESEARCHER_TRANCHE3 ITEM-10 (b3, 2026-07-12; deputy dispatch #9855).
# Deterministic + offline. Fixtures are generated in a tmp dir with reportlab
# (text + blank/no-text PDFs) and pypdf (encryption), so the whole suite runs with
# no network and no external files. Covers the happy path + all 3 fail-loud modes.
set -u
SCRIPT="$(dirname "$0")/../pdf_extract.sh"
[ -x "$SCRIPT" ] || { echo "FAIL [setup]: script missing/not executable at $SCRIPT" >&2; exit 1; }

PASS=0; FAIL=0; SKIP=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- build fixtures (skip suite cleanly if the fixture libs are unavailable) ---
if ! python3 - "$TMP" <<'PY'
import sys
tmp = sys.argv[1]
try:
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter
except Exception as exc:
    sys.stderr.write(f"fixture libs unavailable: {exc}\n")
    sys.exit(42)

# 1) happy-path text PDF
c = canvas.Canvas(f"{tmp}/text.pdf")
c.drawString(100, 700, "Hello World from ITEM-10")
c.showPage(); c.save()

# 2) no-text / scanned: a page with NO text drawn -> empty text layer
c = canvas.Canvas(f"{tmp}/blank.pdf")
c.showPage(); c.save()

# 3) encrypted: encrypt the text PDF with a non-empty password
r = PdfReader(f"{tmp}/text.pdf")
w = PdfWriter()
for p in r.pages:
    w.add_page(p)
w.encrypt("s3cret")
with open(f"{tmp}/encrypted.pdf", "wb") as fh:
    w.write(fh)

# 4) corrupt: a .pdf that is not a parseable PDF
with open(f"{tmp}/corrupt.pdf", "w") as fh:
    fh.write("this is definitely not a valid PDF file\n")
PY
then
    echo "SKIP: fixture libs (reportlab/pypdf) unavailable — suite skipped" >&2
    echo "SKIP=1 (no fixtures)"; exit 0
fi

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

echo "== arg guards (exactly one positional path, no flags) =="
expect_rc 1 "no args"
expect_rc 1 "two args"        "$TMP/text.pdf" extra
expect_rc 1 "flag rejected"   --oops
expect_reason "usage" "flag reason" --oops

echo "== happy path (exit 0, UTF-8 text on stdout) =="
expect_rc 0 "text pdf extracts" "$TMP/text.pdf"
OUT="$(bash "$SCRIPT" "$TMP/text.pdf" 2>/dev/null)"
case "$OUT" in
    *"Hello World from ITEM-10"*) echo "PASS: stdout carries the extracted text"; PASS=$((PASS+1)) ;;
    *) echo "FAIL: stdout missing expected text (got: $OUT)" >&2; FAIL=$((FAIL+1)) ;;
esac
# stdout must NOT be empty on success
if [ -n "$OUT" ]; then echo "PASS: happy-path stdout non-empty"; PASS=$((PASS+1))
else echo "FAIL: happy-path stdout empty" >&2; FAIL=$((FAIL+1)); fi

echo "== fail-loud mode (2) missing / corrupt file =="
expect_rc     2 "missing file"              "$TMP/does-not-exist.pdf"
expect_reason "file_error" "missing reason" "$TMP/does-not-exist.pdf"
expect_rc     2 "corrupt file"              "$TMP/corrupt.pdf"
expect_reason "file_error" "corrupt reason" "$TMP/corrupt.pdf"

echo "== fail-loud mode (3) encrypted =="
expect_rc     3 "encrypted pdf"                "$TMP/encrypted.pdf"
expect_reason "encrypted_pdf" "encrypted reason" "$TMP/encrypted.pdf"
# an encrypted PDF must NOT silent-empty exit 0
ENC_OUT="$(bash "$SCRIPT" "$TMP/encrypted.pdf" 2>/dev/null)"; ENC_RC=$?
if [ "$ENC_RC" != "0" ] && [ -z "$ENC_OUT" ]; then echo "PASS: encrypted is non-zero + empty-stdout (not silent-success)"; PASS=$((PASS+1))
else echo "FAIL: encrypted leaked stdout or exited 0 (rc=$ENC_RC)" >&2; FAIL=$((FAIL+1)); fi

echo "== fail-loud mode (4) no text layer / scanned =="
expect_rc     4 "blank/no-text pdf"              "$TMP/blank.pdf"
expect_reason "no_text_layer" "no-text reason"   "$TMP/blank.pdf"
# the whole point of mode 4: NOT exit 0 + empty stdout
NT_OUT="$(bash "$SCRIPT" "$TMP/blank.pdf" 2>/dev/null)"; NT_RC=$?
if [ "$NT_RC" = "4" ] && [ -z "$NT_OUT" ]; then echo "PASS: no-text is exit 4 + empty-stdout (never silent-success)"; PASS=$((PASS+1))
else echo "FAIL: no-text silent-success or wrong rc (rc=$NT_RC, out=$NT_OUT)" >&2; FAIL=$((FAIL+1)); fi

echo
echo "== summary: PASS=$PASS FAIL=$FAIL SKIP=$SKIP =="
[ "$FAIL" -eq 0 ] || exit 1