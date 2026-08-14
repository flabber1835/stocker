"""Falsifiers for the recovered breadth classifier.

Every predicate in `sentinel/breadth/` is strict-vs-inclusive somewhere, and a
strictness error is invisible in aggregate: it moves a count by one holding on
the rare sessions where a metric lands exactly on a threshold. So the tests here
are written AT the thresholds, and each one is paired — the value on the
boundary and the value one step across it — because a test that only checks the
far side passes against `>` and `>=` alike.

Two of these are not unit tests of this module at all:

```text
TestDifferentialAgainstTheRecoveredArtefact
    randomised cross-check against the pandas classifier stored in docs/. The
    docs artefact is never imported at runtime; it is imported HERE so that a
    semantic drift in the transcription fails the suite offline instead of
    surviving until the NAS run

TestTheFloat32LagContract
    the lag-close precision rule, with a fixture that CHANGES a classification
    under float64. Without it, an all-float64 reimplementation passes every
    other test in this file
```

None of this is corpus certification. It proves the transcription matches its
source and that the boundaries behave; reproducing the 7,061-session tape
against the corrected lineage is the separate NAS step.
"""
from __future__ import annotations

import importlib.util
import math
import os
import random
import sys
from pathlib import Path

import pytest

from sentinel.breadth import (
    GREEN_R63_REQUIRED_FROM_AGE,
    Holding,
    is_amber,
    is_green,
    is_red,
    lag_return,
    own_drawdown,
    sector_stress,
    session_breadth,
    to_float32,
)

SUITE_ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or SUITE_ROOT)
RECOVERED = (SUITE_ROOT / "docs" / "sentinel-breadth-reconstruction"
             / "recovered_breadth_classifier.py")
STANDALONE = (SUITE_ROOT / "docs" / "sentinel-reference-implementation"
              / "sentinel_1p1_standalone.py")


def h(own_dd=0.0, r21=0.01, r63=0.01, age=1000, sector="TECH", ticker="AAA"):
    """A GREEN holding by default, so each test moves ONE thing."""
    return Holding(ticker=ticker, sector=sector, own_dd=own_dd, r21=r21,
                   r63=r63, age_sessions=age)


class TestGreenBoundaries:
    def test_own_dd_exactly_zero_is_GREEN(self):
        # A book marked precisely at its peak is the common case, not an
        # exotic one. `>= -0.075` and `> -0.075` agree here; the point of the
        # case is that a sign or off-by-one in the guard shows up immediately.
        assert is_green(h(own_dd=0.0)) is True

    def test_own_dd_exactly_at_the_GREEN_threshold_is_NOT_green(self):
        # STRICT: `own_dd > -0.075`. -0.075 itself fails.
        assert is_green(h(own_dd=-0.075)) is False

    def test_own_dd_just_above_the_threshold_IS_green(self):
        assert is_green(h(own_dd=-0.0749)) is True

    def test_r21_exactly_zero_is_NOT_green(self):
        # STRICT: `r21 > 0`. This is the boundary the float32 lag contract
        # moves — see TestTheFloat32LagContract.
        assert is_green(h(r21=0.0)) is False

    def test_r21_just_above_zero_IS_green(self):
        assert is_green(h(r21=1e-9)) is True

    def test_r63_exactly_zero_is_NOT_green_once_the_age_gate_applies(self):
        # STRICT: `r63 > 0`, and only consulted at age >= 63.
        assert is_green(h(r63=0.0, age=GREEN_R63_REQUIRED_FROM_AGE)) is False

    def test_r63_just_above_zero_IS_green(self):
        assert is_green(h(r63=1e-9, age=GREEN_R63_REQUIRED_FROM_AGE)) is True


class TestTheAge63Exemption:
    """The clause absent from every prose summary of GREEN.

    It governs every newly admitted position, and admissions are one per
    session at 4% of equity — so a book rebuilding after a recovery is mostly
    holdings inside this band. An implementation that requires r63
    unconditionally under-counts green exactly when the recovery ramp reads it.
    """

    def test_age_62_is_GREEN_with_a_NEGATIVE_r63(self):
        assert is_green(h(r63=-0.99, age=62)) is True

    def test_age_63_is_NOT_green_with_the_same_negative_r63(self):
        assert is_green(h(r63=-0.99, age=63)) is False

    def test_age_62_is_GREEN_with_r63_entirely_ABSENT(self):
        # Waived, not defaulted. A young holding is green on own_dd and r21
        # alone; r63 is never consulted, so None must not fail it.
        assert is_green(h(r63=None, age=62)) is True
        assert is_green(h(r63=float("nan"), age=62)) is True

    def test_age_63_with_r63_ABSENT_is_NOT_green(self):
        assert is_green(h(r63=None, age=63)) is False

    def test_age_63_with_a_POSITIVE_r63_is_green(self):
        assert is_green(h(r63=0.01, age=63)) is True


