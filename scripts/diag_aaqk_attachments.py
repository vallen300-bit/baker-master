"""M365_GRAPH_ATTACHMENT_ID_FORM_FIX_1 — read-only AAQk attachment diagnostic.

The attempt-then-fallback fix (PR #422) was gated on test-shaped AC1; the live
Render run disproved the theory — both native and ImmutableId by-id fetches fail
with HTTPError on the 6 AAQk ids, and GraphClient swallows the status code (logs
only the exception type). This probe captures the ACTUAL HTTP status + body
snippet for each candidate strategy so we can disambiguate 400 (malformed id) vs
404 (not found / wrong namespace) vs 403 (perm), and test translateExchangeIds.

READ-ONLY. No DB writes, no persistence — pure GET/POST probes against Graph.
Runs on the deployed baker-master env (GraphClient.is_ready() gate); refuses on a
dormant box. Uses the same app token the live poller uses; raw requests so the
status_code + body are visible (unlike GraphClient.get which returns None).

Run on Render one-off:
  python3 scripts/diag_aaqk_attachments.py --ids '<id1>,<id2>,...'
  python3 scripts/diag_aaqk_attachments.py --ids-file ids.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import requests  # noqa: E402

_PREFER = {"Prefer": 'IdType="ImmutableId"'}


def _load_ids(args) -> list[str]:
    ids: list[str] = []
    if args.ids:
        ids.extend(p.strip() for p in args.ids.split(",") if p.strip())
    if args.ids_file:
        ids.extend(
            ln.strip() for ln in Path(args.ids_file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        )
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _probe(token: str, method: str, url: str, headers: dict | None = None, body: dict | None = None) -> str:
    """One raw request; returns a compact 'STATUS — body-snippet' string. Never raises."""
    h = {"Authorization": f"Bearer {token}"}
    if headers:
        h.update(headers)
    try:
        if method == "GET":
            r = requests.get(url, headers=h, timeout=15)
        else:
            h["Content-Type"] = "application/json"
            r = requests.post(url, headers=h, json=body, timeout=15)
        snippet = (r.text or "")[:300].replace("\n", " ")
        return f"{r.status_code} — {snippet}"
    except Exception as e:  # noqa: BLE001
        return f"EXC {type(e).__name__}: {e}"


def run(ids: list[str]) -> int:
    if not ids:
        print("no ids supplied (--ids / --ids-file)", file=sys.stderr)
        return 2

    from kbl.graph_client import GraphClient
    from config.settings import GraphConfig

    client = GraphClient(GraphConfig())
    if not client.is_ready():
        print("GraphClient DORMANT (is_ready=False) — run on deployed baker-master env.", file=sys.stderr)
        return 3
    token = client._acquire_token()
    if not token:
        print("token acquisition failed (is_ready true but no token).", file=sys.stderr)
        return 4

    user = client.cfg.mail_user
    base = client.cfg.base_url  # https://graph.microsoft.com/v1.0

    for n, mid in enumerate(ids, 1):
        enc = quote(mid, safe="")
        print(f"\n===== id #{n} (len={len(mid)}) {mid[:20]}…{mid[-12:]} =====")
        # 1. Does the MESSAGE itself resolve? (isolates message vs /attachments sub-path)
        msg_url = f"{base}/users/{user}/messages/{enc}?$select=id,hasAttachments,parentFolderId"
        print(f"  [msg native    ] {_probe(token, 'GET', msg_url)}")
        print(f"  [msg immutable  ] {_probe(token, 'GET', msg_url, _PREFER)}")
        # 2. The /attachments sub-path (the failing call).
        att_url = f"{base}/users/{user}/messages/{enc}/attachments?$select=id,name,contentType,size,isInline&$top=50"
        print(f"  [att native    ] {_probe(token, 'GET', att_url)}")
        print(f"  [att immutable  ] {_probe(token, 'GET', att_url, _PREFER)}")
        # 3. translateExchangeIds: can Graph convert this id to a REST/immutable id?
        #    Try both common source types so the body tells us which namespace it is.
        for src in ("RestId", "EwsId", "RestImmutableEntryId"):
            tx_url = f"{base}/users/{user}/translateExchangeIds"
            tx_body = {
                "inputIds": [mid],
                "sourceIdType": src,
                "targetIdType": "RestImmutableEntryId",
            }
            print(f"  [translate {src:<20}] {_probe(token, 'POST', tx_url, body=tx_body)}")

    print("\n(diagnostic complete — read-only, nothing written)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only AAQk attachment HTTP-status diagnostic.")
    ap.add_argument("--ids", help="comma-separated Graph message ids")
    ap.add_argument("--ids-file", help="file with one id per line (# comments ok)")
    args = ap.parse_args()
    return run(_load_ids(args))


if __name__ == "__main__":
    raise SystemExit(main())
