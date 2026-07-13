#!/usr/bin/env bash
# Vetted, read-only PDF text extraction for Researcher tranche-3 item #10.
set -u

usage() {
  printf '%s\n' '{"error":"invalid_arguments","message":"usage: pdf_extract.sh <pdf-path> [start-page] [end-page]"}'
  exit 2
}
[ "$#" -ge 1 ] && [ "$#" -le 3 ] || usage
case "$1" in -*|'') usage ;; esac
PDF_PATH="$1"
START_PAGE="${2:-1}"
END_PAGE="${3:-0}"
case "$START_PAGE" in ''|*[!0-9]*) echo '{"error":"invalid_start_page"}' ; exit 2 ;; esac
case "$END_PAGE" in ''|*[!0-9]*) echo '{"error":"invalid_end_page"}' ; exit 2 ;; esac
PDF_PATH="$PDF_PATH" START_PAGE="$START_PAGE" END_PAGE="$END_PAGE" python3 - <<'PY'
import hashlib, json, os, pathlib, stat, sys

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 1000
MAX_PAGES_PER_CALL = 100
MAX_TEXT_BYTES = 2 * 1024 * 1024

def fail(code, message, **extra):
    payload = {"error": code, "message": message, **extra}
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(2)

path = os.environ["PDF_PATH"]
start = int(os.environ["START_PAGE"])
end_arg = int(os.environ["END_PAGE"])
if start < 1:
    fail("invalid_start_page", "start page must be >= 1")

try:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
except OSError as exc:
    fail("open_failed", "unable to open PDF", detail=str(exc))
try:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        fail("not_regular_file", "input is not a regular file")
    if st.st_size > MAX_BYTES:
        fail("file_too_large", "PDF exceeds 50 MiB", size=st.st_size)
    try:
        real_path = os.readlink(f"/dev/fd/{fd}")
    except OSError:
        if sys.platform == "darwin":
            import fcntl
            # macOS does not expose descriptor targets through /dev/fd.
            try:
                real_path = fcntl.fcntl(fd, 50, b"\0" * 1024).split(b"\0", 1)[0].decode()
            except Exception as exc:
                fail("path_resolution_failed", "unable to resolve opened descriptor", detail=str(exc))
        else:
            fail("path_resolution_failed", "unable to resolve opened descriptor")
    roots = [os.path.realpath(os.path.expanduser("~/bm-researcher")),
             os.path.realpath(os.path.expanduser("~/baker-vault/wiki/research"))]
    if not any(real_path == r or real_path.startswith(r + os.sep) for r in roots):
        fail("path_not_allowed", "PDF is outside an approved researcher input root")
    try:
        from pypdf import PdfReader
    except Exception as exc:
        fail("dependency_missing", "pypdf is required", detail=str(exc))
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        with os.fdopen(os.dup(fd), "rb", closefd=True) as held:
            reader = PdfReader(held, strict=True)
            total = len(reader.pages)
            if total > MAX_PAGES:
                fail("page_count_exceeded", "PDF exceeds 1000 pages", pages=total)
            end = end_arg or total
            if end < start or end > total or end - start + 1 > MAX_PAGES_PER_CALL:
                fail("page_range_invalid", "page range must be within the document and <= 100 pages",
                     pages=total, start_page=start, end_page=end)
            pages = []
            text_bytes = 0
            image_only = []
            for number in range(start, end + 1):
                text = reader.pages[number - 1].extract_text() or ""
                encoded = text.encode("utf-8")
                if text_bytes + len(encoded) > MAX_TEXT_BYTES:
                    fail("text_limit_exceeded", "extracted text exceeds 2 MiB", page=number)
                text_bytes += len(encoded)
                if not text.strip():
                    image_only.append(number)
                pages.append({"page": number, "text": text})
    except Exception as exc:
        fail("pdf_parse_failed", "unable to parse or extract PDF", detail=str(exc))
finally:
    os.close(fd)

print(json.dumps({"source": {"basename": pathlib.Path(path).name, "sha256": digest.hexdigest()},
                  "page_count": total, "pages": pages,
                  "image_only_pages": image_only,
                  "warning": "image_only_pages_present" if image_only else None},
                 ensure_ascii=False))
PY
