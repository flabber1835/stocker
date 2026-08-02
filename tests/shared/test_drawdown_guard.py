"""Portfolio-drawdown attribution — the report, and the fact that it stays a report.

The whole value is in one distinction: a drawdown driven by ONE name is a
position-level failure, and the same drawdown spread across the book is the
correlated market decline the crash brake addresses. Selling the "culprits" in
the second case is what the motivating evidence showed destroying CAGR. So the
tests that matter are the ones that keep those two shapes distinguishable, and
the one that keeps this module from ever emitting an order.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.drawdown_guard import (approaching_stops,
                                                  average_pairwise_correlation,
                                                  below_sma, build_report,
                                                  drawdown_velocity,
                                                  loss_contributions,
                                                  portfolio_drawdown)


def _equity(peak=100_000.0, drop=0.06, n=60):
    rise = [peak * (0.9 + 0.1 * i / max(1, n // 2)) for i in range(n // 2)]
    fall = [peak * (1 - drop * i / max(1, n // 2)) for i in range(n // 2)]
    return rise + fall


class TestDrawdown:
    def test_it_measures_peak_to_now(self):
        assert portfolio_drawdown([100.0, 120.0, 90.0]) == pytest.approx(90 / 120 - 1)

    def test_the_peak_is_not_forgotten(self):
        """A guard that trails its own watermark resets mid-drawdown and goes
        quiet exactly when the drawdown is worst."""
        eq = [100.0, 200.0] + [110.0] * 300
        assert portfolio_drawdown(eq) == pytest.approx(110 / 200 - 1)

    def test_too_little_history_is_unknown(self):
        assert portfolio_drawdown([100.0]) is None


class TestLossAttribution:
    def test_shares_are_over_LOSSES_not_net_pnl(self):
        """Netting winners against losers makes the shares uninterpretable — near
        a zero net they explode — and 'which names are doing the damage' is not a
        question winners answer."""
        out = loss_contributions({"BAD": -900.0, "OK": -100.0, "GOOD": +5000.0})
        assert [c["ticker"] for c in out] == ["BAD", "OK"]
        assert out[0]["share_of_loss"] == pytest.approx(0.9)
        assert sum(c["share_of_loss"] for c in out) == pytest.approx(1.0)

    def test_worst_first(self):
        out = loss_contributions({"A": -10.0, "B": -50.0, "C": -30.0})
        assert [c["ticker"] for c in out] == ["B", "C", "A"]

    def test_an_all_winners_book_attributes_nothing(self):
        assert loss_contributions({"A": 10.0, "B": 5.0}) == []


class TestTheDistinctionThatMatters:
    def _report(self, pnl, **over):
        kw = dict(equity=_equity(drop=0.10), position_pnl=pnl,
                  warning_drawdown=0.05, attribution_drawdown=0.08)
        kw.update(over)
        return build_report(**kw)

    def test_a_concentrated_drawdown_is_named_as_such(self):
        r = self._report({"BAD": -8000.0, **{f"T{i}": -100.0 for i in range(24)}})
        assert r.top1_share > 0.5
        assert any("CONCENTRATED" in n for n in r.notes)
        assert not any("DIFFUSE" in n for n in r.notes)

    def test_a_diffuse_drawdown_is_named_as_such(self):
        r = self._report({f"T{i}": -400.0 for i in range(25)})
        assert r.top3_share <= 0.5
        assert any("DIFFUSE" in n for n in r.notes)
        assert any("crash brake" in n for n in r.notes)

    def test_the_diffuse_note_says_culprit_selling_would_not_help(self):
        """The note exists to stop the reader drawing the wrong conclusion from a
        correctly-computed table — which is what the source evidence showed
        happening."""
        r = self._report({f"T{i}": -400.0 for i in range(25)})
        assert any("would not have helped" in n for n in r.notes)


class TestThresholdLadder:
    def _r(self, drop):
        return build_report(equity=_equity(drop=drop),
                            position_pnl={"A": -100.0},
                            warning_drawdown=0.05, attribution_drawdown=0.08)

    def test_below_the_warning_nothing_is_attributed(self):
        """Attributing on every ordinary session is packet noise."""
        r = self._r(0.02)
        assert r.breached is None and r.contributors == []

    def test_warning_then_attribution(self):
        assert self._r(0.06).breached == "warning"
        assert self._r(0.12).breached == "attribution"


class TestSupportingSignals:
    def test_velocity_separates_a_cliff_from_a_grind(self):
        cliff = [100.0] * 50 + [100.0 * (1 - 0.01 * i) for i in range(1, 11)]
        assert drawdown_velocity(cliff, 10) < -0.09

    def test_below_sma_excludes_short_histories_from_both_sides(self):
        uni = {f"T{i}": [100.0 - i * 0.1] * 120 for i in range(10)}
        uni["NEW"] = [50.0] * 5
        n_below, n_eval = below_sma(uni, 100)
        assert n_eval == 10

    def test_approaching_stops_is_forward_looking(self):
        """It reports how much of the book the stop is ABOUT to sell — the number
        that decides whether to intervene before it happens, not after."""
        # `within=0.25` means "at least 75% of the way to the stop". A has given
        # back 25 of its 30 points (83%); B has given back 1 (3%). C at 22 points
        # (73%) is deliberately just UNDER the bar — the boundary is where a
        # forward-looking report is easiest to get subtly wrong.
        near = approaching_stops({"A": 100.0, "B": 100.0, "C": 100.0},
                                 {"A": 75.0, "B": 99.0, "C": 78.0}, stop_pct=0.30)
        assert [d["ticker"] for d in near] == ["A"]
        assert near[0]["progress"] == pytest.approx(0.8333, abs=0.001)

    def test_correlation_needs_two_usable_series(self):
        assert average_pairwise_correlation({"A": [0.01] * 30}) is None

    def test_perfectly_correlated_book_reads_as_one_bet(self):
        r = [0.01, -0.02, 0.03, -0.01, 0.02] * 6
        c = average_pairwise_correlation({"A": r, "B": r, "C": r})
        assert c == pytest.approx(1.0, abs=1e-6)


def test_the_module_cannot_emit_an_order():
    """LOAD-BEARING. The evidence behind this feature showed that ACTING on it
    hurt: culprit-selling and blanket stop-tightening cut CAGR badly. It is a
    report. If any order/intent vocabulary ever appears in this module, that
    decision has been reversed silently."""
    import ast
    import inspect

    from stock_strategy_shared import drawdown_guard

    # Scan the CODE, not the prose. A first cut matched the word "order" inside
    # this module's own docstring explaining that it emits none — a test that
    # fails on its subject describing itself correctly is worse than no test.
    tree = ast.parse(inspect.getsource(drawdown_guard))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for forbidden in ("DeltaDecision", "submit", "order", "intent", "sell_trim",
                      "risk_reduce", "risk_restore"):
        assert forbidden not in names, (
            f"{forbidden!r} is referenced in the drawdown guard — it is observe-only")
    for lit in literals:
        for forbidden in ("exit", "sell_trim", "risk_reduce", "buy_add"):
            assert forbidden != lit, (
                f"action literal {lit!r} in the drawdown guard — it is observe-only")
