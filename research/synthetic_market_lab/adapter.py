from __future__ import annotations

import csv
import gzip
from pathlib import Path

from .io import DeterministicCSVGzipWriter

BT_PRICE_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "adj_close", "volume", "security_id", "company_id")
BT_FUNDAMENTAL_COLUMNS = (
    "ticker", "datekey", "period_end", "version", "revenue", "expenses", "net_income", "assets", "liabilities", "equity",
    "cash", "debt", "shares_outstanding", "revenue_growth", "margin", "leverage", "quality", "security_id", "company_id",
)
BT_UNIVERSE_COLUMNS = ("snapshot_date", "ticker", "security_id", "company_id", "sector", "industry")
BT_ACTION_COLUMNS = ("announced_at", "effective_date", "ticker", "security_id", "company_id", "action_type", "ratio", "cash_amount", "new_ticker", "new_security_id", "reason")


def _read(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def export_backtester_tables(public_dir: str | Path, output_dir: str | Path, *, benchmark_alias: str = "SPY") -> dict[str, int]:
    """Export only public synthetic records into the historical backtester's conceptual PIT contract."""
    public = Path(public_dir)
    if public.name != "public":
        raise ValueError("adapter source must be a generated public/ directory")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    with DeterministicCSVGzipWriter(out / "bt_prices.csv.gz", BT_PRICE_COLUMNS) as writer:
        for row in _read(public / "prices.csv.gz"):
            writer.write({c: row.get(c, "") for c in BT_PRICE_COLUMNS})
        benchmark_path = public / "benchmark.csv.gz"
        if benchmark_path.exists():
            for row in _read(benchmark_path):
                writer.write({
                    "ticker": benchmark_alias,
                    "date": row["date"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "adj_close": row["adj_close"],
                    "volume": row["volume"],
                    "security_id": "SYNTHETIC-BENCHMARK",
                    "company_id": "SYNTHETIC-BENCHMARK",
                })
        counts["bt_prices"] = writer.rows

    with DeterministicCSVGzipWriter(out / "bt_fundamentals.csv.gz", BT_FUNDAMENTAL_COLUMNS) as writer:
        for row in _read(public / "disclosures.csv.gz"):
            mapped = {c: row.get(c, "") for c in BT_FUNDAMENTAL_COLUMNS}
            mapped["datekey"] = row["filed_at"]
            writer.write(mapped)
        counts["bt_fundamentals"] = writer.rows

    with DeterministicCSVGzipWriter(out / "bt_universe.csv.gz", BT_UNIVERSE_COLUMNS) as writer:
        for row in _read(public / "universe.csv.gz"):
            writer.write({c: row.get(c, "") for c in BT_UNIVERSE_COLUMNS})
        counts["bt_universe"] = writer.rows

    with DeterministicCSVGzipWriter(out / "bt_actions.csv.gz", BT_ACTION_COLUMNS) as writer:
        for row in _read(public / "actions.csv.gz"):
            writer.write({c: row.get(c, "") for c in BT_ACTION_COLUMNS})
        counts["bt_actions"] = writer.rows

    return counts
