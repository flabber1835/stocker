"""Shared single-field config-edit helpers — one parser for the experiment
queue (test it) and the one-click apply (apply it), so they cannot diverge."""
import pytest

from stock_strategy_shared.config_values import (get_dotted, parse_suggested_value,
                                                 set_dotted)


@pytest.mark.parametrize("raw,expected", [
    ("0.12", 0.12), ("25", 25), ("true", True), ("False", False),
    ("null", None), ("None", None), ("off", None), ('"greedy"', "greedy"),
    (25, 25), (0.5, 0.5), (None, None),
])
def test_parse_literals(raw, expected):
    value, ok = parse_suggested_value(raw)
    assert ok and value == expected


@pytest.mark.parametrize("raw", ["reduce by half", "0.15 (15%)", "", "~0.2", "10-15"])
def test_parse_prose_rejected(raw):
    assert parse_suggested_value(raw)[1] is False


def test_get_set_dotted_roundtrip():
    cfg = {"a": {"b": {"c": 1}}, "top": 2}
    assert get_dotted(cfg, "a.b.c") == 1 and get_dotted(cfg, "top") == 2
    assert get_dotted(cfg, "a.missing") is None
    assert get_dotted(cfg, "top.not_an_object") is None
    assert set_dotted(cfg, "a.b.c", 9) is None
    assert cfg["a"]["b"]["c"] == 9
    assert set_dotted(cfg, "a.new.leaf", 5) is None      # creates intermediates
    assert cfg["a"]["new"]["leaf"] == 5
    assert set_dotted(cfg, "top.x", 1) is not None       # non-object traversal
    assert set_dotted(cfg, "", 1) is not None
