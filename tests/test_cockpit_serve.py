from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from orchestrator import cockpit_serve as cs


def test_project_code_allowlist_rejects_path_escape():
    assert cs.normalize_project_code("bb-auk-001") == "BB-AUK-001"
    for bad in ("../BB-AUK-001", "BB/AUK/001", "BB-AUK-001.html", "BBAUK001"):
        try:
            cs.normalize_project_code(bad)
            raise AssertionError(f"{bad} should have failed")
        except ValueError:
            pass


def test_fetch_cockpit_html_picks_latest_dashboard_and_caches(monkeypatch):
    cs.clear_cache()
    calls: list[str] = []

    def fake_github_json(path: str):
        calls.append(path)
        if path.endswith("/BB-AUK-001"):
            return [
                {
                    "type": "file",
                    "name": "dashboard-v1.html",
                    "path": path + "/dashboard-v1.html",
                },
                {
                    "type": "file",
                    "name": "dashboard-v2-pattern-e.html",
                    "path": path + "/dashboard-v2-pattern-e.html",
                },
                {
                    "type": "file",
                    "name": "mockup-v9.html",
                    "path": path + "/mockup-v9.html",
                },
            ]
        if path.endswith("/dashboard-v2-pattern-e.html"):
            return {
                "type": "file",
                "content": base64.b64encode(b"<html>cockpit</html>").decode("ascii"),
            }
        raise AssertionError(path)

    monkeypatch.setattr(cs, "_github_json", fake_github_json)
    first = cs.fetch_cockpit_html("BB-AUK-001")
    second = cs.fetch_cockpit_html("BB-AUK-001")

    assert first is second
    assert first.project_code == "BB-AUK-001"
    assert first.path.endswith("dashboard-v2-pattern-e.html")
    assert first.html == "<html>cockpit</html>"
    assert calls == [
        "_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001",
        "_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v2-pattern-e.html",
    ]
    cs.clear_cache()


def test_cockpit_route_gate_path_and_cookie(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("ARRIVALS_BOARD_PIN", "123456")
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(
        cs,
        "fetch_cockpit_html",
        lambda code: cs.CockpitHtml(
            project_code=code,
            path="_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v2-pattern-e.html",
            html="<html><title>Cockpit</title><body>Real cockpit</body></html>",
        ),
    )
    client = TestClient(dashboard.app, base_url="https://testserver")

    assert client.get("/cockpit/BB-AUK-001").status_code == 401
    assert client.get("/cockpit/BB.AUK.001", headers={"X-Baker-Key": "test-key"}).status_code == 404

    keyed = client.get("/cockpit/BB-AUK-001", headers={"X-Baker-Key": "test-key"})
    assert keyed.status_code == 200
    assert "Real cockpit" in keyed.text
    assert keyed.headers["X-Baker-Cockpit-Source"].endswith("dashboard-v2-pattern-e.html")

    cookie_client = TestClient(dashboard.app, base_url="https://testserver")
    token = dashboard._arrivals_board_pin_token("123456")
    cookie_resp = cookie_client.get(
        "/cockpit/BB-AUK-001",
        headers={"Cookie": f"arrivals_board_access={token}"},
    )
    assert cookie_resp.status_code == 200
    assert "Real cockpit" in cookie_resp.text


def test_cockpit_route_unknown_returns_404(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)

    def missing(_code: str):
        raise cs.CockpitNotFound("missing")

    monkeypatch.setattr(cs, "fetch_cockpit_html", missing)
    client = TestClient(dashboard.app, base_url="https://testserver")
    resp = client.get("/cockpit/NO-FILE-001", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 404
