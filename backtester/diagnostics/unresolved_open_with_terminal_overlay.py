#!/usr/bin/env python3
"""A-only diagnostic for the next unresolved-open boundary with causal terminal overlay."""
from __future__ import annotations

import dataclasses
from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys

import pandas as pd


def _jsonable(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return vars(value)
    except TypeError:
        return repr(value)


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    diag = Path(os.environ.get(
        "BACKTESTER_DIAG_OUTPUT",
        "backtester-results/unresolved-open-terminal-overlay.json",
    )).resolve()
    diag.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    wrapper_path = lab / "backtester" / "run_sector_ad_causal_terminal_terms_v2.py"
    spec = importlib.util.spec_from_file_location("sector_ad_v2_diag_base", wrapper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {wrapper_path}")
    v2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v2)
    runner = v2.runner

    import sentinel.core.production as production

    real_advance = production.advance_state
    cache = {"session": None, "result": None, "published": None, "a_transitions": 0, "collapsed": 0}

    def a_only_advance(state, published, *args, **kwargs):
        session = str(published.session)
        if cache["session"] == session:
            cache["collapsed"] += 1
            return cache["result"]
        result = real_advance(state, published, *args, **kwargs)
        cache["session"] = session
        cache["result"] = result
        cache["published"] = published
        cache["a_transitions"] += 1
        return result

    production.advance_state = a_only_advance

    captured = {"state": None, "terminal_session": None, "terminal_source_rows": None, "terminal_events": None}
    real_wc = runner.wealth_equities
    def capture_wc(state):
        captured["state"] = state
        return real_wc(state)
    runner.wealth_equities = capture_wc

    real_terminal = runner.build_terminal_events
    def capture_terminal(session, rows, priced_tickers, resolver, main_api):
        events = real_terminal(session, rows, priced_tickers, resolver, main_api)
        captured["terminal_session"] = str(session)
        captured["terminal_source_rows"] = _jsonable(list(rows))
        captured["terminal_events"] = _jsonable(events)
        return events
    runner.build_terminal_events = capture_terminal

    real_step = runner.OverlayAccount.step
    def diagnostic_step(account, core_open, core_close, prior_core_close,
                        bil_gap, bil_intraday, next_target):
        try:
            return real_step(account, core_open, core_close, prior_core_close,
                             bil_gap, bil_intraday, next_target)
        except RuntimeError as exc:
            marker = "allocation transition coincides with unresolved Wealth Core open"
            if marker not in str(exc) or str(account.name) != "A":
                raise
            state = captured["state"]
            if state is None:
                raise RuntimeError("diagnostic state missing") from exc
            session = str(state.last_processed_session)
            evidence = dict(state.last_evidence or {})
            wc = dict(evidence.get("wealth_core") or {})
            unresolved = [str(x) for x in (wc.get("open_unresolved_security_ids") or ())]
            episodes = dict((state.wealth_core or {}).get("episodes") or {})
            held = []
            tickers = set()
            for slot_id, episode in sorted(episodes.items(), key=lambda item: str(item[0])):
                sid = str((episode or {}).get("security_id", ""))
                if sid not in unresolved:
                    continue
                ticker = str((episode or {}).get("ticker") or "")
                if ticker:
                    tickers.add(ticker)
                held.append({"slot_id": str(slot_id), "episode": _jsonable(episode)})

            action_history = []
            try:
                actions = pd.read_csv(lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz", compression="gzip", low_memory=False)
                actions["date"] = actions["date"].astype(str).str[:10]
                actions["ticker"] = actions["ticker"].astype(str)
                d = pd.Timestamp(session)
                lo = (d - timedelta(days=45)).date().isoformat()
                hi = (d + timedelta(days=5)).date().isoformat()
                m = actions[actions["ticker"].isin(sorted(tickers)) & actions["date"].between(lo, hi)]
                action_history = _jsonable(m.to_dict(orient="records"))
            except Exception as probe_exc:
                action_history = [{"probe_error": repr(probe_exc)}]

            sep_history = []
            try:
                year = session[:4]
                for path in sorted((lab / "sharadar").glob(f"SHARADAR_SEP_{year}.csv*.gz")):
                    frame = pd.read_csv(path, usecols=["ticker", "date", "open", "close", "closeunadj", "volume"], low_memory=False)
                    frame["date"] = frame["date"].astype(str).str[:10]
                    frame["ticker"] = frame["ticker"].astype(str)
                    d = pd.Timestamp(session)
                    lo = (d - timedelta(days=15)).date().isoformat()
                    hi = (d + timedelta(days=5)).date().isoformat()
                    m = frame[frame["ticker"].isin(sorted(tickers)) & frame["date"].between(lo, hi)]
                    for row in m.to_dict(orient="records"):
                        sep_history.append({"source": path.name, **_jsonable(row)})
            except Exception as probe_exc:
                sep_history = [{"probe_error": repr(probe_exc)}]

            payload = {
                "schema": "backtester.unresolved-open-terminal-overlay/1",
                "status": "FOUND",
                "session": session,
                "processed_a_sessions": cache["a_transitions"],
                "collapsed_second_arm_transitions": cache["collapsed"],
                "strategy_main_sha": os.environ.get("BACKTESTER_MAIN_SHA"),
                "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
                "error": str(exc),
                "account": {
                    "nav_before_session": account.nav,
                    "effective_before_open": account.effective,
                    "pending_target_for_this_open": account.pending,
                    "close_decision_target_for_next_open": next_target,
                    "prior_core_close": prior_core_close,
                    "core_open": core_open,
                    "core_close": core_close,
                },
                "open_unresolved_security_ids": unresolved,
                "unresolved_holdings": held,
                "wealth_core_evidence": wc,
                "terminal_source_session": captured["terminal_session"],
                "terminal_source_rows": captured["terminal_source_rows"],
                "terminal_events": captured["terminal_events"],
                "nearby_action_history": action_history,
                "nearby_sep_history": sep_history,
                "decision": _jsonable(state.last_decision),
            }
            diag.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            print("[DIAGNOSTIC] unresolved-open boundary captured", flush=True)
            print(json.dumps(payload, sort_keys=True, default=str), flush=True)
            raise

    runner.OverlayAccount.step = diagnostic_step
    runner.END_SESSION = "2002-01-31"
    runner.MEASUREMENT_WINDOWS = {}
    print("[DIAGNOSTIC] A-only replay with frozen causal terminal overlay", flush=True)
    return int(runner.main())


if __name__ == "__main__":
    raise SystemExit(main())
