#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2006-07-31")
END = pd.Timestamp("2026-07-31")
DATASET = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
CERTIFIED_V1_SUMMARY = "7488908b6e3da6141560838e8a825009e4462a11de733681addd17ac0658267a"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(df: pd.DataFrame, col: str) -> dict:
    x = df[["date", col]].dropna().copy()
    a = x[col].astype(float).to_numpy()
    norm = a / a[0]
    ret = norm[1:] / norm[:-1] - 1.0
    years = (x.date.iloc[-1] - x.date.iloc[0]).days / 365.2425
    peak = np.maximum.accumulate(norm)
    std = float(np.std(ret, ddof=1)) if len(ret) > 1 else float("nan")
    return {
        "cagr": float(norm[-1] ** (1 / years) - 1),
        "max_drawdown": float(np.min(norm / peak - 1)),
        "sharpe": float(np.mean(ret) / std * np.sqrt(252)) if np.isfinite(std) and std > 0 else None,
        "ending_multiple": float(norm[-1]),
        "sessions": int(len(x)),
    }


def load_daily(root: Path) -> pd.DataFrame:
    df = pd.read_csv(root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    return df[(df.date >= START) & (df.date <= END)].reset_index(drop=True)


def load_observer(root: Path) -> pd.DataFrame:
    path = root / "wealth_core_daily_observer.csv"
    if not path.is_file():
        raise RuntimeError(f"missing observer daily file: {path}")
    df = pd.read_csv(path, parse_dates=["date"])
    return df[(df.date >= START) & (df.date <= END)].reset_index(drop=True)


def first_numeric_divergence(v1: pd.DataFrame, v2: pd.DataFrame, col: str) -> str | None:
    a, b = v1[col].astype(float).to_numpy(), v2[col].astype(float).to_numpy()
    scale = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0)
    idx = np.flatnonzero(np.abs(a - b) > 1e-10 * scale)
    return str(v1.date.iloc[int(idx[0])].date()) if len(idx) else None


def annual_rows(name: str, df: pd.DataFrame, layer: str, col: str) -> list[dict]:
    r = df.set_index("date")[col].astype(float).pct_change().fillna(0.0)
    out = []
    for year, value in r.groupby(r.index.year).apply(lambda x: float((1 + x).prod() - 1)).items():
        out.append({"variant": name, "layer": layer, "year": int(year), "return": float(value)})
    return out


def observer_stats(df: pd.DataFrame) -> dict:
    return {
        "average_cash_weight": float((df.cash.astype(float) / df.wealth_core_equity.astype(float)).mean()),
        "median_cash_weight": float((df.cash.astype(float) / df.wealth_core_equity.astype(float)).median()),
        "average_invested_weight": float(df.invested_weight.astype(float).mean()),
        "median_invested_weight": float(df.invested_weight.astype(float).median()),
        "average_held_count": float(df.held_count.astype(float).mean()),
        "median_held_count": float(df.held_count.astype(float).median()),
        "full_slot_sessions": int((df.held_count.astype(float) >= 25).sum()),
        "average_reserved_count": float(df.reserved_count.astype(float).mean()),
        "max_reserved_entry_cash": float(df.reserved_entry_cash.astype(float).max()),
        "min_uncommitted_cash": float(df.uncommitted_cash.astype(float).min()),
    }


