#!/usr/bin/env python3
"""Measure fixed-scalar sleeve maintenance turnover for Sentinel 1.1.

The frozen reference compounds an unchanged scalar as a fixed Core/BIL return
mixture and charges no maintenance rebalance cost. Production physically targets
the scalar again on each prepared session. This tool measures only that
incremental sleeve-rebalancing gap; Wealth Core's own stock turnover is common to
both paths and is deliberately excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd


DEFAULT_COST = 0.001
SCALARS = (0.55, 0.65)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_bil_closeadj(sfp_zip: Path) -> pd.Series:
    parts = []
    with zipfile.ZipFile(sfp_zip) as archive:
        names = [name for name in archive.namelist()
                 if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(
                f"expected one CSV in {sfp_zip}, found {names}")
        with archive.open(names[0]) as handle:
            for chunk in pd.read_csv(
                    handle, usecols=["ticker", "date", "closeadj"],
                    chunksize=500_000, low_memory=False):
                selected = chunk[chunk.ticker.astype(str).eq("BIL")]
                if len(selected):
                    parts.append(selected)
    if not parts:
        raise RuntimeError("SFP contains no BIL rows")
    frame = pd.concat(parts, ignore_index=True)
    frame["date"] = pd.to_datetime(frame.date)
    return (frame.drop_duplicates("date", keep="last")
            .set_index("date").closeadj.astype(float).sort_index())


def measure(daily: pd.DataFrame, bil: pd.Series,
            *, cost: float = DEFAULT_COST) -> dict:
    frame = daily.copy().sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame.date)
    frame["prev_shadow"] = frame.shadow_equity.shift(1)
    frame["wc_factor"] = frame.shadow_equity / frame.prev_shadow
    frame["bil_closeadj"] = frame.date.map(bil)
    frame["prev_bil"] = frame.bil_closeadj.shift(1)
    frame["bil_factor"] = frame.bil_closeadj / frame.prev_bil
    frame["prev_alloc"] = frame.allocation.shift(1)

    unchanged = (
        frame.allocation.isin(SCALARS)
        & frame.allocation.eq(frame.prev_alloc)
        & frame.wc_factor.notna()
        & frame.bil_factor.notna()
    )
    rows = frame.loc[unchanged].copy()
    exposure = rows.allocation.astype(float)
    ending_factor = (
        exposure * rows.wc_factor
        + (1.0 - exposure) * rows.bil_factor
    )
    drifted_core = exposure * rows.wc_factor / ending_factor
    rows["one_way_turnover"] = np.abs(exposure - drifted_core)
    rows["gross_two_leg_turnover"] = 2.0 * rows.one_way_turnover
    # This deliberately uses the frozen reference's overlay-change convention:
    # COST * shifted notional, not COST on both legs independently.
    rows["reference_cost_fraction"] = cost * rows.one_way_turnover

    cost_multiplier = float(np.prod(1.0 - rows.reference_cost_fraction))
    years = ((frame.date.iloc[-1] - frame.date.iloc[0]).days / 365.2425)
    result = {
        "start": str(frame.date.iloc[0].date()),
        "end": str(frame.date.iloc[-1].date()),
        "sessions": int(len(rows)),
        "sessions_55": int(rows.allocation.eq(0.55).sum()),
        "sessions_65": int(rows.allocation.eq(0.65).sum()),
        "one_way_turnover_sum": float(rows.one_way_turnover.sum()),
        "gross_two_leg_turnover_sum": float(
            rows.gross_two_leg_turnover.sum()),
        "mean_daily_one_way_turnover": float(
            rows.one_way_turnover.mean()),
        "max_daily_one_way_turnover": float(rows.one_way_turnover.max()),
        "reference_cost_rate_per_shifted_notional": float(cost),
        "linear_cost_fraction": float(rows.reference_cost_fraction.sum()),
        "compounded_ending_nav_multiplier": cost_multiplier,
        "compounded_total_drag_fraction": 1.0 - cost_multiplier,
        "annualized_drag": 1.0 - cost_multiplier ** (1.0 / years),
        "one_way_turnover_sum_0.55": float(
            rows.loc[rows.allocation.eq(0.55), "one_way_turnover"].sum()),
        "one_way_turnover_sum_0.65": float(
            rows.loc[rows.allocation.eq(0.65), "one_way_turnover"].sum()),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--sfp", type=Path, required=True)
    parser.add_argument("--cost", type=float, default=DEFAULT_COST)
    args = parser.parse_args()

    daily = pd.read_csv(args.daily)
    required = {"date", "allocation", "shadow_equity"}
    missing = sorted(required - set(daily.columns))
    if missing:
        raise RuntimeError(f"daily reference is missing columns: {missing}")
    result = measure(daily, load_bil_closeadj(args.sfp), cost=args.cost)
    result["daily_sha256"] = sha256(args.daily)
    result["sfp_sha256"] = sha256(args.sfp)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
