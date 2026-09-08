#!/usr/bin/env python3
"""Run the certified Research Champion with only slot-funding economics corrected.

Execute this from the root of an exact checkout of certified source
27bb992087182c42c3c051e62bf837895f5d2ab7.  The current research branch owns
this overlay; the certified historical checkout remains read-only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from backtester import run_research_champion_strict_pit_20y_v2 as certified

CERTIFIED_SOURCE_SHA = "27bb992087182c42c3c051e62bf837895f5d2ab7"
CURRENT_KERNEL_ANCHOR = "bd5ba4572fb170ac5a5ac24c408c27ac2fe1b823"
FUNDING_PROFILE = "full_whole_share_target_v1"
PROFILE = "strategy9-e3-research-champion-v1"

_BASE_TRANSFORM = certified.champion.strict20.corrected.transformed_source


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source seam, found {count}")
    return text.replace(old, new, 1)


def apply_slot_funding(text: str) -> str:
    """Apply only the cash-reservation semantics frozen in EXPERIMENT_CONTRACT."""
    # Persistent budget on each queued entry.  The old research replay already
    # persisted pending security/share/signal-day state in the Slot object.
    text = _replace_once(
        text,
        "pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_cash:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "slot pending-cash state",
    )

    text = _replace_once(
        text,
        "    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}\n",
        "    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}\n"
        "    def reserved_cash_total(self): return float(sum(s.pending_cash for s in self.slots if s.reserved()))\n"
        "    def uncommitted_cash(self): return float(self.cash)-self.reserved_cash_total()\n",
        "book reservation budget queries",
    )

    # Research-only observer counters. They do not feed any strategy decision.
    text = _replace_once(
        text,
        "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; "
        "slot_funding_rejections=slot_funding_fill_count=slot_funding_gap_clipped_count=slot_funding_open_budget_cancels=0; "
        "slot_funding_min_fill_fraction=1.0",
        "slot-funding observer counters",
    )

    # A reverse split that makes a pending whole-share order inexpressible must
    # release both the slot reservation and its cash claim.
    text = _replace_once(
        text,
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if abs(q-round(q))>1e-8: s.pending_cash=0.; s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "split cancellation releases cash",
    )

    text = _replace_once(
        text,
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if s.reserved() and s.pending_tid in term_tids: s.pending_cash=0.; s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "terminal cancellation releases cash",
    )

    # Fill authority is the budget frozen at the decision close. Account cash
    # that arrived later cannot enlarge or rescue this queued entry.
    text = _replace_once(
        text,
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n"
        "                    if q>=1:\n",
        "                    planned=int(round(s.pending_shares)); afford=math.floor(s.pending_cash/(float(px)*(1+COST))); q=min(planned,afford)\n"
        "                    if q>=1:\n"
        "                        slot_funding_fill_count+=1\n"
        "                        _fill_fraction=float(q)/float(planned) if planned>0 else 0.0\n"
        "                        slot_funding_min_fill_fraction=min(slot_funding_min_fill_fraction,_fill_fraction)\n"
        "                        if q<planned: slot_funding_gap_clipped_count+=1\n",
        "next-open fill uses reserved budget",
    )

    # After split/terminal replacements above, exactly one generic reservation
    # reset remains: the executable-open fill/cancel path.
    text = _replace_once(
        text,
        "                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1\n",
        "                    if q<1: slot_funding_open_budget_cancels+=1\n"
        "                    s.pending_cash=0.; s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1\n",
        "open fill/cancel releases cash",
    )

    # Decision-time sizing: target shares are formed from the full 4% nominal
    # budget. The cash test is against genuinely uncommitted account cash.
    text = _replace_once(
        text,
        "                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n"
        "                        if q<1: continue\n",
        "                        target=eq*ENTRY_W; per_share=float(px)*(1+COST); q=int(target//per_share)\n"
        "                        if q<1: continue\n"
        "                        required=float(q)*per_share; available=book.uncommitted_cash()\n"
        "                        if required>available:\n"
        "                            slot_funding_rejections+=1; continue\n",
        "full-target decision funding",
    )

    # Store the exact dollar claim next to the queued share intent.
    text = _replace_once(
        text,
        "s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday;",
        "s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_cash=float(required); s.pending_signal_day=gday;",
        "decision reservation stores cash",
    )

    # Observer-only daily state. No value below is read by the strategy.
    text = _replace_once(
        text,
        "                rows.append({'date':date,'shadow_equity':eq,",
        "                _slot_reserved=book.reserved_cash_total()\n"
        "                _slot_uncommitted=book.uncommitted_cash()\n"
        "                if _slot_reserved>book.cash+1e-6 or _slot_uncommitted<-1e-6:\n"
        "                    raise RuntimeError(f'slot-funding cash invariant breached on {ds}: cash={book.cash} reserved={_slot_reserved} uncommitted={_slot_uncommitted}')\n"
        "                rows.append({'date':date,'slot_funding_cash':float(book.cash),'slot_funding_receivables':float(sum(x[1] for x in book.receivables)),"
        "'slot_funding_reserved_cash':float(_slot_reserved),'slot_funding_uncommitted_cash':float(_slot_uncommitted),"
        "'slot_funding_held_count':int(sum(1 for s in book.slots if s.held())),'slot_funding_pending_count':int(sum(1 for s in book.slots if s.reserved())),"
        "'slot_funding_ready_count':int(sum(1 for s in book.slots if (not s.held()) and (not s.reserved()) and gday>=s.ready_day)),"
        "'slot_funding_rejections':int(slot_funding_rejections),'slot_funding_fill_count':int(slot_funding_fill_count),"
        "'slot_funding_gap_clipped_count':int(slot_funding_gap_clipped_count),'slot_funding_open_budget_cancels':int(slot_funding_open_budget_cancels),"
        "'slot_funding_min_fill_fraction':float(slot_funding_min_fill_fraction),'shadow_equity':eq,",
        "slot-funding observer daily columns",
    )

    # Refuse silent fallback to either legacy cash-clipped seam.
    forbidden = (
        "target=min(eq*ENTRY_W,book.cash)",
        "afford=math.floor(book.cash/(float(px)*(1+COST)))",
    )
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(f"legacy slot-funding seam survived: {needle}")

    required = (
        "N_SLOTS = 25",
        "ENTRY_W = 0.04",
        "pending_cash:float=0.",
        "def uncommitted_cash(self)",
        "required=float(q)*per_share",
        "afford=math.floor(s.pending_cash/(float(px)*(1+COST)))",
        "slot_funding_rejections",
        "LDRC_DD=-0.1; LDRC_R20=-0.085; LDRC_CEIL=.55; LDRC_REC=8; LDRC_V=0.11",
        "'dam':0.88",
        "dam<=0.63",
        "pend['control']=a_d",
        "gday+15",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"corrected Champion source missing frozen seams: {missing}")
    return text


def corrected_transform(mode: str, output: Path) -> str:
    return apply_slot_funding(_BASE_TRANSFORM(mode, output))


# The historical runner resolves this function dynamically when it creates the
# executable replay. No certified file is modified.
certified.champion.strict20.corrected.transformed_source = corrected_transform


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _output_arg() -> Path:
    try:
        return Path(sys.argv[sys.argv.index("--output") + 1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("corrected Champion wrapper requires --output") from exc


def _write_identity(output: Path, generated_sha: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    overlay_sha = _sha256_bytes(Path(__file__).read_bytes())
    identity = {
        "schema": "research.corrected-champion-slot-funding/1",
        "status": "RESEARCH_COUNTERFACTUAL_PASS",
        "production_certification": False,
        "profile": PROFILE,
        "certified_historical_source_sha": CERTIFIED_SOURCE_SHA,
        "current_kernel_anchor_sha": CURRENT_KERNEL_ANCHOR,
        "funding_profile": FUNDING_PROFILE,
        "overlay_sha256": overlay_sha,
        "generated_replay_source_sha256": generated_sha,
        "one_factor_change": "wealth_core_entry_slot_funding_and_pending_cash_reservation",
        "frozen": {
            "n_slots": 25,
            "entry_weight": 0.04,
            "ldrc_rec": 8,
            "ldrc_r20": -0.085,
            "ldrc_v": 0.11,
            "ldrc_dd": -0.10,
            "divergence_spy_floor": 0.0,
            "full_recovery_r40_floor": 0.0,
            "fast_damaged": 0.88,
            "healthy_damaged_ceiling": 0.63,
            "measurement_start": "2006-07-31",
            "end": "2026-07-31",
            "dividend_lag_sessions": 15,
        },
    }
    (output / "slot-funding-experiment-identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    if "--self-test-slot-funding" in sys.argv:
        output = Path("/tmp/research-champion-slot-funding-selftest")
        source = corrected_transform("fullpit", output)
        compile(source, "<corrected-research-champion>", "exec")
        print(json.dumps({
            "status": "PASS",
            "profile": PROFILE,
            "funding_profile": FUNDING_PROFILE,
            "generated_sha256": _sha256_bytes(source.encode("utf-8")),
        }, sort_keys=True), flush=True)
        return 0

    output = _output_arg()
    source = corrected_transform("fullpit", output)
    generated_sha = _sha256_bytes(source.encode("utf-8"))
    print(
        f"[CONTRACT] research_only=1 profile={PROFILE} funding_profile={FUNDING_PROFILE} "
        f"certified_parent={CERTIFIED_SOURCE_SHA} generated_sha256={generated_sha}",
        flush=True,
    )
    rc = int(certified.main())
    if rc != 0:
        return rc
    _write_identity(output, generated_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
