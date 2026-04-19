# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** Mac Mini Step 7 prep items 1-4 COMPLETE (deploy key live + remote swapped + flock tested + auth verified). Items 5-6 deferred until B1's Step 7 code merged. **PR #16 merged at `20370e7e` — Step 7 code now on main.**
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — final Mac Mini infra bolt-on

---

## Task: MAC_MINI_LAUNCHD_PROVISION — Items 5-6 from the original prep brief

### Why

Step 7 code is merged. `kbl/steps/step7_commit.py` is ready. But Mac Mini needs to:
- **Poll PG for signals** at `status='awaiting_commit'` + unrealized cross-links → trigger Step 7
- **Heartbeat** to Neon so Baker can detect when Mac Mini is offline

Both run via launchd on Mac Mini. Without them, Step 7 code exists but sits dormant — pipeline doesn't complete on the vault.

### Scope

**IN — provision two launchd plists on Mac Mini (via SSH over Tailscale):**

### Item 5 — Poller plist: `com.brisen.baker.poller.plist`

**Purpose:** Every 60 seconds, poll Neon for signals in `status='awaiting_commit'` OR unrealized cross-links. For each, invoke Step 7's `commit(signal_id, conn)` or equivalent. Uses the Python `fcntl` in-process lock (B1's Step 7 code already has this) — no external `flock` binary needed.

**Script location:** `~/baker-pipeline/poller.py` on Mac Mini (create the `baker-pipeline` dir).

**Script body — thin, calls into the merged Step 7 code:**

```python
#!/usr/bin/env python3
"""Mac Mini poller — claims awaiting_commit signals + invokes Step 7."""
import os
import sys
import psycopg2
from contextlib import closing

# Ensure Step 7 code is on PYTHONPATH — clone of baker-master under ~/baker-pipeline-repo
sys.path.insert(0, os.path.expanduser("~/baker-pipeline-repo"))
from kbl.steps.step7_commit import commit as step7_commit
from kbl.exceptions import CommitError, VaultLockTimeoutError

DATABASE_URL = os.environ["DATABASE_URL"]
BAKER_VAULT_PATH = os.environ["BAKER_VAULT_PATH"]  # ~/baker-vault on Mac Mini
BATCH_SIZE = int(os.environ.get("MAC_MINI_POLLER_BATCH", "5"))

def main():
    with closing(psycopg2.connect(DATABASE_URL)) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM signal_queue
                WHERE status = 'awaiting_commit'
                ORDER BY id
                LIMIT %s
            """, (BATCH_SIZE,))
            signal_ids = [r[0] for r in cur.fetchall()]

        for sid in signal_ids:
            try:
                step7_commit(sid, conn)
                conn.commit()
                print(f"[poller] committed sig={sid}")
            except VaultLockTimeoutError:
                conn.rollback()
                print(f"[poller] lock timeout sig={sid}; will retry next tick")
            except CommitError as e:
                conn.rollback()
                print(f"[poller] commit_failed sig={sid}: {e}")
            except Exception as e:
                conn.rollback()
                print(f"[poller] UNEXPECTED sig={sid}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
```

**Plist path:** `~/Library/LaunchAgents/com.brisen.baker.poller.plist`

**Plist content:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.brisen.baker.poller</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/dimitry/baker-pipeline/poller.py</string>
  </array>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DATABASE_URL</key>
    <string>PLACEHOLDER_SEE_DIRECTOR</string>
    <key>BAKER_VAULT_PATH</key>
    <string>/Users/dimitry/baker-vault</string>
    <key>MAC_MINI_POLLER_BATCH</key>
    <string>5</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/dimitry/baker-pipeline/poller.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/dimitry/baker-pipeline/poller.err.log</string>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

**Escalation to Director:** need `DATABASE_URL` (Neon connection string) populated. Leave `PLACEHOLDER_SEE_DIRECTOR` until you ask.

**Also required:** clone baker-master at `~/baker-pipeline-repo` so the poller can import Step 7 code:
```bash
cd ~
git clone git@github.com:vallen300-bit/baker-master.git baker-pipeline-repo
```

(Use Director's default SSH key for this clone; the deploy key is baker-vault-scoped only. OR: configure a second SSH alias `github-baker-master` with another deploy key — flag to Director if you think that's cleaner.)

### Item 6 — Heartbeat plist: `com.brisen.baker.heartbeat.plist`

**Purpose:** Every 60s, INSERT a row into `mac_mini_heartbeat(created_at)` in Neon. Baker's `/health` endpoint exposes the latest row's age. Alert threshold: >5 min WARN, >15 min critical.

**Migration needed first:**