class TestRedBoundaries:
    def test_own_dd_exactly_at_minus_10pct_with_negative_r21_IS_red(self):
        # INCLUSIVE on drawdown: `own_dd <= -0.10`.
        assert is_red(h(own_dd=-0.10, r21=-0.01)) is True

    def test_own_dd_just_above_minus_10pct_is_NOT_red(self):
        assert is_red(h(own_dd=-0.0999, r21=-0.01)) is False

    def test_r21_exactly_zero_is_NOT_red(self):
        # STRICT: `r21 < 0`. A flat holding at -10% drawdown is not RED, and
        # therefore does not feed its sector's stress numerator.
        assert is_red(h(own_dd=-0.20, r21=0.0)) is False

    def test_r21_just_below_zero_IS_red(self):
        assert is_red(h(own_dd=-0.20, r21=-1e-9)) is True


class TestAmberBoundaries:
    def test_r21_exactly_minus_3pct_IS_amber(self):
        # INCLUSIVE, unlike every GREEN and RED comparison on r21.
        assert is_amber(h(r21=-0.03), stress=0.0, green=False) is True

    def test_r21_just_above_minus_3pct_is_NOT_amber(self):
        assert is_amber(h(r21=-0.0299), stress=0.0, green=False) is False

    def test_own_dd_exactly_minus_10pct_IS_amber(self):
        assert is_amber(h(own_dd=-0.10), stress=0.0, green=False) is True

    def test_own_dd_just_above_minus_10pct_is_NOT_amber(self):
        assert is_amber(h(own_dd=-0.0999), stress=0.0, green=False) is False


class TestSectorEscalation:
    def test_stress_exactly_half_escalates_a_NON_green_holding(self):
        # INCLUSIVE: `sector_stress >= 0.50`.
        assert is_amber(h(), stress=0.50, green=False) is True

    def test_stress_just_below_half_does_NOT_escalate(self):
        assert is_amber(h(), stress=0.4999, green=False) is False

    def test_stress_at_half_does_NOT_escalate_a_GREEN_holding(self):
        # `AND NOT green` — a healthy name in a burning sector stays out of the
        # damaged count. Dropping this clause inflates damaged breadth exactly
        # during a sector rout, which is when the severe thresholds are read.
        assert is_amber(h(), stress=0.50, green=True) is False

    def test_stress_at_ONE_still_does_not_escalate_a_green_holding(self):
        assert is_amber(h(), stress=1.0, green=True) is False

    def test_sector_stress_is_the_RED_fraction_within_each_sector(self):
        book = [
            h(ticker="A", sector="TECH", own_dd=-0.20, r21=-0.05),   # red
            h(ticker="B", sector="TECH"),                            # not red
            h(ticker="C", sector="FIN", own_dd=-0.20, r21=-0.05),    # red
            h(ticker="D", sector="FIN", own_dd=-0.20, r21=-0.05),    # red
        ]
        assert sector_stress(book) == {"TECH": 0.5, "FIN": 1.0}

    def test_an_UNKNOWN_sector_is_its_own_bucket_not_dropped(self):
        # Dropping None would shrink a stressed sector's denominator and
        # understate its stress.
        book = [h(ticker="A", sector=None, own_dd=-0.20, r21=-0.05),
                h(ticker="B", sector=None)]
        assert sector_stress(book) == {None: 0.5}

    def test_escalation_reaches_the_damaged_count_through_session_breadth(self):
        # Two of four TECH names are RED -> stress 0.50 -> the two healthy but
        # non-green names escalate. Proves the wiring, not just the predicate.
        book = [
            h(ticker="A", sector="TECH", own_dd=-0.20, r21=-0.05),
            h(ticker="B", sector="TECH", own_dd=-0.20, r21=-0.05),
            h(ticker="C", sector="TECH", own_dd=-0.01, r21=0.0),
            h(ticker="D", sector="TECH", own_dd=-0.01, r21=0.0),
        ]
        b = session_breadth(book)
        assert b.reds == 2
        assert b.greens == 0            # r21 == 0 is not green
        assert b.ambers == 4            # 2 by damage, 2 by escalation
        assert b.damaged_breadth == 1.0


