#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import pandas as pd

MODES = ["whole", "fractional"]
CONTROL_RESULT_PATH = Path("research/wealth-core-v1-buffer-sweep-evidence/arms/10bp/RESULT.json")
CONTROL_DAILY_PATH = Path("research/wealth-core-v1-buffer-sweep-evidence/arms/10bp/daily.csv")
CONTROL_TX_PATH = Path("research/wealth-core-v1-buffer-sweep-evidence/arms/10bp/transactions.csv")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def locate(root: Path, mode: str) -> Path:
    matches = sorted(p.parent for p in root.rglob("RESULT.json") if mode in str(p.parent).lower())
    if len(matches) != 1:
        raise RuntimeError(f"expected one {mode} arm, found {matches}")
    return matches[0]


def buys(tx: pd.DataFrame) -> pd.DataFrame:
    b = tx.loc[tx["Buy or sell"].eq("BUY"), ["Transaction date", "Ticker", "Amount of shares"]].copy()
    b["Transaction date"] = b["Transaction date"].astype(str)
    return b


def sells(tx: pd.DataFrame) -> pd.DataFrame:
    s = tx.loc[tx["Buy or sell"].eq("SELL"), ["Transaction date", "Ticker", "Amount of shares"]].copy()
    s["Transaction date"] = s["Transaction date"].astype(str)
    return s


