#!/usr/bin/env python3
"""lease_heartbeat_emitter_selftest.py — CASE_ONE_P2_LIVENESS_LIFECYCLE_1 (P2.2).

Round-trip smoke test for scripts/lease_heartbeat_emitter.sh WITHOUT a real
daemon: spins a mock HTTP server that records the request + returns a chosen
status, runs the emitter as a subprocess against it, and asserts it POSTs the
right renew (method/path/header) and handles each daemon outcome tolerantly.

This is the emitter half of the brief's "fleet round-trip" check (emitter renews
the lease). The "killed emitter → missing heartbeat" half is proved daemon-side
by test_case_one_p2_liveness_lifecycle::test_ttl_expiry_* (a lease with no renew
goes stale/assigned-but-dead).

Self-contained, no network, no pytest needed:  python3 <this>  → exit 0 = pass.
"""
import http.server
import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
EMITTER = os.path.join(HERE, "lease_heartbeat_emitter.sh")

_requests = []


def _make_handler(status, body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            _requests.append({
                "path": self.path,
                "key": self.headers.get("X-Terminal-Key"),
                "method": "POST",
            })
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):  # silence
            pass
    return H


def _run_emitter(lab_url):
    env = dict(os.environ)
    env["BAKER_ROLE"] = "b1"
    env["BRISEN_LAB_TERMINAL_KEY"] = "b1-key"
    env["LAB_URL"] = lab_url
    # unique lock per case so back-to-back runs never collide on the mutex
    env["LOCK_DIR"] = f"/tmp/lease_hb_selftest_{os.getpid()}_{len(_requests)}.lock"
    return subprocess.run(["/bin/bash", EMITTER], env=env,
                          capture_output=True, text=True, timeout=30)


def _case(name, status, body, expect_path="/lease/b1/heartbeat"):
    _requests.clear()
    srv = http.server.HTTPServer(("127.0.0.1", 0), _make_handler(status, body))
    port = srv.server_address[1]
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    r = _run_emitter(f"http://127.0.0.1:{port}")
    t.join(timeout=5)
    srv.server_close()
    assert r.returncode == 0, f"[{name}] emitter exit {r.returncode}: {r.stderr}"
    assert len(_requests) == 1, f"[{name}] expected 1 request, got {_requests}"
    req = _requests[0]
    assert req["method"] == "POST", f"[{name}] method {req['method']}"
    assert req["path"] == expect_path, f"[{name}] path {req['path']}"
    assert req["key"] == "b1-key", f"[{name}] key {req['key']}"
    print(f"[PASS] {name}: POST {req['path']} (X-Terminal-Key ok), exit 0")


def main():
    # 200: lease renewed on cadence.
    _case("renew-200", 200, {"lease": {"owner_seat": "b1"}, "cadence_s": 60})
    # 404: seat idle (no active lease) — tolerant, still exit 0.
    _case("idle-404", 404, {"detail": "no_lease_for_seat"})
    # 503: transient daemon error — tolerant, exit 0 (launchd must not back off).
    _case("transient-503", 503, {"detail": "lease_renew_failed"})
    print("\nAll emitter round-trip cases passed.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        sys.exit(1)
