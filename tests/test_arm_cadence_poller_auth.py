"""BUS_HEALTH_401_POLLER_KEY_1 — regression coverage for the ARM cadence
poller's terminal-key auth.

/api/bus_health went authed (bare=401, X-Terminal-Key=200). The cadence
snapshot poller previously hit it bare, so every snapshot was 'degraded'. These
tests pin the wiring that keys it — hermetic (no network, no launchctl, no model):

  1. worker builds an X-Terminal-Key header from a resolved key
  2. plist template carries the seat + key placeholders
  3. `install --dry-run` deploys the key helper next to the worker
  4. `install --check` FAILs loudly when the installed plist carries no key
"""
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POLLER = REPO / "scripts" / "arm_cadence_poll.sh"
INSTALL = REPO / "scripts" / "install_arm_cadence_job.sh"
TEMPLATE = REPO / "scripts" / "launchd" / "com.baker.arm-cadence.plist"


def test_worker_wires_terminal_key_header():
    src = POLLER.read_text()
    # key resolved via the standard helper (env -> cache -> 1P) ...
    assert "brisen_lab_read_terminal_key" in src
    assert "ARM_CADENCE_KEY" in src
    # ... and passed as a single, correctly-quoted curl header (array, not inline
    # ${KEY:+...} which would word-split the "Header: value" space).
    assert "X-Terminal-Key:" in src
    assert "AUTH_HEADER=(" in src
    assert 'AUTH_HEADER[@]+"${AUTH_HEADER[@]}"' in src


def test_worker_is_bash32_safe_and_syntax_clean():
    # macOS /bin/bash is 3.2; `set -u` + a bare "${arr[@]}" on an empty array
    # errors. The guarded idiom must keep bash -n clean.
    r = subprocess.run(["bash", "-n", str(POLLER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_plist_template_has_seat_and_key_placeholders():
    body = TEMPLATE.read_text()
    assert "__KEY__" in body
    assert "__SEAT__" in body
    assert "ARM_CADENCE_KEY" in body
    assert "ARM_CADENCE_SEAT" in body


def test_dryrun_install_deploys_key_helper(tmp_path):
    deploy = tmp_path / "deploy"
    env = dict(os.environ, ARM_CADENCE_DRYRUN="1", ARM_CADENCE_DEPLOY_DIR=str(deploy))
    r = subprocess.run(["bash", str(INSTALL)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert (deploy / "arm_cadence_poll.sh").exists()
    # the helper must ship alongside the worker so the deployed poller can fall
    # back to the key cache if the plist env is ever cleared.
    assert (deploy / "brisen_lab_terminal_key.sh").exists()


def test_check_fails_when_installed_plist_has_no_key(tmp_path):
    # Build a fake $HOME with a keyless installed plist; --check must emit the
    # specific auth-regression FAIL line (other FAILs are expected noise here).
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    body = TEMPLATE.read_text()
    for a, b in (
        ("__WORKER_PATH__", str(home / "w.sh")),
        ("__LABEL__", "com.baker.arm-cadence"),
        ("__CADENCE__", "1800"),
        ("__LOG__", str(home / "l")),
        ("__ERRLOG__", str(home / "e")),
        ("__SNAP_DIR__", str(home / "snap")),
        ("__CADENCE_LOG__", str(home / "cl")),
        ("__SEAT__", "arm"),
        ("__KEY__", ""),  # <-- the regression: no embedded key
    ):
        body = body.replace(a, b)
    (home / "Library" / "LaunchAgents" / "com.baker.arm-cadence.plist").write_text(body)

    env = dict(os.environ, HOME=str(home))
    r = subprocess.run(
        ["bash", str(INSTALL), "--check"], capture_output=True, text=True, env=env
    )
    assert r.returncode != 0
    assert "no embedded ARM_CADENCE_KEY" in r.stdout