class TestTheDenominator:
    def test_breadth_divides_by_the_HELD_COUNT(self):
        book = [h(ticker="A"), h(ticker="B"), h(ticker="C", r21=-0.05),
                h(ticker="D", r21=-0.05)]
        b = session_breadth(book)
        assert b.denominator == 4
        assert b.green_breadth == 0.5
        assert b.damaged_breadth == 0.5

    def test_an_EMPTY_book_is_zero_and_zero_not_NaN(self):
        # Reachable in production: a cold start before the first fill.
        b = session_breadth([])
        assert (b.damaged_breadth, b.green_breadth, b.denominator) == (0.0, 0.0, 0)

    def test_green_and_damaged_need_NOT_sum_to_one(self):
        # They are disjoint but do not partition the book. A classifier that
        # forces the complement has changed the strategy.
        book = [h(ticker="A"), h(ticker="B", own_dd=-0.05, r21=-0.01)]
        b = session_breadth(book)
        assert b.green_breadth == 0.5
        assert b.damaged_breadth == 0.0
        assert b.green_breadth + b.damaged_breadth != 1.0

    def test_RED_never_enters_either_fraction_directly(self):
        # A lone RED name in an otherwise calm book: it is amber by its own
        # damage, and its sector stress is 1.0 but it is alone in that sector.
        book = [h(ticker="A", sector="ENERGY", own_dd=-0.20, r21=-0.05),
                h(ticker="B", sector="TECH"), h(ticker="C", sector="TECH")]
        b = session_breadth(book)
        assert b.reds == 1
        assert b.ambers == 1
        assert b.greens == 2
        # The RED count is 1/3 of the book, but neither fraction is 1/3: the
        # name is counted once as AMBER, and RED contributes nothing of its own.
        assert b.damaged_breadth == 1 / 3        # the amber, not the red
        assert b.green_breadth == 2 / 3
        assert b.reds / b.denominator not in (b.green_breadth,)


class TestUnavailableIsNotZero:
    """None and NaN mean "we could not evaluate this" and must fail every
    predicate — never be coerced into a passing zero. Same rule as the
    controller's evidence records."""

    @pytest.mark.parametrize("absent", [None, float("nan")])
    def test_absent_own_dd_is_not_green_and_not_red(self, absent):
        assert is_green(h(own_dd=absent)) is False
        assert is_red(h(own_dd=absent, r21=-0.05)) is False

    @pytest.mark.parametrize("absent", [None, float("nan")])
    def test_absent_r21_is_not_green_and_not_red(self, absent):
        assert is_green(h(r21=absent)) is False
        assert is_red(h(own_dd=-0.20, r21=absent)) is False

    @pytest.mark.parametrize("absent", [None, float("nan")])
    def test_a_holding_with_NO_metrics_is_amber_ONLY_via_escalation(self, absent):
        blind = h(own_dd=absent, r21=absent, r63=absent)
        assert is_amber(blind, stress=0.0, green=False) is False
        assert is_amber(blind, stress=0.50, green=False) is True

    def test_infinities_are_unavailable_too(self):
        assert is_green(h(own_dd=float("inf"))) is False
        assert is_red(h(own_dd=float("-inf"), r21=-0.05)) is False