def read_audit(root: Path, variant: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    orders = pd.read_csv(root / "wealth_core_order_blotter.csv")
    positions = pd.read_csv(root / "wealth_core_position_lifecycle.csv")
    if orders.empty or positions.empty:
        raise RuntimeError(f"{variant}: audit surfaces are empty")
    if not orders.order_seq.astype(int).is_monotonic_increasing:
        raise RuntimeError(f"{variant}: order sequence is not chronological")
    orders.insert(0, "comparison_variant", variant)
    positions.insert(0, "comparison_variant", variant)
    return orders, positions


def main() -> int:
    v1root = Path("backtester-results/wc-v1")
    v2root = Path("backtester-results/wc-v2")
    out = Path("backtester-results/comparison")
    out.mkdir(parents=True, exist_ok=True)

    v1, v2 = load_daily(v1root), load_daily(v2root)
    o1, o2 = load_observer(v1root), load_observer(v2root)
    assert len(v1) == len(v2) > 5000, (len(v1), len(v2))
    assert v1.date.equals(v2.date)
    assert len(o1) == len(o2) == len(v1), (len(o1), len(o2), len(v1))
    assert o1.date.equals(o2.date) and o1.date.equals(v1.date)

    h1, h2 = v1root / "canonical_input_session_hashes.csv", v2root / "canonical_input_session_hashes.csv"
    if h1.exists() and h2.exists():
        assert h1.read_bytes() == h2.read_bytes(), "canonical input session hashes differ"

    v1_summary_sha = sha(v1root / "summary.json")
    v1_exact = v1_summary_sha == CERTIFIED_V1_SUMMARY

    variants: dict[str, dict] = {}
    for name, df, obs in (("V1", v1, o1), ("V2", v2, o2)):
        variants[name] = {
            "wealth_core": metrics(df, "research_wealth_core_equity"),
            "research_champion_ex3": metrics(df, "research_nav"),
            "wealth_core_state": observer_stats(obs),
            "allocation_transitions": int((df.research_allocation.astype(float).diff().abs() > 1e-12).sum()),
        }

    first = {
        "wealth_core_equity": first_numeric_divergence(v1, v2, "research_wealth_core_equity"),
        "research_champion_nav": first_numeric_divergence(v1, v2, "research_nav"),
        "research_champion_allocation": first_numeric_divergence(v1, v2, "research_allocation"),
        "wealth_core_cash": first_numeric_divergence(o1, o2, "cash"),
        "wealth_core_held_count": first_numeric_divergence(o1, o2, "held_count"),
    }
    if "research_selected_positions_sha256" in v1 and "research_selected_positions_sha256" in v2:
        z = v1.research_selected_positions_sha256.astype(str).ne(v2.research_selected_positions_sha256.astype(str))
        first["selected_positions"] = str(v1.loc[z, "date"].iloc[0].date()) if z.any() else None

    annual: list[dict] = []
    for name, df in (("V1", v1), ("V2", v2)):
        annual += annual_rows(name, df, "wealth_core", "research_wealth_core_equity")
        annual += annual_rows(name, df, "research_champion_ex3", "research_nav")
    pd.DataFrame(annual).to_csv(out / "annual_returns.csv", index=False)

    state_cmp = o1.add_prefix("v1_").join(o2.add_prefix("v2_"))
    state_cmp.to_csv(out / "wealth_core_state_comparison.csv.gz", index=False, compression="gzip")

    orders1, positions1 = read_audit(v1root, "V1")
    orders2, positions2 = read_audit(v2root, "V2")
    combined_orders = pd.concat([orders1, orders2], ignore_index=True)
    combined_orders["issued_session"] = pd.to_datetime(combined_orders.issued_session)
    combined_orders.sort_values(["issued_session", "comparison_variant", "order_seq"], inplace=True)
    combined_orders.to_csv(out / "chronological_order_blotter_v1_v2.csv", index=False)

    combined_positions = pd.concat([positions1, positions2], ignore_index=True)
    combined_positions["entry_session"] = pd.to_datetime(combined_positions.entry_session)
    combined_positions.sort_values(["entry_session", "comparison_variant", "episode_id"], inplace=True)
    combined_positions.to_csv(out / "position_lifecycle_v1_v2.csv", index=False)

    position_summary = []
    for name, p in (("V1", positions1), ("V2", positions2)):
        position_summary.append({
            "variant": name,
            "episodes": int(len(p)),
            "open_at_end": int((p.exit_reason.astype(str) == "OPEN_AT_END").sum()),
            "median_entry_open_weight": float(pd.to_numeric(p.entry_open_portfolio_weight, errors="coerce").median()),
            "median_min_close_weight": float(pd.to_numeric(p.min_close_portfolio_weight, errors="coerce").median()),
            "median_max_close_weight": float(pd.to_numeric(p.max_close_portfolio_weight, errors="coerce").median()),
            "minimum_observed_position_weight": float(pd.to_numeric(p.min_close_portfolio_weight, errors="coerce").min()),
            "maximum_observed_position_weight": float(pd.to_numeric(p.max_close_portfolio_weight, errors="coerce").max()),
        })
    pd.DataFrame(position_summary).to_csv(out / "position_size_summary.csv", index=False)

    s1 = json.loads((v1root / "summary.json").read_text())
    s2 = json.loads((v2root / "summary.json").read_text())
    funding = s2.get("wealth_core_entry_funding") or s2.get("wealth_core_v2") or {}

    order_summary = {}
    for name, orders in (("V1", orders1), ("V2", orders2)):
        side = orders.side.astype(str)
        status = orders.status.astype(str)
        order_summary[name] = {
            "orders_issued": int(len(orders)),
            "buy_orders": int(side.eq("BUY").sum()),
            "sell_orders": int(side.eq("SELL").sum()),
            "cancelled_orders": int(status.eq("CANCELLED").sum()),
            "partial_fills": int(status.eq("PARTIAL_FILLED").sum()),
        }

    result = {
        "schema": "research.wealth-core-v1-v2-pit-ab/2",
        "status": "PASS" if v1_exact else "V1_CERTIFIED_SUMMARY_PARITY_FAIL",
        "dataset_sha256": DATASET,
        "window": {"warmup_start": "2006-01-03", "measurement_start": "2006-07-31", "end": "2026-07-31"},
        "architecture": {
            "universe": "canonical broad point-in-time",
            "research_champion_profile": "strategy9-e3-research-champion-v1",
            "slots": 25,
            "entry_weight": 0.04,
            "v1_entry_funding": "cash_clipped_target",
            "v2_entry_funding": "full_whole_share_target_v1",
            "controller_retuned": False,
        },
        "layers": {
            "wealth_core": "raw Wealth Core book before Sentinel/LDRC allocation overlay",
            "research_champion_ex3": "same Wealth Core book passed through frozen Sentinel + EX3/LDRC",
        },
        "v1_control": {
            "summary_sha256": v1_summary_sha,
            "certified_summary_sha256": CERTIFIED_V1_SUMMARY,
            "exact_summary_parity": v1_exact,
        },
        "metrics": variants,
        "first_divergence": first,
        "orders": order_summary,
        "positions": {row["variant"]: row for row in position_summary},
        "v2_funding_diagnostics": funding,
        "v1_buys": s1.get("buys"), "v1_sells": s1.get("sells"),
        "v2_buys": s2.get("buys"), "v2_sells": s2.get("sells"),
    }
    (out / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    md = [
        "# Wealth Core V1 vs V2 — broad-PIT research A/B", "",
        f"Status: **{result['status']}**", "",
        f"Dataset: `{DATASET}`", "",
        "V1 is the retained certified control. V2 changes only Wealth Core entry slot funding. The observer is output-only.", "",
        "## Layer 1 — pure Wealth Core", "",
        "| Metric | V1 | V2 |", "|---|---:|---:|",
    ]
    for key, label in (("cagr", "CAGR"), ("max_drawdown", "Max DD"), ("sharpe", "Sharpe"), ("ending_multiple", "Ending multiple")):
        md.append(f"| {label} | {variants['V1']['wealth_core'][key]:.10g} | {variants['V2']['wealth_core'][key]:.10g} |")
    md += [
        f"| Average invested weight | {variants['V1']['wealth_core_state']['average_invested_weight']:.6f} | {variants['V2']['wealth_core_state']['average_invested_weight']:.6f} |",
        f"| Average held count | {variants['V1']['wealth_core_state']['average_held_count']:.4f} | {variants['V2']['wealth_core_state']['average_held_count']:.4f} |",
        "", f"First raw Wealth Core equity divergence: **{first['wealth_core_equity']}**",
        f"First Wealth Core cash divergence: **{first['wealth_core_cash']}**",
        f"First Wealth Core holding-count divergence: **{first['wealth_core_held_count']}**", "",
        "## Layer 2 — frozen Research Champion / EX3", "",
        "| Metric | V1 | V2 |", "|---|---:|---:|",
    ]
    for key, label in (("cagr", "CAGR"), ("max_drawdown", "Max DD"), ("sharpe", "Sharpe"), ("ending_multiple", "Ending multiple")):
        md.append(f"| {label} | {variants['V1']['research_champion_ex3'][key]:.10g} | {variants['V2']['research_champion_ex3'][key]:.10g} |")
    md += [
        "", f"First full-account NAV divergence: **{first['research_champion_nav']}**",
        f"First frozen-controller allocation divergence: **{first['research_champion_allocation']}**", "",
        "## Audit files", "",
        "- `chronological_order_blotter_v1_v2.csv`: every issued BUY/SELL with issue session, requested/fill shares, execution price, reason, slot and cancellation status.",
        "- `position_lifecycle_v1_v2.csv`: every episode with entry/exit prices and open/close/min/max position value and portfolio weight.",
        "- `wealth_core_state_comparison.csv.gz`: daily cash, receivables, reserved cash, invested weight and holding count for both books.",
        "- `annual_returns.csv`: annual returns for both the pure Wealth Core and full Research Champion/EX3 layers.", "",
        "## V2 funding diagnostics", "```json", json.dumps(funding, indent=2, sort_keys=True), "```", "",
    ]
    (out / "COMPARISON.md").write_text("\n".join(md))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not v1_exact:
        raise SystemExit("V1 control did not reproduce retained certified summary hash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
