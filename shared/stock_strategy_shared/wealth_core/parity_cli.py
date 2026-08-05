"""Emit the seven Wealth Core parity hashes as JSON.

    python -m stock_strategy_shared.wealth_core.parity_cli [--engine NAME]

Runs the SHARED golden scenario through the engine named and prints its hashes,
so a deployed backtester, wind tunnel and live pipeline can be compared with
three `docker exec` calls and a diff.

WHY THIS RUNS IN THE CONTAINER RATHER THAN IN CI. CI proves the source agrees.
This proves the IMAGES agree — which is a different claim, and the one that
matters, because the backtest stack has no `shared/` bind mount and imports the
copy baked into `stocker-base`. A backtester rebuilt on a fresh base and a
bt-engine re-layered on a stale one are the exact configuration this project has
already been bitten by, and their source is identical in git.

The scenario is generated in code, so nothing has to be mounted or copied into
the containers for this to work.
"""
from __future__ import annotations

import argparse
import json
import sys


def _run(engine: str) -> dict:
    from stock_strategy_shared.wealth_core.golden import golden_scenario
    from stock_strategy_shared.wealth_core.run import run_with_hashes

    g = golden_scenario()
    result, hashes = run_with_hashes(
        sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
        starting_cash=g.starting_cash, terminal_events=g.terminal_events)
    return {
        "engine": engine,
        "strategy_id": "stocker_wealth_core_v1",
        "ordering_profile": __import__(
            "stock_strategy_shared.wealth_core.ordering",
            fromlist=["CANONICAL_PROFILE"]).CANONICAL_PROFILE,
        "sessions": len(g.sessions),
        "securities": len(g.meta),
        "hashes": hashes.to_dict(),
        "final_cash": round(result.state.cash, 2),
        "final_positions": len(result.state.episodes),
        "marked_equity": (None if not result.final
                          else result.final.marked_equity),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", default="unknown",
                    help="label for this container, e.g. backtester")
    ap.add_argument("--compare", metavar="FILE",
                    help="a previously emitted JSON to diff against; exits "
                         "non-zero and names the FIRST diverging layer")
    args = ap.parse_args(argv)

    out = _run(args.engine)
    if args.compare:
        from stock_strategy_shared.wealth_core.hashes import divergence_report
        other = json.loads(open(args.compare).read())
        rep = divergence_report(out["hashes"], other["hashes"],
                                left=out["engine"],
                                right=other.get("engine", "reference"))
        out["comparison"] = rep
        print(json.dumps(out, indent=2, sort_keys=True))
        if not rep["identical"]:
            print(f"\nDIVERGES AT {rep['first_divergence']}: "
                  f"{rep['interpretation']}", file=sys.stderr)
            return 1
        return 0

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
