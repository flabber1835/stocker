"""_experiment_queue must survive a malformed `diff` entry.

A queue entry's canonical diff is {path: {from, to}}. A hand-written entry
(scripts/queue-experiment.py) can carry {path: value} instead, and rendering that
raised `AttributeError: 'bool' object has no attribute 'get'`.

The blast radius is the point. Packet sections are caught as a UNIT, so one
malformed row blanked the ENTIRE experiment_queue and backtest_lab views — leaving
the evaluator unable to see its own queue, which is how an unrelated candidate
consumed a daily lane slot without anyone noticing. A rendering detail must never
cost the model a whole section.
"""
import json
import os

import pytest

from app.packet import _experiment_queue


def _write(tmp_path, entries):
    d = tmp_path / "bt"
    d.mkdir(parents=True, exist_ok=True)
    (d / "proposals.json").write_text(json.dumps({"proposals": entries}))
    os.environ["ARTIFACTS_PATH"] = str(tmp_path)


def _entry(diff, **over):
    e = {"id": "e1", "kind": "full_config", "status": "pending",
         "hypothesis": "h", "config_hash": "abc123", "diff": diff}
    e.update(over)
    return e


def test_canonical_from_to_diff_renders(tmp_path):
    _write(tmp_path, [_entry({"max_positions": {"from": 35, "to": 50}})])
    out = _experiment_queue()
    assert out["recent"][0]["changes"] == {"max_positions": "35 -> 50"}


@pytest.mark.parametrize("value", [True, False, 0.1, 35, "raw", [1, 2]])
def test_a_value_only_diff_does_not_raise(tmp_path, value):
    """THE regression: a bare value where a {from,to} dict was expected."""
    _write(tmp_path, [_entry({"trailing_stop.enabled": value})])
    out = _experiment_queue()
    assert out["available"] is True
    assert "trailing_stop.enabled" in out["recent"][0]["changes"]


def test_one_malformed_entry_does_not_hide_the_others(tmp_path):
    """The blast radius that made this expensive — a bad row must not take the
    whole queue view with it."""
    _write(tmp_path, [
        _entry({"trailing_stop.enabled": True}, id="bad"),
        _entry({"max_positions": {"from": 35, "to": 50}}, id="good"),
    ])
    out = _experiment_queue()
    ids = [r["id"] for r in out["recent"]]
    assert ids == ["bad", "good"]
    assert out["counts"]["pending"] == 2


def test_mixed_shapes_in_one_diff(tmp_path):
    _write(tmp_path, [_entry({"a": {"from": 1, "to": 2}, "b": True})])
    changes = _experiment_queue()["recent"][0]["changes"]
    assert changes["a"] == "1 -> 2" and "True" in changes["b"]
