#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FORMAL_DIR = HERE.parents[0] / "wealth-core-v2-formal-ab-v1"
if str(FORMAL_DIR) not in sys.path:
    sys.path.insert(0, str(FORMAL_DIR))
import formal_ab

BASE_HEAD = "880209078f2b4817e837431984dc0ba0bf0b9d79"
CAESAR20_EVIDENCE_HEAD = "171d2e1fcea7f7ada2f6eeeefeccceb8d5c120b0"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
INITIAL_CAPITAL = 100_000.0
BUFFER_BPS = 10.0
BUFFER_FRAC = BUFFER_BPS / 10000.0


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact source seam, found {count}")
    return text.replace(old, new, 1)


def build_source(output: Path) -> tuple[str, str, str]:
    os.environ["WC_AB_VARIANT"] = "V2"
    _, transform = formal_ab._formal_transform()
    v1 = transform("fullpit", output)
    v2 = formal_ab.apply_v2_patch(v1)
    src = v2

    # Capital scale only.
    src = replace_one(
        src,
        "    cash:float=100_000_000.; receivables:list=field(default_factory=list)",
        "    cash:float=100_000.; receivables:list=field(default_factory=list)",
        "initial capital",
    )

    # Frozen Caesar 20 definition: only capacity and nominal target weight.
    src = replace_one(src, "N_SLOTS = 25", "N_SLOTS = 20", "Caesar 20 slots")
    src = replace_one(src, "ENTRY_W = 0.04", "ENTRY_W = 0.05", "Caesar 20 entry weight")

    counter_old = (
        "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; "
        "slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0"
    )
    counter_new = counter_old + (
        "; nextopen_admissions=nextopen_blocks=nextopen_close_unaffordable=nextopen_buffer_rejects=0"
        "; nextopen_cash_limited=nextopen_delayed=0; nextopen_max_delay=0"
        "; nextopen_rounding_underfill=0.; nextopen_reserved_dollars=0.; nextopen_executed_gross=0."
    )
    src = replace_one(src, counter_old, counter_new, "next-open counters")

    # V2 close decision becomes a dollar intent. No share count is bound here.
    src = replace_one(
        src,
        "target=eq*ENTRY_W; q=int(target//(float(px)*(1+COST))); required_cash=float(q)*float(px)*(1+COST)",
        f"target=eq*ENTRY_W; required_cash=float(target); _buffer_required_close=max(0.,float(eq)*{BUFFER_FRAC!r})",
        "close-bound dollar intent",
    )

    close_old = (
        "                        if q<1: continue\n"
        "                        if required_cash>book.uncommitted_cash()+1e-8: slot_v2_rejected+=1; continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.reserved_cash=required_cash; slot_v2_reserved+=1;"
    )
    close_new = (
        "                        _available_close=max(0.,book.uncommitted_cash()-_buffer_required_close)\n"
        "                        if required_cash>_available_close+1e-8: slot_v2_rejected+=1; nextopen_buffer_rejects+=1; continue\n"
        "                        _one_share_close_cost=float(px)*(1+COST)\n"
        "                        if required_cash+1e-12<_one_share_close_cost: nextopen_close_unaffordable+=1; continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=0.; s.pending_signal_day=gday; s.reserved_cash=required_cash; slot_v2_reserved+=1; nextopen_admissions+=1; nextopen_reserved_dollars+=required_cash;"
    )
    src = replace_one(src, close_old, close_new, "10bp close admission and dollar reservation")

    # Actual whole-share quantity is determined from the actual opening price.
    open_old = (
        "                    if _research_capacity_guard(s.pending_shares,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:\n"
        "                        continue\n"
        "                    afford=math.floor(s.reserved_cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford); slot_v2_gap_clipped+=int(q<int(round(s.pending_shares))); slot_v2_gap_cancelled+=int(q<1)"
    )
    open_new = (
        "                    _execution_budget=min(float(s.reserved_cash),float(book.cash))\n"
        "                    q=math.floor(_execution_budget/(float(px)*(1+COST)))\n"
        "                    if q>=1 and _research_capacity_guard(q,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:\n"
        "                        continue\n"
        "                    nextopen_cash_limited+=int(float(book.cash)+1e-8<float(s.reserved_cash))\n"
        "                    nextopen_blocks+=int(q<1); slot_v2_gap_cancelled+=int(q<1)\n"
        "                    if q>=1:\n"
        "                        _gross_nextopen=float(q)*float(px)*(1+COST)\n"
        "                        nextopen_rounding_underfill+=max(0.,float(_execution_budget)-_gross_nextopen)\n"
        "                        nextopen_executed_gross+=_gross_nextopen\n"
        "                        _delay=max(0,int(gday)-int(s.pending_signal_day)-1)\n"
        "                        nextopen_delayed+=int(_delay>0); nextopen_max_delay=max(nextopen_max_delay,_delay)"
    )
    src = replace_one(src, open_old, open_new, "next-open quantity determination")

    summary_old = (
        "        'wealth_core_entry_funding':{'profile':'wealth-core-v2-full-whole-share-target-v1',"
        "'reserved':slot_v2_reserved,'rejected_insufficient_uncommitted_cash':slot_v2_rejected,"
        "'gap_clipped':slot_v2_gap_clipped,'gap_cancelled':slot_v2_gap_cancelled},"
    )
    summary_new = summary_old + (
        "\n        'wealth_core_caesar20':{'profile':'caesar-20','slots':20,'target_entry_weight':0.05,'evidence_head':'171d2e1fcea7f7ada2f6eeeefeccceb8d5c120b0'},"
        "\n        'wealth_core_next_open_sizing':{'profile':'wealth-core-v2-caesar20-next-open-whole-10bp-v1','initial_capital':100000.0,'buffer_basis_points':10.0,'buffer_role':'CLOSE_TIME_ADMISSION_CUSHION','share_quantity_bound_at_close':False,'whole_shares':True,'admissions':nextopen_admissions,'open_zero_quantity_blocks':nextopen_blocks,'close_whole_share_unaffordable_skips':nextopen_close_unaffordable,'close_full_target_buffer_rejects':nextopen_buffer_rejects,'cash_limited_open_executions':nextopen_cash_limited,'delayed_beyond_next_market_session':nextopen_delayed,'max_extra_market_session_delay':nextopen_max_delay,'rounding_underfill_dollars_total':nextopen_rounding_underfill,'reserved_target_dollars_total':nextopen_reserved_dollars,'executed_gross_total':nextopen_executed_gross},"
    )
    src = replace_one(src, summary_old, summary_new, "summary telemetry")

    required = (
        "N_SLOTS = 20",
        "ENTRY_W = 0.05",
        "pending_shares=0.",
        "_buffer_required_close=max(0.,float(eq)*0.001)",
        "_execution_budget=min(float(s.reserved_cash),float(book.cash))",
        "q=math.floor(_execution_budget/(float(px)*(1+COST)))",
        "_research_capacity_guard(q,_capacity_volumes.get(int(tid),())",
        "a_d,a_reason=ca.step",
        "pend['A']=a_d",
    )
    missing = [marker for marker in required if marker not in src]
    if missing:
        raise RuntimeError(f"required economic markers missing: {missing}")
    forbidden = (
        "N_SLOTS = 25",
        "ENTRY_W = 0.04",
        "afford=math.floor(s.reserved_cash/(float(px)*(1+COST)))",
        "_research_capacity_guard(s.pending_shares,_capacity_volumes.get(int(tid),())",
        "return _median_top3(",
        "MEDIAN5_CANONICAL",
    )
    survived = [marker for marker in forbidden if marker in src]
    if survived:
        raise RuntimeError(f"forbidden/legacy mechanics survived: {survived}")

    compile(src, "<wealth-core-v2-caesar20-next-open-10bp-ex3>", "exec")
    return v1, v2, src


