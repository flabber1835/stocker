#!/usr/bin/env python3
"""Corrections to the causal runtime before certification execution."""
from __future__ import annotations

import math
from typing import Any, Mapping

from backtester import research_causal_runtime as base
from backtester.canonical_pit_dataset import (
    CanonicalPITDataset as ImmutableCanonicalPITDataset,
)
from backtester.research_causal_runtime import *  # noqa: F401,F403


class CausalPITDataset(base.CausalPITDataset):
    """Causal dataset with byte-exact unpoisoned benchmark prefixes."""

    def benchmark(self) -> tuple[dict[str, float], dict[str, float]]:
        levels, returns = ImmutableCanonicalPITDataset.benchmark(self)
        if self.variant == "prefix":
            levels = {k: v for k, v in levels.items() if k <= str(self.cutoff)}
            returns = {k: v for k, v in returns.items() if k <= str(self.cutoff)}
        elif self.variant == "poison":
            running: float | None = None
            poisoned_levels: dict[str, float] = {}
            poisoned_returns: dict[str, float] = {}
            for session in sorted(levels):
                if session <= str(self.cutoff):
                    running = float(levels[session])
                    poisoned_levels[session] = running
                    poisoned_returns[session] = float(returns[session])
                    continue
                factor = 0.82 + 0.36 * base._poison_unit("benchmark|" + session)
                if running is None:
                    raise RuntimeError("future benchmark poison has no causal anchor")
                running *= factor
                poisoned_levels[session] = running
                poisoned_returns[session] = factor - 1.0
                self._poison_counts["benchmark"] += 1
            levels, returns = poisoned_levels, poisoned_returns
        return levels, returns


def assert_med_age119(
    *,
    session: object,
    entry_session: object,
    age: int,
    entry_basis: float,
    current_close: float,
) -> None:
    base.assert_med_age119(
        session=session,
        entry_session=entry_session,
        age=age,
        entry_basis=entry_basis,
        current_close=current_close,
    )
    if not math.isclose(float(entry_basis), 6.8, rel_tol=0.0, abs_tol=1.0e-12):
        raise RuntimeError(
            f"MED regression execution-open basis changed: {entry_basis!r}"
        )


