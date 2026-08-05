"""Strategy-aware chain routing."""
from __future__ import annotations

import pytest

from app.execution_model import (
    CHAINS,
    DEFAULT_EXECUTION_MODEL,
    LEGACY_STAGES_BYPASSED,
    STATEFUL_OWNERSHIP_CHAIN,
    TARGET_PORTFOLIO_CHAIN,
    ExecutionModel,
    UnknownExecutionModel,
    resolve,
    steps_for,
)


def test_a_config_saying_nothing_gets_the_legacy_chain():
    """Every strategy predates this field and they are all target-portfolio
    strategies, so silence has an unambiguous correct reading."""
    assert resolve({}) is TARGET_PORTFOLIO_CHAIN
    assert resolve(None) is TARGET_PORTFOLIO_CHAIN
    assert DEFAULT_EXECUTION_MODEL is ExecutionModel.TARGET_PORTFOLIO


def test_wealth_core_gets_the_stateful_chain():
    spec = resolve({"execution_model": "stateful_ownership"})
    assert spec is STATEFUL_OWNERSHIP_CHAIN
    assert spec.steps[0] == "broker-sync"
    assert "wealth-core-session" in spec.steps


def test_an_unknown_model_is_refused_rather_than_defaulted():
    """Defaulting would run a target-diff chain against a stateful book, and
    the delta engine would propose selling every position it did not
    recognise."""
    with pytest.raises(UnknownExecutionModel) as e:
        resolve({"execution_model": "whatever_v2"})
    assert "stateful_ownership" in str(e.value)


def test_the_field_is_read_at_the_TOP_LEVEL():
    """Nested, it would land in the part of the config that config-replay and
    the parity manifests treat as inert — the trap the trailing-stop block was
    moved to the top level to avoid."""
    assert resolve({"delta_engine": {"execution_model": "stateful_ownership"}}) \
        is TARGET_PORTFOLIO_CHAIN


class TestTheChainsAreGenuinelyDisjointWhereItMatters:

    def test_the_stateful_chain_requires_none_of_the_target_stages(self):
        assert set(LEGACY_STAGES_BYPASSED) == {
            "fetch-data", "pipeline", "vet", "portfolio-builder", "delta"}
        for stage in LEGACY_STAGES_BYPASSED:
            assert not STATEFUL_OWNERSHIP_CHAIN.runs(stage)

    def test_the_stateful_chain_runs_sync_then_session_then_execution(self):
        """The order is the contract: the account must be synced before the
        session decides anything (sizing is 4% of CURRENT equity), and the risk
        gate must sit between the decision and the broker."""
        s = STATEFUL_OWNERSHIP_CHAIN.steps
        assert s.index("broker-sync") < s.index("wealth-core-session")
        assert s.index("wealth-core-session") < s.index("risk-reserve")
        assert s.index("risk-reserve") < s.index("execute")
        assert s.index("execute") < s.index("broker-reconcile")

    def test_every_model_has_a_chain(self):
        assert set(CHAINS) == set(ExecutionModel)

    def test_steps_for_is_the_same_answer_as_resolve(self):
        cfg = {"execution_model": "stateful_ownership"}
        assert steps_for(cfg) == resolve(cfg).steps


def test_the_two_bypass_lists_agree():
    """The scheduler and the live module each name what is bypassed. Two
    hand-maintained lists drift, and the drift shows up as a live book that
    stops trading when a service it does not use has a bad night."""
    import importlib.util
    import pathlib
    import sys
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "services" / "pipeline" / "app" / "wealth_core_live.py"
    spec = importlib.util.spec_from_file_location("_wc_live_bypass", path)
    mod = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves annotations through
    # sys.modules[cls.__module__], so a module executed without being
    # registered blows up on its first dataclass rather than on anything real.
    sys.modules["_wc_live_bypass"] = mod
    spec.loader.exec_module(mod)
    assert set(mod.BYPASSED_STAGES) == set(LEGACY_STAGES_BYPASSED)
    assert mod.EXECUTION_MODEL == ExecutionModel.STATEFUL_OWNERSHIP.value
