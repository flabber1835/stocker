"""Historical SEP/ACTIONS corrections must replay canonical session boundaries."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel.feed import maintenance, renormalize, universe


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
            published_through=__import__("datetime").date(2026, 8, 18))


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
