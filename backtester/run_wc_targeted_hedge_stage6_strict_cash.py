#!/usr/bin/env python3
"""Run Stage 6 with Wealth Core's next-open fills given first claim on cash.

This is a source-identity guard around the zero-budget Stage 6 diagnostic. It
changes one research accounting seam only: the initial hedge budget is capped by
cash actually remaining in the Wealth Core book after the next-open Wealth Core
fills. No accepted-E3 strategy or Sentinel mechanic is changed.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

SOURCE = Path("backtester/diagnose_wc_targeted_hedge_stage6_pricing.py")

OLD = """        cash_frac=float(d.iloc[ti].wc_next_open_unreserved_cash_fraction)\n        # Use only natural cash attributable to the active WC sleeve. This is a\n        # conservative cap; Sentinel defensive cash is excluded.\n        initial_budget=max(account_value*max(next_alloc,0.0)*max(cash_frac,0.0),0.0)\n"""

NEW = """        planned_cash_frac=float(d.iloc[ti].wc_next_open_unreserved_cash_fraction)\n        # Wealth Core executes first at the next open. The actual post-WC cash\n        # balance is observable after those fills and before the separate hedge\n        # sleeve is allowed to spend. Cap the causal prior-close estimate by that\n        # realized remaining cash fraction so a gap-up admission cannot be starved.\n        entry_wc_open_equity=float(d.iloc[entry_i].research_wealth_core_open_equity)\n        actual_post_wc_cash_frac=(\n            float(d.iloc[entry_i].wc_cash_on_hand)/entry_wc_open_equity\n            if entry_wc_open_equity>0 else 0.0\n        )\n        cash_frac=min(max(planned_cash_frac,0.0),max(actual_post_wc_cash_frac,0.0))\n        # Use only natural cash attributable to the active WC sleeve. Sentinel\n        # defensive cash remains excluded.\n        initial_budget=max(account_value*max(next_alloc,0.0)*cash_frac,0.0)\n"""


def transformed_source() -> str:
    text=SOURCE.read_text(encoding="utf-8")
    count=text.count(OLD)
    if count!=1:
        raise RuntimeError(f"Stage6 cash-priority seam count={count}; source identity changed")
    text=text.replace(OLD,NEW,1)
    legacy_line="        cash_frac=float(d.iloc[ti].wc_next_open_unreserved_cash_fraction)"
    if legacy_line in text.splitlines():
        raise RuntimeError("uncapped Stage6 initial cash seam survived transform")
    if text.count("actual_post_wc_cash_frac") != 2:
        raise RuntimeError("strict Stage6 post-WC cash cap was not installed exactly once")
    return text


def main() -> int:
    generated=Path("/tmp/wc_targeted_hedge_stage6_strict_cash.py")
    generated.write_text(transformed_source(),encoding="utf-8")
    env=dict(os.environ)
    print("[RUN] Stage6 strict cash priority: Wealth Core next-open fills execute first",flush=True)
    subprocess.run([sys.executable,str(generated),*sys.argv[1:]],check=True,env=env)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
