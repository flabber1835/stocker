from __future__ import annotations

import datetime as dt

import pytest

from sentinel.feed import authority as A
from sentinel.feed import sharadar


def _sep(day: str, n: int, *, missing: str | None = None):
    rows = []
    for i in range(n):
        row = {
            "date": day,
            "ticker": f"T{i:04d}",
            "close": 100.0,
            "closeunadj": 100.0,
            "open": 99.0,
            "volume": 1_000_000.0,
        }
        if missing is not None:
            row[missing] = None
        rows.append(row)
    return rows


def test_sep_fingerprint_is_order_independent_but_multiset_sensitive():
    rows = _sep("2026-08-18", 20)
    forward = A.observe_sep(rows)
    backward = A.observe_sep(reversed(rows))
    A.require_stable("SEP", forward, backward)

    duplicate = A.observe_sep(rows + [rows[0]])
    with pytest.raises(A.VendorPublicationUnstable):
        A.require_stable("SEP", forward, duplicate)


def test_partial_sep_above_old_80_percent_floor_is_not_authority():
    # 85% would pass readiness's deliberately retained anomaly floor. It is not
    # allowed to pass the source-authority boundary when a later complete
    # traversal exposes the publication still moving.
    partial = A.observe_sep(_sep("2026-08-18", 85))
    complete = A.observe_sep(_sep("2026-08-18", 100))
    assert partial.rows / complete.rows > 0.80
    with pytest.raises(A.VendorPublicationUnstable):
        A.require_stable("SEP", partial, complete)


@pytest.mark.parametrize(
    ("missing", "label"),
    [
        ("close", "signal close"),
        ("closeunadj", "raw close"),
        ("open", "raw open"),
        ("volume", "volume"),
    ],
)
def test_frontier_domain_collapse_is_checked_per_session(missing, label):
    rows = []
    frontier = dt.date(2026, 8, 18)
    for offset in range(126, 0, -1):
        rows.extend(_sep((frontier - dt.timedelta(days=offset)).isoformat(), 1))
    rows.extend(_sep(frontier.isoformat(), 100, missing=missing))
    observation = A.observe_sep(rows)
    with pytest.raises(A.FrontierDomainIncomplete, match=label):
        A.assert_frontier_domains(observation)


def test_actions_disappearance_and_later_terminal_are_not_one_snapshot_truth():
    prior = {
        "ticker": "AAA", "date": "2026-08-01", "action": "dividend",
        "value": 0.25, "name": None, "contraticker": None, "contraname": None,
    }
    terminal = {
        "ticker": "AAA", "date": "2026-08-18", "action": "acquisitionby",
        "value": 500.0, "name": None, "contraticker": "BBB", "contraname": None,
    }
    partial = A.observe_actions([])
    complete = A.observe_actions([prior, terminal])
    with pytest.raises(A.VendorPublicationUnstable):
        A.require_stable("ACTIONS", partial, complete)

    # Once two complete observations agree, the same new terminal row is valid
    # publication evidence rather than something inferred from a single fetch.
    again = A.observe_actions([terminal, prior])
    A.require_stable("ACTIONS", complete, again)


def test_moving_actions_are_refused_before_protected_sep_can_replay():
    action_calls = 0
    prior = {"ticker": "AAA", "date": "2026-08-01", "action": "dividend",
             "value": 0.25}

    def fetch(table, params=None, **kwargs):
        nonlocal action_calls
        if table == sharadar.ACTIONS:
            action_calls += 1
            return [] if action_calls == 1 else [prior]
        assert table == sharadar.SEP
        return _sep("2026-08-18", 100)

    guarded = A.StableSharadarFetch(fetch)
    # The first response may populate a PENDING candidate. It is not authority:
    # the second observation is delayed across a full SEP traversal and must
    # agree before any protected SEP row can be handed to the ingest/publisher.
    assert guarded(sharadar.ACTIONS, {"date.gte": "2026-08-01",
                                      "date.lte": "2026-08-18"}) == []
    with pytest.raises(A.VendorPublicationUnstable):
        guarded(sharadar.SEP, {"date.gte": "2026-08-01",
                               "date.lte": "2026-08-18"})
    assert action_calls == 2


def test_stable_fetch_refuses_moving_sep_before_replay():
    calls = 0

    def fetch(table, params=None, **kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        return _sep("2026-08-18", 85 if calls == 1 else 100)

    guarded = A.StableSharadarFetch(fetch)
    with pytest.raises(A.VendorPublicationUnstable):
        guarded(sharadar.SEP, {"date.gte": "2026-08-01",
                               "date.lte": "2026-08-18"})
    assert calls == 2
