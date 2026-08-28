#!/usr/bin/env python3
"""Scan the full A path for every held unresolved terminal/open gap.

Diagnostic only. This is broader than the allocation-boundary scanner: every
session with a held security in Wealth Core's open-unresolved set is recorded,
including sessions where Sentinel does not change exposure. The second arm is
collapsed onto A so Wealth Core/Sentinel production state is computed once.

If an unresolved open coincides with a research overlay allocation transition,
the scanner records that collision and advances OverlayAccount approximately so
production-state traversal can continue. Overlay NAV from the first such
collision onward is explicitly non-authoritative and is never a backtest result.
Production SessionState does not consume OverlayAccount NAV.
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
        "BACKTESTER_TERMINAL_GAP_OUTPUT",
        "backtester-results/all-held-terminal-gaps.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    wrapper = lab / "backtester" / "run_sector_ad_causal_terminal_terms_v2.py"
    spec = importlib.util.spec_from_file_location("scan_all_held_terminal_gaps_v2", wrapper)
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

    # The scanner needs session output after all chronological transitions have
    # run. The base runner's final unresolved-split certification is a separate
    # corpus audit and can abort before diagnostic evidence is written. Change
    # only the final disposition match token; session normalization/economics
    # still execute unchanged.
    runner.SPLIT_UNRESOLVED = "__TERMINAL_GAP_SCAN_FINAL_AUDIT_ONLY__"
    runner.MEASUREMENT_WINDOWS = {}

    gap_events: list[dict] = []
    gap_index: dict[tuple[str, str], int] = {}
    session_gap_indices: list[int] = []
    captured = {"state": None, "session": None}
    invalid_overlay_from: str | None = None

    real_wc = runner.wealth_equities

    def capture_wc(state):
        captured["state"] = state
        session = str(state.last_processed_session)
        captured["session"] = session
        session_gap_indices.clear()

        wc = dict(((state.last_evidence or {}).get("wealth_core") or {}))
        unresolved = [str(x) for x in (wc.get("open_unresolved_security_ids") or ())]
        if unresolved:
            episodes = dict((state.wealth_core or {}).get("episodes") or {})
            by_sid = {}
            for slot_id, episode in sorted(episodes.items(), key=lambda item: str(item[0])):
                sid = str((episode or {}).get("security_id", ""))
                if sid in unresolved:
                    by_sid[sid] = {"slot_id": str(slot_id), "episode": _jsonable(episode)}

            for sid in sorted(unresolved):
                held = by_sid.get(sid)
                episode = dict((held or {}).get("episode") or {})
                key = (sid, str(episode.get("entry_date") or ""))
                index = gap_index.get(key)
                if index is None:
                    index = len(gap_events)
                    gap_index[key] = index
                    gap_events.append({
                        "security_id": sid,
                        "ticker": str(episode.get("ticker") or ""),
                        "entry_date": episode.get("entry_date"),
                        "slot_id": (held or {}).get("slot_id"),
                        "shares": episode.get("current_shares"),
                        "first_unresolved_session": session,
                        "last_unresolved_session": session,
                        "unresolved_session_count": 1,
                        "allocation_transition_collision_sessions": [],
                        "first_wealth_core_evidence": wc,
                        "first_episode": episode,
                        "terminal_pending_terms": _jsonable(
                            (state.wealth_core or {}).get("terminal_pending_terms") or {}),
                        "unresolved_terminals": _jsonable(
                            (state.wealth_core or {}).get("unresolved_terminals") or {}),
                    })
                    print(
                        f"[GAP] first unresolved held terminal sid={sid} "
                        f"ticker={gap_events[index]['ticker']} session={session}",
                        flush=True,
                    )
                else:
                    row = gap_events[index]
                    row["last_unresolved_session"] = session
                    row["unresolved_session_count"] = int(row["unresolved_session_count"]) + 1
                session_gap_indices.append(index)

        return real_wc(state)

    runner.wealth_equities = capture_wc

    real_step = runner.OverlayAccount.step

    def scanner_step(account, core_open, core_close, prior_core_close,
                     bil_gap, bil_intraday, next_target):
        nonlocal invalid_overlay_from
        collision = (
            core_open is None
            and account.initialized
            and prior_core_close is not None
            and abs(account.pending - account.effective) > 1e-15
        )
        if collision:
            session = str(captured.get("session") or "")
            if str(account.name) == "A":
                for index in session_gap_indices:
                    gap_events[index]["allocation_transition_collision_sessions"].append(session)
                if invalid_overlay_from is None:
                    invalid_overlay_from = session
                print(
                    f"[GAP] allocation-transition collision session={session} "
                    f"gap_count={len(session_gap_indices)}",
                    flush=True,
                )

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

    print("[GAP] comprehensive A-only held-terminal-gap traversal started", flush=True)
    runner_error = None
    rc = 0
    try:
        rc = int(runner.main())
    except Exception as exc:
        runner_error = repr(exc)
        rc = 1
        print(f"[GAP] runner error after captured evidence: {runner_error}", flush=True)

    payload = {
        "schema": "backtester.held-terminal-gap-scan/1",
        "status": "PASS" if rc == 0 else "RUNNER_ERROR",
        "runner_error": runner_error,
        "strategy_main_sha": os.environ.get("BACKTESTER_MAIN_SHA"),
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "fresh_chronological_replay": True,
        "diagnostic_only": True,
        "session_economics_approximated": False,
        "overlay_nav_authoritative": invalid_overlay_from is None,
        "overlay_nav_invalid_from": invalid_overlay_from,
        "a_production_transitions": int(advance_cache["a_calls"]),
        "collapsed_second_arm_transitions": int(advance_cache["collapsed"]),
        "distinct_held_terminal_gap_count": len(gap_events),
        "allocation_transition_collision_count": sum(
            len(row["allocation_transition_collision_sessions"]) for row in gap_events),
        "gaps": gap_events,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[GAP] completed rc={rc} distinct_gaps={len(gap_events)} "
        f"A_transitions={advance_cache['a_calls']}",
        flush=True,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
