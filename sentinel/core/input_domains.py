"""Pure conversion of admitted canonical source rows into engine domains."""
from stock_strategy_shared.wealth_core.feed import VendorBar
from sentinel.core.session import DefensiveBar
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark


def _vendor(row: CanonicalBar) -> VendorBar:
    return VendorBar(
        session=row.session.isoformat(), security_id=row.security_id,
        ticker=row.ticker, raw_close=row.close_unadjusted,
        raw_open=row.open_unadjusted, volume=row.volume,
        split_ratio=row.split_ratio, dividend_per_share=row.dividend_per_share,
        tradeable=bool(row.close_unadjusted and row.volume),
        signal_close=row.close_signal)



def _defensive(row: CanonicalBenchmark) -> DefensiveBar:
    return DefensiveBar(
        session=row.session.isoformat(), security_id="SENTINEL:BIL", ticker="BIL",
        open_signal=row.bil_open_signal, close_signal=row.bil_close_signal,
        close_adjusted=row.bil_close_adjusted,
        close_unadjusted=row.bil_close_unadjusted)
