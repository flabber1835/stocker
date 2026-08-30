"""Causal defensive-cash return authority for historical backtests.

BIL is authoritative whenever a valid BIL return factor exists. Before BIL (or
for a missing BIL session), the model accrues Treasury cash from the *previous
calendar month's* GS3M observation. GS3M is the Federal Reserve H.15 3-month
constant-maturity Treasury yield, quoted on an investment basis and published
by FRED as monthly averages of business days.

Using the previous completed month keeps the fallback causal. No current-month
average is used. Calendar-day accrual is split into the close-to-open gap and
one day of open-to-close accrual so weekend/holiday interest is retained.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

DAYS_PER_YEAR = 365.2425
SOURCE_ID = "FRED:GS3M"
SOURCE_DESCRIPTION = (
    "Federal Reserve H.15 3-month constant-maturity Treasury yield, investment "
    "basis; FRED GS3M monthly average; strict previous-calendar-month lag"
)


def load_monthly_yields(path: Path) -> dict[str, float]:
    rows: dict[str, float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            month = str(row["month"])
            value = float(row["annual_yield_percent"])
            if not month.endswith("-01") or value < 0:
                raise RuntimeError(f"invalid GS3M row: {row}")
            rows[month] = value
    if not rows:
        raise RuntimeError("GS3M authority file is empty")
    return rows


def _previous_month_key(session: str) -> str:
    d = date.fromisoformat(str(session))
    if d.month == 1:
        return f"{d.year-1:04d}-12-01"
    return f"{d.year:04d}-{d.month-1:02d}-01"


def treasury_factors(
    session: str,
    prior_session: str | None,
    monthly_yields: Mapping[str, float],
) -> tuple[float, float]:
    """Return (prior-close->open factor, open->close factor)."""
    key = _previous_month_key(session)
    if key not in monthly_yields:
        raise RuntimeError(f"no causal GS3M yield available for {session}: need {key}")
    annual = float(monthly_yields[key]) / 100.0
    if prior_session is None:
        gap_days = 0
    else:
        elapsed = (date.fromisoformat(session) - date.fromisoformat(prior_session)).days
        if elapsed <= 0:
            raise RuntimeError(f"non-positive session gap: {prior_session} -> {session}")
        gap_days = max(elapsed - 1, 0)
    gap_factor = (1.0 + annual) ** (gap_days / DAYS_PER_YEAR)
    intraday_factor = (1.0 + annual) ** (1.0 / DAYS_PER_YEAR)
    return float(gap_factor), float(intraday_factor)


def complete_cash_factors(
    sessions: Sequence[str],
    bil_factors: Mapping[str, tuple[float, float]],
    authority_path: Path,
) -> tuple[dict[str, tuple[float, float]], dict]:
    """Fill missing BIL sessions with strict-lag Treasury cash factors."""
    yields = load_monthly_yields(authority_path)
    completed: dict[str, tuple[float, float]] = {}
    bil_sessions = 0
    treasury_sessions = 0
    prior: str | None = None
    for raw in sessions:
        session = str(raw)
        pair = bil_factors.get(session)
        if pair is not None and pair[0] > 0 and pair[1] > 0:
            completed[session] = (float(pair[0]), float(pair[1]))
            bil_sessions += 1
        else:
            completed[session] = treasury_factors(session, prior, yields)
            treasury_sessions += 1
        prior = session
    return completed, {
        "source_id": SOURCE_ID,
        "source_description": SOURCE_DESCRIPTION,
        "bil_sessions": bil_sessions,
        "treasury_fallback_sessions": treasury_sessions,
        "authority_file": str(authority_path),
    }
