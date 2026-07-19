"""Experiment queue (Phase 6b) — deterministic harvest of the evaluator's own
recommendations into artifacts/bt/proposals.json. The harvest path involves no
LLM write: recommendations are already schema-validated and harvesting is pure
Python. (The separate queue_experiment TOOL — tests in test_queue_experiment.py
— appends exploratory entries to the same file under the same caps.)"""
import os

import pytest

from app.proposals import (PENDING_CAP, RETAIN, harvest_proposals,
                           parse_suggested_value, proposal_id)


def _base_config() -> dict:
    import yaml
    here = os.path.join(os.path.dirname(__file__), "..", "..",
                        "strategies", "quality_core_v1.yaml")
    return yaml.safe_load(open(here))


def _rec(field, value, valid=True, **kw):
    return {"config_field": field, "suggested_value": value,
            "config_field_valid": valid, "confidence": "medium",
            "observation": "test observation", **kw}


_KW = dict(run_id="r1", iso_week="2026-W28", now_iso="2026-07-11T00:00:00+00:00")


# ── parse_suggested_value ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0.12", 0.12), ("25", 25), ("true", True), ("false", False),
    ("null", None), ("None", None), ("disabled", None), ('"equal_weight"', "equal_weight"),
])
def test_parse_literals(raw, expected):
    value, ok = parse_suggested_value(raw)
    assert ok and value == expected


@pytest.mark.parametrize("raw", ["reduce by half", "0.15 (15%)", "", "~0.2"])
def test_parse_prose_rejected(raw):
    assert parse_suggested_value(raw)[1] is False


# ── harvest ───────────────────────────────────────────────────────────────────

def test_valid_recommendation_is_queued():
    content, added = harvest_proposals(
        [_rec("portfolio_builder.max_positions", "25")], _base_config(), None, **_KW)
    assert len(added) == 1
    p = added[0]
    assert p["config_field"] == "portfolio_builder.max_positions"
    assert p["value"] == 25 and p["status"] == "pending"
    assert p["source_run_id"] == "r1" and p["sweep_id"] is None
    assert content["proposals"] == added


def test_skips_invalid_field_none_field_prose_value_and_schema_reject():
    recs = [
        _rec("portfolio_builder.fake_knob", "1", valid=False),   # not stamped valid
        _rec("none", "advice only"),                             # general advice
        _rec("portfolio_builder.max_positions", "roughly 20"),   # prose value
        _rec("portfolio_builder.max_position_weight", "5.0"),    # schema-invalid
    ]
    _, added = harvest_proposals(recs, _base_config(), None, **_KW)
    assert added == []


def test_dedupes_against_all_existing_statuses():
    existing = {"proposals": [{
        "id": proposal_id("portfolio_builder.max_positions", 25),
        "config_field": "portfolio_builder.max_positions", "value": 25,
        "status": "tested", "sweep_id": "s0"}]}
    _, added = harvest_proposals(
        [_rec("portfolio_builder.max_positions", "25")], _base_config(),
        existing, **_KW)
    assert added == []   # tested entry suppresses re-queuing until it ages out


def test_pending_cap_and_retain_window():
    existing = {"proposals": [
        {"id": f"old{i}", "config_field": "x", "value": i, "status": "pending"}
        for i in range(PENDING_CAP)]}
    _, added = harvest_proposals(
        [_rec("portfolio_builder.max_positions", "25")], _base_config(),
        existing, **_KW)
    assert added == []   # queue full

    many = {"proposals": [
        {"id": f"hist{i}", "config_field": "x", "value": i, "status": "tested"}
        for i in range(RETAIN)]}
    content, added = harvest_proposals(
        [_rec("portfolio_builder.max_positions", "25")], _base_config(),
        many, **_KW)
    assert len(added) == 1
    assert len(content["proposals"]) == RETAIN          # oldest fell off
    assert content["proposals"][-1]["id"] == added[0]["id"]


def test_null_value_proposal_for_nullable_knob():
    """'null' → disable a nullable knob (e.g. cluster count cap) — a real,
    testable experiment the sweep can run."""
    _, added = harvest_proposals(
        [_rec("portfolio_builder.max_tickers_per_cluster", "null")],
        _base_config(), None, **_KW)
    assert len(added) == 1 and added[0]["value"] is None
