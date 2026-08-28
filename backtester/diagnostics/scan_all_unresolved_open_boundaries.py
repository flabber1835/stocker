#!/usr/bin/env python3
"""Scan the whole A path for every unresolved-open allocation boundary.

Diagnostic only. It uses the exact production A state transition with the frozen
causal terminal overlay, collapses the second arm onto A for speed, records every
session where an allocation change requires an unavailable Wealth Core open, and
continues scanning. Overlay NAV after the first such boundary is intentionally
non-authoritative and is never emitted as a backtest result; production Wealth
Core/Sentinel state does not consume overlay NAV.
"""
from __future__ import annotations

import copy
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
    raw = getattr(value, "__dict__", None)
    return _jsonable(raw) if raw is not None else repr(value)


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_SCAN_OUTPUT",
        "backtester-results/all-unresolved-open-boundaries.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    wrapper = lab / "backtester" / "run_sector_ad_causal_terminal_terms_v2.py"
    spec = importlib.util.spec_from_file_location("scan_unresolved_v2", wrapper)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {wrapper}")
    v2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v2)
    runner = v2.runner

    import sentinel.core.production as production

    real_advance = production.advance_state
    advance_cache = {"session": None, "result": None, "a_calls": 0, "collapsed": 0}

    def a_only_advance(state, published, *args, **kwargs):
        session = str(published.session)
        if advance_cache["session"] == session:
            advance_cache["collapsed"] += 1
            return copy.deepcopy(advance_cache["result"])
        result = real_advance(state, published, *args, **kwargs)
        advance_cache["session"] = session
        advance_cache["result"] = copy.deepcopy(result)
        advance_cache["a_calls"] += 1
        return result

    production.advance_state = a_only_advance

    captured = {"state": None}
    real_wc = runner.wealth_equities

    def capture_wc(state):
        captured["state"] = state
        return real_wc(state)

    runner.wealth_equities = capture_wc

    records: list[dict] = []
    invalid_overlay_from: str | None = None
    real_step = runner.OverlayAccount.step

    def scanner_step(account, core_open, core_close, prior_core_close,
                     bil_gap, bil_intraday, next_target):
        nonlocal invalid_overlay_from
        if (core_open is None and account.initialized and prior_core_close is not None
                and abs(account.pending - account.effective) > 1e-15):
            state = captured["state"]
            if state is None:
                raise RuntimeError("scanner failed to capture production state")
            session = str(state.last_processed_session)
            wc = dict(((state.last_evidence or {}).get("wealth_core") or {}))
            unresolved = [str(x) for x in (wc.get("open_unresolved_security_ids") or ())]
            episodes = dict((state.wealth_core or {}).get("episodes") or {})
            holdings = []
            for slot_id, episode in sorted(episodes.items(), key=lambda item: str(item[0])):
                sid = str((episode or {}).get("security_id", ""))
                if sid in unresolved:
                    holdings.append({"slot_id": str(slot_id), "episode": _jsonable(episode)})
            if str(account.name) == "A":
                records.append({
                    "session": session,
                    "open_unresolved_security_ids": unresolved,
                    "unresolved_holdings": holdings,
                    "pending_target_for_open": float(account.pending),
                    "effective_before_open": float(account.effective),
                    "close_decision_target_for_next_open": float(next_target),
                    "resolved_open_equity": wc.get("resolved_open_equity"),
                    "estimated_equity": wc.get("estimated_equity"),
                    "terminal_pending_terms": _jsonable(
                        (state.wealth_core or {}).get("terminal_pending_terms") or {}),
                    "unresolved_terminals": _jsonable(
                        (state.wealth_core or {}).get("unresolved_terminals") or {}),
                })
                print(
                    f"[SCAN] unresolved-open transition session={session} ids={unresolved}",
                    flush=True,
                )
                if invalid_overlay_from is None:
                    invalid_overlay_from = session

            # Continue diagnostic traversal. This deliberately does not claim an
            # exact overlay NAV. Production strategy state is independent of the
            # research OverlayAccount bookkeeping.
            core_c2c = core_close / prior_core_close
            bil_c2c = bil_gap * bil_intraday
            account.nav *= account.effective * core_c2c + (1.0 - account.effective) * bil_c2c
            account.effective = account.pending
            account.pending = next_target
            return account.nav
        return real_step(
            account, core_open, core_close, prior_core_close,
            bil_gap, bil_intraday, next_target)

    runner.OverlayAccount.step = scanner_step
    runner.MEASUREMENT_WINDOWS = {}

    print("[SCAN] full A-only unresolved-open traversal started", flush=True)
    rc = int(runner.main())
    payload = {
        "schema": "backtester.unresolved-open-scan/1",
        "status": "PASS" if rc == 0 else "RUNNER_ERROR",
        "strategy_main_sha": os.environ.get("BACKTESTER_MAIN_SHA"),
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "fresh_chronological_replay": True,
        "diagnostic_only": True,
        "overlay_nav_authoritative": False if invalid_overlay_from else True,
        "overlay_nav_invalid_from": invalid_overlay_from,
        "a_production_transitions": int(advance_cache["a_calls"]),
        "collapsed_second_arm_transitions": int(advance_cache["collapsed"]),
        "unresolved_boundary_count": len(records),
        "records": records,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[SCAN] completed boundaries={len(records)} rc={rc}", flush=True)
    if rc != 0:
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
