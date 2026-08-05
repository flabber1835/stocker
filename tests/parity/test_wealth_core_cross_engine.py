"""Cross-engine parity: backtester, wind tunnel and live dry-run.

WHAT THIS TEST IS ACTUALLY CHECKING. All three engines call the same
`run_sessions`, so they cannot disagree about the strategy. What they CAN
disagree about is everything around it — how bars are normalised, what gets
hashed, whether an engine quietly post-processes a result. This test removes the
one legitimate difference (where data comes from) by injecting the shared golden
stream into all three, and then requires that nothing else is left.

A test that ran each engine against its own database would be measuring the
databases. This one measures the engines.
"""
from __future__ import annotations

import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# NOTE: the service directories are deliberately NOT put on sys.path. Every
# service ships a top-level `app` package, so inserting three of them makes
# `import app.anything` resolve to whichever was inserted last — for any OTHER
# suite sharing the interpreter. It broke tests/shared when the two ran in one
# process. The modules below are loaded by explicit path instead, which needs no
# path manipulation because none of them import `app.*`.

from stock_strategy_shared.wealth_core.golden import golden_scenario  # noqa: E402
from stock_strategy_shared.wealth_core.hashes import (  # noqa: E402
    HASH_ORDER,
    divergence_report,
    first_divergence,
)
from stock_strategy_shared.wealth_core.run import run_with_hashes  # noqa: E402


def _import(service: str, module: str):
    """Import one service's module under its own `app` package.

    Every service ships an `app` package, so they collide in one interpreter.
    The project's own runner solves this with a process per suite; here only
    three modules are needed, so they are loaded by path under distinct names.
    """
    import importlib.util
    path = ROOT / "services" / service / "app" / f"{module}.py"
    name = f"_parity_{service.replace('-', '_')}_{module}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


backtester = _import("backtester", "wealth_core_replay")
tunnel = _import("bt-engine", "wealth_core_tunnel")
live = _import("pipeline", "wealth_core_live")


@pytest.fixture(scope="module")
def scenario():
    return golden_scenario()


@pytest.fixture(scope="module")
def reference(scenario):
    """The backtester's run. It is the REFERENCE by convention — somebody has
    to be, and it is the engine whose output a human reads."""
    g = scenario
    return backtester.run_normalized(
        sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
        starting_cash=g.starting_cash, terminal_events=g.terminal_events)


class TestAllThreeEnginesAgree:

    def test_the_backtester_produces_all_seven_hashes(self, reference):
        _, hashes = reference
        assert set(hashes.to_dict()) == set(HASH_ORDER)
        assert all(hashes[k] for k in HASH_ORDER)

    def test_the_wind_tunnel_reproduces_the_backtester_exactly(self, scenario,
                                                               reference):
        g = scenario
        _, expected = reference
        run = tunnel.baseline_replay(
            sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, expected=expected,
            terminal_events=g.terminal_events)
        assert run.divergence["identical"] is True
        assert run.hashes.to_dict() == expected.to_dict()

    def test_the_live_dry_run_reproduces_the_backtester_exactly(self, scenario,
                                                                reference):
        g = scenario
        _, expected = reference
        _, hashes, intents = live.dry_run(
            sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events)
        assert first_divergence(hashes, expected.to_dict()) is None
        assert intents, "a dry run that produces no intents proves nothing"

    def test_the_live_path_emits_ONLY_wealth_core_operations(self, scenario):
        """No buy_add, no sell_trim, no target diff. Those have no meaning in a
        strategy that never scales into or out of a position, and offering them
        would invite a change that quietly makes live a different strategy from
        the backtest."""
        g = scenario
        _, _, intents = live.dry_run(
            sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events)
        assert {i["operation"] for i in intents} <= {"OPEN_SLOT_POSITION",
                                                     "CLOSE_POSITION"}
        assert all(i["strategy_id"] == "stocker_wealth_core_v1" for i in intents)


