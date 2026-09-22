"""Observed controller boundary experiments, not return-optimized settings."""
import copy
import gzip
import json
from pathlib import Path

from sentinel.controller.champion_frozen import Native

ROOT = Path(__file__).resolve().parents[2]/"audit/economic-diagnosis"
FIELDS = ("shadow_drawdown", "shadow_r5", "shadow_r10", "shadow_r20", "shadow_r40",
          "damaged_breadth", "green_breadth", "damaged_breadth_delta5", "spy_r20",
          "spy_vol_ratio", "stops20", "shadow_nav")


def transition(year, day, changes=None, memory=None):
    rows = json.loads(gzip.decompress((ROOT/f"window-{year}.json.gz").read_bytes()))["observations"]
    index = next(i for i, r in enumerate(rows) if r["session"] == day)
    prior = copy.deepcopy(rows[index-1]["decision"]["evidence"]["native_snapshot"])
    prior["state"].update(memory or {})
    native = Native.from_snapshot(prior)
    observation = rows[index]["observation"] | (changes or {})
    result = native.step(tuple(observation[k] for k in FIELDS))
    if not changes and not memory:
        assert native.snapshot() == rows[index]["decision"]["evidence"]["native_snapshot"]
    return result, native.snapshot()


def test_saturated_damage_can_block_entry_despite_all_owned_names_damaged():
    result, _ = transition(2011, "2011-08-04")
    assert result == (1., False, False)
    # All other real observed gates already pass. Changing only the increase
    # makes the old rule enter. This establishes the binding gate, not its cure.
    changed, _ = transition(2011, "2011-08-04", {"damaged_breadth_delta5": .31})
    assert changed == (0., True, False)


def test_one_additional_damaged_vote_crosses_binary_exposure_boundary():
    result, _ = transition(2018, "2018-10-10")
    assert result == (1., False, False)
    # 16/19 damaged, 3/19 green -> 17/19 damaged, 2/19 green, with
    # corresponding same-history change in breadth delta.
    changed, _ = transition(2018, "2018-10-10", {
        "damaged_breadth": 17/19, "green_breadth": 2/19,
        "damaged_breadth_delta5": 17/19-1/3})
    assert changed == (0., True, False)


def test_tiny_signal_margin_changes_the_whole_account_instruction():
    result, _ = transition(2026, "2026-03-30")
    assert result == (0., True, False)
    changed, _ = transition(2026, "2026-03-30", {"damaged_breadth_delta5": .2999})
    assert changed == (1., False, False)


def test_recovered_owned_book_remains_out_because_of_minimum_age():
    result, snapshot = transition(2026, "2026-04-07")
    assert result == (0., False, False)
    assert snapshot["state"]["fast_h"] == 3
    assert snapshot["state"]["fast_age"] == 5
    changed, _ = transition(2026, "2026-04-07", memory={"fast_age": 8})
    assert changed == (1., False, False)
