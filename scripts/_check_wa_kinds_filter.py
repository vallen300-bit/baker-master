"""BAKER_WA_DIRECTOR_FILTER_1 — filter pass for check_wa_director_kinds.sh.

Reads grep output via $WA_CHECK_RAW env var. Emits lines that look like real
`send_whatsapp(` or `send_director_alert(` calls missing `kind=` or
`chat_id=`. False-positive filter:

  - docstring / string-literal / backticked references (any of `, ', " appears
    anywhere before the call on the same line)
  - comments (line stripped starts with `#`)
  - calls that explicitly pass `chat_id=` (non-Director target — only
    meaningful for `send_whatsapp`; `send_director_alert` has no `chat_id=`
    parameter, so a `chat_id=` token cannot legitimately appear on the same
    line as a `send_director_alert(` call without separately failing review)
  - calls that explicitly pass `kind=` (allowlisted send)

Separate file so the bash wrapper can stay free of nested quoting. Heuristic,
not AST — false positives are acceptable per brief.
"""
from __future__ import annotations

import os
import sys

QUOTE_CHARS = ("\"", "'", "`")
CALL_TOKENS = ("send_whatsapp(", "send_director_alert(")


def _earliest_call_idx(content: str) -> int:
    """Return the smallest index at which any tracked call token appears, or
    -1 if none. Lets the prefix-quote heuristic key off the first call so a
    string literal preceding a real call still suppresses correctly."""
    found = [content.find(tok) for tok in CALL_TOKENS]
    found = [i for i in found if i != -1]
    return min(found) if found else -1


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
        idx = _earliest_call_idx(content)
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
