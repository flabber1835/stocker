"""Falsifiers for generic action quarantine and retained price verification."""
from __future__ import annotations

import pytest

from sentinel.feed import action_quarantine


class _Identity:
    def resolver(self):
        return self

    def resolve(self, ticker, session):
        return {"AAA": "101", "BBB": "202"}.get(ticker)


def _action(ticker, kind, value):
    return {"ticker": ticker, "date": "2026-09-14", "action": kind,
            "value": value, "name": None, "contraticker": None, "contraname": None}


def test_unusable_dividend_quarantines_permanent_identity_and_preserves_other_actions():
    rows = [_action("AAA", "dividend", "0"), _action("BBB", "dividend", "0.3")]
    result = action_quarantine.classify(_Identity(), rows, ["2026-09-14"])
    assert [item["security_id"] for item in result] == ["101"]
    assert [row["ticker"] for row in action_quarantine.safe_actions(
        rows, _Identity(), result, ["2026-09-14"])] == ["BBB"]
    carried = action_quarantine.classify(_Identity(), [], ["2026-09-14"], prior=result)
    assert carried == result


def test_unknown_action_identity_refuses_instead_of_guessing():
    with pytest.raises(ValueError, match="permanent identity"):
        action_quarantine.classify(_Identity(), [_action("UNKNOWN", "dividend", 0)],
                                   ["2026-09-14"])


def test_conflicting_split_values_quarantine_without_choosing_a_ratio():
    rows = [_action("AAA", "split", "2"), _action("AAA", "split", "3")]
    result = action_quarantine.classify(_Identity(), rows, ["2026-09-14"])
    assert result[0]["reason"] == "AMBIGUOUS_SPLIT"
    assert action_quarantine.safe_actions(rows, _Identity(), result, ["2026-09-14"]) == []


def test_systemic_anomalies_refuse_instead_of_quarantining_unbounded_universe():
    prior = [{"security_id": str(i), "reason": "UNUSABLE_DIVIDEND",
              "session": "2026-09-14", "source": {}}
             for i in range(action_quarantine.MAX_QUARANTINED_SECURITIES + 1)]
    with pytest.raises(ValueError, match="systemic"):
        action_quarantine.classify(_Identity(), [], ["2026-09-14"], prior=prior)
