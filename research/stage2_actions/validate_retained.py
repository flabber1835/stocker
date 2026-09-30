"""Check corrected schedule against the eleven retained held cash episodes.

The result is a canonical terminal primitive check, not a full replay.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path

from research.bounded_20y.run import terminals
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState, SlotState
from stock_strategy_shared.wealth_core.terminal import apply_terminal


def validate(schedule_path: Path, cases_path: Path) -> dict:
    schedule = terminals(json.loads(schedule_path.read_text(encoding="utf-8")))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if len(cases) != 11:
        raise ValueError("expected eleven retained held episodes")
    results = []
    for case in cases:
        source = case["terms"]
        sid, ticker = source["security_id"], source["ticker"]
        old, legal = source["effective_session"], source["actual_legal_completion"]
        if any(e.security_id == sid for e in schedule.get(old, ())):
            raise ValueError("premature terminal remains: " + ticker)
        events = [e for e in schedule.get(legal, ()) if e.security_id == sid]
        if len(events) != 1:
            raise ValueError("corrected terminal absent or duplicated: " + ticker)
        book = PortfolioState.fresh(float(case["cash_at_merger"]), n_slots=20)
        for held in case["held_episodes"]:
            ep = HoldingEpisode(**held)
            book.episodes[ep.slot_id] = ep
            book.slots[ep.slot_id].occupied_by = sid
        expected = (sum(Decimal(str(h["current_shares"])) for h in case["held_episodes"])
                    * Decimal(source["cash_per_share"]))
        before_cash = Decimal(str(book.cash))
        if sid not in book.held_security_ids():
            raise ValueError("retained position missing before completion: " + ticker)
        prior_quote = case["quotes"][old]
        if prior_quote["tradeable"] != "1" or not prior_quote["raw_close"]:
            raise ValueError("final trading-day mark missing: " + ticker)
        ledger = Ledger()
        result = apply_terminal(book, events[0], ledger=ledger,
                                session=legal, cfg=WealthCoreConfig())
        if (not result["applied"] or sid in book.held_security_ids()
                or len(ledger.events) != 1
                or abs(Decimal(str(book.cash)) - before_cash - expected) > Decimal("0.000001")):
            raise ValueError("corrected held cash economics differ: " + ticker)
        duplicate = apply_terminal(book, events[0], ledger=ledger,
                                   session=legal, cfg=WealthCoreConfig())
        if duplicate["applied"] or len(ledger.events) != 1:
            raise ValueError("duplicate cash accepted: " + ticker)
        slot = SlotState(slot_id=0)
        slot.start_cooldown()
        for _ in range(20):
            slot.age_cooldown()
        if slot.ready:
            raise ValueError("age-20 slot unexpectedly ready: " + ticker)
        results.append({"ticker": ticker, "old": old, "completion": legal,
                        "shares": str(sum(Decimal(str(h["current_shares"]))
                                          for h in case["held_episodes"])),
                        "cash": str(expected), "old_day_mark": prior_quote["raw_close"]})
    return {"status": "PASS_CANONICAL_TERMINAL_PRIMITIVES",
            "count": len(results), "cases": results,
            "scope": "No full-session selection, controller, missing-mark or broker-credit proof"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.schedule, args.cases)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, sort_keys=True))
