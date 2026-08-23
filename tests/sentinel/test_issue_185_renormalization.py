"""Historical SEP/ACTIONS corrections must replay canonical session boundaries."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import (
    anomalies, maintenance, publication, renormalize, universe)


def test_weekend_action_replays_prior_effective_and_following_session():
    # Saturday source event snaps to Monday 2026-08-17. The replay must also
    # include Friday's predecessor and Tuesday's following session because a
    # corrected price pair can change split inference on either boundary.
    assert renormalize._window_for_date("2026-08-15") == (
        "2026-08-14", "2026-08-18")


def test_adjacent_corrections_merge_into_one_bounded_replay_window():
    windows = renormalize.correction_windows(["2026-08-17", "2026-08-18"])
    assert len(windows) == 1
    assert windows[0][0] <= "2026-08-14"
    assert windows[0][1] >= "2026-08-19"


def test_complete_action_history_is_clipped_to_retained_market_sessions():
    windows = renormalize.correction_windows(
        ["1900-01-01", "1998-01-02", "2025-07-01", "2026-08-24"],
        market_start="2025-07-01", market_end="2026-08-21")

    # The old and future events are outside the retained price authority.  The
    # first retained-session event cannot pull in its ordinary predecessor.
    assert windows == [("2025-07-01", "2025-07-02")]


def test_retained_market_bounds_must_be_complete_and_ordered():
    with pytest.raises(ValueError, match="supplied together"):
        renormalize.correction_windows(
            ["2025-07-01"], market_start="2025-07-01")
    with pytest.raises(ValueError, match="reversed"):
        renormalize.correction_windows(
            ["2025-07-01"], market_start="2026-01-01",
            market_end="2025-01-01")


def test_sep_mutation_validation_refuses_unknown_permanent_identity(monkeypatch):
    monkeypatch.setattr(
        universe, "load_resolver",
        lambda conn: SimpleNamespace(resolve=lambda ticker, session: None))
    row = {
        "ticker": "AAA", "date": "2020-01-02",
        "lastupdated": "2026-08-18", "closeunadj": 10.0,
    }
    with pytest.raises(maintenance.SharadarMutationRefused, match="no permanent identity"):
        maintenance._validate_sep_mutation_rows(
            object(), [row], lo=__import__("datetime").date(2026, 8, 17),
            hi=__import__("datetime").date(2026, 8, 18),
            published_from=__import__("datetime").date(2020, 1, 1),
            published_through=__import__("datetime").date(2026, 8, 18))


def test_sep_mutation_validation_refuses_missing_new_raw_price(monkeypatch):
    monkeypatch.setattr(
        universe, "load_resolver",
        lambda conn: SimpleNamespace(resolve=lambda ticker, session: "P:1"))
    row = {
        "ticker": "AAA", "date": "2020-01-02",
        "lastupdated": "2026-08-18", "closeunadj": None,
    }
    with pytest.raises(maintenance.SharadarMutationRefused, match="no positive raw close"):
        maintenance._validate_sep_mutation_rows(
            object(), [row], lo=__import__("datetime").date(2026, 8, 17),
            hi=__import__("datetime").date(2026, 8, 18),
            published_from=__import__("datetime").date(2020, 1, 1),
            published_through=__import__("datetime").date(2026, 8, 18))


def test_sep_mutation_before_retained_market_is_not_imported(monkeypatch):
    def must_not_resolve(_ticker, _session):
        raise AssertionError("an out-of-range mutation must not resolve identity")

    monkeypatch.setattr(
        universe, "load_resolver",
        lambda conn: SimpleNamespace(resolve=must_not_resolve))
    row = {
        "ticker": "OLD", "date": "1998-01-02",
        "lastupdated": "2026-08-18", "closeunadj": 10.0,
    }

    dates = maintenance._validate_sep_mutation_rows(
        object(), [row], lo=__import__("datetime").date(2026, 8, 17),
        hi=__import__("datetime").date(2026, 8, 18),
        published_from=__import__("datetime").date(2025, 7, 1),
        published_through=__import__("datetime").date(2026, 8, 18))

    assert dates == []


def test_action_change_dates_replay_only_bar_affecting_actions(monkeypatch):
    prior = {
        "old-split": {
            "ticker": "AAA", "date": "2020-01-02", "action": "split",
            "name": None, "value": 2.0, "contraticker": None,
            "contraname": None,
        },
        "terminal": {
            "ticker": "ZZZ", "date": "2020-02-03", "action": "delisted",
            "name": None, "value": None, "contraticker": None,
            "contraname": None,
        },
    }
    monkeypatch.setattr(maintenance, "_active_action_rows", lambda conn: prior)

    # Current source removes the old split (must replay its old effective date),
    # keeps the terminal row (no bar replay), and adds a dividend (must replay).
    current = [
        prior["terminal"],
        {
            "ticker": "BBB", "date": "2020-03-04", "action": "dividend",
            "name": None, "value": 0.5, "contraticker": None,
            "contraname": None,
        },
    ]
    dates = maintenance._action_change_dates(object(), current)
    assert dates == ["2020-01-02", "2020-03-04"]


def test_semantic_reearn_includes_accepted_resolved_direct_and_adr_dates(
        monkeypatch):
    observed = {}

    def active_rows(conn, *, start, end, kinds):
        observed.update(start=start, end=end, kinds=kinds)
        return [
            {"kind": "SPLIT_CORROBORATED_DERIVED", "session": "2026-08-14"},
            {"kind": "SPLIT_AUTHORITATIVE_APPLIED", "session": "2026-08-17"},
            {"kind": "SPLIT_RESOLVED_NO_EVENT", "session": "2026-08-18"},
            {"kind": "SPLIT_DISAGREEMENT", "session": "2026-08-19"},
        ]

    monkeypatch.setattr(anomalies, "active_rows", active_rows)
    monkeypatch.setattr(
        publication, "effective_nonunit_split_rows",
        lambda conn, *, start, end: [{
            "ticker": "LEGACY", "session": "2026-08-16",
            "split_ratio": 2.0,
        }])
    current = [
        {"action": "split", "date": "2026-08-20"},
        {"action": "adrratiosplit", "date": "2026-08-21"},
        {"action": "split", "date": "2024-01-02"},
        {"action": "dividend", "date": "2026-08-13"},
    ]
    prior = [
        # Removed now, but legacy code could already have resized the stored
        # book from it without leaving a blocking disposition.
        {"action": "adrratiosplit", "date": "2026-08-15"},
    ]

    assert maintenance._semantic_upgrade_replay_dates(
        object(), market_start="2026-08-14", market_end="2026-08-21",
        current_action_rows=current, prior_action_rows=prior) == [
            "2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17",
            "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
        ]
    assert observed == {
        "start": "2026-08-14", "end": "2026-08-21",
        "kinds": anomalies.SPLIT_DISPOSITION_KINDS,
    }


@pytest.mark.parametrize("old_epoch", ["v4", "v5"])
def test_legacy_cursor_cannot_bypass_v6_semantic_reearn(old_epoch):
    old_name = f"sharadar-actions-export-reconcile:{old_epoch}"
    old_state = {
        "kind": f"sharadar-actions-export-reconcile/{old_epoch}",
        "processed_through": "2026-08-21",
        "publication_version": 41,
    }

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
            self.row = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params=()):
            if "WHERE cursor_name=%s" in sql:
                self.conn.requested.append(params[0])
                self.row = self.conn.rows.get(params[0])

        def fetchone(self):
            return self.row

    class Conn:
        rows = {old_name: (dt.date(2026, 8, 21), old_state)}

        def __init__(self):
            self.requested = []

        def cursor(self):
            return Cursor(self)

    conn = Conn()
    assert maintenance.load_actions_cursor(conn) is None
    assert conn.requested == ["sharadar-actions-export-reconcile:v6"]
