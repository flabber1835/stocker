#!/usr/bin/env python3
"""Strategy 9 E6: rare exceptional-leader displacement.

Single Wealth Core change, activated only from 2020-01-02 for the bounded A/B:
when all 25 slots are occupied, no exit/replacement is already pending, and the
current durable rank #1 security is an otherwise admissible new position, it may
replace the weakest held security that has fallen outside the existing top-decile
momentum pool. The replacement is decided at close and executes at the next open.

No Sentinel/E3 parameters or mechanics are changed. No return series is consulted
at runtime. Research experiment; consumes Strategy 9 experiment budget slot 6/10.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from backtester import experiment_architecture_recovery_concordance_e3 as e3

LABEL = "STRATEGY9_E6_EXCEPTIONAL_LEADER_DISPLACEMENT"
VARIANT = "E6_EXCEPTIONAL_LEADER_DISPLACEMENT"
BUDGET_NUMBER = 6
E3_SOURCE_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
ACTIVATION = pd.Timestamp("2020-01-02")
ACCEPTED_E3_RUN_ID = 33912976460
ACCEPTED_E3_ARTIFACT_ID = 9953264982
ACCEPTED_E3_DIGEST = "sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = e3.transformed_source(output)

    state_old = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    state_new = state_old + "\n    e6_displacements=[]"
    text = replace_once(text, state_old, state_new, "E6 displacement telemetry state")

    admission_marker = "                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]"
    e6_block = r'''                # E6: rare exceptional-leader displacement.
                # Only the current durable rank #1 may force entry, and only by
                # replacing a held security that is already outside the existing
                # top-decile momentum pool. No numeric return/score threshold is
                # introduced; all ordinary admission gates remain authoritative.
                if (date>=pd.Timestamp('2020-01-02')
                    and len(durable)>0
                    and sum(int(s.held()) for s in book.slots)==N_SLOTS
                    and not any(s.pending_sell or s.reserved() for s in book.slots)):
                    _e6_tid=int(durable[0]); _e6_tk=str(tick[_e6_tid])
                    _e6_held=book.held_ids(); _e6_res=book.reserved_ids()
                    _e6_admissible=(
                        finite(recent[_e6_tid]) and recent[_e6_tid]>=0
                        and _e6_tid not in _e6_held and _e6_tid not in _e6_res
                        and book.sec_ready.get(_e6_tid,-1)<=gday
                        and _e6_tid not in term_tids
                        and finite(clraw[_e6_tid]) and clraw[_e6_tid]>0
                    )
                    if _e6_admissible:
                        _e6_victims=[s for s in book.slots
                                     if s.held() and not inpool[s.tid]
                                     and finite(score[s.tid]) and finite(clraw[s.tid]) and clraw[s.tid]>0]
                        if _e6_victims:
                            _e6_v=min(_e6_victims,key=lambda s:(score[s.tid],str(sid[s.tid]),str(tick[s.tid])))
                            if finite(score[_e6_tid]) and score[_e6_tid]>score[_e6_v.tid]:
                                _e6_px=float(clraw[_e6_tid]); _e6_target=float(eq)*ENTRY_W
                                _e6_q=int(_e6_target//(_e6_px*(1+COST)))
                                if _e6_q>=1:
                                    _e6_old_tid=int(_e6_v.tid)
                                    e6_displacements.append({
                                        'signal_date':ds,
                                        'candidate_ticker':str(tick[_e6_tid]),
                                        'candidate_security_id':str(sid[_e6_tid]),
                                        'candidate_durable_rank':1,
                                        'candidate_score':float(score[_e6_tid]),
                                        'candidate_recent_r21':float(recent[_e6_tid]),
                                        'victim_ticker':str(tick[_e6_old_tid]),
                                        'victim_security_id':str(sid[_e6_old_tid]),
                                        'victim_score':float(score[_e6_old_tid]),
                                        'victim_in_top_decile':bool(inpool[_e6_old_tid]),
                                        'planned_shares':int(_e6_q),
                                    })
                                    _e6_v.pending_sell=True
                                    _e6_v.sell_reason='leader_displacement'
                                    _e6_v.pending_tid=_e6_tid
                                    _e6_v.pending_shares=float(_e6_q)
                                    _e6_v.pending_signal_day=gday
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]'''
    text = replace_once(text, admission_marker, e6_block, "E6 displacement decision")

    out_marker = "    out=pd.DataFrame(rows)"
    out_new = "    pd.DataFrame(e6_displacements).to_csv(OUT/'e6_displacement_events.csv',index=False)\n" + out_marker
    text = replace_once(text, out_marker, out_new, "E6 displacement telemetry output")
    return text


def hash_pre_activation(frame: pd.DataFrame) -> str:
    cols = ["date", "research_wealth_core_equity", "research_nav", "A_nav"]
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise RuntimeError(f"pre-activation parity columns missing: {missing}")
    x = frame[pd.to_datetime(frame.date) < ACTIVATION][cols].copy()
    h = hashlib.sha256()
    for row in x.itertuples(index=False, name=None):
        payload = [pd.Timestamp(row[0]).strftime("%Y-%m-%d")]
        payload.extend(None if pd.isna(v) else format(float(v), ".12g") for v in row[1:])
        h.update((json.dumps(payload, separators=(",", ":")) + "\n").encode())
    return h.hexdigest()


def metric(frame: pd.DataFrame, column: str) -> dict:
    return e3.corrected.old.metric_block(frame, column, str(ACTIVATION.date()), None)


def finalize(output: Path) -> None:
    # Use the accepted Strategy 9 post-processing stack, but do not invoke E3's
    # control-parity assertion because Wealth Core is intentionally changed by E6.
    e3.strategy9.finalize(output)

    accepted_root = Path(os.environ["ACCEPTED_E3_ROOT"])
    accepted = pd.read_csv(accepted_root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    candidate = pd.read_csv(output / "daily.csv.gz", compression="gzip", parse_dates=["date"])

    ah = hash_pre_activation(accepted)
    ch = hash_pre_activation(candidate)
    if ah != ch:
        raise RuntimeError(f"E6 pre-activation parity failure accepted={ah} candidate={ch}")

    events = pd.read_csv(output / "e6_displacement_events.csv")
    if events.empty:
        raise RuntimeError("E6 produced zero displacement events")

    rows = []
    for label, frame, col in (
        ("ACCEPTED_E3", accepted, "A_nav"),
        ("ACCEPTED_CORE", accepted, "research_wealth_core_equity"),
        ("E6_E3", candidate, "A_nav"),
        ("E6_CORE", candidate, "research_wealth_core_equity"),
        ("SPY", candidate, "spy_nav"),
    ):
        rows.append({"variant": label, **metric(frame, col)})
    metrics = pd.DataFrame(rows)
    metrics.to_csv(output / "e6_2020_2026_metrics.csv", index=False)

    # Calendar-year comparison is descriptive only; it does not alter the rule.
    annual = []
    for year in range(2020, 2027):
        for label, frame, col in (
            ("ACCEPTED_E3", accepted, "A_nav"),
            ("ACCEPTED_CORE", accepted, "research_wealth_core_equity"),
            ("E6_E3", candidate, "A_nav"),
            ("E6_CORE", candidate, "research_wealth_core_equity"),
        ):
            y = frame[pd.to_datetime(frame.date).dt.year.eq(year)][["date", col]].dropna()
            if len(y) < 2:
                continue
            annual.append({"year": year, "variant": label, "return": float(y.iloc[-1][col] / y.iloc[0][col] - 1.0)})
    pd.DataFrame(annual).to_csv(output / "e6_annual_returns.csv", index=False)

    summary = json.loads((output / "summary.json").read_text())
    summary.update({
        "experiment": "strategy9_e6_exceptional_leader_displacement",
        "evidence_label": LABEL,
        "experiment_budget_number": BUDGET_NUMBER,
        "experiment_budget_consumed_after_completion": 6,
        "experiment_budget_limit": 10,
        "activation_date": str(ACTIVATION.date()),
        "pre_activation_parity": {"status": "PASS", "accepted_sha256": ah, "candidate_sha256": ch},
        "displacement_rule": {
            "wealth_core_changed": True,
            "native_sentinel_changed": False,
            "e3_overlay_code_changed": False,
            "new_fitted_return_thresholds": 0,
            "candidate": "current durable rank #1, ordinary admission gates satisfied, recent_r21 >= 0",
            "portfolio_condition": "all 25 slots held and no pending exit or reservation",
            "victim": "lowest-score held security outside existing top-decile momentum pool",
            "timing": "decision at close; victim sell and candidate buy at next open",
        },
        "displacement_events": int(len(events)),
        "accepted_e3_run_id": ACCEPTED_E3_RUN_ID,
        "accepted_e3_artifact_id": ACCEPTED_E3_ARTIFACT_ID,
        "accepted_e3_digest": ACCEPTED_E3_DIGEST,
    })
    (output / "e6_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    manifest = {
        "schema": "backtester.strategy9-e6-exceptional-leader-displacement/1",
        "status": "PASS",
        "evidence_label": LABEL,
        "strategy_source_head": E3_SOURCE_HEAD,
        "experiment_budget_number": BUDGET_NUMBER,
        "activation_date": str(ACTIVATION.date()),
        "pre_activation_parity": True,
        "fresh_chronological_replay": True,
        "decision_at_close_next_open_effect": True,
        "native_sentinel_changed": False,
        "e3_overlay_code_changed": False,
    }
    (output / "e6_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    files = [
        output / "daily.csv.gz",
        output / "e6_displacement_events.csv",
        output / "e6_2020_2026_metrics.csv",
        output / "e6_annual_returns.csv",
        output / "e6_summary.json",
        output / "e6_manifest.json",
    ]
    (output / "E6_SHA256SUMS.txt").write_text(
        "".join(f"{e3.corrected.old.sha256(p)}  {p.name}\n" for p in files)
    )
    print("[E6 METRICS]", flush=True)
    print(metrics.to_string(index=False), flush=True)
    print("[E6 DISPLACEMENTS]", len(events), flush=True)
    print(events.head(50).to_string(index=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    generated = Path("/tmp/strategy9_e6_exceptional_leader_displacement.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {LABEL} experiment={BUDGET_NUMBER}/10 activation={ACTIVATION.date()}", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