def divergence(control_daily: pd.DataFrame, arm_daily: pd.DataFrame, control_tx: pd.DataFrame, arm_tx: pd.DataFrame) -> dict:
    c = control_daily[["date", "research_selected_positions"]].copy()
    a = arm_daily[["date", "research_selected_positions"]].copy()
    m = c.merge(a, on="date", suffixes=("_control", "_arm"), how="inner")
    diff = m["research_selected_positions_control"].astype(str) != m["research_selected_positions_arm"].astype(str)
    cb = buys(control_tx); ab = buys(arm_tx)
    cs = sells(control_tx); ass = sells(arm_tx)
    c_buy_pairs = set(zip(cb["Transaction date"], cb["Ticker"]))
    a_buy_pairs = set(zip(ab["Transaction date"], ab["Ticker"]))
    c_sell_pairs = set(zip(cs["Transaction date"], cs["Ticker"]))
    a_sell_pairs = set(zip(ass["Transaction date"], ass["Ticker"]))
    c_dates = set(cb["Transaction date"]); a_dates = set(ab["Transaction date"])
    c_tickers = set(cb["Ticker"]); a_tickers = set(ab["Ticker"])
    return {
        "first_holdings_divergence_date": (str(m.loc[diff, "date"].iloc[0]) if diff.any() else None),
        "cumulative_days_with_differing_holdings": int(diff.sum()),
        "differing_buy_date_ticker_decisions": int(len(c_buy_pairs.symmetric_difference(a_buy_pairs))),
        "differing_executed_entry_dates": int(len(c_dates.symmetric_difference(a_dates))),
        "differing_ticker_admissions": int(len(c_tickers.symmetric_difference(a_tickers))),
        "differing_exit_date_ticker_decisions": int(len(c_sell_pairs.symmetric_difference(a_sell_pairs))),
        "control_buy_count": int(len(cb)),
        "arm_buy_count": int(len(ab)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collected", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--trigger-head", required=True)
    args = ap.parse_args()

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    control_result = json.loads(CONTROL_RESULT_PATH.read_text())
    control_daily = pd.read_csv(CONTROL_DAILY_PATH)
    control_tx = pd.read_csv(CONTROL_TX_PATH)

    results = {}
    combined_tx = []
    combined_events = []
    rows = []

    for mode in MODES:
        src = locate(args.collected.resolve(), mode)
        arm_out = out / "arms" / mode
        shutil.copytree(src, arm_out, dirs_exist_ok=True)
        r = json.loads((arm_out / "RESULT.json").read_text())
        if r.get("status") != "PASS":
            raise RuntimeError(f"{mode} arm did not pass")
        if r.get("dataset_sha256") != control_result.get("dataset_sha256"):
            raise RuntimeError(f"{mode} PIT authority mismatch")
        if int(r.get("financial_grade_dividend_lag_sessions", -1)) != 1:
            raise RuntimeError(f"{mode} dividend lag mismatch")

        tx = pd.read_csv(arm_out / "transactions.csv")
        ev = pd.read_csv(arm_out / "open-sizing-events.csv")
        daily = pd.read_csv(arm_out / "daily.csv")
        div = divergence(control_daily, daily, control_tx, tx)
        r["path_divergence_vs_certified_10bp_control"] = div
        results[mode] = r
        (arm_out / "RESULT_WITH_DIVERGENCE.json").write_text(json.dumps(r, indent=2, sort_keys=True) + "\n")

        tx2 = tx.copy(); tx2.insert(0, "Mode", mode); combined_tx.append(tx2)
        ev2 = ev.copy(); ev2.insert(0, "Mode", mode); combined_events.append(ev2)
        p = r["portfolio_performance"]; e = r["execution"]; scale = r["entry_telemetry"]
        rows.append({
            "mode": mode,
            "cagr": p["cagr"],
            "max_drawdown": p["max_drawdown"],
            "sharpe": p["sharpe_daily_252"],
            "ending_equity": p["end_equity"],
            "close_admissions": e["close_admissions"],
            "completed_entries": e["completed_entries"],
            "next_open_blocks": e["next_open_blocks"],
            "invalid_open_market_blocks": e["invalid_open_market_blocks"],
            "zero_quantity_blocks": e["zero_quantity_blocks"],
            "cash_limited_open_executions": e["cash_limited_open_executions"],
            "rounding_underfill_dollars_total": e["rounding_underfill_dollars_total"],
            "average_rounding_underfill_fraction": e["average_rounding_underfill_fraction"],
            "fractional_buy_count": e["fractional_buy_count"],
            "all_admitted_trades_executed": e["all_admitted_trades_executed"],
            "entry_fraction_lt_1pct": scale["entry_fraction_lt_1pct"],
            "entry_fraction_lt_5pct": scale["entry_fraction_lt_5pct"],
            "entry_fraction_lt_10pct": scale["entry_fraction_lt_10pct"],
            "entry_fraction_lt_25pct": scale["entry_fraction_lt_25pct"],
            "entry_fraction_lt_50pct": scale["entry_fraction_lt_50pct"],
            "entry_fraction_lt_99pct": scale["entry_fraction_lt_99pct"],
            "minimum_entry_fraction": scale["minimum_entry_fraction"],
            "average_entry_fraction": scale["average_entry_fraction"],
            "maximum_entry_fraction": scale["maximum_entry_fraction"],
            **div,
        })

    comparison = pd.DataFrame(rows)
    comparison.to_csv(out / "comparison.csv", index=False)
    pd.concat(combined_tx, ignore_index=True).to_csv(out / "combined-transactions.csv", index=False)
    pd.concat(combined_events, ignore_index=True).to_csv(out / "combined-open-sizing-events.csv", index=False)

    whole = results["whole"]; frac = results["fractional"]
    control_p = control_result["portfolio_performance"]
    conclusion = {
        "whole_all_admitted_executed": bool(whole["execution"]["all_admitted_trades_executed"]),
        "fractional_all_admitted_executed": bool(frac["execution"]["all_admitted_trades_executed"]),
        "whole_open_blocks": int(whole["execution"]["next_open_blocks"]),
        "fractional_open_blocks": int(frac["execution"]["next_open_blocks"]),
        "whole_rounding_underfill_dollars_total": float(whole["execution"]["rounding_underfill_dollars_total"]),
        "fractional_rounding_underfill_dollars_total": float(frac["execution"]["rounding_underfill_dollars_total"]),
        "fractional_minus_whole_cagr_pp": (frac["portfolio_performance"]["cagr"] - whole["portfolio_performance"]["cagr"]) * 100.0,
        "whole_minus_control_cagr_pp": (whole["portfolio_performance"]["cagr"] - control_p["cagr"]) * 100.0,
        "fractional_minus_control_cagr_pp": (frac["portfolio_performance"]["cagr"] - control_p["cagr"]) * 100.0,
    }

    final = {
        "schema": "research.wealth-core-v1-open-sizing-10bp-ab/1",
        "status": "PASS",
        "workflow_run_id": int(args.run_id),
        "trigger_head": args.trigger_head,
        "base_evidence_head": "3b5d70de258dadaac6272f2bd9d682d291117d29",
        "buffer_basis_points": 10,
        "control_10bp": control_result,
        "arms": results,
        "conclusion": conclusion,
    }
    (out / "AB_RESULT.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n")

    def pct(x): return f"{100.0*float(x):.6f}%"
    def money(x): return f"${float(x):,.2f}"
    wp = whole["portfolio_performance"]; fp = frac["portfolio_performance"]
    we = whole["execution"]; fe = frac["execution"]
    insight = f"""# Wealth Core V1 — 10 bp open-time sizing A/B insights

## Authority

- Workflow run: `{args.run_id}`
- Trigger head: `{args.trigger_head}`
- Base evidence head: `3b5d70de258dadaac6272f2bd9d682d291117d29`
- Canonical PIT dataset: `{control_result['dataset_sha256']}`
- Dividend lag remained one session in both arms.
- Production code was not modified.

## Execution result

| Metric | Certified 10 bp control | Open-time whole shares | Open-time fractional |
|---|---:|---:|---:|
| CAGR | {pct(control_p['cagr'])} | {pct(wp['cagr'])} | {pct(fp['cagr'])} |
| Max DD | {pct(control_p['max_drawdown'])} | {pct(wp['max_drawdown'])} | {pct(fp['max_drawdown'])} |
| Sharpe | {float(control_p['sharpe_daily_252']):.6f} | {float(wp['sharpe_daily_252']):.6f} | {float(fp['sharpe_daily_252']):.6f} |
| Ending equity | {money(control_p['end_equity'])} | {money(wp['end_equity'])} | {money(fp['end_equity'])} |
| Close admissions | n/a | {we['close_admissions']} | {fe['close_admissions']} |
| Completed entries | {control_result['entry_execution']['completed_entries']} | {we['completed_entries']} | {fe['completed_entries']} |
| Next-open blocks | {control_result['entry_execution']['planned_entries_fully_blocked_next_open']} | {we['next_open_blocks']} | {fe['next_open_blocks']} |
| Zero-quantity blocks | n/a | {we['zero_quantity_blocks']} | {fe['zero_quantity_blocks']} |
| Invalid-open blocks | n/a | {we['invalid_open_market_blocks']} | {fe['invalid_open_market_blocks']} |
| Rounding underfill | n/a | {money(we['rounding_underfill_dollars_total'])} | {money(fe['rounding_underfill_dollars_total'])} |
| Fractional buys | 0 | {we['fractional_buy_count']} | {fe['fractional_buy_count']} |

## Direct answers

**Did open-time whole-share sizing execute every admitted trade?** {'Yes.' if we['all_admitted_trades_executed'] else 'No.'} It recorded {we['next_open_blocks']} next-open blocks.

**Did fractional sizing execute every admitted trade?** {'Yes.' if fe['all_admitted_trades_executed'] else 'No.'} It recorded {fe['next_open_blocks']} next-open blocks.

**What does fractional sizing add?** Whole-share rounding left {money(we['rounding_underfill_dollars_total'])} of cumulative execution budget unused across executed buys. Fractional sizing left {money(fe['rounding_underfill_dollars_total'])}.

**Performance interpretation.** CAGR differences are path-dependent consequences of altered admissions and sizing. They are reported for completeness and are not the selection criterion.

## Research conclusion

The production-design question should be decided from execution completeness, sizing fidelity, operational broker support for fractional shares, and the path-divergence evidence. This experiment does not authorize a production change.
"""
    (out / "INSIGHTS.md").write_text(insight)

    provenance = {
        "schema": "research.wealth-core-v1-open-sizing-10bp-provenance/1",
        "workflow_run_id": int(args.run_id),
        "trigger_head": args.trigger_head,
        "base_evidence_head": "3b5d70de258dadaac6272f2bd9d682d291117d29",
        "control_source_sha256": control_result["authority"]["generated_arm_source_sha256"],
        "canonical_pit_dataset_sha256": control_result["dataset_sha256"],
    }
    (out / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")

    sums = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            sums.append(f"{sha(p)}  {p.relative_to(out)}")
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    print(insight)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
