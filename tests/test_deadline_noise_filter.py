"""DEADLINE_SIGNAL_HYGIENE_1 Scope A tests — pre-classifier noise filter.

Covers:
  T1. is_noise() True positives — SaaS / promo / training / billing / delivery
  T2. is_noise() True negatives — concrete matter language must pass through
  T3. is_noise() defensive — empty / None description
  T4. insert_deadline() rejects noise pre-classifier (no DB row, returns None)
  T5. Classifier threshold raise — best_score == 2 no longer returns a match
  T6. Threshold proof — best_score == 3 still returns a match
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# T1 — known-noise structural signatures must match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    [
        "Slack subscription renewal",
        "Subscribe to Bloomberg.com for daily news",
        "Register for AML analysis course",
        "Special subscription offer for Reuters readers",
        "Make payment to American Express",
        # M1 tightened — must still match real consumer logistics.
        "Amazon delivery scheduled for tomorrow",
        "Delivery of your package on Friday",
        "Package out for delivery",
        # M2 — credit-card statement billing (kept as noise).
        "Credit card payment due 25th",
        "Credit card statement Apr 2026",
        "Mother's Day gifts",
        "Discuss Q1/YTD and forecast",
        "20% discount on premium plan",
    ],
)
def test_is_noise_true_positives(description):
    from kbl.noise_patterns import is_noise

    assert is_noise(description) is True, (
        f"expected NOISE for: {description}"
    )


# ---------------------------------------------------------------------------
# T2 — concrete matter language must pass through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    [
        "Cupial settlement chase",
        "Sign Aukera term sheet by Friday",
        "Oskolkov capital call due 2026-05-20",
        "Hagenauer claim filing deadline",
        "Review MOHG draft amendment",
        "Send Wertheimer counter-proposal",
        "Eastdil pitch meeting prep",
        # 2026-05-13 REQUEST_CHANGES regression cases (M1 + M2):
        # legitimate deal-doc nouns commonly preceded by "delivery of"
        # MUST pass the noise filter.
        "Delivery of closing documents to notary",
        "Delivery of title deed by Friday",
        "Delivery of guarantee letter to bank",
        "Delivery of executed share purchase agreement",
        # M2 — commercial invoices (Balgerstrasse / Cupial / Heidenauer)
        # MUST pass through.
        "Pay Heidenauer invoice 2024-07",
        "Process Cupial commercial invoice 1184-A",
        "Approve Balgerstrasse contractor invoice payment",
        "Invoice payment due for general contractor",
    ],
)
def test_is_noise_true_negatives(description):
    from kbl.noise_patterns import is_noise

    assert is_noise(description) is False, (
        f"expected NOT-NOISE for: {description}"
    )


# ---------------------------------------------------------------------------
# T3 — defensive: empty / None
# ---------------------------------------------------------------------------


def test_is_noise_handles_empty_and_none():
    from kbl.noise_patterns import is_noise

    assert is_noise(None) is False
    assert is_noise("") is False
    assert is_noise("   ") is False


# ---------------------------------------------------------------------------
# T4 — insert_deadline() rejects noise pre-classifier (no INSERT)
# ---------------------------------------------------------------------------


class _RecordingCursor:
    def __init__(self):
        self.statements: list[str] = []
        self.fetchone_result = None

    def execute(self, sql, params=None):
        self.statements.append(sql)

    def fetchone(self):
        return self.fetchone_result

    def close(self):
        pass


class _RecordingConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_insert_deadline_rejects_noise_no_insert(monkeypatch):
    from datetime import datetime, timezone

    from models import deadlines

    cur = _RecordingCursor()
    conn = _RecordingConn(cur)
    monkeypatch.setattr(deadlines, "get_conn", lambda: conn)
    monkeypatch.setattr(deadlines, "put_conn", lambda c: None)

    result = deadlines.insert_deadline(
        description="Slack subscription renewal",
        due_date=datetime.now(timezone.utc),
        source_type="email",
        confidence="high",
    )
    assert result is None
    assert not any("INSERT INTO deadlines" in s for s in cur.statements), (
        f"expected no INSERT, got: {cur.statements}"
    )
    assert conn.committed is False


def test_insert_deadline_passes_through_concrete_language(monkeypatch):
    """Sanity check: a matter-language deadline reaches the INSERT path."""
    from datetime import datetime, timezone

    from models import deadlines

    cur = _RecordingCursor()
    cur.fetchone_result = (12345,)
    conn = _RecordingConn(cur)
    monkeypatch.setattr(deadlines, "get_conn", lambda: conn)
    monkeypatch.setattr(deadlines, "put_conn", lambda c: None)
    monkeypatch.setattr(
        deadlines, "_deadline_dedup_check", lambda *a, **kw: None
    )

    result = deadlines.insert_deadline(
        description="Cupial settlement chase",
        due_date=datetime.now(timezone.utc),
        source_type="manual",
        confidence="high",
    )
    assert result == 12345
    assert any("INSERT INTO" in s for s in cur.statements), (
        f"expected INSERT, got: {cur.statements}"
    )


# ---------------------------------------------------------------------------
# T5 + T6 — classifier threshold raised from >=1 to >=3
# ---------------------------------------------------------------------------


def test_classifier_threshold_raised_score_two_no_match(monkeypatch):
    """A single keyword + a partial-person match (score=2) used to pass with
    the old >=1 threshold but must now be rejected by the new >=3 threshold."""
    from orchestrator import pipeline

    # Fake store that yields one matter with one keyword + one person partial.
    class _FakeStore:
        def get_matters(self, status="active"):
            return [
                {
                    "matter_name": "TestMatter",
                    "keywords": ["unicornword"],
                    "people": ["Aleksei Oskolkov"],
                }
            ]

    # Search text contains the keyword (score +2) and the partial person
    # name "alek" (score +1, ≥4 chars). Total score = 3. We want to verify
    # the threshold proof from the OTHER direction: weaker text scoring
    # exactly 2 should return None.
    res_low = pipeline._match_matter_slug(
        "unicornword by itself", "", _FakeStore()
    )
    assert res_low is None, (
        "score=2 (single keyword hit, no person match) must NOT match under "
        f"the >=3 threshold; got {res_low}"
    )


def test_classifier_threshold_raised_score_three_matches(monkeypatch):
    """A keyword hit (2pt) + a person-partial hit (1pt) = 3 → match returned."""
    from orchestrator import pipeline

    class _FakeStore:
        def get_matters(self, status="active"):
            return [
                {
                    "matter_name": "TestMatter",
                    "keywords": ["unicornword"],
                    "people": ["Aleksei Oskolkov"],
                }
            ]

    res = pipeline._match_matter_slug(
        "unicornword and aleksei together",
        "",
        _FakeStore(),
    )
    assert res == "TestMatter", (
        f"score=3 (keyword + person partial) should match; got {res}"
    )
