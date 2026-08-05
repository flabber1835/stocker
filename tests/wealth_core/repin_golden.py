"""Regenerate the pinned golden fixture.

    python -m tests.wealth_core.repin_golden

Deliberately a separate command rather than a `--update` flag on the test. A pin
that any test run can rewrite is not a pin: the first CI failure regenerates it
and the guarantee is gone with no one deciding anything. Running this is meant to
be a considered act, recorded in the commit that explains WHY the strategy's
output moved.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

from stock_strategy_shared.wealth_core.golden import golden_scenario
from stock_strategy_shared.wealth_core.run import run_sessions

OUT = pathlib.Path(__file__).parent / "fixtures" / "golden_wealth_core_v1.json"


def main() -> None:
    g = golden_scenario()
    r = run_sessions(sessions=g.sessions, bars_by_session=g.bars_by_session,
                     meta=g.meta, starting_cash=g.starting_cash,
                     terminal_events=g.terminal_events)
    payload = {
        "_comment": "Pinned by tests/wealth_core/repin_golden.py. A change here "
                    "means the strategy's output moved; explain it in the commit.",
        "strategy_id": "stocker_wealth_core_v1",
        "strategy_version": 1,
        "sessions": len(g.sessions),
        "securities": len(g.meta),
        "starting_cash": g.starting_cash,
        "result_hash": r.result_hash(),
        "final_state_hash": r.state.state_hash(),
        "ledger_hash": r.ledger.ledger_hash(),
        "final_cash": round(r.state.cash, 2),
        "final_positions": len(r.state.episodes),
        "blocked_sessions": list(r.blocked_sessions),
        "ledger_event_counts": dict(
            Counter(e.event_type.value for e in r.ledger.events)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"pinned {OUT}\n  result_hash {payload['result_hash']}")


if __name__ == "__main__":
    main()
