# BRIEF 9A — Environment & API Health Checks

> **For:** Claude Code execution
> **Predecessor:** Brief 8 PASS
> **Successor:** Brief 9B (WhatsApp), Brief 9C (Fireflies)
> **Estimated time:** 5 minutes
> **Modifies code:** NO — read-only checks

---

## OBJECTIVE

Verify that all environment variables, API connections, and data stores are
healthy before running live WhatsApp and Fireflies trigger validation.

## WORKING DIRECTORY

```
cd 01_build
```

All paths below are relative to `01_build/`.

---

## STEP 1 — Check environment variables

```python
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path("config/.env"), override=True)

required = {
    "WASSENGER_API_KEY": os.getenv("WASSENGER_API_KEY", ""),
    "WASSENGER_DEVICE_ID": os.getenv("WASSENGER_DEVICE_ID", ""),
    "FIREFLIES_API_KEY": os.getenv("FIREFLIES_API_KEY", ""),
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    "QDRANT_URL": os.getenv("QDRANT_URL", ""),
    "QDRANT_API_KEY": os.getenv("QDRANT_API_KEY", ""),
    "VOYAGE_API_KEY": os.getenv("VOYAGE_API_KEY", ""),
    "POSTGRES_HOST": os.getenv("POSTGRES_HOST", ""),
    "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
}

missing = [k for k, v in required.items() if not v]
if missing:
    print(f"FAIL — missing env vars: {missing}")
    print("ACTION: Add these to config/.env before proceeding to Brief 9B/9C")
else:
    print(f"PASS — all {len(required)} env vars present")
```

**STOP if FAIL.** Do not proceed to Steps 2-4. Report missing vars to user.

---

## STEP 2 — Wassenger device health

```python
import os, httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path("config/.env"), override=True)

api_key = os.getenv("WASSENGER_API_KEY")
device_id = os.getenv("WASSENGER_DEVICE_ID")

r = httpx.get(
    f"https://api.wassenger.com/v1/devices/{device_id}",
    headers={"Token": api_key},
    timeout=15,
)

if r.status_code != 200:
    print(f"FAIL — Wassenger API returned {r.status_code}")
    print(f"Response: {r.text[:300]}")
else:
    data = r.json()
    device_status = data.get("status", "unknown")
    session_status = data.get("session", {}).get("status", "unknown")
    phone = data.get("phone", "unknown")
    print(f"Device: {phone}")
    print(f"Device status: {device_status}")
    print(f"Session status: {session_status}")
    if device_status == "operative" and session_status == "online":
        print("PASS — Wassenger device operative and online")
    else:
        print(f"FAIL — device={device_status}, session={session_status}")
        print("HUMAN GATE: Dimitry must re-scan WhatsApp Linked Devices if session is offline")
```

**STOP if session is `offline` or `timeout`.** This requires human action (phone re-scan).

---

## STEP 3 — Fireflies API health

```python
import os, httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path("config/.env"), override=True)

api_key = os.getenv("FIREFLIES_API_KEY")

r = httpx.post(
    "https://api.fireflies.ai/graphql",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={"query": "{ user { name email } }"},
    timeout=15,
)

if r.status_code != 200:
    print(f"FAIL — Fireflies API returned {r.status_code}")
    print(f"Response: {r.text[:300]}")
    print("HUMAN GATE: API key may be expired — regenerate at app.fireflies.ai/integrations")
else:
    data = r.json()
    user = data.get("data", {}).get("user", {})
    name = user.get("name", "unknown")
    email = user.get("email", "unknown")
    print(f"Fireflies user: {name} ({email})")
    if name and email:
        print("PASS — Fireflies API responding")
    else:
        print("WARN — API responded but user data empty")
```

**STOP if 401.** This requires human action (new API key).

---

## STEP 4 — Qdrant connectivity

```python
import sys
sys.path.insert(0, ".")
from memory.retriever import SentinelRetriever

try:
    r = SentinelRetriever()
    collections = r.client.get_collections()
    names = [c.name for c in collections.collections]
    print(f"Qdrant collections: {names}")
    expected = ["baker-people", "baker-deals", "baker-projects", "baker-conversations", "baker-whatsapp"]
    missing = [e for e in expected if e not in names]
    if missing:
        print(f"WARN — missing collections: {missing}")
    else:
        print(f"PASS — all {len(expected)} Qdrant collections present")
except Exception as e:
    print(f"FAIL — Qdrant connection error: {e}")
```

---

## STEP 5 — PostgreSQL connectivity

```python
import sys
sys.path.insert(0, ".")
from triggers.state import trigger_state

try:
    wm = trigger_state.get_watermark("whatsapp")
    print(f"WhatsApp watermark: {wm.isoformat()}")
    wm2 = trigger_state.get_watermark("fireflies")
    print(f"Fireflies watermark: {wm2.isoformat()}")
    print("PASS — trigger_state accessible")
except Exception as e:
    print(f"FAIL — trigger_state error: {e}")
```

---

## VERIFICATION SUMMARY

Report results as a table:

| Check | Expected | Result |
|-------|----------|--------|
| Env vars (9 keys) | All present | PASS / FAIL |
| Wassenger device | `operative` + `online` | PASS / FAIL / HUMAN GATE |
| Fireflies API | 200 + user profile | PASS / FAIL / HUMAN GATE |
| Qdrant | 5 collections | PASS / WARN |
| PostgreSQL (trigger_state) | Watermarks readable | PASS / FAIL |

**Gate rule:** ALL must be PASS (or WARN for Qdrant) before proceeding to Brief 9B.

If any check returns HUMAN GATE, report to user with the specific action needed.

---

## STOP CONDITIONS

1. Any missing env var → STOP, report which ones
2. Wassenger session offline → STOP, needs phone re-scan (human gate)
3. Fireflies 401 → STOP, needs new API key (human gate)
4. Qdrant unreachable → STOP, check QDRANT_URL and QDRANT_API_KEY
5. All PASS → proceed to Brief 9B
