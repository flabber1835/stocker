"""The price-domain contract (spec §2) — enforced, not documented.

Every failure this guards against is SILENT. Feed a dividend-adjusted series in
as the signal close and momentum shifts on every dividend payer; feed an
adjusted close in as the mark and every 4% admission is sized off the wrong
equity. Neither raises. Both produce a complete, plausible backtest of a
strategy nobody specified — which is the exact failure mode this project has
already paid for once, with a quality factor that silently became ROE.

So the tests below are mostly about REFUSAL, and about refusing at wiring time
rather than at the end of a multi-hour run.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.prices import (
    BANNED_FIELD_NAMES,
    DailyBar,
    PriceDomainError,
    marks_from,
    signal_closes,
)


def bar(**over):
    base = dict(security_id="S1", ticker="T1", issuer_id="I1", session="2026-08-03",
                signal_close_split_adj_div_unadj=101.0, raw_open=99.0,
                raw_mark_close=100.0)
    base.update(over)
    return DailyBar(**base)


class TestAmbiguousNamesAreRefused:
    @pytest.mark.parametrize("name", sorted(BANNED_FIELD_NAMES))
    def test_every_domainless_name_is_rejected(self, name):
        """`close` cannot say WHICH close. A contract that relies on the caller
        remembering is a comment, not a contract."""
        row = {"security_id": "S1", "ticker": "T1", "issuer_id": "I1",
               "session": "d", name: 100.0}
        with pytest.raises(PriceDomainError, match="ambiguous price field"):
            DailyBar.from_mapping(row)

    def test_the_error_names_the_domains_the_caller_should_use(self):
        """An error that only says 'invalid' sends the reader to the source. The
        four domain names are the actual answer, so the message carries them."""
        with pytest.raises(PriceDomainError) as e:
            DailyBar.from_mapping({"security_id": "S", "ticker": "T",
                                   "issuer_id": "I", "session": "d", "close": 1.0})
        msg = str(e.value)
        assert "signal_close_split_adj_div_unadj" in msg
        assert "raw_open" in msg and "raw_mark_close" in msg

    def test_an_unknown_field_is_refused_rather_than_ignored(self):
        """A closed contract. A renamed column must fail loudly instead of
        arriving as a silent no-op that leaves a domain unset."""
        with pytest.raises(PriceDomainError, match="unknown field"):
            DailyBar.from_mapping({"security_id": "S", "ticker": "T",
                                   "issuer_id": "I", "session": "d",
                                   "signal_close_split_adj_div_unadj": 1.0,
                                   "raw_open": 1.0, "raw_mark_close": 1.0,
                                   "totalreturn_close": 1.0})

    def test_the_explicit_names_are_accepted(self):
        b = DailyBar.from_mapping({
            "security_id": "S1", "ticker": "T1", "issuer_id": "I1",
            "session": "2026-08-03", "signal_close_split_adj_div_unadj": 101.0,
            "raw_open": 99.0, "raw_mark_close": 100.0})
        assert b.signal_close_split_adj_div_unadj == 101.0


class TestPriceValidation:
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_zero_and_nonfinite_prices_are_refused(self, bad):
        """None means 'not observed'; zero is a price. Letting 0.0 through makes
        it a real observation to everything downstream — a free share, a
        division by zero, or a 100% drawdown depending on which domain it
        entered through."""
        with pytest.raises(PriceDomainError, match="positive finite price"):
            bar(raw_open=bad)

    def test_None_is_allowed_and_means_not_observed(self):
        assert bar(raw_open=None).raw_open is None

    def test_a_split_ratio_must_be_positive(self):
        with pytest.raises(PriceDomainError, match="split_ratio"):
            bar(split_ratio=0.0)
        assert bar(split_ratio=2.0).split_ratio == 2.0

    def test_a_negative_dividend_is_refused(self):
        with pytest.raises(PriceDomainError, match="dividend_per_share"):
            bar(dividend_per_share=-0.01)


class TestFailClosed:
    def test_an_unresolved_action_cannot_be_tradeable(self):
        """Spec §1/§2: unresolved terminal actions FAIL CLOSED. Allowing the
        combination would let the simulator trade a security whose corporate
        action nobody has resolved, at a price nobody has verified."""
        with pytest.raises(PriceDomainError, match="FAIL CLOSED"):
            bar(unresolved_corporate_action=True, tradeable=True)

    def test_an_unresolved_action_can_neither_execute_nor_mark(self):
        b = bar(unresolved_corporate_action=True, tradeable=False)
        assert b.can_execute is False and b.can_mark is False

    def test_a_halted_session_still_has_a_close_but_cannot_execute(self):
        """Tradeability is a fact about the SESSION, not something inferable
        from a price — a halted name still prints one."""
        b = bar(tradeable=False)
        assert b.can_mark is True and b.can_execute is False

    def test_execution_requires_a_positive_raw_open(self):
        assert bar(raw_open=None).can_execute is False


class TestDomainAccessors:
    def test_signal_closes_reads_the_signal_domain_only(self):
        bars = [bar(session=f"d{i}", signal_close_split_adj_div_unadj=100.0 + i,
                    raw_mark_close=999.0) for i in range(3)]
        assert signal_closes(bars) == [100.0, 101.0, 102.0]

    def test_marks_read_the_RAW_domain_only(self):
        bars = [bar(security_id="A", signal_close_split_adj_div_unadj=1.0,
                    raw_mark_close=50.0),
                bar(security_id="B", signal_close_split_adj_div_unadj=2.0,
                    raw_mark_close=60.0)]
        assert marks_from(bars) == {"A": 50.0, "B": 60.0}

    def test_an_unmarkable_security_is_OMITTED_not_carried_stale(self):
        """PortfolioState.equity treats a missing mark as contributing nothing,
        which is the honest reading of 'we do not know what this is worth'.
        Carrying yesterday's price would resize every subsequent admission off
        an equity figure that includes a price nobody observed."""
        ok = bar(security_id="A", raw_mark_close=50.0)
        gone = bar(security_id="B", raw_mark_close=None)
        stuck = bar(security_id="C", unresolved_corporate_action=True,
                    tradeable=False, raw_mark_close=70.0)
        assert marks_from([ok, gone, stuck]) == {"A": 50.0}
