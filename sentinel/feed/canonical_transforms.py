"""Pure, explicit provider-to-canonical economic price-domain conversions."""
from sentinel.feed import domains
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark

_SFP_TOTAL_RETURN_COLUMN = domains.SEP_FORBIDDEN_COLUMNS[0]


def benchmarks(window, rows):
    by_key = {}
    for row in rows:
        key = (str(row["date"]), str(row["ticker"]))
        if key in by_key or key[1] not in {"SPY", "BIL"}:
            raise ValueError("duplicate or unexpected benchmark identity")
        by_key[key] = row
    expected = {(str(day), ticker) for day in window.sessions for ticker in ("SPY", "BIL")}
    if set(by_key) != expected:
        raise ValueError("SPY/BIL must cover every session exactly")
    for day in window.sessions:
        spy, bil = by_key[(str(day), "SPY")], by_key[(str(day), "BIL")]
        # Same mandatory BIL fields as the existing dedicated defensive writer.
        yield CanonicalBenchmark(
            session=day, spy_total_return=float(spy[_SFP_TOTAL_RETURN_COLUMN]),
            bil_open_signal=float(bil["open"]), bil_close_signal=float(bil["close"]),
            bil_close_adjusted=float(bil[_SFP_TOTAL_RETURN_COLUMN]),
            bil_close_unadjusted=float(bil["closeunadj"]))


def alpaca_bar(row, *, asset_id, split_ratio, dividend_per_share):
    return CanonicalBar(security_id=asset_id,session=row['date'],ticker=row['ticker'],
        close_signal=float(row['adjusted_close']),close_unadjusted=float(row['closeunadj']),
        open_unadjusted=float(row['open']),volume=float(row['volume']),
        split_ratio=float(split_ratio),dividend_per_share=float(dividend_per_share))


def sharadar_bar(item):
    return CanonicalBar(security_id=str(item.vendor.security_id),session=item.vendor.session,
        ticker=item.vendor.ticker,close_signal=item.close_signal,
        close_unadjusted=item.vendor.raw_close,open_unadjusted=item.vendor.raw_open,
        volume=item.vendor.volume,split_ratio=item.vendor.split_ratio,
        dividend_per_share=item.vendor.dividend_per_share)
