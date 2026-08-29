#!/usr/bin/env python3
"""Classify unresolved split conflicts that are provably unreachable by Wealth Core.

A conflict is excluded only when its security never satisfies every
split-independent entry gate from the fresh replay start through the complete
127-close signal contamination horizon. This is a sufficient, deliberately
conservative proof: raw price/liquidity, session continuity and history length
cannot be changed by choosing a different positive split multiplier.
"""
from __future__ import annotations

from collections import defaultdict, deque
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

MIN_PRICE = 1.0
MIN_ADV20 = 20_000_000.0
MIN_SIGNAL_DV = 5_000_000.0
ADV_WINDOW = 20
REQUIRED_CLOSES = 127
CONTAMINATION_FUTURE_SESSIONS = 126


def finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_SPLIT_UNREACHABLE_OUTPUT",
        "backtester-results/split-unreachable-classification.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    base_path = lab / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
    spec = importlib.util.spec_from_file_location("split_unreachable_base", base_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {base_path}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    import sentinel.core.production as production
    import stock_strategy_shared.split_reconciliation as split_module
    from sentinel.core.production import PublishedSession, SessionState
    from sentinel.feed.actions_map import dividends_from_actions, split_ratios_from_actions
    from sentinel.feed.domains import NormalisationReport, normalise_sep_rows
    from sentinel.feed.universe import parse_related_tickers
    from sentinel.core.terminal import ActionSide, TERMINAL_ACTION_SIDES, terminal_from_action
    from stock_strategy_shared.terminal_coalescing import TerminalCandidate, coalesce_terminal_terms
    from stock_strategy_shared.split_reconciliation import SPLIT_UNRESOLVED
    from stock_strategy_shared.wealth_core.feed import SecurityMeta
    from backtester.causal_split_overrides import install_primary_split_adjudication, load_frozen_split_overrides

    actual_main = os.environ.get("BACKTESTER_MAIN_SHA", "")
    if actual_main != runner.EXPECTED_MAIN_SHA:
        raise RuntimeError(f"main SHA mismatch: expected {runner.EXPECTED_MAIN_SHA}, got {actual_main}")

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

    manifest = runner.load_phase1_manifest(lab / "PIT input data" / "MANIFEST.csv")
    sessions, _spy_level, _spy_return, _bil = runner.build_sfp_levels(
        lab / "PIT input data" / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz")
    session_index = {s: i for i, s in enumerate(sessions)}
    _actions, authoritative_splits, maps = runner.load_actions(
        lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz", sessions, main_api)
    dividends = maps["dividends"]
    _meta, _sectors, resolver, _sid_to_ticker = runner.load_current_metadata(
        lab / "sharadar" / "SHARADAR_TICKERS.zip", main_api)

    def resolve_identity(ticker, session):
        return resolver.resolve(str(ticker), str(session))

    override_sha, overrides = load_frozen_split_overrides(
        lab / "backtester" / "data" / "causal-split-overrides-v1.json",
        lab / "backtester" / "data" / "causal-split-overrides-v1.SHA256",
        authority=authoritative_splits,
        sessions=sessions,
        resolve_identity=resolve_identity,
    )
    real_decide = install_primary_split_adjudication(split_module, overrides)

    report = NormalisationReport()
    observed_inputs: dict[str, dict] = {}
    last_idx: dict[str, int] = {}
    contiguous: dict[str, int] = defaultdict(int)
    dv20: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=ADV_WINDOW))
    ever_pass: dict[str, bool] = defaultdict(bool)
    first_pass: dict[str, str] = {}
    events: dict[tuple[str, str], dict] = {}
    active: dict[str, list[tuple[str, str]]] = defaultdict(list)
    bars = 0

    try:
        raw_stream = runner.raw_sep_rows(lab / "sharadar", manifest, runner.END_SESSION, observed_inputs)
        normalized = normalise_sep_rows(
            raw_stream,
            resolve_identity=resolve_identity,
            dividends=dividends,
            authoritative_splits=authoritative_splits,
            report=report,
        )
        for row in normalized:
            bar = row.vendor
            session = str(bar.session)
            if session < runner.CHAIN_START:
                continue
            idx = session_index.get(session)
            if idx is None:
                continue
            sid = str(bar.security_id)
            ticker = str(bar.ticker)
            bars += 1

            if last_idx.get(sid) != idx - 1:
                contiguous[sid] = 0
                dv20[sid].clear()

            raw = float(bar.raw_close) if finite(bar.raw_close) else None
            vol = float(bar.volume) if finite(bar.volume) else None
            valid_close = raw is not None and raw > 0.0
            valid_dv = valid_close and vol is not None and vol >= 0.0
            if valid_close:
                contiguous[sid] += 1
            else:
                contiguous[sid] = 0
            if valid_dv:
                dv20[sid].append(raw * vol)
            else:
                dv20[sid].clear()

            current_dv = raw * vol if valid_dv else None
            adv = (sum(dv20[sid]) / ADV_WINDOW) if len(dv20[sid]) == ADV_WINDOW else None
            independent_pass = bool(
                contiguous[sid] >= REQUIRED_CLOSES
                and raw is not None and raw >= MIN_PRICE
                and current_dv is not None and current_dv >= MIN_SIGNAL_DV
                and adv is not None and adv >= MIN_ADV20
            )

            # Existing unresolved events for this identity consume the current
            # session while their split-sensitive 127-close window is active.
            if active[sid]:
                keep = []
                for key in active[sid]:
                    ev = events[key]
                    if idx <= ev["horizon_index"]:
                        if independent_pass:
                            ev["pass_during_contamination"] = True
                            ev.setdefault("first_contamination_pass_session", session)
                        keep.append(key)
                active[sid] = keep

            key = (ticker, session)
            disp = report.split_dispositions.get(key)
            if disp and disp.get("disposition") == SPLIT_UNRESOLVED and key not in events:
                horizon_index = min(idx + CONTAMINATION_FUTURE_SESSIONS, len(sessions) - 1)
                ev = {
                    "ticker": ticker,
                    "session": session,
                    "security_id": sid,
                    "event_index": idx,
                    "horizon_index": horizon_index,
                    "horizon_session": sessions[horizon_index],
                    "pass_before_event": bool(ever_pass[sid]),
                    "first_prior_pass_session": first_pass.get(sid),
                    "pass_during_contamination": bool(independent_pass),
                }
                if independent_pass:
                    ev["first_contamination_pass_session"] = session
                events[key] = ev
                active[sid].append(key)

            if independent_pass and not ever_pass[sid]:
                ever_pass[sid] = True
                first_pass[sid] = session
            last_idx[sid] = idx

            if bars % 1_000_000 == 0:
                print(f"[UNREACHABLE] bars={bars:,} events={len(events)} session={session}", flush=True)
    finally:
        split_module.SplitStreamReconciler.decide = real_decide

    unresolved = []
    unreachable = []
    blocking = []
    for (ticker, session), value in sorted(report.split_dispositions.items()):
        if value.get("disposition") != SPLIT_UNRESOLVED:
            continue
        key = (str(ticker), str(session))
        proof = events.get(key)
        row = {"ticker": key[0], "session": key[1], **{str(k): v for k, v in value.items()}}
        unresolved.append(row)
        if proof is None:
            blocking.append({**row, "reachability": "BLOCKING", "reason": "NO_EVENT_PROOF"})
            continue
        safe = not proof["pass_before_event"] and not proof["pass_during_contamination"]
        classified = {
            **row,
            "security_id": proof["security_id"],
            "proof_horizon_session": proof["horizon_session"],
            "pass_before_event": proof["pass_before_event"],
            "first_prior_pass_session": proof.get("first_prior_pass_session"),
            "pass_during_contamination": proof["pass_during_contamination"],
            "first_contamination_pass_session": proof.get("first_contamination_pass_session"),
            "reachability": "PROVEN_UNREACHABLE" if safe else "BLOCKING",
            "proof": (
                "Never satisfied all split-independent Wealth Core entry gates from "
                "fresh replay start through the complete split-sensitive 127-close horizon."
                if safe else
                "Satisfied all split-independent entry gates before or during the split-sensitive horizon."
            ),
        }
        (unreachable if safe else blocking).append(classified)

    payload = {
        "schema": "backtester.split-unreachable-classification/1",
        "status": "PASS",
        "diagnostic_only": True,
        "strategy_main_sha": actual_main,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "split_override_sha256": override_sha,
        "chain_start": runner.CHAIN_START,
        "end_session": runner.END_SESSION,
        "proof_rule": {
            "min_unadjusted_price": MIN_PRICE,
            "min_adv20_dollars": MIN_ADV20,
            "min_signal_dollar_volume": MIN_SIGNAL_DV,
            "required_contiguous_closes": REQUIRED_CLOSES,
            "contamination_future_sessions": CONTAMINATION_FUTURE_SESSIONS,
            "category_not_used_for_exclusion": True,
            "exchange_not_used_for_exclusion": True,
            "split_adjusted_signals_not_used_for_exclusion": True,
        },
        "bars_processed_from_chain_start": bars,
        "raw_unresolved_count": len(unresolved),
        "proven_unreachable_count": len(unreachable),
        "blocking_unresolved_count": len(blocking),
        "proven_unreachable": unreachable,
        "blocking_unresolved": blocking,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "raw_unresolved": len(unresolved),
        "proven_unreachable": len(unreachable),
        "blocking_unresolved": len(blocking),
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
