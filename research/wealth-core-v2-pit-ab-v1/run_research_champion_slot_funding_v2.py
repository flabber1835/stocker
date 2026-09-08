#!/usr/bin/env python3
"""Research-only Wealth Core V2 overlay for the certified Research Champion PIT replay.

V1 remains byte-for-byte untouched.  V2 changes exactly one economic domain:
entry slot funding.  A candidate may reserve a slot only when uncommitted settled
cash can fund the complete decision-close whole-share target.  The reservation
carries that cash budget to the next executable open; an overnight gap may reduce
shares only within the reserved budget.  No top-ups, leverage, winner trimming,
or fitted minimum-fill threshold are introduced.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from backtester import run_research_champion_strict_pit_20y_v2 as certified

PROFILE = "full_whole_share_target_v1"
BASE = certified.champion
_PRIOR_TRANSFORM = BASE.strict20.corrected.transformed_source


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def install_slot_funding_v2(text: str) -> str:
    # Persistent reservation budget.  Reserved cash remains part of equity but is
    # unavailable to subsequent admissions until this pending episode resolves.
    text = replace_once(
        text,
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; reserved_cash:float=0.; ready_day:int=0",
        "slot reservation cash state",
    )
    text = replace_once(
        text,
        "    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}\n",
        "    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}\n"
        "    def reserved_cash_total(self): return float(sum(s.reserved_cash for s in self.slots if s.reserved()))\n"
        "    def uncommitted_cash(self): return max(0.,float(self.cash)-self.reserved_cash_total())\n",
        "book uncommitted cash accounting",
    )

    # Diagnostics are observational only and never feed decisions.
    text = replace_once(
        text,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0",
        "slot-funding diagnostic counters",
    )

    # Any cancellation of a still-pending episode releases its budget immediately.
    text = replace_once(
        text,
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.reserved_cash=0.",
        "fractional split reservation cancellation",
    )
    text = replace_once(
        text,
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.reserved_cash=0.",
        "terminal reservation cancellation",
    )

    # Execution is bounded by the decision-close reservation, never by cash that
    # appeared later from an unrelated sale/dividend.
    text = replace_once(
        text,
        "afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)",
        "afford=math.floor(s.reserved_cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford); slot_v2_gap_clipped+=int(q<int(round(s.pending_shares))); slot_v2_gap_cancelled+=int(q<1)",
        "reservation-bounded next-open fill",
    )
    # Bind reservation release to the actual successful/open-fill resolution
    # seam. Champion legitimately contains additional bare pending cleanups, so
    # the cleanup statement alone is not a unique execution anchor.
    text = replace_once(
        text,
        "book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.reserved_cash=0.",
        "open-fill reservation release",
    )

    # Decision-close target is no longer cash-clipped.  Whole-share rounding is
    # retained exactly.  If the complete rounded target cannot be funded from
    # uncommitted cash, the candidate receives no slot and can compete again later.
    text = replace_once(
        text,
        "target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))",
        "target=eq*ENTRY_W; q=int(target//(float(px)*(1+COST))); required_cash=float(q)*float(px)*(1+COST)",
        "full whole-share target",
    )
    text = replace_once(
        text,
        "                        if q<1: continue\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday;",
        "                        if q<1: continue\n"
        "                        if required_cash>book.uncommitted_cash()+1e-8: slot_v2_rejected+=1; continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.reserved_cash=required_cash; slot_v2_reserved+=1;",
        "fully funded slot reservation",
    )

    # Capital-state telemetry for the A/B analysis.  These fields are outputs only.
    text = replace_once(
        text,
        "rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'wc_dd':dd,'damaged':dam_b,'green':green_b,",
        "rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'wc_cash':float(book.cash),'wc_reserved_entry_cash':book.reserved_cash_total(),'wc_uncommitted_cash':book.uncommitted_cash(),'wc_held_count':int(len(held)),'wc_dd':dd,'damaged':dam_b,'green':green_b,",
        "slot-funding daily telemetry",
    )
    text = replace_once(
        text,
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,",
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n"
        "        'wealth_core_entry_funding':{'profile':'full_whole_share_target_v1','reserved':slot_v2_reserved,'rejected_insufficient_uncommitted_cash':slot_v2_rejected,'gap_clipped':slot_v2_gap_clipped,'gap_cancelled':slot_v2_gap_cancelled},",
        "slot-funding summary telemetry",
    )

    forbidden = (
        "target=min(eq*ENTRY_W,book.cash)",
        "afford=math.floor(book.cash/(float(px)*(1+COST)))",
    )
    survived = [needle for needle in forbidden if needle in text]
    if survived:
        raise RuntimeError(f"legacy cash-clipped admission survived V2 transform: {survived}")
    required = (
        "reserved_cash:float=0.",
        "def uncommitted_cash(self)",
        "required_cash>book.uncommitted_cash()",
        "afford=math.floor(s.reserved_cash/",
        "'profile':'full_whole_share_target_v1'",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"V2 slot-funding transform incomplete: {missing}")
    return text


def transformed_source(mode: str, output: Path) -> str:
    if mode != "fullpit":
        raise RuntimeError("Wealth Core V2 experiment is full-PIT only")
    return install_slot_funding_v2(_PRIOR_TRANSFORM(mode, output))


BASE.strict20.corrected.transformed_source = transformed_source


def _seal_v2_identity(output: Path) -> None:
    summary_path = output / "summary.json"
    identity_path = output / "research-champion-identity.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    binding = {
        "profile": PROFILE,
        "economic_change_count": 1,
        "changed_domain": "wealth_core_entry_slot_funding",
        "target_slots": 25,
        "entry_weight": 0.04,
        "cash_clip_at_decision": False,
        "full_whole_share_target_required": True,
        "pending_cash_reserved": True,
        "next_open_fill_bounded_by_reservation": True,
        "top_up": False,
        "winner_trim": False,
        "leverage": False,
        "minimum_fill_threshold": None,
    }
    summary["wealth_core_v2"] = binding
    identity["wealth_core_v2"] = binding
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    rc = int(certified.main())
    if rc != 0 or "--self-test-imports" in sys.argv[1:]:
        return rc
    try:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    except (ValueError, IndexError):
        raise RuntimeError("V2 wrapper requires --output")
    _seal_v2_identity(output)
    print(f"[WEALTH_CORE_V2] PASS profile={PROFILE}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
