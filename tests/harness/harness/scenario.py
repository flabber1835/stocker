"""
Scenario and RegimeChange dataclasses, plus trading-day utilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List


@dataclass
class RegimeChange:
    """Marks the start of a new market regime."""
    start_date: date
    regime_type: str  # "bull_calm" | "bull_stress" | "bear_stress" | "bear_calm"


@dataclass
class Scenario:
    """Full description of a multi-day simulation run."""
    name: str
    seed: int
    universe_size: int
    start_date: date
    end_date: date
    regimes: List[RegimeChange]
    run_vetter: bool = False
    vetter_every_n_days: int = 5  # run vetter every N trading days
    description: str = ""


@dataclass
class DayObservation:
    """Recorded state at the end of one simulated trading day."""
    date: date
    position_count: int
    account_value: float
    cash: float
    regime: str
    label: str = ""
    pipeline_status: str = ""
    intents_submitted: int = 0
    intents_accepted: int = 0


def list_trading_days(start: date, end: date) -> List[date]:
    """Return all weekdays (Mon–Fri) from start to end inclusive."""
    days: List[date] = []
    current = start
    while current <= end:
        # weekday(): 0=Mon … 4=Fri, 5=Sat, 6=Sun
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days