def emit_session_trace(writer: base.CausalTraceWriter, state: Mapping[str, Any]) -> None:
    session = str(state["ds"])
    base.reject_future(session, "trace")
    dataset: CausalPITDataset = state["_CANONICAL"]
    base.verify_benchmark_cache(state["spy"], session)

    sid = state["sid"]
    tick = state["tick"]
    tids = [int(value) for value in state["tids"]]
    eligible = [str(sid[int(value)]) for value in state["et"]]
    ranking = [str(sid[int(value)]) for value in state["durable"]]
    signals = []
    for tid in sorted(tids, key=lambda value: str(sid[value])):
        signals.append(
            {
                "security_id": str(sid[tid]),
                "ticker": str(tick[tid]),
                "open_raw": base._float_token(state["opraw"][tid]),
                "open_signal": base._float_token(state["opsig"][tid]),
                "close_signal": base._float_token(state["clsig"][tid]),
                "close_raw": base._float_token(state["clraw"][tid]),
                "volume": base._float_token(state["volume"][tid]),
                "momentum": base._float_token(state["mom"][tid]),
                "recent": base._float_token(state["recent"][tid]),
                "score": base._float_token(state["score"][tid]),
                "adv20": base._float_token(state["adv"][tid]),
            }
        )
    signal_digest, signal_bytes = base.canonical_sha256(signals)

    book = state["book"]
    sessions = state["_causal_sessions"]
    positions = []
    pending = []
    for slot_index, slot in enumerate(book.slots):
        if slot.held():
            security_id = str(sid[int(slot.tid)])
            age = int(state["gday"]) - int(slot.entry_day)
            base.assert_position_age(
                session_index=int(state["gday"]),
                entry_index=int(slot.entry_day),
                observed_age=age,
                security_id=security_id,
            )
            positions.append(
                {
                    "slot": slot_index,
                    "security_id": security_id,
                    "ticker": str(tick[int(slot.tid)]),
                    "qty": base._float_token(slot.qty),
                    "entry_session": base._session_from_index(
                        sessions, int(slot.entry_day)
                    ),
                    "entry_basis": base._float_token(slot.entry_sig),
                    "peak": base._float_token(slot.peak),
                    "age": age,
                    "reviewed": bool(slot.reviewed),
                    "pending_sell": bool(slot.pending_sell),
                    "sell_reason": str(slot.sell_reason),
                }
            )
        if slot.reserved():
            pending.append(
                {
                    "slot": slot_index,
                    "security_id": str(sid[int(slot.pending_tid)]),
                    "shares": base._float_token(slot.pending_shares),
                    "signal_session": base._session_from_index(
                        sessions, int(slot.pending_signal_day)
                    ),
                }
            )

    orders = list(state.get("_session_orders") or ())
    fills = list(state.get("_session_fills") or ())
    decisions = list(state.get("_session_decisions") or ())
    chronological_events = []
    for category, events in (
        ("order", orders),
        ("fill", fills),
        ("decision", decisions),
    ):
        for sequence, event in enumerate(events):
            phase = int(event.get("phase", -1))
            if phase not in {1, 2, 4}:
                raise RuntimeError(
                    f"CAUSAL_GUARD: invalid event phase on {session}: {event}"
                )
            chronological_events.append(
                {"category": category, "sequence": sequence, **event}
            )
    chronological_events.sort(
        key=lambda event: (
            int(event["phase"]),
            str(event["category"]),
            int(event["sequence"]),
        )
    )

    action_payload = state.get("dayact") or {}
    action_digest, action_bytes = base.canonical_sha256(action_payload)
    selected = sorted(position["security_id"] for position in positions)
    payload = {
        "schema": "backtester.research-causal-session-trace/1",
        "session": session,
        "session_index": int(state["gday"]),
        "dataset_session_hash": dataset.session_hash(session),
        "eligible_universe": sorted(eligible),
        "eligible_count": len(eligible),
        "signals_sha256": signal_digest,
        "signals_canonical_bytes": signal_bytes,
        "signals_count": len(signals),
        "ranking": ranking,
        "ranking_count": len(ranking),
        "selected_positions": selected,
        "positions": positions,
        "pending_orders": pending,
        "orders_generated": orders,
        "fills": fills,
        "decisions": decisions,
        "chronological_events": chronological_events,
        "event_phase_order": [int(event["phase"]) for event in chronological_events],
        "session_actions_sha256": action_digest,
        "session_actions_canonical_bytes": action_bytes,
        "split_dividend_events": list(state.get("_session_actions") or ()),
        "terminal_security_ids": sorted(
            str(sid[int(value)]) for value in state.get("term_tids", ())
        ),
        "wealth_core": {
            "open_equity": base._float_token(state["open_eq"]),
            "close_equity": base._float_token(state["eq"]),
            "cash": base._float_token(book.cash),
            "receivables": list(book.receivables),
            "drawdown": base._float_token(state["dd"]),
        },
        "breadth": {
            "damaged": base._float_token(state["dam_b"]),
            "green": base._float_token(state["green_b"]),
            "recent_r20": base._float_token(state["recent_r20"]),
            "recent_r40": base._float_token(state["recent_r40"]),
        },
        "native_target": base._float_token(state["native_target"]),
        "native_state": dict(state["native"].__dict__),
        "ldrc_desired_close_target": base._float_token(state["ctl_d"]),
        "ldrc_state": dict(state["ctl"].__dict__),
        "allocation": {
            "prior_close_pending_native": base._float_token(
                state["_prior_pending_native"]
            ),
            "prior_close_pending_control": base._float_token(
                state["_prior_pend"]["control"]
            ),
            "effective_native": base._float_token(state["effective_native"]),
            "effective_control": base._float_token(state["eff"]["control"]),
            "next_close_native_target": base._float_token(state["native_target"]),
            "next_close_control_target": base._float_token(state["ctl_d"]),
        },
        "nav": {
            "control": base._float_token(state["navs"]["control"]),
            "spy": base._float_token(state.get("spy_nav")),
        },
    }
    writer.write(payload)