class TestTheParityCheckCanActuallyFail:
    """Mutation controls. A parity test that cannot fail is a green light with
    no bulb in it."""

    def test_a_changed_config_breaks_baseline_replay(self, scenario, reference):
        g = scenario
        _, expected = reference
        changed = tunnel.apply_config_change(
            __import__("stock_strategy_shared.wealth_core.engine",
                       fromlist=["WealthCoreConfig"]).WealthCoreConfig(),
            {"entry_weight": 0.05})
        with pytest.raises(tunnel.ParityViolation) as e:
            tunnel.baseline_replay(
                sessions=g.sessions, bars_by_session=g.bars_by_session,
                meta=g.meta, starting_cash=g.starting_cash, expected=expected,
                cfg=changed, terminal_events=g.terminal_events)
        assert "decision" in str(e.value) or "order" in str(e.value)

    def test_a_changed_price_breaks_it_at_normalized_input_FIRST(self, scenario,
                                                                 reference):
        """And the diagnosis must name the DATA layer, not the ranking — the
        whole point of ordering the hashes."""
        import dataclasses
        g = scenario
        _, expected = reference
        bars = {s: list(v) for s, v in g.bars_by_session.items()}
        first = g.sessions[0]
        bars[first] = [dataclasses.replace(bars[first][0],
                                           raw_close=bars[first][0].raw_close * 1.5)] \
            + bars[first][1:]
        _, hashes = run_with_hashes(
            sessions=g.sessions, bars_by_session=bars, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events)
        assert first_divergence(hashes, expected) == "normalized_input"
        rep = divergence_report(hashes, expected)
        assert "different DATA" in rep["interpretation"]


class TestExperimentMode:

    def test_an_experiment_records_its_parent_and_its_change(self, scenario,
                                                             reference):
        from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
        g = scenario
        _, baseline = reference
        change = {"entry_weight": 0.05}
        run = tunnel.experiment(
            sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, baseline=baseline, change=change,
            cfg=tunnel.apply_config_change(WealthCoreConfig(), change),
            terminal_events=g.terminal_events)
        assert run.baseline_parent == baseline.to_dict()
        assert run.change == change
        assert run.divergence["first_divergence"] in ("decision", "order",
                                                      "candidate_audit")

    def test_an_experiment_with_no_recorded_change_is_refused(self, scenario,
                                                              reference):
        g = scenario
        _, baseline = reference
        with pytest.raises(ValueError):
            tunnel.experiment(
                sessions=g.sessions, bars_by_session=g.bars_by_session,
                meta=g.meta, starting_cash=g.starting_cash, baseline=baseline,
                change={}, terminal_events=g.terminal_events)

    def test_an_experiment_that_changed_the_DATA_is_flagged_not_scored(
            self, scenario, reference):
        """Comparing two configs across two different datasets is the most
        persuasive wrong answer this system can produce."""
        import dataclasses
        g = scenario
        _, baseline = reference
        bars = {s: list(v) for s, v in g.bars_by_session.items()}
        first = g.sessions[0]
        bars[first] = [dataclasses.replace(bars[first][0], volume=1.0)] + \
            bars[first][1:]
        run = tunnel.experiment(
            sessions=g.sessions, bars_by_session=bars, meta=g.meta,
            starting_cash=g.starting_cash, baseline=baseline,
            change={"note": "volume tweak"}, terminal_events=g.terminal_events)
        assert run.divergence["first_divergence"] == "normalized_input"
        assert "confounded" in run.divergence["warning"]

    def test_the_tunnel_reimplements_nothing(self):
        """The constraint in prose, enforced over the SOURCE.

        The tunnel must not carry its own eligibility, ranking, review, stop,
        cooldown, reservation or sizing logic. Checked with comments and
        docstrings stripped, because this module's own docstring lists exactly
        those words while explaining that it must not implement them.
        """
        import ast
        src = (ROOT / "services" / "bt-engine" / "app"
               / "wealth_core_tunnel.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                node.value.value = ""
        code = ast.unparse(tree).lower()
        for forbidden in ("def score_universe", "def rank_candidates",
                          "def whole_shares", "def still_qualifies",
                          "episode_peak", "cooldown", "reserved_for",
                          "in_top_decile", "durable_score"):
            assert forbidden not in code, (
                f"the wind tunnel appears to reimplement {forbidden!r}; it must "
                f"call the shared state machine and nothing else")
