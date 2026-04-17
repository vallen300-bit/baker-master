"""Mac Mini → Render liveness signal.

Sole owner of the `mac_mini_heartbeat` key in kbl_runtime_state per
R1.S7 (pipeline_tick does NOT write it). Invoked every 30 min by the
dedicated LaunchAgent `com.brisen.kbl.heartbeat`.

Render-side sentinel polls the key every 15 min; >30 min stale → CRITICAL
alert (component='heartbeat_stale') through existing dedupe.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from kbl.runtime_state import set_state


def main() -> int:
    set_state(
        "mac_mini_heartbeat",
        datetime.now(timezone.utc).isoformat(),
        updated_by="heartbeat",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