class TestTheFloat32LagContract:
    """The retained replay stored lag closes in float32 before dividing.

    Reproducing it in all-float64 shifts r21/r63 by ~1e-8 relative, and every
    boundary in this classifier is strict-vs-inclusive. The fixture below turns
    that into a CLASSIFICATION change, so an all-float64 implementation fails
    here rather than drifting silently against the tape.
    """

    def test_to_float32_matches_numpy(self):
        np = pytest.importorskip("numpy")
        for v in (100.1, 0.1, 1e-8, 12345.6789, 3.0, -7.25, 1e30):
            assert to_float32(v) == float(np.float32(v))

    def test_an_UNCHANGED_price_is_green_under_float32_and_NOT_under_float64(self):
        # THE falsifier. Current close == lag close == 100.1.
        #   float64 lag -> r21 == 0.0            -> `r21 > 0` fails -> NOT green
        #   float32 lag -> r21 == +1.52e-08      -> `r21 > 0` holds -> GREEN
        close = 100.1
        contract = lag_return(close, close)
        naive = close / close - 1.0

        assert naive == 0.0
        assert contract > 0.0
        assert is_green(h(r21=naive)) is False
        assert is_green(h(r21=contract)) is True

    def test_the_same_fixture_moves_the_SESSION_breadth(self):
        # Not just a predicate: the scalar the controller reads changes.
        close = 100.1
        book_naive = [h(ticker="A", r21=close / close - 1.0)]
        book_contract = [h(ticker="A", r21=lag_return(close, close))]
        assert session_breadth(book_naive).green_breadth == 0.0
        assert session_breadth(book_contract).green_breadth == 1.0

    def test_a_non_positive_lag_is_UNAVAILABLE_not_a_minus_100pct_return(self):
        assert math.isnan(lag_return(50.0, 0.0))
        assert math.isnan(lag_return(50.0, -1.0))

    def test_absent_inputs_propagate_as_NaN(self):
        assert math.isnan(lag_return(None, 100.0))
        assert math.isnan(lag_return(100.0, None))
        assert math.isnan(lag_return(float("nan"), 100.0))

    def test_own_drawdown_is_NOT_float32_rounded(self):
        # The episode peak is stored as a Python float, never through the ring
        # (standalone:474). Rounding it would be a defect, not a tightening.
        peak = 100.1
        assert own_drawdown(peak, peak) == 0.0
        assert own_drawdown(peak, peak) != peak / to_float32(peak) - 1.0

    def test_own_drawdown_rejects_a_non_positive_peak(self):
        assert math.isnan(own_drawdown(50.0, 0.0))
        assert math.isnan(own_drawdown(50.0, None))


def _load_recovered_artefact():
    """Import the stored pandas classifier from docs/ FOR TESTING ONLY.

    `sentinel/` must never do this — it is pure and stdlib-only. The import
    lives here so the production transcription is checked against its authority
    on every run.
    """
    pytest.importorskip("pandas")
    pytest.importorskip("numpy")
    spec = importlib.util.spec_from_file_location("_recovered_breadth", RECOVERED)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: the artefact defines a @dataclass, and the
    # decorator resolves annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDifferentialAgainstTheRecoveredArtefact:
    """Randomised cross-check against `recovered_breadth_classifier.py`.

    The values are drawn to CLUSTER ON THE THRESHOLDS — uniform noise almost
    never lands on -0.075 or -0.03, which is exactly where a transcription
    error lives. Any disagreement on green, red, amber or the two fractions
    fails, naming the holding.
    """

    def test_the_stored_artefact_is_present_and_is_the_authority(self):
        assert RECOVERED.is_file()
        assert STANDALONE.is_file()

    def test_randomised_books_agree_on_every_holding_and_both_fractions(self):
        mod = _load_recovered_artefact()
        import pandas as pd

        edges = [-0.075, -0.10, -0.03, 0.0, 0.5, -0.0749, -0.0751,
                 -0.0999, -0.1001, -0.0299, -0.0301, 1e-9, -1e-9]
        sectors = ["TECH", "FIN", "ENERGY"]
        rng = random.Random(20260812)

        for trial in range(300):
            n = rng.randint(1, 12)
            book = []
            for i in range(n):
                pick = lambda: (rng.choice(edges) if rng.random() < 0.65
                                else rng.uniform(-0.4, 0.4))
                book.append(Holding(
                    ticker=f"T{i}",
                    sector=rng.choice(sectors),
                    own_dd=pick(),
                    r21=pick(),
                    r63=pick(),
                    age_sessions=rng.choice([0, 1, 61, 62, 63, 64, 500]),
                ))

            ours = session_breadth(book)
            frame = pd.DataFrame([{
                "sector": b.sector, "age_sessions": b.age_sessions,
                "own_dd": b.own_dd, "r21": b.r21, "r63": b.r63,
            } for b in book])
            theirs, _ = mod.recovered_breadth_features(frame)

            for i, label in enumerate(ours.labels):
                ctx = f"trial={trial} holding={i} {book[i]}"
                assert label.green == bool(theirs["green"].iloc[i]), f"green {ctx}"
                assert label.red == bool(theirs["red"].iloc[i]), f"red {ctx}"
                assert label.amber == bool(theirs["amber"].iloc[i]), f"amber {ctx}"

            assert ours.green_breadth == pytest.approx(
                float(theirs["green"].mean()), abs=1e-12), f"green_b trial={trial}"
            assert ours.damaged_breadth == pytest.approx(
                float(theirs["amber"].mean()), abs=1e-12), f"damaged_b trial={trial}"


class TestPriorityIsNotHere:
    """`priority` is an unused output of the historical helper. Sentinel's
    breadth dependency is mean(amber) and mean(green), both recovered. These
    assert the production surface stays narrow — they are not a placeholder
    for work owed."""

    def test_the_production_module_exposes_no_priority(self):
        import sentinel.breadth as breadth
        assert not [n for n in dir(breadth) if "priority" in n.lower()]

    def test_the_production_module_does_not_reproduce_position_features(self):
        import sentinel.breadth as breadth
        assert not hasattr(breadth, "position_features")

    def test_the_recovered_artefact_still_FAILS_CLOSED_on_priority(self):
        # Preserved behaviour, not new behaviour: a guessed ranking would run,
        # produce plausible cohorts and be wrong with no symptom.
        mod = _load_recovered_artefact()
        import pandas as pd

        frame = pd.DataFrame([{"sector": "TECH", "age_sessions": 100,
                               "own_dd": 0.0, "r21": 0.01, "r63": 0.01}])
        with pytest.raises(mod.PriorityNotRecoveredError):
            mod.position_features(frame)


class TestTheModuleIsPure:
    """No oracle tape, no docs/ dependency, no frozen CSV, no hidden fallback."""

    def test_no_source_file_references_docs_or_a_tape(self):
        forbidden = ("docs/", "oracle", ".csv", "BREADTH_ORACLES", "sentinel-handoff")
        for path in sorted((REPO / "sentinel" / "breadth").glob("*.py")):
            body = path.read_text()
            code = "\n".join(_executable_lines(body))
            for needle in forbidden:
                assert needle not in code, f"{path.name} reaches for {needle!r}"

    def test_it_imports_nothing_outside_the_stdlib(self):
        allowed = {"math", "struct", "dataclasses", "typing", "__future__"}
        for path in sorted((REPO / "sentinel" / "breadth").glob("*.py")):
            for line in _executable_lines(path.read_text()):
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    root = stripped.split()[1].split(".")[0]
                    assert root in allowed or root == "", f"{path.name}: {stripped}"

    def test_classification_is_deterministic_across_repeated_calls(self):
        book = [h(ticker="A"), h(ticker="B", own_dd=-0.2, r21=-0.05)]
        first = session_breadth(book)
        for _ in range(5):
            assert session_breadth(book) == first


def _executable_lines(body: str):
    """Lines outside docstrings and comments.

    The module docstrings CITE `docs/...` paths as provenance, which is the
    point of them. Only executable code is checked for those needles.
    """
    out = []
    in_doc = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            ticks = stripped.count('"""') + stripped.count("'''")
            if not (ticks >= 2 and len(stripped) > 3):
                in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#") or not stripped:
            continue
        out.append(line.split("#")[0])
    return out


class TestTheSeamIntoTheController:
    def test_it_returns_exactly_the_two_Observation_fields(self):
        from sentinel.breadth import breadth_observation_fields

        fields = breadth_observation_fields([h(ticker="A")])
        assert set(fields) == {"damaged_breadth", "green_breadth"}

    def test_the_values_are_accepted_by_the_controller_Observation(self):
        # Proves the chain is POSSIBLE. It does not activate it — nothing here
        # calls decide(), and the seam stays empty until the NAS run.
        from sentinel.breadth import breadth_observation_fields
        from sentinel.controller.machine import Observation

        book = [h(ticker="A"), h(ticker="B", own_dd=-0.2, r21=-0.05)]
        ob = Observation(session="2026-08-12", **breadth_observation_fields(book))
        assert ob.green_breadth == 0.5
        assert ob.damaged_breadth == 0.5
