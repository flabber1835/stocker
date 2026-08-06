"""The crash brake — a rare, coarse, book-level exposure cut.

It exists because the trailing stop cannot see the drawdown that actually hurts a
concentrated momentum book: twenty-five correlated names falling together, none
yet 30% off its own peak. By the time individual stops fire the damage is done.

Almost every test here is about the brake NOT firing. That is the design: a
control that halves the book must be wrong in the safe direction, and the two
conditions exist to make it rare rather than to make it sensitive. The one thing
worse than missing a crash is de-risking on a data gap every time the benchmark
feed hiccups.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.crash_brake import (CrashState, breadth_above_sma,
                                               evaluate_crash_state,
                                               market_window_return,
                                               scale_weights, target_exposure,
                                               transition_hash,
                                               transition_record)


def _falling(n=200, start=100.0, daily=-0.004):
    px, out = start, []
    for _ in range(n):
        out.append(px)
        px *= 1 + daily
    return out


def _rising(n=200, start=100.0, daily=0.002):
    return _falling(n, start, daily)


def _universe(n_names=200, share_below=0.8, length=200):
    """A universe where `share_below` of names sit under their own SMA."""
    out = {}
    n_below = int(n_names * share_below)
    for i in range(n_names):
        out[f"T{i:03d}"] = _falling(length) if i < n_below else _rising(length)
    return out


def _call(**over):
    kw = dict(
        benchmark_closes=_falling(200),
        closes_by_ticker=_universe(),
        market_return_window_sessions=20,
        market_return_threshold=-0.06,
        breadth_sma_sessions=100,
        breadth_threshold=0.42,
    )
    kw.update(over)
    return evaluate_crash_state(**kw)


# ── the inputs ────────────────────────────────────────────────────────────────

class TestMarketWindowReturn:
    def test_it_measures_the_window_not_the_whole_series(self):
        closes = [100.0] * 180 + [100.0 * (1 - 0.001 * i) for i in range(1, 21)]
        r = market_window_return(closes, 20)
        assert r == pytest.approx(closes[-1] / closes[-21] - 1.0)

    def test_short_history_is_unknown_not_zero(self):
        """Zero would read as 'measured, market flat' and silently disarm the
        brake's first condition."""
        assert market_window_return([100.0] * 5, 20) is None

    def test_nonpositive_or_nan_prices_are_unknown(self):
        assert market_window_return([0.0] + [100.0] * 25, 20) is not None  # old zero is outside the window
        assert market_window_return([100.0] * 25 + [0.0], 20) is None
        assert market_window_return([float("nan")] * 25, 20) is None


class TestBreadth:
    def test_it_counts_names_above_their_own_average(self):
        share, n = breadth_above_sma(_universe(200, share_below=0.75), 100, min_names=50)
        assert n == 200
        assert share == pytest.approx(0.25, abs=0.02)

    def test_a_name_without_enough_history_is_excluded_from_BOTH_sides(self):
        """Counting it as 'below' would collapse breadth every time the universe
        refreshes — an ingestion event, not a market event."""
        uni = _universe(100, share_below=0.0)
        uni.update({f"NEW{i}": [100.0] * 5 for i in range(50)})
        share, n = breadth_above_sma(uni, 100, min_names=50)
        assert n == 100 and share == pytest.approx(1.0)

    def test_too_few_names_reads_as_unavailable(self):
        share, n = breadth_above_sma(_universe(10), 100, min_names=50)
        assert share is None and n == 10


# ── the switch ────────────────────────────────────────────────────────────────

class TestBothConditionsRequired:
    def test_engages_only_when_market_AND_breadth_are_bad(self):
        s = _call()
        assert s.engaged, s.reason
        assert s.market_return < -0.06 and s.breadth < 0.42

    def test_a_falling_index_with_healthy_breadth_does_NOT_engage(self):
        """Routinely a handful of mega-caps. Halving the book for that would make
        the brake a market-timing overlay nobody configured."""
        s = _call(closes_by_ticker=_universe(share_below=0.0))
        assert not s.engaged
        assert "breadth" in s.reason

    def test_thin_breadth_in_a_rising_market_does_NOT_engage(self):
        """A normal feature of a narrow bull market."""
        s = _call(benchmark_closes=_rising(200))
        assert not s.engaged
        assert "market" in s.reason