```sql
CREATE TABLE IF NOT EXISTS mac_mini_heartbeat (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    host TEXT NOT NULL,
    version TEXT
);
CREATE INDEX IF NOT EXISTS idx_mac_mini_heartbeat_created_at
    ON mac_mini_heartbeat (created_at DESC);
```

Add as `migrations/20260419_mac_mini_heartbeat.sql` in the baker-master repo, open a small PR (#17) — B2 reviews, merge, Render applies via existing migration runner. If schema drift is small enough for a direct-to-main commit by AI Head, flag it; otherwise follow the PR route.

**Script location:** `~/baker-pipeline/heartbeat.py` on Mac Mini.

**Script body:**

```python
#!/usr/bin/env python3
"""Mac Mini heartbeat — insert row to mac_mini_heartbeat every tick."""
import os
import socket
import psycopg2
from contextlib import closing

DATABASE_URL = os.environ["DATABASE_URL"]

def main():
    hostname = socket.gethostname()
    with closing(psycopg2.connect(DATABASE_URL)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO mac_mini_heartbeat (host, version) VALUES (%s, %s)",
                (hostname, "baker-pipeline-1")
            )
        conn.commit()

if __name__ == "__main__":
    main()
```

**Plist path:** `~/Library/LaunchAgents/com.brisen.baker.heartbeat.plist`

**Plist content — similar shape:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.brisen.baker.heartbeat</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/dimitry/baker-pipeline/heartbeat.py</string>
  </array>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DATABASE_URL</key>
    <string>PLACEHOLDER_SEE_DIRECTOR</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/dimitry/baker-pipeline/heartbeat.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/dimitry/baker-pipeline/heartbeat.err.log</string>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

### Sequence on Mac Mini

```bash
# On Mac Mini via ssh macmini:
mkdir -p ~/baker-pipeline
# (clone baker-pipeline-repo with Director's key OR use 2nd deploy key)
git clone git@github.com:vallen300-bit/baker-master.git ~/baker-pipeline-repo

# Install psycopg2 if absent
/usr/bin/python3 -m pip install --user psycopg2-binary

# Write scripts
cat > ~/baker-pipeline/poller.py << 'EOF'
# ... (contents above)
EOF
cat > ~/baker-pipeline/heartbeat.py << 'EOF'
# ... (contents above)
EOF
chmod +x ~/baker-pipeline/*.py

# Write plists (with real DATABASE_URL from Director)
# Load into launchd
launchctl load ~/Library/LaunchAgents/com.brisen.baker.poller.plist
launchctl load ~/Library/LaunchAgents/com.brisen.baker.heartbeat.plist

# Verify
launchctl list | grep brisen
# Expected: two entries, both PID-listed (not just status 0)
```

### Director escalations

1. **`DATABASE_URL`** — the Neon connection string. Get from Render env vars or Director's secrets vault. Paste into both plists' `EnvironmentVariables` dict.
2. **Second SSH key for baker-master clone on Mac Mini?** Director-default key works for the read-only clone; cleaner would be a second deploy key. Flag preference. **Lean: reuse Director's key** (read-only access, no push needed from the pipeline-repo clone).
3. **`mac_mini_heartbeat` migration** — PR or direct-to-main? It's 10 lines, purely additive, zero-risk. **Lean: AI Head opens as PR #17 with a one-line description, B2 fast-APPROVE, merge.** Structure integrity over speed.

### CHANDA pre-push

- **Q1 Loop Test:** infrastructure glue, not pipeline logic. No Leg touched. Pass.
- **Q2 Wish Test:** serves wish — without this, Step 7 code doesn't run on Mac Mini. Pass.
- **Inv 9:** this is the operational path — Mac Mini polls + writes. Aligned.

### Timeline

~30-45 min once `DATABASE_URL` + migration answered:
- ~10 min: write scripts + plists
- ~5 min: clone baker-pipeline-repo + install psycopg2
- ~5 min: launchctl load + verify entries
- ~10 min: smoke test (force an `awaiting_commit` signal through, watch poller log, verify vault commit lands)

### Dispatch back

> B3 MAC_MINI_LAUNCHD_PROVISION COMPLETE — com.brisen.baker.poller + com.brisen.baker.heartbeat loaded on Mac Mini, `launchctl list` shows both active. Smoke test: signal ID <N> reached `completed` state after poller tick. Mac Mini fully operational. Phase 1 is live on the vault.

---

*Posted 2026-04-19 by AI Head. After this, Phase 1 Cortex T3 runs end-to-end. New ACTIVE signals begin flowing through the 7-step pipeline on next ingestion.*
