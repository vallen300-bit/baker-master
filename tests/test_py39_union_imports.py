"""PY39_UNION_IMPORT_SWEEP_1 — modules must import under the runtime Python (incl. 3.9).

These modules used PEP 604 unions (`X | None`) in annotation positions WITHOUT
`from __future__ import annotations`, so on Python 3.9 the union evaluated at
import time -> `TypeError: unsupported operand type(s) for |: 'type' and
'NoneType'`. CI runs 3.11 so it was green there, but anything imported by a LOCAL
script under 3.9 (the backfills, pollers, CLIs) broke — exactly how it bit us via
memory/store_back (BACKFILL_SENTINEL_HEARTBEAT_FIX_1) and job_heartbeat.

Each module is imported in a subprocess so import side-effects stay isolated.
Pre-fix on 3.9 these fail with the union TypeError; post-fix they import on every
interpreter.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

# The full set fixed in this sweep (6 roots + 2 that surfaced once their deps were
# fixed). Keep alphabetised; add to this list when a new module gets the import.
SWEPT_MODULES = [
    "claimsmax.recharge_report.validator",
    "outputs.dashboard",
    "scripts.recharge_report_cli",
    "tools.ingest.extractors",
    "triggers.exchange_poller",
    "triggers.plaud_trigger",
    "triggers.todoist_client",
    "triggers.youtube_ingest",
]


@pytest.mark.parametrize("mod", SWEPT_MODULES)
def test_module_imports_without_pep604_union_error(mod):
    r = subprocess.run(
        [sys.executable, "-c", f"import {mod}"],
        capture_output=True, text=True, timeout=120,
    )
    assert "unsupported operand type(s) for |" not in r.stderr, (
        f"{mod} still fails the PEP 604 union import on "
        f"{sys.version_info.major}.{sys.version_info.minor}:\n{r.stderr[-600:]}"
    )
    assert r.returncode == 0, f"{mod} failed to import:\n{r.stderr[-800:]}"


def test_swept_modules_have_future_annotations():
    # Belt-and-suspenders: the source files must carry the future-import so a
    # future edit can't silently reintroduce the runtime-eval'd union.
    import importlib.util
    for mod in SWEPT_MODULES:
        spec = importlib.util.find_spec(mod)
        assert spec and spec.origin, f"cannot locate {mod}"
        with open(spec.origin, "r", encoding="utf-8") as fh:
            head = fh.read(4000)
        assert "from __future__ import annotations" in head, (
            f"{mod} ({spec.origin}) is missing 'from __future__ import annotations'"
        )
