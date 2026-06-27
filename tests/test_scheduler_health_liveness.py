from __future__ import annotations


def test_scheduler_liveness_uses_recent_execution_when_local_object_empty(monkeypatch):
    import outputs.dashboard as dash

    monkeypatch.setattr(dash, "get_scheduler_status", lambda: {"running": False, "job_count": 0})

    class _State:
        def seconds_since_last_scheduler_execution(self):
            return 5

    import triggers.state as state_mod
    monkeypatch.setattr(state_mod, "trigger_state", _State())

    running, job_count, exec_age = dash._scheduler_live_from_status()
    assert running is True
    assert job_count == 0
    assert exec_age == 5


def test_scheduler_liveness_stays_false_without_recent_execution(monkeypatch):
    import outputs.dashboard as dash

    monkeypatch.setattr(dash, "get_scheduler_status", lambda: {"running": False, "job_count": 0})

    class _State:
        def seconds_since_last_scheduler_execution(self):
            return 999

    import triggers.state as state_mod
    monkeypatch.setattr(state_mod, "trigger_state", _State())

    running, job_count, exec_age = dash._scheduler_live_from_status()
    assert running is False
    assert job_count == 0
    assert exec_age == 999
