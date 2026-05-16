"""BAKER_WA_DIRECTOR_FILTER_1 — filter pass for check_wa_director_kinds.sh.

Reads grep output via $WA_CHECK_RAW env var. Emits lines that look like real
`send_whatsapp(` calls missing `kind=` or `chat_id=`. False-positive filter:

  - docstring / string-literal / backticked references (any of `, ', " appears
    anywhere before `send_whatsapp(` on the same line)
  - comments (line stripped starts with `#`)
  - calls that explicitly pass `chat_id=` (non-Director target)
  - calls that explicitly pass `kind=` (allowlisted send)

Separate file so the bash wrapper can stay free of nested quoting. Heuristic,
not AST — false positives are acceptable per brief.
"""
from __future__ import annotations

import os
import sys

QUOTE_CHARS = ("\"", "'", "`")


def main() -> int:
    raw = os.environ.get("WA_CHECK_RAW", "")
    out: list[str] = []
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _path, _lineno, content = parts
        idx = content.find("send_whatsapp(")
        if idx == -1:
            continue
        prefix = content[:idx]
        if any(ch in prefix for ch in QUOTE_CHARS):
            continue
        stripped = content.lstrip()
        if stripped.startswith("#"):
            continue
        if "chat_id=" in content or "kind=" in content:
            continue
        out.append(line)
    sys.stdout.write("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
