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
    std = float(np.std(ret, ddof=1))
    return {
        "cagr": float(norm[-1] ** (1 / years) - 1),
        "max_drawdown": float(np.min(norm / peak - 1)),
        "sharpe": float(np.mean(ret) / std * np.sqrt(252)) if std > 0 else None,
        "ending_multiple": float(norm[-1]),
        "sessions": int(len(x)),
    }


def load(root: Path) -> pd.DataFrame:
    df = pd.read_csv(root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    return df[(df.date >= START) & (df.date <= END)].reset_index(drop=True)


def main() -> int:
    v1root = Path("backtester-results/wc-v1")
    v2root = Path("backtester-results/wc-v2")
    out = Path("backtester-results/comparison")
    out.mkdir(parents=True, exist_ok=True)
    v1, v2 = load(v1root), load(v2root)
    assert len(v1) == len(v2) > 5000, (len(v1), len(v2))
    assert v1.date.equals(v2.date)

    h1, h2 = v1root / "canonical_input_session_hashes.csv", v2root / "canonical_input_session_hashes.csv"
    if h1.exists() and h2.exists():
        assert h1.read_bytes() == h2.read_bytes(), "canonical input session hashes differ"

    v1_summary_sha = sha(v1root / "summary.json")
    v1_exact = v1_summary_sha == CERTIFIED_V1_SUMMARY

    variants = {}
    for name, df in (("V1", v1), ("V2", v2)):
        variants[name] = {
            "portfolio": metrics(df, "research_nav"),
            "wealth_core": metrics(df, "research_wealth_core_equity"),
            "average_held_count": float(df.held_count.astype(float).mean()) if "held_count" in df else None,
            "median_held_count": float(df.held_count.astype(float).median()) if "held_count" in df else None,
            "full_slot_sessions": int((df.held_count.astype(float) >= 25).sum()) if "held_count" in df else None,
            "allocation_transitions": int((df.research_allocation.astype(float).diff().abs() > 1e-12).sum()),
        }

    first = {}
    for col in ("research_wealth_core_equity", "research_nav", "research_allocation"):
        a, b = v1[col].astype(float).to_numpy(), v2[col].astype(float).to_numpy()
        scale = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0)
        idx = np.flatnonzero(np.abs(a - b) > 1e-10 * scale)
        first[col] = str(v1.date.iloc[int(idx[0])].date()) if len(idx) else None
    if "research_selected_positions_sha256" in v1 and "research_selected_positions_sha256" in v2:
        z = v1.research_selected_positions_sha256.astype(str).ne(v2.research_selected_positions_sha256.astype(str))
        first["selected_positions"] = str(v1.loc[z, "date"].iloc[0].date()) if z.any() else None

    annual = []
    for name, df in (("V1", v1), ("V2", v2)):
        r = df.set_index("date").research_nav.astype(float).pct_change().fillna(0.0)
        for year, value in r.groupby(r.index.year).apply(lambda x: float((1 + x).prod() - 1)).items():
            annual.append({"variant": name, "year": int(year), "return": float(value)})
    pd.DataFrame(annual).to_csv(out / "annual_returns.csv", index=False)

    s1 = json.loads((v1root / "summary.json").read_text())
    s2 = json.loads((v2root / "summary.json").read_text())
    funding = s2.get("wealth_core_entry_funding", {})
    result = {
        "schema": "research.wealth-core-v1-v2-pit-ab/1",
        "status": "PASS" if v1_exact else "V1_CERTIFIED_SUMMARY_PARITY_FAIL",
        "dataset_sha256": DATASET,
        "window": {"warmup_start": "2006-01-03", "measurement_start": "2006-07-31", "end": "2026-07-31"},
        "architecture": {
            "research_champion_profile": "strategy9-e3-research-champion-v1",
            "slots": 25,
            "entry_weight": 0.04,
            "v1_entry_funding": "cash_clipped_target",
            "v2_entry_funding": "full_whole_share_target_v1",
        },
        "v1_control": {
            "summary_sha256": v1_summary_sha,
            "certified_summary_sha256": CERTIFIED_V1_SUMMARY,
            "exact_summary_parity": v1_exact,
        },
        "metrics": variants,
        "first_divergence": first,
        "v2_funding_diagnostics": funding,
        "v1_buys": s1.get("buys"), "v1_sells": s1.get("sells"),
        "v2_buys": s2.get("buys"), "v2_sells": s2.get("sells"),
    }
    (out / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    md = [
        "# Wealth Core V1 vs V2 — certified broad-PIT A/B", "",
        f"Status: **{result['status']}**", "", f"Dataset: `{DATASET}`", "",
        "| Metric | V1 | V2 |", "|---|---:|---:|",
    ]
    for key, label in (("cagr", "CAGR"), ("max_drawdown", "Max DD"), ("sharpe", "Sharpe"), ("ending_multiple", "Ending multiple")):
        md.append(f"| {label} | {variants['V1']['portfolio'][key]:.10g} | {variants['V2']['portfolio'][key]:.10g} |")
    md += [
        "", f"First Wealth Core equity divergence: **{first['research_wealth_core_equity']}**",
        f"First portfolio NAV divergence: **{first['research_nav']}**",
        f"First allocation divergence: **{first['research_allocation']}**", "",
        "## V2 funding diagnostics", "```json", json.dumps(funding, indent=2, sort_keys=True), "```", "",
    ]
    (out / "COMPARISON.md").write_text("\n".join(md))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not v1_exact:
        raise SystemExit("V1 control did not reproduce retained certified summary hash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
