#!/usr/bin/env python3
"""Fresh A-only diagnostic for unresolved Wealth Core open/allocation transitions.

This wrapper does not change strategy economics and does not create a backtest
result. It executes the existing fresh chronological runner while collapsing
its second (B) strategy transition onto the already-computed A state, so the
first failing A session can be diagnosed faster. No prerecorded strategy state,
decisions, holdings, NAV, or transition schedule is consumed.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import sys


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
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    lab_root = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    diag_path = Path(os.environ.get(
        "BACKTESTER_DIAG_OUTPUT",
        "backtester-results/unresolved-open-diagnostic.json",
    )).resolve()
    diag_path.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    import sentinel.core.production as production

    runner_path = lab_root / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
    spec = importlib.util.spec_from_file_location("sector_ab_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import runner at {runner_path}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    exact_sha = os.environ.get("BACKTESTER_MAIN_SHA", "")
    if exact_sha != runner.EXPECTED_MAIN_SHA:
        raise RuntimeError(
            f"diagnostic main SHA mismatch: expected {runner.EXPECTED_MAIN_SHA}, got {exact_sha}")

    real_advance = production.advance_state
    cache = {
        "session": None,
        "result": None,
        "published": None,
        "a_transitions": 0,
        "collapsed_b_transitions": 0,
    }

    def a_only_advance(state, published, *args, **kwargs):
        session = str(published.session)
        if cache["session"] == session:
            cache["collapsed_b_transitions"] += 1
            return cache["result"]
        result = real_advance(state, published, *args, **kwargs)
        cache["session"] = session
        cache["result"] = result
        cache["published"] = published
        cache["a_transitions"] += 1
        return result

    production.advance_state = a_only_advance

    diagnostic_state = {"state": None}
    real_wealth_equities = runner.wealth_equities

    def capture_state(state):
        diagnostic_state["state"] = state
        return real_wealth_equities(state)

    runner.wealth_equities = capture_state
    real_step = runner.OverlayAccount.step

    def diagnostic_step(account, core_open, core_close, prior_core_close,
                        bil_gap, bil_intraday, next_target):
        try:
            return real_step(
                account, core_open, core_close, prior_core_close,
                bil_gap, bil_intraday, next_target)
        except RuntimeError as exc:
            marker = "allocation transition coincides with unresolved Wealth Core open"
            if marker not in str(exc) or account.name != "A":
                raise

            state = diagnostic_state["state"]
            if state is None:
                raise RuntimeError("diagnostic state was not captured") from exc
            session = str(state.last_processed_session)
            evidence = dict(state.last_evidence or {})
            wc = dict(evidence.get("wealth_core") or {})
            unresolved = [str(x) for x in (wc.get("open_unresolved_security_ids") or [])]
            published = cache.get("published")
            bars = list(getattr(published, "bars", ()) or ())
            by_sid = {str(getattr(bar, "security_id", "")): bar for bar in bars}

            episodes = dict((state.wealth_core or {}).get("episodes") or {})
            held_rows = []
            for slot_id, episode in sorted(episodes.items(), key=lambda item: str(item[0])):
                sid = str((episode or {}).get("security_id", ""))
                if sid not in unresolved:
                    continue
                feed_series = dict(((state.feed or {}).get("series") or {}).get(sid) or {})
                held_rows.append({
                    "slot_id": str(slot_id),
                    "episode": _jsonable(episode),
                    "feed_anchor": {
                        key: feed_series.get(key)
                        for key in ("security_id", "ticker", "issuer_id", "split_factor")
                    },
                    "published_bar": _jsonable(by_sid.get(sid)),
                })

            raw_rows = []
            tickers = sorted({
                str(row.get("episode", {}).get("ticker") or row.get("feed_anchor", {}).get("ticker") or "")
                for row in held_rows
                if str(row.get("episode", {}).get("ticker") or row.get("feed_anchor", {}).get("ticker") or "")
            })
            year = session[:4]
            try:
                import pandas as pd
                for path in sorted((lab_root / "sharadar").glob(f"SHARADAR_SEP_{year}.csv*.gz")):
                    frame = pd.read_csv(
                        path,
                        usecols=["ticker", "date", "open", "close", "closeunadj", "volume"],
                        low_memory=False,
                    )
                    frame["date"] = frame["date"].astype(str).str[:10]
                    frame["ticker"] = frame["ticker"].astype(str)
                    match = frame[(frame["date"] == session) & frame["ticker"].isin(tickers)]
                    for row in match.to_dict(orient="records"):
                        raw_rows.append({"source": path.name, **_jsonable(row)})
            except Exception as raw_exc:  # diagnostic evidence must survive even if this probe fails
                raw_rows.append({"probe_error": repr(raw_exc)})

            payload = {
                "schema": "backtester.unresolved-open-diagnostic/1",
                "status": "FOUND",
                "strategy_main_sha": exact_sha,
                "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
                "fresh_chronological_replay": True,
                "prerecorded_decision_inputs": False,
                "diagnostic_mode": "A_ONLY_SECOND_ARM_COLLAPSED",
                "session": session,
                "processed_a_sessions": cache["a_transitions"],
                "collapsed_b_transitions": cache["collapsed_b_transitions"],
                "account": {
                    "name": account.name,
                    "effective_before_open": account.effective,
                    "pending_target_for_this_open": account.pending,
                    "close_decision_target_for_next_open": next_target,
                    "nav_before_session": account.nav,
                    "prior_core_close": prior_core_close,
                    "core_open": core_open,
                    "core_close": core_close,
                    "bil_gap": bil_gap,
                    "bil_intraday": bil_intraday,
                },
                "open_unresolved_security_ids": unresolved,
                "wealth_core_evidence": wc,
                "unresolved_holdings": held_rows,
                "raw_sep_rows_for_unresolved_tickers": raw_rows,
                "decision": _jsonable(state.last_decision),
            }
            diag_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            print("[DIAGNOSTIC] unresolved-open allocation transition found", flush=True)
            print(json.dumps(payload, sort_keys=True, default=str), flush=True)
            raise

    runner.OverlayAccount.step = diagnostic_step

    print("[DIAGNOSTIC] fresh A-only replay; B strategy transition collapsed after A for speed", flush=True)
    print("[DIAGNOSTIC] no prerecorded decisions/state/NAV used", flush=True)
    return int(runner.main())


if __name__ == "__main__":
    raise SystemExit(main())