def path_metrics(frame: pd.DataFrame, col: str) -> dict:
    nav = pd.to_numeric(frame[col], errors="raise").astype(float)
    dates = pd.to_datetime(frame["date"])
    if len(nav) < 2 or not np.isfinite(nav).all() or (nav <= 0).any():
        raise RuntimeError(f"invalid NAV path: {col}")
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    ret = nav.pct_change().dropna()
    vol = float(ret.std(ddof=1))
    return {
        "start": str(dates.iloc[0].date()),
        "end": str(dates.iloc[-1].date()),
        "sessions": int(len(nav)),
        "start_equity": float(nav.iloc[0]),
        "end_equity": float(nav.iloc[-1]),
        "ending_multiple": multiple,
        "cagr": float(multiple ** (1.0 / years) - 1.0),
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
        "sharpe_daily_252": float(ret.mean() / vol * np.sqrt(252.0)) if vol > 0 else None,
    }


def horizon_metrics(frame: pd.DataFrame, col: str) -> dict:
    dates = pd.to_datetime(frame["date"])
    end = dates.iloc[-1]
    out: dict[str, dict] = {}
    for years in (5, 10, 15, 20):
        part = frame.loc[dates >= end - pd.DateOffset(years=years)].copy()
        out[str(years)] = path_metrics(part, col)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    if args.self_test:
        prior = os.environ.get("CANONICAL_PIT_DATASET")
        os.environ["CANONICAL_PIT_DATASET"] = "/tmp/source-generation-only-canonical-pit"
        try:
            v1, v2, src = build_source(Path("/tmp/wc-v2-caesar20-nextopen-selftest"))
            print(json.dumps({
                "status": "PASS",
                "v1_sha256": digest_bytes(v1.encode()),
                "v2_sha256": digest_bytes(v2.encode()),
                "experiment_sha256": digest_bytes(src.encode()),
            }, sort_keys=True))
        finally:
            if prior is None:
                os.environ.pop("CANONICAL_PIT_DATASET", None)
            else:
                os.environ["CANONICAL_PIT_DATASET"] = prior
        return 0

    dataset = Path(os.environ["CANONICAL_PIT_DATASET"])
    manifest = json.loads((dataset / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256:
        raise RuntimeError("canonical PIT dataset hash mismatch")

    v1, v2, src = build_source(out)
    generated = out / "wealth-core-v2-caesar20-next-open-10bp-ex3-generated.py"
    generated.write_text(src)

    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    module = types.ModuleType("wealth_core_v2_caesar20_next_open_ex3")
    module.__file__ = str(generated)
    sys.modules[module.__name__] = module
    exec(compile(src, str(generated), "exec"), module.__dict__)
    if getattr(module, "MODE", None) != "fullpit" or getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError("generated source did not enter full-PIT mode")
    module.OUT = out
    module.run()

    daily_path = out / "daily.csv"
    summary_path = out / "summary.json"
    tx_path = out / "transactions.csv"
    for p in (daily_path, summary_path, tx_path):
        if not p.is_file():
            raise RuntimeError(f"required replay evidence missing: {p.name}")

    frame = pd.read_csv(daily_path)
    if (
        len(frame) != 5032
        or str(pd.to_datetime(frame["date"]).iloc[0].date()) != "2006-07-31"
        or str(pd.to_datetime(frame["date"]).iloc[-1].date()) != "2026-07-31"
        or pd.to_datetime(frame["date"]).duplicated().any()
    ):
        raise RuntimeError("full-PIT measurement witness mismatch")
    for col in ("shadow_equity", "A_nav", "A_allocation"):
        if col not in frame.columns:
            raise RuntimeError(f"required daily column missing: {col}")

    summary = json.loads(summary_path.read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256:
        raise RuntimeError("summary lost canonical PIT dataset binding")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError("dividend lag changed")

    nextopen = summary.get("wealth_core_next_open_sizing") or {}
    caesar = summary.get("wealth_core_caesar20") or {}
    if int(caesar.get("slots", -1)) != 20 or abs(float(caesar.get("target_entry_weight", -1)) - 0.05) > 1e-12:
        raise RuntimeError("Caesar 20 telemetry mismatch")
    if nextopen.get("share_quantity_bound_at_close") is not False or nextopen.get("whole_shares") is not True:
        raise RuntimeError("next-open sizing telemetry mismatch")
    if abs(float(nextopen.get("buffer_basis_points", -1)) - 10.0) > 1e-12:
        raise RuntimeError("10 bp telemetry mismatch")

    tx = pd.read_csv(tx_path)
    if "Buy or sell" not in tx.columns or "Amount of shares" not in tx.columns:
        raise RuntimeError("transaction schema mismatch")
    buy_rows = tx[tx["Buy or sell"].eq("BUY")]
    sell_rows = tx[tx["Buy or sell"].eq("SELL")]
    buy_qty = pd.to_numeric(buy_rows["Amount of shares"], errors="raise").to_numpy(dtype=float)
    if not np.allclose(buy_qty, np.round(buy_qty), atol=1e-9):
        raise RuntimeError("fractional BUY detected")

    core_windows = horizon_metrics(frame, "shadow_equity")
    ex3_windows = horizon_metrics(frame, "A_nav")
    contribution = {}
    for horizon in ("5", "10", "15", "20"):
        c = core_windows[horizon]
        e = ex3_windows[horizon]
        contribution[horizon] = {
            "cagr_percentage_points": (e["cagr"] - c["cagr"]) * 100.0,
            "max_drawdown_percentage_points": (e["max_drawdown"] - c["max_drawdown"]) * 100.0,
            "sharpe_delta": e["sharpe_daily_252"] - c["sharpe_daily_252"],
            "ending_multiple_delta": e["ending_multiple"] - c["ending_multiple"],
        }

    result = {
        "schema": "research.wealth-core-v2-caesar20-next-open-10bp-ex3/1",
        "status": "PASS_FRESH_CAUSAL_PIT_REPLAY",
        "research_only": True,
        "performance_target_used": False,
        "measurement_start": "2006-07-31",
        "measurement_end": "2026-07-31",
        "sessions": 5032,
        "dataset_sha256": DATASET_SHA256,
        "formal_v2_base_head": BASE_HEAD,
        "caesar20_evidence_head": CAESAR20_EVIDENCE_HEAD,
        "initial_capital": INITIAL_CAPITAL,
        "wealth_core": {
            "version": "V2",
            "slots": 20,
            "target_entry_weight": 0.05,
            "cash_buffer_basis_points": BUFFER_BPS,
            "position_sizing": "NEXT_VALID_OPEN_WHOLE_SHARES",
            "share_quantity_bound_at_close": False,
            "median5_enabled": False,
            "windows": core_windows,
            "next_open_telemetry": nextopen,
            "entry_funding_telemetry": summary.get("wealth_core_entry_funding"),
        },
        "sentinel_ex3": {
            "controller_path": "CandidateA / A_nav",
            "windows": ex3_windows,
            "average_allocation": float(pd.to_numeric(frame["A_allocation"], errors="raise").mean()),
            "zero_allocation_sessions": int(pd.to_numeric(frame["A_allocation"], errors="raise").eq(0.0).sum()),
            "transition_counts": summary.get("transition_counts"),
            "modeled_allocation_transition_cost_sum": summary.get("modeled_allocation_transition_cost_sum"),
            "candidate_A_episodes": summary.get("candidate_A_episodes"),
            "candidate_A_concordance_releases": summary.get("candidate_A_concordance_releases"),
        },
        "sentinel_incremental_contribution": contribution,
        "transactions": {
            "rows": int(len(tx)),
            "buys": int(len(buy_rows)),
            "sells": int(len(sell_rows)),
            "all_buy_share_amounts_integer": True,
        },
        "source": {
            "v1_generated_sha256": digest_bytes(v1.encode()),
            "v2_generated_sha256": digest_bytes(v2.encode()),
            "final_generated_sha256": digest_bytes(src.encode()),
            "experiment_head": os.environ.get("GITHUB_SHA"),
        },
    }
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    c20 = core_windows["20"]
    e20 = ex3_windows["20"]
    insights = f"""# Wealth Core V2 + Caesar 20 + next-open 10 bp + EX3 — full-PIT result\n\nStatus: **PASS_FRESH_CAUSAL_PIT_REPLAY**\n\n- Canonical PIT dataset: `{DATASET_SHA256}`\n- Initial capital: `$100,000`\n- Caesar 20: 20 slots / 5% target weight\n- Median-5: disabled\n- Sizing: close-bound dollar intent; next-valid-open whole-share quantity\n- 10 bp close-time admission cushion\n- Dividend lag: 1 session\n- EX3: frozen Candidate-A / `A_nav`\n\n## 20-year headline\n\n| Path | CAGR | Max DD | Sharpe | Ending multiple |\n|---|---:|---:|---:|---:|\n| Pure Wealth Core | {c20['cagr']:.6%} | {c20['max_drawdown']:.6%} | {c20['sharpe_daily_252']:.6f} | {c20['ending_multiple']:.4f}x |\n| Wealth Core + EX3 | {e20['cagr']:.6%} | {e20['max_drawdown']:.6%} | {e20['sharpe_daily_252']:.6f} | {e20['ending_multiple']:.4f}x |\n\n## Execution\n\n- Admissions: {nextopen.get('admissions')}\n- Open zero-quantity blocks: {nextopen.get('open_zero_quantity_blocks')}\n- Close whole-share unaffordable skips: {nextopen.get('close_whole_share_unaffordable_skips')}\n- Close full-target/buffer rejects: {nextopen.get('close_full_target_buffer_rejects')}\n- Whole-share rounding underfill total: ${float(nextopen.get('rounding_underfill_dollars_total', 0.0)):,.2f}\n- Buys: {len(buy_rows)}\n- Sells: {len(sell_rows)}\n\nNo parameter was tuned from these results.\n"""
    (out / "INSIGHTS.md").write_text(insights)

    checksum_names = [
        "RESULT.json", "INSIGHTS.md", "daily.csv", "summary.json", "transactions.csv",
        "wealth-core-v2-caesar20-next-open-10bp-ex3-generated.py",
    ]
    lines = []
    for name in checksum_names:
        path = out / name
        if not path.is_file():
            raise RuntimeError(f"checksum member missing: {name}")
        lines.append(f"{digest_file(path)}  {name}\n")
    (out / "EXPERIMENT_SHA256SUMS.txt").write_text("".join(lines))

    print(json.dumps({
        "status": result["status"],
        "wealth_core_20y": c20,
        "ex3_20y": e20,
        "execution": nextopen,
        "transactions": result["transactions"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
