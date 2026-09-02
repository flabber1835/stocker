#!/usr/bin/env python3
"""Public Production/SPY reporting for retained backtester harnesses.

Economic replay may use internal A/B/D labels while it is running. Those labels
are implementation details. This module converts a completed raw bundle into a
single public Production path plus SPY, recomputes metrics from that path, and
rehashes the resulting evidence. The transform is idempotent so a corrected
warm-up wrapper may finalize before and after measurement trimming.
"""
from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd


_NOMINAL_WINDOW_TOLERANCE_DAYS = 10.0


def _source_variant_from_columns(columns) -> str:
    names = set(map(str, columns))
    if "Production_nav" in names:
        return "Production"
    if "D_nav" in names:
        return "D"
    if "B_nav" in names:
        return "B"
    raise RuntimeError("daily output has no Production economic account column")


def _source_variant_from_values(values) -> str:
    labels = set(map(str, values))
    for candidate in ("Production", "D", "B"):
        if candidate in labels:
            return candidate
    raise RuntimeError("metrics output has no Production economic variant")


def _block_elapsed_years(block: Mapping) -> float | None:
    raw = block.get("elapsed_years")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float("nan")
    if math.isfinite(value) and value >= 0.0:
        return value
    start = block.get("start")
    end = block.get("end")
    if start is None or end is None:
        return None
    try:
        elapsed_days = (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
    except ValueError:
        return None
    return elapsed_days / 365.2425 if elapsed_days >= 0 else None


def _nominal_window_is_complete(window, block: Mapping) -> bool:
    """Admit a nominal N-year label only when the evidence is actually N years."""
    try:
        nominal = float(window)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(nominal) or nominal <= 0.0:
        return False
    elapsed = _block_elapsed_years(block)
    # Legacy synthetic unit tests and old external callers can omit dates. Real
    # replay rows always carry start/end, where this gate is authoritative.
    if elapsed is None:
        return True
    tolerance = _NOMINAL_WINDOW_TOLERANCE_DAYS / 365.2425
    return abs(elapsed - nominal) <= tolerance


def public_production_daily(raw: pd.DataFrame) -> pd.DataFrame:
    """Expose only Production account fields and the SPY benchmark."""
    if "date" not in raw.columns or "SPY_level" not in raw.columns:
        raise RuntimeError("daily output lacks date/SPY benchmark")
    source = _source_variant_from_columns(raw.columns)
    result = pd.DataFrame({
        "date": raw["date"],
        "Production_nav": raw[f"{source}_nav"].astype(float),
    })
    allocation = f"{source}_allocation"
    if allocation in raw.columns:
        result["Production_allocation"] = raw[allocation].astype(float)
    ranking = next(
        (name for name in (
            "Production_ranking_count", "D_ranking_count", "B_ranking_count"
        ) if name in raw.columns),
        None,
    )
    if ranking is not None:
        result["Production_ranking_count"] = raw[ranking]
    core = next(
        (name for name in (
            "Production_wealth_core_equity",
            "D_wealth_core_equity",
            "B_wealth_core_equity",
        ) if name in raw.columns),
        None,
    )
    if core is not None:
        result["Production_wealth_core_equity"] = raw[core].astype(float)
    result["SPY_level"] = raw["SPY_level"].astype(float)
    return result


def public_production_metrics(raw: pd.DataFrame, max_blocks: Mapping[str, Mapping]) -> pd.DataFrame:
    """Filter legacy variants and issue truthful public measurement-window rows."""
    if "variant" not in raw.columns or "window_years" not in raw.columns:
        raise RuntimeError("metrics output lacks variant/window columns")
    source = _source_variant_from_values(raw["variant"].astype(str))
    current = raw[raw["variant"].astype(str).isin({source, "SPY"})].copy()
    current = current[~current["window_years"].astype(str).eq("max")]
    if not current.empty:
        keep = current.apply(
            lambda row: _nominal_window_is_complete(
                row["window_years"], row.to_dict()
            ),
            axis=1,
        )
        current = current[keep].copy()
    current.loc[current["variant"].astype(str).eq(source), "variant"] = "Production"
    rows = []
    for label in ("Production", "SPY"):
        block = dict(max_blocks[label])
        rows.append({"window_years": "max", "variant": label, **block})
    result = pd.concat([current, pd.DataFrame(rows)], ignore_index=True, sort=False)
    return result


def public_metric_summary(raw: Mapping, max_blocks: Mapping[str, Mapping]) -> dict:
    """Translate nested legacy metrics to truthful Production/SPY naming."""
    result: dict[str, dict] = {}
    for window, values in raw.items():
        if str(window) == "max" or not isinstance(values, Mapping):
            continue
        source = next((key for key in ("Production", "D", "B") if key in values), None)
        if source is None or "SPY" not in values:
            raise RuntimeError(f"metric summary {window} lacks Production/SPY evidence")
        production = dict(values[source])
        spy = dict(values["SPY"])
        if not (
            _nominal_window_is_complete(window, production)
            and _nominal_window_is_complete(window, spy)
        ):
            continue
        result[str(window)] = {
            "Production": production,
            "SPY": spy,
        }
    result["max"] = {
        "Production": dict(max_blocks["Production"]),
        "SPY": dict(max_blocks["SPY"]),
    }
    return result


def metric_block(frame: pd.DataFrame, column: str, measurement_start: str, end_session: str) -> dict:
    x = frame[frame["date"].astype(str) >= str(measurement_start)][["date", column]].dropna().copy()
    if x.empty or str(x.iloc[-1]["date"]) != str(end_session):
        raise RuntimeError(f"{column} has incomplete measurement window through {end_session}")
    values = x[column].astype(float).to_numpy()
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        raise RuntimeError(f"{column} has invalid measurement values")
    normalized = values / values[0]
    returns = normalized[1:] / normalized[:-1] - 1.0
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    # Public evidence is strict JSON. A constant-return or single-return window
    # has no observed return dispersion, so the finite backtester convention is
    # Sharpe 0.0. This matches app.metrics and avoids NaN/Infinity certificates.
    sharpe = (
        float(np.mean(returns) / std * math.sqrt(252.0))
        if math.isfinite(std) and std > 0.0
        else 0.0
    )
    peak = np.maximum.accumulate(normalized)
    max_drawdown = float(np.min(normalized / peak - 1.0))
    elapsed_years = (
        date.fromisoformat(str(x.iloc[-1]["date"]))
        - date.fromisoformat(str(x.iloc[0]["date"]))
    ).days / 365.2425
    if elapsed_years <= 0:
        raise RuntimeError("Production measurement elapsed years is non-positive")
    return {
        "start": str(x.iloc[0]["date"]),
        "end": str(x.iloc[-1]["date"]),
        "sessions": int(len(x)),
        "elapsed_years": float(elapsed_years),
        "cagr": float(normalized[-1] ** (1.0 / elapsed_years) - 1.0),
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "ending_multiple": float(normalized[-1]),
    }


def _purge_internal_labels(value):
    """Recursively remove legacy control/account labels from public JSON."""
    if isinstance(value, list):
        return [_purge_internal_labels(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, child in value.items():
        text = str(key)
        if text in {"A", "B", "D"} or text.startswith(("A_", "B_", "D_")):
            continue
        out[text] = _purge_internal_labels(child)
    return out


def write_final_comparison(owner) -> None:
    """Rewrite one completed replay bundle as Production/SPY evidence."""
    output = Path(owner.base.OUTPUT)
    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"
    for path in (daily_path, metrics_path, summary_path, manifest_path):
        if not path.is_file():
            raise RuntimeError(f"Production reporting input is missing: {path.name}")

    daily = pd.read_csv(daily_path, compression="gzip", low_memory=False)
    source = _source_variant_from_columns(daily.columns)
    if "Production_wealth_core_equity" not in daily.columns:
        history = getattr(owner, "_pit_core_by_session", None)
        if not isinstance(history, dict):
            raise RuntimeError("Production Wealth Core history is unavailable")
        core_values = []
        for session in daily["date"].astype(str):
            pair = history.get(session)
            if pair is None or len(pair) != 2 or not math.isfinite(float(pair[1])) or float(pair[1]) <= 0:
                raise RuntimeError(f"Production Wealth Core history lacks {session}")
            core_values.append(float(pair[1]))
        daily["Production_wealth_core_equity"] = core_values
    if source != "Production":
        daily[f"{source}_wealth_core_equity"] = daily["Production_wealth_core_equity"]
    public_daily = public_production_daily(daily)
    public_daily.to_csv(
        daily_path,
        index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )

    measurement_start = str(
        getattr(owner, "_production_measurement_start", None)
        or public_daily.iloc[0]["date"]
    )
    end_session = str(owner.base.runner.END_SESSION)
    max_blocks = {
        "Production": metric_block(public_daily, "Production_nav", measurement_start, end_session),
        "SPY": metric_block(public_daily, "SPY_level", measurement_start, end_session),
    }

    raw_metrics = pd.read_csv(metrics_path, dtype={"window_years": str})
    public_metrics = public_production_metrics(raw_metrics, max_blocks)
    public_metrics.to_csv(metrics_path, index=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["wealth_core_parity"] = False
    summary["full_stack_pit"] = True
    summary["wealth_core_pit_enabled"] = True
    summary["metrics"] = public_metric_summary(summary.get("metrics") or {}, max_blocks)
    transitions = summary.get("transitions") or {}
    transition_cost = summary.get("transition_cost_sum") or {}
    source_key = next((key for key in ("Production", "D", "B") if key in transitions), None)
    summary["transitions"] = ({"Production": int(transitions[source_key])} if source_key else {})
    source_cost = next((key for key in ("Production", "D", "B") if key in transition_cost), None)
    summary["transition_cost_sum"] = (
        {"Production": float(transition_cost[source_cost])} if source_cost else {}
    )
    summary.pop("d_pit_semantics", None)
    summary.setdefault("pit_authority", {
        "wealth_core_issuer_family": "strict-prior SEC CIK; unknown-before-evidence becomes security singleton",
        "sentinel_sector": "strict-prior SEC CIK -> SEC SIC -> frozen FF12",
        "present_day_relatedtickers_in_Production": False,
    })
    summary.setdefault("comparison_contract", {})
    summary["comparison_contract"].update({
        "Production": "full-stack causal PIT Production with an independent Wealth Core equity path",
        "wealth_core": f"exact current main {owner.EXPECTED_MAIN_SHA}; independent Production state and account equity path",
        "measurement_windows": sorted(summary["metrics"]),
        "SPY": "same causal benchmark series used by the Production replay",
    })
    summary = _purge_internal_labels(summary)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["current_main_sha"] = owner.EXPECTED_MAIN_SHA
    manifest["full_stack_pit"] = True
    manifest["public_variants"] = ["Production", "SPY"]
    manifest["internal_account_labels_exposed"] = False
    outputs = manifest.setdefault("outputs", {})
    for path in (daily_path, metrics_path, summary_path):
        outputs[path.name] = {
            "sha256": owner.base._sha256(path),
            "bytes": path.stat().st_size,
        }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{owner.base._sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )
