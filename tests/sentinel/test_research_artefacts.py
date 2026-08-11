"""Step 3a — the frozen research artefacts as ACCEPTANCE ORACLES.

These files are evidence produced by the research process and frozen with it.
Asserting against them is strictly stronger than re-running the equivalent
experiments, because a re-run can only ever agree with the code that produced
it: it re-derives the answer from the same assumptions and calls the agreement a
result. A frozen artefact was written before this implementation existed and
cannot be argued with.

```text
11_controlled_recovery_adversarial_worlds.csv   3,000 synthetic recoveries
06_exact_gate_plateau.csv                       a 4x5 horizon/threshold grid
05_exact_parameter_plateau.csv                  45 ramp configurations
08_rolling_start_validation.csv                 60 rolling start dates
09_fixed_5y_windows.csv                         15 fixed windows
10_time_blocks.csv                              5 regime blocks
```

## What is NOT asserted here, and why

`07_leave_one_crisis_out.csv` and `04_delay_cost_sensitivity.csv` require
RE-RUNNING the overlay with a crisis removed or a delay applied, which needs the
defensive sleeve's return series — `BIL_total_return` per the frozen rule. BIL is
in no repository artefact, exactly like SPY. Their base rows ARE asserted, since
those describe the tape this repository holds; the perturbed rows move to the NAS
alongside step 2.

Saying so explicitly matters more than the coverage it costs. A certification
suite that quietly skips the rows it cannot compute reads identically to one that
passes them.
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.controller import frozen_rule  # noqa: E402
from sentinel.controller.machine import Controller  # noqa: E402
from tests.sentinel.test_controller_certification import observations  # noqa: E402

ORACLE = ROOT / "docs" / "sentinel-handoff" / "02_SENTINEL_1P1_FROZEN_ORACLE"

#: CALENDAR DAYS / 365.25, solved against the artefacts rather than assumed.
#: A 252-session basis is off by up to 1.5e-3 on a twenty-year CAGR, which is
#: large enough to mask a real difference and small enough to look like
#: rounding — the worst size for an error to be.
DAYS_PER_YEAR = 365.25

#: The residual once the convention is right. Eight parts per million is the
#: CSV's own printed precision, not slack for a disagreement.
CAGR_TOL = 5e-5


def read(name):
    with (ORACLE / name).open() as fh:
        return list(csv.DictReader(fh))


def tape_nav():
    """(dates, candidate_nav) from the frozen daily tape."""
    rows, _ = observations()
    return [r["date"] for r in rows], {r["date"]: float(r["candidate_nav"])
                                       for r in rows}


def cagr(nav, dates, start=None, end=None):
    window = [d for d in dates
              if (start is None or d >= start) and (end is None or d <= end)]
    if len(window) < 2:
        return None
    years = ((dt.date.fromisoformat(window[-1])
              - dt.date.fromisoformat(window[0])).days / DAYS_PER_YEAR)
    return (nav[window[-1]] / nav[window[0]]) ** (1 / years) - 1 if years else None


def max_drawdown(nav, dates, start=None, end=None):
    window = [d for d in dates
              if (start is None or d >= start) and (end is None or d <= end)]
    peak, worst = None, 0.0
    for d in window:
        v = nav[d]
        peak = v if peak is None else max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


class TestTheThreeThousandAdversarialWorlds:
    """The single largest oracle in the handoff, and it lands squarely on the
    one predicate Sentinel 1.1 exists to add.

    Six families of synthetic recovery — clean_v, double_dip, explosive_rebound,
    fragile_recovery, slow_bear, whipsaw — 500 worlds each, every one carrying
    its `delta_r40_5` and the verdict the frozen gate reached on it. Seven
    historical recoveries cannot distinguish a correct comparison from one that
    happens to agree seven times; three thousand can.
    """

    def test_the_gate_reproduces_ALL_THREE_THOUSAND_verdicts(self):
        cfg = frozen_rule.load()
        ctl = Controller(cfg)
        worlds = read("11_controlled_recovery_adversarial_worlds.csv")
        assert len(worlds) == 3000

        wrong = [(w["family"], w["world"], w["delta_r40_5"], w["flagged"])
                 for w in worlds
                 if ctl.is_fragile(float(w["delta_r40_5"]))
                 is not (w["flagged"].strip().lower() == "true")]
        assert not wrong, f"{len(wrong)} gate verdicts disagree, e.g. {wrong[:5]}"

    def test_every_family_is_actually_exercised(self):
        """A pass over 3,000 rows that are all one family would prove much less.
        The summary file states the flag rates, and they differ per family —
        clean_v flags nothing, fragile_recovery flags 82.4% — so the corpus
        genuinely spans both verdicts."""
        import collections

        worlds = read("11_controlled_recovery_adversarial_worlds.csv")
        by_family = collections.Counter(w["family"] for w in worlds)
        assert len(by_family) == 6 and set(by_family.values()) == {500}

        summary = {r["family"]: float(r["flag_rate"])
                   for r in read("12_controlled_recovery_adversarial_summary.csv")}
        cfg = frozen_rule.load()
        ctl = Controller(cfg)
        for family, want in summary.items():
            rows = [w for w in worlds if w["family"] == family]
            got = sum(1 for w in rows
                      if ctl.is_fragile(float(w["delta_r40_5"]))) / len(rows)
            assert abs(got - want) < 1e-9, f"{family}: {got} vs {want}"

    def test_the_families_disagree_with_each_other(self):
        """clean_v flags nothing and fragile_recovery flags most. A gate that
        answered the same way everywhere would pass the row-by-row test above
        only if the data were degenerate; this says it is not."""
        summary = {r["family"]: float(r["flag_rate"])
                   for r in read("12_controlled_recovery_adversarial_summary.csv")}
        assert summary["clean_v"] == 0.0
        assert summary["fragile_recovery"] > 0.8


class TestTheGatePlateauGrid:
    """`06_exact_gate_plateau.csv` sweeps the gate over four horizons and five
    thresholds and records how many of the seven historical recoveries each
    combination flags. Twenty cells, and the counts are not all equal — which
    is what makes it a discriminating oracle rather than a constant."""

    def _flagged(self, horizon: int, threshold: float) -> int:
        """How many recoveries this (horizon, threshold) would flag.

        `delta_r40` at each horizon is computed the way the controller computes
        it — at the PRIOR CLOSE — from the tape's own r40 series.
        """
        rows, _ = observations()
        idx = {r["date"]: i for i, r in enumerate(rows)}
        r40 = [float(r["r40"]) if r["r40"] not in ("", "nan") else None
               for r in rows]
        n = 0
        for g in read("02_recovery_gate_flags.csv"):
            i = idx[g["prior_close"]]
            if i < horizon or r40[i] is None or r40[i - horizon] is None:
                continue
            if (r40[i] - r40[i - horizon]) <= threshold:
                n += 1
        return n

    def test_every_cell_of_the_grid_matches(self):
        grid = read("06_exact_gate_plateau.csv")
        assert len(grid) == 20
        wrong = []
        for cell in grid:
            h, t = int(cell["horizon"]), float(cell["threshold"])
            got, want = self._flagged(h, t), int(cell["n_flagged"])
            if got != want:
                wrong.append((h, t, got, want))
        assert not wrong, f"gate-plateau cells disagree: {wrong}"

    def test_the_grid_is_not_degenerate(self):
        counts = {int(c["n_flagged"]) for c in read("06_exact_gate_plateau.csv")}
        assert len(counts) > 1, (
            "every cell flags the same number, so matching it proves nothing")


class TestTheParameterPlateauGrid:
    """`05_exact_parameter_plateau.csv`: 45 ramp configurations, each with the
    number of allocation TRANSITIONS it produces. Transitions are computable
    from the allocation path alone — no NAV overlay, no BIL — so this grid is
    assertable here in full."""

    def _transitions(self, first, second, confirm) -> int:
        import dataclasses

        base = frozen_rule.load()
        cfg = dataclasses.replace(base, ramp=dataclasses.replace(
            base.ramp, steps=(first, second, 1.0),
            confirmation_sessions=(confirm, confirm)))
        rows, obs = observations()
        ctl = Controller(cfg)
        st = ctl.initial_state()
        prev, n = None, 0
        for i, (row, ob) in enumerate(zip(rows, obs)):
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            st, d = ctl.step_with_parent(
                observation=ob, state=st,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)
            if prev is not None and abs(d.target_core_exposure - prev) > 1e-12:
                n += 1
            prev = d.target_core_exposure
        return n

    def test_the_frozen_configuration_matches_its_own_row(self):
        """0.55 / 0.65 / 10 is the shipped rule; its transition count is the
        anchor the other 44 rows are deltas from."""
        row = next(r for r in read("05_exact_parameter_plateau.csv")
                   if r["name"] == "55-65-100_n10")
        assert self._transitions(0.55, 0.65, 10) == int(row["transitions"])

    @pytest.mark.parametrize("name", ["60-65-100_n10", "55-65-100_n9",
                                      "55-65-100_n12", "60-65-100_n12"])
    def test_neighbouring_configurations_match_too(self, name):
        """One matching cell can be luck. Four neighbours along both axes —
        step level and confirmation count — cannot all be."""
        row = next(r for r in read("05_exact_parameter_plateau.csv")
                   if r["name"] == name)
        got = self._transitions(float(row["first"]), float(row["second"]),
                                int(row["confirm"]))
        assert got == int(row["transitions"]), f"{name}: {got} vs {row['transitions']}"


class TestTheWindowedPerformanceOracles:
    """Rolling starts, fixed windows and regime blocks, computed from the
    tape's own `candidate_nav`.

    These need no overlay re-run: the frozen tape already carries the NAV the
    candidate strategy produced, so a windowed CAGR is a direct read. The year
    basis was SOLVED against the artefacts rather than assumed — calendar days
    over 365.25, which lands within 9e-6, where a 252-session basis is off by
    1.5e-3.
    """

    def test_all_sixty_rolling_starts(self):
        dates, nav = tape_nav()
        wrong = []
        for r in read("08_rolling_start_validation.csv"):
            got = cagr(nav, dates, start=r["start"])
            want = float(r["candidate_cagr"])
            if got is None or abs(got - want) > CAGR_TOL:
                wrong.append((r["start"], got, want))
        assert not wrong, f"{len(wrong)} rolling starts disagree: {wrong[:4]}"

    def test_all_fifteen_fixed_five_year_windows(self):
        dates, nav = tape_nav()
        wrong = []
        for r in read("09_fixed_5y_windows.csv"):
            got = cagr(nav, dates, start=r["start"], end=r["end"])
            want = float(r["candidate_cagr"])
            if got is None or abs(got - want) > CAGR_TOL:
                wrong.append((r["start"], r["end"], got, want))
        assert not wrong, f"{len(wrong)} fixed windows disagree: {wrong[:4]}"

    def test_the_five_regime_blocks(self):
        dates, nav = tape_nav()
        wrong = []
        for r in read("10_time_blocks.csv"):
            got = cagr(nav, dates, start=r["start"], end=r["end"])
            want = float(r["candidate_cagr"])
            if got is None or abs(got - want) > CAGR_TOL:
                wrong.append((r["block"], got, want))
        assert not wrong, f"{len(wrong)} time blocks disagree: {wrong}"

    def test_the_drawdowns_agree_too(self):
        """CAGR alone can match while the path differs. Max drawdown is the
        other half of every one of these rows and it reads the whole series."""
        dates, nav = tape_nav()
        wrong = []
        for r in read("09_fixed_5y_windows.csv"):
            got = max_drawdown(nav, dates, start=r["start"], end=r["end"])
            want = float(r["candidate_dd"])
            if abs(got - want) > 1e-6:
                wrong.append((r["start"], got, want))
        assert not wrong, f"{len(wrong)} window drawdowns disagree: {wrong[:4]}"


class TestTheHeadlineMetrics:
    def test_the_twenty_year_numbers_match_the_frozen_rule(self):
        """The frozen rule states its own reference metrics. Recomputing them
        from the tape closes the loop between the two artefacts."""
        import json

        want = json.loads(frozen_rule.RULE_PATH.read_text())[
            "reference_metrics_2006_07_31_to_2026_07_31"]
        dates, nav = tape_nav()
        assert abs(cagr(nav, dates) - want["cagr"]) < CAGR_TOL
        assert abs(max_drawdown(nav, dates) - want["max_drawdown"]) < 1e-6
        assert abs(nav[dates[-1]] / nav[dates[0]]
                   - want["ending_multiple"]) < 1e-6

    def test_the_base_rows_of_the_BLOCKED_grids_still_match(self):
        """`04_delay_cost_sensitivity` and `07_leave_one_crisis_out` need an
        overlay re-run with BIL, which no artefact carries. Their UNPERTURBED
        rows describe the tape this repository holds, so those are asserted —
        and the perturbed ones are named as NAS work rather than skipped
        silently."""
        dates, nav = tape_nav()
        base_cagr = cagr(nav, dates)

        delay0 = next(r for r in read("04_delay_cost_sensitivity.csv")
                      if r["name"] == "delay_0")
        assert abs(float(delay0["cagr"]) - base_cagr) < CAGR_TOL

        # GFC and COVID are recorded with zero change vs the full candidate —
        # the strategy's severe path never fired inside those exclusions — so
        # their rows equal the base and ARE checkable without a re-run.
        for crisis in ("GFC", "COVID"):
            row = next(r for r in read("07_leave_one_crisis_out.csv")
                       if r["crisis"] == crisis)
            assert float(row["cagr_change_vs_full_candidate"]) == 0.0
            assert abs(float(row["cagr"]) - base_cagr) < CAGR_TOL


class TestTheGateBOUNDARY:
    """`delta_r40_5 == 0.0` exactly — the one case 3,007 oracle rows never hit.

    Found by mutation: changing `<=` to `<` leaves every artefact assertion in
    this module green. The closest any of the 3,000 adversarial worlds comes to
    zero is 4.3e-6, and none of the seven historical recoveries is exactly zero
    either, so the boundary the frozen rule actually specifies is untested by
    the entire research corpus.

    It is not a hypothetical. The rule was TIGHTENED to this comparison — from
    `<= +0.01` to `<= 0.0` — so the boundary is where the author deliberately
    put the line, and a flat r40 window over five sessions produces exactly
    zero. `<` there would call a fragile recovery healthy and go straight to
    100% instead of ramping 0.55 -> 0.65 -> 1.0.
    """

    def test_exactly_zero_is_FRAGILE(self):
        ctl = Controller(frozen_rule.load())
        assert ctl.is_fragile(0.0) is True, (
            "the frozen rule is `<= 0.0`; `< 0.0` sends a flat recovery "
            "straight to full exposure")

    def test_just_above_zero_is_NOT(self):
        ctl = Controller(frozen_rule.load())
        assert ctl.is_fragile(1e-12) is False

    def test_just_below_zero_IS(self):
        ctl = Controller(frozen_rule.load())
        assert ctl.is_fragile(-1e-12) is True

    def test_an_UNEVALUABLE_gate_is_neither(self):
        """None is not False. A recovery whose gate cannot be computed has not
        been shown to be robust, and the caller fails it closed."""
        ctl = Controller(frozen_rule.load())
        assert ctl.is_fragile(None) is None
