from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import SecurityBar, Operation
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.median5 import config, fresh
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


def test_carried_terminal_value_does_not_fund_new_median5_admissions():
    state = PortfolioState.fresh(100_000., 20)
    state.initialized = True
    state.median5 = fresh()
    state.slots[0].occupied_by = "held"
    state.episodes[0] = HoldingEpisode(
        "held", "HELD", "SID:held", 0, "0000", "0001", 10., 10., 10, 10,
        episode_peak_split_adjusted_close=10.)
    bars, securities = [], []
    for i in range(30):
        sid = f"{i:03}"
        bars.append(DailyBar(sid, sid, f"SID:{sid}", "0002",
                             100., 100., 100., 1e6, 100.))
        securities.append(SecurityBar(sid, sid, f"SID:{sid}", [90., 100.], 100.,
                                      True, "", (.5, .1, .2, float(100-i))))
    ledger = Ledger()
    result = step_session(session="0002", state=state, bars=bars,
        security_bars=securities, pending=[], ledger=ledger,
        last_known={"held": 10.}, cfg=config(), strategy_id="median5", strategy_version=1,
        terminal_terms=[TerminalTerms("0002", "held", TerminalKind.CASH_MERGER,
                                      reference="documented-incomplete-terms")])
    assert result.blocked
    assert result.resolved_equity is None
    assert result.estimated_equity == 100_100.
    assert state.terminal_pending_sessions["held"] == 0
    assert state.episodes[0].current_shares == 10
    assert not any(op.operation is Operation.OPEN_SLOT_POSITION for op in result.decision.operations)
