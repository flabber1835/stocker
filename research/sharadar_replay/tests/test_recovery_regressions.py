"""End-to-end regressions for repeated daily recovery and split retry authority."""
from __future__ import annotations

import copy
import datetime as dt
import os
from pathlib import Path

import pytest

from research.sharadar_replay.model import Fault, Revision, Scenario
from research.sharadar_replay.runner import run_scenario
from research.sharadar_replay.scenarios import (
    FIRST, OLD_CORRECTION, SECOND, SEED, SPLIT, START, THIRD, sessions, step)

pytestmark = pytest.mark.postgres


def _dsn() -> str:
    dsn = os.environ.get("SHARADAR_REPLAY_TEST_DSN")
    assert dsn, "SHARADAR_REPLAY_TEST_DSN is required"
    return dsn


def _seed():
    return step(
        "bootstrap", SEED, ready=False,
        required_blockers=("SEP recent complete reconciliation",))


def _hidden_references(initial):
    reference_start = sessions(FIRST)[-41]
    return initial.model_copy(update={
        "spy": tuple(row for row in initial.spy if row[0] < reference_start),
        "defensive": tuple(
            row for row in initial.defensive if row[0] < reference_start),
    })


def _mixed_daily_recovery_scenario() -> Scenario:
    seed = _seed()
    hidden = _hidden_references(seed.expected)

    first = step(
        "sep_failed_after_sfp", FIRST, expected=hidden, ready=False,
        error="VendorPublicationUnstable", required_blockers=("freshness",))
    tables = copy.deepcopy(first.tables)
    revised = copy.deepcopy(tables["SEP"])
    for row in revised:
        if row["ticker"] == "AAA":
            row["open"] += 1
    first = first.model_copy(update={
        "tables": tables,
        "revisions": (Revision(
            name="sep_changes_after_first_complete_observation",
            table="SEP", observation=2,
            query={"date.gte": SPLIT, "date.lte": FIRST},
            rows=tuple(revised)),),
    })

    second = step(
        "sfp_failed_with_older_reference_owner", SECOND, expected=hidden,
        ready=False, error="SharadarRequestError",
        required_blockers=("freshness",),
        faults=(Fault(table="SFP", kind="http_400"),))
    recover = step("clean_daily_supersedes_both", THIRD)
    return Scenario(
        name="mixed_sep_sfp_daily_recovery",
        seed_start=dt.date.fromisoformat(START), seed=seed,
        steps=(first, second, recover),
        recovery_from="clean_daily_supersedes_both")


def _persistent_unresolved_step(name: str, day: str):
    current = step(
        name, day, ready=False,
        required_blockers=("split source agreement",))
    tables = copy.deepcopy(current.tables)
    split = {
        "ticker": "AAA", "date": OLD_CORRECTION, "action": "split",
        "name": "AAA", "value": 2, "contraticker": None,
        "contraname": None,
    }
    tables["ACTIONS"] = (*tables["ACTIONS"], split)
    expected = current.expected.model_copy(update={
        "actions": (*current.expected.actions,
                    ("AAA", OLD_CORRECTION, "split", "AAA", 2, None, None)),
    })
    return current.model_copy(update={"tables": tables, "expected": expected})


def _persistent_unresolved_scenario() -> Scenario:
    return Scenario(
        name="persistent_historical_unresolved_split",
        seed_start=dt.date.fromisoformat(START), seed=_seed(),
        steps=(
            _persistent_unresolved_step("first_observation", FIRST),
            _persistent_unresolved_step("unchanged_next_day", SECOND),
            _persistent_unresolved_step("unchanged_third_day", THIRD),
        ))


def test_mixed_sep_then_sfp_failures_converge_on_next_clean_daily(tmp_path):
    scenario = _mixed_daily_recovery_scenario()
    result = run_scenario(
        scenario, server_dsn=_dsn(), output=Path(tmp_path) / scenario.name)
    assert result["verdict"] == "PASS"
    assert result["recovery_attempts"] == 1


def test_persistent_unresolved_split_replays_historical_sep_only_once(
        monkeypatch, tmp_path):
    from sentinel.feed import maintenance_impl

    scenario = _persistent_unresolved_scenario()
    original = maintenance_impl.renormalize.renormalize
    action_replays = []

    def counted(*args, **kwargs):
        if kwargs.get("chunk_prefix") == "actions":
            action_replays.append(tuple(kwargs.get("dates") or ()))
        return original(*args, **kwargs)

    monkeypatch.setattr(maintenance_impl.renormalize, "renormalize", counted)
    result = run_scenario(
        scenario, server_dsn=_dsn(), output=Path(tmp_path) / scenario.name)
    assert result["verdict"] == "PASS"
    assert action_replays == [(OLD_CORRECTION,)]