class TestFailSafeOnMissingData:
    """Deliberately the OPPOSITE stance to the falling-knife veto's fail-closed
    load. Refusing to buy on missing data costs an opportunity; selling half the
    book on missing data is an unforced loss."""

    def test_short_benchmark_history_holds_exposure(self):
        s = _call(benchmark_closes=[100.0] * 5)
        assert not s.engaged and "cannot evaluate" in s.reason

    def test_unavailable_breadth_holds_exposure(self):
        s = _call(closes_by_ticker=_universe(n_names=5))
        assert not s.engaged and "breadth unavailable" in s.reason

    def test_an_empty_universe_holds_exposure(self):
        s = _call(closes_by_ticker={})
        assert not s.engaged

    def test_disabled_is_inert_even_in_an_obvious_crash(self):
        s = _call(enabled=False)
        assert not s.engaged and s.market_return is None


class TestReporting:
    def test_every_input_is_reported_even_when_disengaged(self):
        """A risk control that says only 'engaged' cannot be argued with after
        the fact."""
        s = _call(benchmark_closes=_rising(200))
        assert s.market_return is not None and s.breadth is not None
        assert s.n_breadth_names > 0 and s.reason


# ── applying it ───────────────────────────────────────────────────────────────

class TestExposure:
    def test_engaged_uses_the_stressed_exposure(self):
        assert target_exposure(_call(), 1.0, 0.5, prior=1.0) == 0.5

    def test_disengaged_uses_the_normal_exposure(self):
        assert target_exposure(_call(benchmark_closes=_rising(200)), 1.0, 0.5,
                           prior=0.5) == 1.0

    def test_scaling_preserves_relative_weights_exactly(self):
        """THE property. Re-deriving weights on restore would turn the brake into
        a rebalancing trigger — the rotation a stop-only policy exists to avoid.
        A 6% position comes back as 6%, not as whatever today's target says."""
        w = {"A": 0.06, "B": 0.03, "C": 0.01}
        half = scale_weights(w, 0.5)
        assert half == {"A": 0.03, "B": 0.015, "C": 0.005}
        assert scale_weights(half, 2.0) == pytest.approx(w)
        ratios = [half[k] / w[k] for k in w]
        assert len(set(round(r, 12) for r in ratios)) == 1

    def test_composition_is_untouched(self):
        w = {"A": 0.06, "B": 0.03}
        assert set(scale_weights(w, 0.5)) == set(w)

    def test_a_nonsense_exposure_is_ignored_rather_than_applied(self):
        w = {"A": 0.06}
        assert scale_weights(w, -1.0) == w
        assert scale_weights(w, None) == w


def test_the_state_names_its_own_exposure_key():
    assert _call().equity_exposure_key == "stressed"
    assert _call(benchmark_closes=_rising(200)).equity_exposure_key == "normal"


class TestExposureMoves:
    """Turning an exposure change into intents. The brake must be SILENT on the
    ~99% of days it is disengaged, and must preserve relative weights so that
    restoring cannot quietly re-rank the book."""

    W = {"A": 0.06, "B": 0.04, "C": 0.02}

    def test_no_change_produces_no_moves(self):
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        assert plan_exposure_moves(self.W, 1.0, prev_exposure=1.0) == []

    def test_engaging_sells_every_position_by_the_same_factor(self):
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        moves = plan_exposure_moves(self.W, 0.5, prev_exposure=1.0)
        assert {m["action"] for m in moves} == {"risk_reduce"}
        ratios = {m["ticker"]: m["target_weight"] / m["current_weight"] for m in moves}
        assert len(set(round(r, 12) for r in ratios.values())) == 1

    def test_restoring_returns_each_name_to_its_ORIGINAL_share(self):
        """The property that makes this a risk overlay rather than a rebalance:
        a name that was 6% comes back as 6%, not as whatever today's target says."""
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        half = {m["ticker"]: m["target_weight"]
                for m in plan_exposure_moves(self.W, 0.5, prev_exposure=1.0)}
        back = plan_exposure_moves(half, 1.0, prev_exposure=0.5)
        assert {m["action"] for m in back} == {"risk_restore"}
        for m in back:
            assert m["target_weight"] == pytest.approx(self.W[m["ticker"]], abs=1e-9)

    def test_moves_too_small_to_pay_for_themselves_are_dropped(self):
        """A 0.1% nudge across 25 names is 25 orders of pure commission."""
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        moves = plan_exposure_moves({"A": 0.01}, 0.99, prev_exposure=1.0)
        assert moves == []

    def test_an_empty_book_produces_nothing(self):
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        assert plan_exposure_moves({}, 0.5) == []


