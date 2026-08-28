#!/usr/bin/env python3
"""Fast full-corpus audit of unresolved split reconciliation.

Diagnostic only. This exhausts the exact frozen current-main SEP normalization
path across the replay corpus without executing Wealth Core or Sentinel. It
exists to identify every split event that would fail the base runner's final
split-certification audit, so those source conflicts can be investigated before
another multi-hour economic replay reaches the end.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_SPLIT_SCAN_OUTPUT",
        "backtester-results/full-corpus-unresolved-splits.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    base_path = lab / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
    spec = importlib.util.spec_from_file_location("split_audit_base", base_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {base_path}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    import sentinel.core.production as production
    from sentinel.core.production import PublishedSession, SessionState
    from sentinel.feed.actions_map import dividends_from_actions, split_ratios_from_actions
    from sentinel.feed.domains import NormalisationReport, normalise_sep_rows
    from sentinel.feed.universe import parse_related_tickers
    from sentinel.core.terminal import ActionSide, TERMINAL_ACTION_SIDES, terminal_from_action
    from stock_strategy_shared.terminal_coalescing import TerminalCandidate, coalesce_terminal_terms
    from stock_strategy_shared.split_reconciliation import SPLIT_UNRESOLVED
    from stock_strategy_shared.wealth_core.feed import SecurityMeta

    expected_main = runner.EXPECTED_MAIN_SHA
    actual_main = os.environ.get("BACKTESTER_MAIN_SHA", "")
    if actual_main != expected_main:
        raise RuntimeError(f"main SHA mismatch: expected {expected_main}, got {actual_main}")

    main_api = {
        "PublishedSession": PublishedSession,
        "SessionState": SessionState,
        "SecurityMeta": SecurityMeta,
        "parse_related_tickers": parse_related_tickers,
        "split_ratios_from_actions": split_ratios_from_actions,
        "dividends_from_actions": dividends_from_actions,
        "ActionSide": ActionSide,
        "TERMINAL_ACTION_SIDES": TERMINAL_ACTION_SIDES,
        "terminal_from_action": terminal_from_action,
        "TerminalCandidate": TerminalCandidate,
        "coalesce_terminal_terms": coalesce_terminal_terms,
        "FeedAnchor": production.FeedAnchor,
    }

    phase1_manifest = runner.load_phase1_manifest(lab / "PIT input data" / "MANIFEST.csv")
    sfp_path = lab / "PIT input data" / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"
    sessions, _spy_level, _spy_return, _bil_factors = runner.build_sfp_levels(sfp_path)

    actions_path = lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz"
    _action_rows, authoritative_splits, action_maps = runner.load_actions(
        actions_path, sessions, main_api)
    dividends = action_maps["dividends"]

    tickers_path = lab / "sharadar" / "SHARADAR_TICKERS.zip"
    _meta, _sectors, resolver, _sid_to_ticker = runner.load_current_metadata(
        tickers_path, main_api)

    def resolve_identity(ticker, session):
        return resolver.resolve(str(ticker), str(session))

    observed_inputs: dict[str, dict] = {}
    raw_stream = runner.raw_sep_rows(
        lab / "sharadar", phase1_manifest, runner.END_SESSION, observed_inputs)
    report = NormalisationReport()
    normalized = normalise_sep_rows(
        raw_stream,
        resolve_identity=resolve_identity,
        dividends=dividends,
        authoritative_splits=authoritative_splits,
        report=report,
    )

    bars = 0
    last_session = None
    for row in normalized:
        bars += 1
        last_session = str(row.vendor.session)
        if bars % 1_000_000 == 0:
            print(
                f"[SPLIT-SCAN] bars={bars:,} last_session={last_session} "
                f"split_dispositions={len(report.split_dispositions):,}",
                flush=True,
            )

    unresolved = []
    for (ticker, session), value in sorted(report.split_dispositions.items()):
        if value.get("disposition") != SPLIT_UNRESOLVED:
            continue
        unresolved.append({
            "ticker": str(ticker),
            "session": str(session),
            **{str(k): v for k, v in value.items()},
        })

    payload = {
        "schema": "backtester.full-corpus-unresolved-splits/1",
        "status": "PASS",
        "diagnostic_only": True,
        "strategy_execution": False,
        "fresh_normalization": True,
        "strategy_main_sha": actual_main,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "end_session": runner.END_SESSION,
        "bars_processed": bars,
        "last_session": last_session,
        "split_disposition_count": len(report.split_dispositions),
        "unresolved_split_count": len(unresolved),
        "unresolved_splits": unresolved,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[SPLIT-SCAN] PASS bars={bars:,} last_session={last_session} "
        f"unresolved={len(unresolved)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
