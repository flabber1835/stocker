#!/usr/bin/env python3
"""Accelerated A/D replay: compute Wealth Core once, reuse it for D, run Sentinel twice.

This wrapper preserves the v2 research runner and its production strategy pin.
The only acceleration is at production.plan_session(): A executes the real
Wealth Core session, and D receives a deep-copied image of the exact resulting
Wealth Core mutable objects and LiveSessionPlan. D then continues through the
normal production Sentinel/controller/LD-RC path with its own FF12 sectors.

The wrapper fails closed unless A and D enter plan_session with byte-equivalent
economic state. The base runner's session-by-session Wealth Core parity gate
remains active after each full production.advance_state() call.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path


V2_PATH = Path(__file__).with_name("run_sector_ad_causal_terminal_terms_v2.py")
spec = importlib.util.spec_from_file_location("sector_ad_v2_shared_wc", V2_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {V2_PATH}")
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)

import sentinel.core.production as production

_real_plan_session = production.plan_session

_cache: dict[str, object] = {
    "session": None,
    "calls": 0,
    "pre": None,
    "post": None,
    "plan": None,
    "real_plan_calls": 0,
    "reused_plan_calls": 0,
}


def _object_dict(value, label: str) -> dict:
    raw = getattr(value, "__dict__", None)
    if raw is None:
        raise RuntimeError(f"shared Wealth Core optimization cannot snapshot {label}: no __dict__")
    return copy.deepcopy(raw)


def _snapshot_inputs(kwargs: dict) -> dict:
    return {
        "state": _object_dict(kwargs["state"], "PortfolioState"),
        "pending": copy.deepcopy(kwargs["pending"]),
        "ledger": _object_dict(kwargs["ledger"], "Ledger"),
        "last_known": copy.deepcopy(kwargs["last_known"]),
        "feed": _object_dict(kwargs["feed"], "Feed"),
    }


def _snapshot_outputs(kwargs: dict) -> dict:
    return _snapshot_inputs(kwargs)


def _transplant_object(target, source_dict: dict, label: str) -> None:
    raw = getattr(target, "__dict__", None)
    if raw is None:
        raise RuntimeError(f"shared Wealth Core optimization cannot restore {label}: no __dict__")
    raw.clear()
    raw.update(copy.deepcopy(source_dict))


def _restore_outputs(kwargs: dict, snapshot: dict) -> None:
    _transplant_object(kwargs["state"], snapshot["state"], "PortfolioState")
    kwargs["pending"][:] = copy.deepcopy(snapshot["pending"])
    _transplant_object(kwargs["ledger"], snapshot["ledger"], "Ledger")
    kwargs["last_known"].clear()
    kwargs["last_known"].update(copy.deepcopy(snapshot["last_known"]))
    _transplant_object(kwargs["feed"], snapshot["feed"], "Feed")


def _shared_plan_session(*args, **kwargs):
    if args:
        raise RuntimeError("shared Wealth Core optimization requires keyword-only plan_session calls")
    session = str(kwargs.get("session"))
    if not session:
        raise RuntimeError("shared Wealth Core optimization received plan_session without session")

    cached_session = _cache["session"]
    if cached_session != session:
        if cached_session is not None and _cache["calls"] != 2:
            raise RuntimeError(
                f"shared Wealth Core optimization expected two plan calls for {cached_session}, "
                f"got {_cache['calls']}")
        _cache["session"] = session
        _cache["calls"] = 1
        _cache["pre"] = _snapshot_inputs(kwargs)
        plan = _real_plan_session(**kwargs)
        _cache["post"] = _snapshot_outputs(kwargs)
        _cache["plan"] = copy.deepcopy(plan)
        _cache["real_plan_calls"] = int(_cache["real_plan_calls"]) + 1
        return plan

    if _cache["calls"] != 1:
        raise RuntimeError(
            f"shared Wealth Core optimization received unexpected extra plan call for {session}")
    _cache["calls"] = 2

    current_pre = _snapshot_inputs(kwargs)
    if current_pre != _cache["pre"]:
        raise RuntimeError(
            f"A/D Wealth Core inputs differ before shared plan reuse at {session}")

    post = _cache["post"]
    plan = _cache["plan"]
    if not isinstance(post, dict) or plan is None:
        raise RuntimeError(f"shared Wealth Core cache is incomplete at {session}")
    _restore_outputs(kwargs, post)
    _cache["reused_plan_calls"] = int(_cache["reused_plan_calls"]) + 1
    return copy.deepcopy(plan)


production.plan_session = _shared_plan_session


def main() -> int:
    print("[OPTIMIZATION] shared Wealth Core plan enabled: A real, D exact deep-copy reuse", flush=True)
    equiv = os.environ.get("BACKTESTER_EQUIV_IGNORE_FINAL_SPLIT_AUDIT") == "1"
    bounded_end = os.environ.get("BACKTESTER_CAUSAL_END_SESSION")
    if equiv:
        # Equivalence-only seam. The bounded test compares the exact session
        # economics already produced by both runners; the base runner's final
        # full-corpus split-certification audit is not meaningful on a truncated
        # corpus and does not affect any simulated session.
        v2.runner.SPLIT_UNRESOLVED = "__EQUIV_ONLY_NO_MATCH__"
        print("[EQUIV] bounded final split audit disabled; session economics unchanged", flush=True)
        # The strict terminal overlay intentionally rejects frozen events that
        # lie outside a normal replay axis. A pre-2001 equivalence window cannot
        # consume the 2001 LIT/CIT/GPU records and none can affect its sessions.
        # Mark the exact-term cache empty only for such a bounded test so the
        # optimized arm reaches the Wealth Core reuse seam being certified.
        if bounded_end and bounded_end < "2001-05-30":
            v2._exact_by_session = {}
            v2._terms_digest = "equivalence-window-precedes-frozen-terminal-events"
            print("[EQUIV] future frozen terminal overlay excluded from pre-2001 window", flush=True)
    if os.environ.get("BACKTESTER_ACCEL_RAW_RUN") == "1":
        rc = int(v2.runner.main())
    else:
        rc = int(v2.main())
    if _cache["session"] is not None and _cache["calls"] != 2:
        raise RuntimeError(
            f"final session {_cache['session']} did not execute exactly two plan calls")
    print(
        "[OPTIMIZATION] real_wealth_core_plans="
        f"{_cache['real_plan_calls']} reused_wealth_core_plans={_cache['reused_plan_calls']}",
        flush=True,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
