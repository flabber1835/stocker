#!/usr/bin/env python3
"""
Run a harness scenario against the live Docker Compose stack.

Usage:
    python tests/harness/run.py quick_smoke
    python tests/harness/run.py year_bull_bear
    python tests/harness/run.py year_bull_bear --no-vetter --tickers 50
    python tests/harness/run.py quick_smoke --log-level DEBUG
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from copy import copy
from datetime import date
from typing import Optional

# Make sure the repo root is on sys.path when run directly
import os

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.harness.harness.driver import (
    DEFAULT_DSN,
    DEFAULT_SERVICE_URLS,
    SimulationDriver,
)
from tests.harness.harness.report import generate_report
from tests.harness.harness.scenario import RegimeChange, Scenario

# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

def _load_scenario(name: str) -> Scenario:
    if name == "quick_smoke":
        from tests.harness.scenarios.quick_smoke import QUICK_SMOKE
        return QUICK_SMOKE
    if name == "year_bull_bear":
        from tests.harness.scenarios.year_bull_bear import YEAR_BULL_BEAR
        return YEAR_BULL_BEAR
    raise ValueError(
        f"Unknown scenario '{name}'.  Available: quick_smoke, year_bull_bear"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a harness scenario against the live Docker Compose stack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "scenario",
        choices=["quick_smoke", "year_bull_bear"],
        help="Name of the scenario to run.",
    )
    parser.add_argument(
        "--no-vetter",
        action="store_true",
        help="Disable LLM vetter even if the scenario has run_vetter=True.",
    )
    parser.add_argument(
        "--tickers",
        type=int,
        default=None,
        metavar="N",
        help="Override the scenario's universe_size.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override the scenario's random seed.",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Override the scenario start date.",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Override the scenario end date.",
    )
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help=f"Postgres DSN (default: {DEFAULT_DSN}).",
    )
    parser.add_argument(
        "--report-dir",
        default="tests/harness/reports",
        help="Directory for report output files.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level (default: INFO).",
    )
    return parser


def _apply_overrides(scenario: Scenario, args: argparse.Namespace) -> Scenario:
    """Return a shallow-copied scenario with CLI overrides applied."""
    s = copy(scenario)
    if args.no_vetter:
        s.run_vetter = False
    if args.tickers is not None:
        s.universe_size = args.tickers
    if args.seed is not None:
        s.seed = args.seed
    if args.start_date is not None:
        s.start_date = args.start_date
    if args.end_date is not None:
        s.end_date = args.end_date
    return s


# ---------------------------------------------------------------------------
# Main coroutine
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    scenario = _load_scenario(args.scenario)
    scenario = _apply_overrides(scenario, args)

    print(f"=== Harness: {scenario.name} ===")
    print(f"  Universe: {scenario.universe_size} tickers | Seed: {scenario.seed}")
    print(f"  Period:   {scenario.start_date} → {scenario.end_date}")
    print(f"  Vetter:   {'yes (every %d days)' % scenario.vetter_every_n_days if scenario.run_vetter else 'no'}")
    print()

    driver = SimulationDriver(dsn=args.dsn, service_urls=DEFAULT_SERVICE_URLS)
    observations = await driver.run(scenario)

    report_text = generate_report(scenario, observations, report_dir=args.report_dir)
    print(report_text)


if __name__ == "__main__":
    asyncio.run(main())
