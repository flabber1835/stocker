import ast
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from sentinel.controller import champion_config, champion_frozen, median5
from sentinel.controller.machine import Controller
from sentinel.core.session import SessionState
from sentinel.strategy import production_strategy


def test_production_transitions_preserve_the_complete_frozen_controller_ast():
    source = Path(__file__).with_name("frozen_reference.txt").read_bytes()
    assert hashlib.sha256(source).hexdigest() == champion_config.REFERENCE_SOURCE_SHA256
    names = {"ORD_DD", "FAST", "SLOW", "LDRC_DD", "LDRC_R20", "LDRC_CEIL", "LDRC_REC", "LDRC_V"}
    def selected(text):
        return [ast.dump(n, include_attributes=False) for n in ast.parse(text).body
                if (isinstance(n, (ast.FunctionDef, ast.ClassDef))
                    and n.name in {"finite", "Native", "CandidateA"})
                or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                    and t.id in names for t in n.targets))]
    assert selected(Path(champion_frozen.__file__).read_text()) == selected(source)


def fresh():
    cfg, identity = production_strategy()
    return SessionState.fresh(starting_cash=100000., controller=Controller(cfg),
                              strategy_identity=identity)


@pytest.mark.parametrize("field,value", [("ordinary_stress_age", 21),
    ("fast_severe_age", 10), ("ramp_entry_session", "2006-01-03"),
    ("last_target_core", .65)])
def test_restart_rejects_incompatible_compact_native_memory(field, value):
    raw = fresh().to_dict()
    raw["controller"][field] = value
    with pytest.raises(ValueError):
        SessionState.from_dict(raw)


@pytest.mark.parametrize("change", ["old_schema", "counter", "lost_audit", "fractional_native"])
def test_restart_rejects_corrupted_or_previous_recovery_memory(change):
    raw = fresh().to_dict()
    if change == "old_schema":
        raw["median5"] = median5.fresh()
    elif change == "counter":
        raw["median5"]["full_streak"] = 9
    elif change == "lost_audit":
        del raw["median5"]["champion_audit"]
    else:
        raw["median5"]["effective_native"] = .65
    with pytest.raises(ValueError):
        SessionState.from_dict(raw)


def test_configuration_drift_is_rejected_before_a_transition():
    from tests.champion.test_controller import observations
    cfg, _ = production_strategy()
    wrong = Controller(replace(cfg, fast_entry={**cfg.fast_entry, "min_damaged_breadth": .9}))
    state = wrong.initial_state()
    before = deepcopy(state)
    with pytest.raises(ValueError, match="configuration differs"):
        wrong.step(observation=next(observations(1)), state=state)
    assert state == before


def test_certificate_reference_retains_twenty_year_metrics():
    result = json.loads(Path(__file__).with_name("certified_result.json").read_text())
    assert result["status"] == "PASS_RESEARCH_CHAMPION_CERTIFICATION"
    assert result["source_sha256"] == champion_config.REFERENCE_SOURCE_SHA256
    assert result["metrics"]["20"]["ending_multiple"] == 56.26534933655832
    assert result["allocation"]["transitions"] == 23
