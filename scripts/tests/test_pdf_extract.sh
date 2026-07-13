#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/pdf_extract.sh"
[ -x "$SCRIPT" ] || { echo 'FAIL: script not executable'; exit 1; }
PASS=0; FAIL=0
expect_reason() { local reason="$1"; shift; out="$(bash "$SCRIPT" "$@" 2>/dev/null)"; if printf '%s' "$out" | grep -q '"error"[[:space:]]*:[[:space:]]*"'"$reason"'"'; then PASS=$((PASS+1)); else echo "FAIL: $reason => $out"; FAIL=$((FAIL+1)); fi; }
expect_json_error() { local reason="$1"; shift; out="$(bash "$SCRIPT" "$@" 2>/dev/null)"; if printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("error")==sys.argv[1] else 1)' "$reason"; then PASS=$((PASS+1)); else echo "FAIL: JSON error $reason => $out"; FAIL=$((FAIL+1)); fi; }
expect_reason invalid_start_page /Users/dimitry/bm-researcher/no.pdf 0
expect_reason path_not_allowed /etc/hosts
expect_json_error invalid_arguments
expect_json_error invalid_arguments -

# Static assertions lock the race-free design into the wrapper itself.
grep -q 'O_NOFOLLOW' "$SCRIPT" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
grep -q 'PdfReader(held' "$SCRIPT" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
if python3 -c 'import pypdf' 2>/dev/null; then
  tmp="/Users/dimitry/bm-researcher/.item10-sample.pdf"
  python3 - "$tmp" <<'PY'
from pathlib import Path
from reportlab.pdfgen import canvas
import sys
p=Path(sys.argv[1]); p.parent.mkdir(exist_ok=True)
c=canvas.Canvas(str(p)); c.drawString(72,720,'item10 page one'); c.showPage(); c.showPage(); c.save()
PY
  out="$(bash "$SCRIPT" "$tmp")"; printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["page_count"]==2 and d["image_only_pages"]==[2] and d["source"]["basename"]==".item10-sample.pdf"' && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
  expect_json_error page_range_invalid "$tmp" 1 101
  printf 'not a PDF' > "$tmp"
  expect_json_error pdf_parse_failed "$tmp"
  rm -f "$tmp"
  python3 - "$tmp" <<'PY'
from reportlab.pdfgen import canvas
import sys
p=sys.argv[1]
c=canvas.Canvas(p); c.drawString(72,720,'item10 page one'); c.save()
PY
  ln -sf /etc/hosts /Users/dimitry/bm-researcher/.item10-symlink.pdf
  expect_reason open_failed /Users/dimitry/bm-researcher/.item10-symlink.pdf
  rm -f /Users/dimitry/bm-researcher/.item10-symlink.pdf
  python3 - "$tmp" <<'PY'
import sys
with open(sys.argv[1], 'ab') as f:
    f.truncate(50 * 1024 * 1024 + 1)
PY
  expect_json_error file_too_large "$tmp"
  rm -f "$tmp"
else
  echo 'SKIP: pypdf unavailable';
fi
echo "pdf_extract tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