class TestAnUnknownSignalCannotReRiskTheBook:
    """Defect: the brake failed OPEN on the restore side.

    `engaged=False` answered two different questions with one value — "the
    evidence says no crash" and "there is no evidence" — and `target_exposure`
    mapped both to `normal`. With the book cut to 50% and one session of thin
    breadth, the delta step computed a target of 100% and emitted risk_restore
    buys across every position, while the state's own reason string still read
    "holding exposure".

    The module reasoned correctly about the ENGAGE direction and never
    re-examined the identical state for RESTORE. These fail against that code.
    """

    def _thin_breadth(self):
        """Benchmark fine, breadth unavailable — fewer names than min_names."""
        return evaluate_crash_state(
            benchmark_closes=[100.0] * 300,
            closes_by_ticker={"AAA": [10.0] * 300},
            market_return_window_sessions=20,
            market_return_threshold=-0.06,
            breadth_sma_sessions=100,
            breadth_threshold=0.42,
            min_breadth_names=50,
            enabled=True)

    def _short_benchmark(self):
        return evaluate_crash_state(
            benchmark_closes=[100.0] * 5,
            closes_by_ticker={f"T{i}": [10.0] * 300 for i in range(80)},
            market_return_window_sessions=20,
            market_return_threshold=-0.06,
            breadth_sma_sessions=100,
            breadth_threshold=0.42,
            min_breadth_names=50,
            enabled=True)

    def test_thin_breadth_is_NOT_EVALUABLE_not_merely_disengaged(self):
        s = self._thin_breadth()
        assert s.evaluable is False
        assert s.engaged is False
        assert "holding exposure" in s.reason

    def test_a_short_benchmark_is_NOT_EVALUABLE_either(self):
        assert self._short_benchmark().evaluable is False

    def test_an_unknown_signal_PRESERVES_a_reduced_exposure(self):
        """THE defect, stated as the number it produced. A book at 50% must stay
        at 50%, not be bought back to 100%."""
        assert target_exposure(self._thin_breadth(), 1.0, 0.5, prior=0.5) == 0.5
        assert target_exposure(self._short_benchmark(), 1.0, 0.5, prior=0.5) == 0.5

    def test_an_unknown_signal_ALSO_preserves_a_full_exposure(self):
        """Symmetry: unknown must not de-risk either. A control that cut the book
        on missing data would be the mirror-image bug."""
        assert target_exposure(self._thin_breadth(), 1.0, 0.5, prior=1.0) == 1.0

    def test_the_prior_is_MANDATORY(self):
        """No default. A call site that says nothing would silently keep the
        fail-open behaviour, which is how this survived review."""
        import inspect
        sig = inspect.signature(target_exposure)
        p = sig.parameters["prior"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is inspect.Parameter.empty
        with pytest.raises(TypeError):
            target_exposure(self._thin_breadth(), 1.0, 0.5)

    def test_an_EVALUABLE_state_still_ignores_the_prior(self):
        """The prior is a fallback for ignorance, not hysteresis. Real evidence
        must still move the book, or this fix would have disabled the brake."""
        calm = evaluate_crash_state(
            benchmark_closes=[100.0 + i for i in range(300)],
            closes_by_ticker={f"T{i}": [10.0 + j * 0.1 for j in range(300)]
                              for i in range(80)},
            market_return_window_sessions=20,
            market_return_threshold=-0.06,
            breadth_sma_sessions=100,
            breadth_threshold=0.42,
            min_breadth_names=50,
            enabled=True)
        assert calm.evaluable is True
        assert target_exposure(calm, 1.0, 0.5, prior=0.5) == 1.0, (
            "a genuine all-clear MUST restore, or the brake would never release")

    def test_the_exposure_key_names_the_third_state(self):
        assert self._thin_breadth().equity_exposure_key == "unknown"


class TestNoDeadConfigurationPromisesARiskControl:
    """`stressed_stop_pct` / `stressed_stop_sma_sessions` were in the schema and
    in the ACTIVE config, with a Field description specific enough to be
    believed — and no consumer anywhere. A reader concluded the book tightened
    its stops during a crash. It did not.

    Removed rather than implemented: implementing is a strategy change needing
    wind-tunnel evidence the tunnel cannot currently produce. These tests fail
    against the version that carried the fields.
    """

    def test_the_fields_are_GONE_from_the_schema(self):
        from stock_strategy_shared.schemas.strategy import CrashBrakeConfig
        fields = set(CrashBrakeConfig.model_fields)
        assert "stressed_stop_pct" not in fields
        assert "stressed_stop_sma_sessions" not in fields

    def test_a_config_still_setting_them_is_REJECTED_not_ignored(self):
        """The removal must fail LOUD. Silently accepting the key would leave the
        same false promise with an extra step."""
        import pydantic
        from stock_strategy_shared.schemas.strategy import CrashBrakeConfig
        with pytest.raises(pydantic.ValidationError):
            CrashBrakeConfig(enabled=True, stressed_stop_pct=0.2)
        with pytest.raises(pydantic.ValidationError):
            CrashBrakeConfig(enabled=True, stressed_stop_sma_sessions=100)

    def test_no_module_references_them(self):
        """The falsifier for the actual defect: presence in the schema was never
        the problem, absence of a CONSUMER was."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        def code_only(text: str) -> str:
            # The removal COMMENT names the fields on purpose — it is the record
            # of why they are gone. Searching raw text would make keeping that
            # explanation impossible, which is the wrong trade.
            return "\n".join(ln for ln in text.splitlines()
                             if not ln.lstrip().startswith("#"))
        hits = []
        for pat in ("shared/**/*.py", "services/**/*.py"):
            for f in root.glob(pat):
                if "stressed_stop" in code_only(f.read_text()):
                    hits.append(str(f.relative_to(root)))
        assert hits == [], f"a consumer appeared without the field: {hits}"

    def test_the_surviving_crash_brake_fields_all_HAVE_consumers(self):
        """Generalises the defect rather than fixing one instance of it."""
        import pathlib
        from stock_strategy_shared.schemas.strategy import CrashBrakeConfig
        root = pathlib.Path(__file__).resolve().parents[2]
        src = "\n".join(
            f.read_text() for pat in ("shared/**/*.py", "services/**/*.py")
            for f in root.glob(pat))
        orphans = [n for n in CrashBrakeConfig.model_fields
                   if f'"{n}"' not in src and f"'{n}'" not in src
                   and f".{n}" not in src]
        assert orphans == [], (
            f"crash_brake fields with no consumer: {orphans} — dead config that "
            f"promises a risk control is worse than no config")


class TestTheTransitionRecordMakesDivergenceVISIBLE:
    """Defect 5. The only parity check on this control asserted that the live
    SOURCE CONTAINS a call to evaluate_crash_state. Presence is not equivalence,
    and presence is precisely what let the fail-open restore defect stay green:
    both engines called the shared evaluator, both got engaged=False, and nothing
    the test could see disagreed.

    The decisive property asserted here is that semantic divergence shows up EVEN
    WHEN THE RESULTING EXPOSURE MATCHES.
    """

    def _rec(self, state, prior, target):
        return transition_record(
            state, prior=prior, target=target,
            market_return_threshold=-0.06, breadth_threshold=0.42,
            min_breadth_names=50)

    def _calm(self):
        return evaluate_crash_state(
            benchmark_closes=[100.0 + i for i in range(300)],
            closes_by_ticker={f"T{i}": [10.0 + j * 0.1 for j in range(300)]
                              for i in range(80)},
            market_return_window_sessions=20, market_return_threshold=-0.06,
            breadth_sma_sessions=100, breadth_threshold=0.42,
            min_breadth_names=50, enabled=True)

    def _unknown(self):
        return evaluate_crash_state(
            benchmark_closes=[100.0] * 300,
            closes_by_ticker={"AAA": [10.0] * 300},
            market_return_window_sessions=20, market_return_threshold=-0.06,
            breadth_sma_sessions=100, breadth_threshold=0.42,
            min_breadth_names=50, enabled=True)

    def test_SAME_exposure_by_DIFFERENT_reasoning_does_not_hash_equal(self):
        """THE point of the record. An engine that carries 100% because the market
        is calm and one that carries 100% because it could not evaluate are not in
        parity — they are one input away from disagreeing, and an exposure-only
        comparison says they are identical."""
        calm = self._rec(self._calm(), prior=1.0, target=1.0)
        unknown = self._rec(self._unknown(), prior=1.0, target=1.0)
        assert calm["target_exposure"] == unknown["target_exposure"] == 1.0, (
            "the premise of this test is that the EXPOSURES match")
        assert transition_hash(calm) != transition_hash(unknown), (
            "two different decisions hashed identically — the record cannot "
            "distinguish reasoning from outcome")

    def test_each_predicate_is_recorded_SEPARATELY(self):
        """Two engines can agree on `engaged` while disagreeing about which
        condition carried it. A single boolean hides that."""
        r = self._rec(self._calm(), prior=1.0, target=1.0)
        assert "predicate_market_bad" in r and "predicate_breadth_bad" in r

    def test_an_UNAVAILABLE_predicate_is_None_not_False(self):
        """False means 'evaluated, and no'. None means 'not evaluated'. Folding
        the second into the first is the shape of the original defect."""
        r = self._rec(self._unknown(), prior=0.5, target=0.5)
        assert r["predicate_breadth_bad"] is None
        assert r["evaluable"] is False

    def test_the_record_carries_the_DIRECTION_not_just_two_numbers(self):
        engaged_like = self._rec(self._calm(), prior=1.0, target=0.5)
        assert engaged_like["implied_action"] == "risk_reduce"
        assert self._rec(self._calm(), prior=0.5,
                         target=1.0)["implied_action"] == "risk_restore"
        assert self._rec(self._calm(), prior=1.0,
                         target=1.0)["implied_action"] == "none"

    def test_the_hash_EXCLUDES_the_prose_reason(self):
        """`reason` names thresholds inside formatted strings. Hashing it would
        make a wording change look like a behavioural divergence, which trains
        people to re-pin the hash — which is how a real one gets waved through."""
        import dataclasses
        s = self._calm()
        a = self._rec(s, prior=1.0, target=1.0)
        b = self._rec(dataclasses.replace(s, reason="totally different prose"),
                      prior=1.0, target=1.0)
        assert a["reason"] != b["reason"]
        assert transition_hash(a) == transition_hash(b)

    def test_the_hash_is_STABLE_across_equal_records(self):
        s = self._calm()
        assert (transition_hash(self._rec(s, 1.0, 1.0))
                == transition_hash(self._rec(s, 1.0, 1.0)))

    def test_floats_are_QUANTISED_before_hashing(self):
        """An unrounded float makes the record depend on the interpreter's repr
        rather than on the decision — the exact defect that made several Wealth
        Core hashes interpreter-dependent."""
        r = self._rec(self._calm(), prior=1.0 / 3.0, target=1.0)
        assert len(str(r["prior_exposure"]).split(".")[-1]) <= 10

    def test_BOTH_engines_build_the_record_from_the_SHARED_function(self):
        """Structural: a second implementation would agree until it did not, and
        nothing downstream would notice — this control has already shipped that
        exact failure once."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        for rel in ("services/pipeline/app/main.py",
                    "services/bt-engine/app/sim.py"):
            src = (root / rel).read_text()
            assert "transition_record(" in src, (
                f"{rel} does not emit the canonical transition record")
