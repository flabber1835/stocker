"""Private, forecast-only numerical baseline; never imports trading machinery."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from forecast_collect import BARS, canonical, digest, save

FEATURES = ["momentum5", "momentum21", "momentum63", "vol21", "vol63", "drawdown63",
            "volume_relative21", "intraday", "price_gap", "spy_momentum21", "spy_momentum63",
            "spy_vol21", "beta63", "correlation63"]
HEADS = ["intraday", "price_gap"]


def common_price_scale(raw, split):
    tolerance = 0.005000001
    lower = max((split[key] - tolerance) / raw[key] for key in ("o", "h", "l", "c"))
    upper = min((split[key] + tolerance) / raw[key] for key in ("o", "h", "l", "c"))
    return 0 < upper and max(0, lower) <= upper


def verify_inputs(acquisition_dir, cohort_path, protocol_path):
    root = Path(acquisition_dir)
    acquisition_raw = (root / "acquisition.json").read_bytes()
    acquisition = json.loads(acquisition_raw)
    protocol_raw = Path(protocol_path).read_bytes()
    cohort_raw = Path(cohort_path).read_bytes()
    protocol, cohort = json.loads(protocol_raw), json.loads(cohort_raw)
    if (acquisition["status"] != "COMPLETE" or not acquisition["pagination_complete"]
            or acquisition["protocol_sha256"] != digest(protocol_raw)
            or acquisition["cohort_sha256"] != digest(cohort_raw)
            or cohort["protocol_sha256"] != digest(protocol_raw)
            or acquisition["broker_account_calls"] != 0 or acquisition["production_contacted"]):
        raise ValueError("REFUSED_INPUT_BINDING")
    frames, totals = {"raw": {}, "split": {}}, {"raw": 0, "split": 0}
    ny = ZoneInfo("America/New_York")
    for receipt in acquisition["provider_receipts"]:
        name = receipt["file"]
        if Path(name).name != name:
            raise ValueError("REFUSED_PROVIDER_FILE_PATH")
        raw = (root / name).read_bytes()
        if len(raw) != receipt["bytes"] or digest(raw) != receipt["sha256"]:
            raise ValueError("REFUSED_PROVIDER_BYTES")
        if receipt["endpoint"] != BARS:
            continue
        params = receipt["params"]
        adjustment = params["adjustment"]
        if (adjustment not in frames or params["feed"] != protocol["feed"]
                or params["timeframe"] != "1Day" or params["asof"] != protocol["end"]):
            raise ValueError("REFUSED_BAR_IDENTITY")
        for ticker, bars in json.loads(raw)["bars"].items():
            target = frames[adjustment].setdefault(ticker, {})
            for bar in bars:
                stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("REFUSED_UNDATED_BAR")
                day = stamp.astimezone(ny).date().isoformat()
                values = {key: float(bar[key]) for key in ("o", "h", "l", "c", "v")}
                if (day in target or not protocol["start"] <= day <= protocol["end"]
                        or not all(math.isfinite(v) for v in values.values())
                        or min(values[k] for k in ("o", "h", "l", "c")) <= 0 or values["v"] < 0
                        or values["h"] < max(values["o"], values["c"], values["l"])
                        or values["l"] > min(values["o"], values["c"], values["h"])):
                    raise ValueError("REFUSED_INVALID_OR_DUPLICATE_BAR")
                target[day] = values
                totals[adjustment] += 1
    if totals != acquisition["bar_counts"]:
        raise ValueError("REFUSED_PROVIDER_ROW_COUNTS")
    if set(frames["raw"]) != set(frames["split"]) or "SPY" not in frames["raw"]:
        raise ValueError("REFUSED_PRICE_DOMAIN_COVERAGE")
    axis = sorted(frames["raw"]["SPY"])
    for ticker in frames["raw"]:
        if set(frames["raw"][ticker]) != set(frames["split"][ticker]):
            raise ValueError("REFUSED_RAW_SPLIT_AXIS")
        for day, raw in frames["raw"][ticker].items():
            adjusted = frames["split"][ticker][day]
            # Published adjusted OHLC may be rounded to cents. Require one common
            # positive factor inside every half-cent interval; never change prices.
            if not common_price_scale(raw, adjusted):
                raise ValueError("REFUSED_INTRADAY_PRICE_DOMAIN")
            if day not in axis:
                raise ValueError("REFUSED_NONMARKET_SESSION")
    return acquisition, protocol, frames, axis, {
        "acquisition_sha256": digest(acquisition_raw), "cohort_sha256": digest(cohort_raw),
        "protocol_sha256": digest(protocol_raw), "provider_file_count": len(acquisition["provider_receipts"]),
        "actual_provider_bar_counts": totals, "axis_sessions": len(axis), "first_session": axis[0],
        "last_session": axis[-1], "provider_bytes_verified": True,
    }


def frame_for(frames, ticker, axis, adjustment):
    return pd.DataFrame.from_dict(frames[adjustment][ticker], orient="index").reindex(axis)


def feature_matrix(frames, admitted, axis, protocol):
    spy = frame_for(frames, "SPY", axis, "split")
    sr = spy.c.pct_change(fill_method=None)
    spy_features = {"spy_momentum21": spy.c / spy.c.shift(21) - 1,
                    "spy_momentum63": spy.c / spy.c.shift(63) - 1,
                    "spy_vol21": sr.rolling(21).std(ddof=0)}
    blocks, coverage = [], []
    for identity in admitted:
        ticker = identity["ticker"]
        if ticker == "SPY":
            continue
        if ticker not in frames["raw"]:
            coverage.append({"ticker": ticker, "reason": "NO_PROVIDER_BARS", "model_rows": 0})
            continue
        raw, split = (frame_for(frames, ticker, axis, kind) for kind in ("raw", "split"))
        ret = split.c.pct_change(fill_method=None)
        intra, gap = raw.c / raw.o - 1, split.o / split.c.shift(1) - 1
        features = {f"momentum{n}": split.c / split.c.shift(n) - 1 for n in (5, 21, 63)}
        features.update(vol21=ret.rolling(21).std(ddof=0), vol63=ret.rolling(63).std(ddof=0),
                        drawdown63=split.c / split.c.rolling(63).max() - 1,
                        volume_relative21=np.log1p(raw.v) - np.log1p(raw.v.rolling(21).mean()),
                        intraday=intra, price_gap=gap, **spy_features,
                        beta63=ret.rolling(63).cov(sr) / sr.rolling(63).var(),
                        correlation63=ret.rolling(63).corr(sr))
        block = pd.DataFrame(features, index=axis)
        block["intraday_y"], block["price_gap_y"] = intra.shift(-1), gap.shift(-1)
        floor, n = protocol["target_scale_floor"], protocol["target_scale_window"]
        block["intraday_scale"] = intra.rolling(n).std(ddof=0).clip(lower=floor)
        block["price_gap_scale"] = gap.rolling(n).std(ddof=0).clip(lower=floor)
        # Reindex to SPY first: absent sessions cannot become multi-day next-session labels.
        good = raw[["o", "c"]].notna().all(axis=1) & split[["o", "c"]].notna().all(axis=1)
        consecutive = good.astype(int).rolling(protocol["minimum_history"]).sum() == protocol["minimum_history"]
        valid = consecutive & good.shift(-1, fill_value=False)
        block["decision_date"] = axis
        block["target_date"] = pd.Series(axis, index=axis).shift(-1)
        block["ticker"], block["asset_id"] = ticker, identity["asset_id"]
        numeric = FEATURES + [f"{head}_{suffix}" for head in HEADS for suffix in ("y", "scale")]
        valid &= pd.Series(np.isfinite(block[numeric].to_numpy()).all(axis=1), index=axis)
        block = block.loc[valid].copy()
        coverage.append({"ticker": ticker, "provider_rows": int(good.sum()), "model_rows": len(block),
                         "test_rows": int((block.target_date >= protocol["test_start"]).sum()),
                         "first_target": None if block.empty else block.target_date.iloc[0],
                         "last_target": None if block.empty else block.target_date.iloc[-1]})
        blocks.append(block)
    if not blocks:
        raise ValueError("INSUFFICIENT_FEATURE_ROWS")
    result = pd.concat(blocks, ignore_index=True).sort_values(["target_date", "asset_id"]).reset_index(drop=True)
    if (result.decision_date >= result.target_date).any() or result.duplicated(["asset_id", "target_date"]).any():
        raise ValueError("REFUSED_FORECAST_TIMING_OR_DUPLICATE")
    return result, coverage


def fit_ridge(x, y, penalty):
    if penalty <= 0 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("REFUSED_RIDGE_INPUT")
    center, spread = x.mean(axis=0), x.std(axis=0)
    spread = np.where(spread > 1e-12, spread, 1.0)
    z, intercept = (x - center) / spread, float(y.mean())
    beta = np.linalg.solve(z.T @ z / len(x) + penalty * np.eye(x.shape[1]),
                           z.T @ (y - intercept) / len(x))
    return {"center": center.tolist(), "spread": spread.tolist(), "beta": beta.tolist(), "intercept": intercept}


def predict(model, x):
    return (x - np.array(model["center"])) / np.array(model["spread"]) @ np.array(model["beta"]) + model["intercept"]


def month_partition(data, month):
    train = data.loc[data.target_date < month + "-01"]
    test = data.loc[data.target_date.str.startswith(month)]
    if not train.empty and train.target_date.max() >= month + "-01":
        raise ValueError("REFUSED_FUTURE_LABEL")
    return train, test


def walk_forward(data, protocol):
    months = sorted(data.loc[data.target_date >= protocol["test_start"], "target_date"].str[:7].unique())
    rows, models = [], []
    for month in months:
        train, test = month_partition(data, month)
        if train.target_date.nunique() < protocol["minimum_train_dates"] or test.empty:
            raise ValueError("INSUFFICIENT_CHRONOLOGICAL_TRAINING")
        xtrain, xtest = train[FEATURES].to_numpy(), test[FEATURES].to_numpy()
        for head in HEADS:
            target, scale = f"{head}_y", f"{head}_scale"
            train_y, train_scale = train[target].to_numpy(), train[scale].to_numpy()
            test_y, test_scale = test[target].to_numpy(), test[scale].to_numpy()
            model = fit_ridge(xtrain, train_y / train_scale, protocol["ridge_lambda"])
            train_prediction = predict(model, xtrain) * train_scale
            prediction = predict(model, xtest) * test_scale
            # Nominal bands are in-sample residual calibration, explicitly scored later.
            residual = train_y - train_prediction
            lo, hi = np.quantile(residual, [0.1, 0.9])
            historical_mean = float(train_y.mean())
            evidence = {"head": head, "month": month, "model": model, "features": FEATURES,
                        "train_rows": len(train), "train_target_dates": train.target_date.nunique(),
                        "train_first_target": train.target_date.min(), "train_last_target": train.target_date.max(),
                        "test_first_target": test.target_date.min(), "test_last_target": test.target_date.max(),
                        "training_mean": historical_mean, "raw_residual_quantiles": [float(lo), float(hi)],
                        "lambda": protocol["ridge_lambda"]}
            model_hash = digest(canonical(evidence))
            models.append({**evidence, "model_sha256": model_hash})
            for index, (record, actual, estimate, sigma) in enumerate(zip(test.to_dict("records"), test_y, prediction, test_scale)):
                rows.append({"head": head, "ticker": record["ticker"], "asset_id": record["asset_id"],
                             "decision_date": record["decision_date"], "target_date": record["target_date"],
                             "actual": float(actual), "ridge": float(estimate), "historical_mean": historical_mean,
                             "zero": 0.0, "lower80": float(estimate + lo), "upper80": float(estimate + hi),
                             "lagged_scale": float(sigma), "model_sha256": model_hash,
                             "train_last_target": evidence["train_last_target"]})
    return rows, models


def nw_mean_se(values, lags=5):
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = float(values.mean())
    centered = values - mean
    variance = float(centered @ centered / n)
    for lag in range(1, min(lags, n - 1) + 1):
        variance += 2 * (1 - lag / (lags + 1)) * float(centered[lag:] @ centered[:-lag] / n)
    return {"daily_mean_loss_difference": mean, "newey_west_standard_error": math.sqrt(max(variance, 0) / n),
            "lags": lags, "days": n, "loss_difference": "ridge squared error minus comparator squared error"}


def metric_block(rows):
    frame = pd.DataFrame(rows)
    y = frame.actual.to_numpy()
    result = {"rows": len(frame), "target_dates": frame.target_date.nunique(), "assets": frame.asset_id.nunique(),
              "first_target": frame.target_date.min(), "last_target": frame.target_date.max(), "methods": {}}
    losses = {}
    for method in ("zero", "historical_mean", "ridge"):
        p = frame[method].to_numpy()
        losses[method] = (y - p) ** 2
        result["methods"][method] = {"mse": float(losses[method].mean()), "mae": float(np.abs(y - p).mean()),
                                     "direction_accuracy": float((np.sign(y) == np.sign(p)).mean())}
    for base in ("zero", "historical_mean"):
        mse = result["methods"][base]["mse"]
        result["methods"]["ridge"]["skill_vs_" + base] = 1 - result["methods"]["ridge"]["mse"] / mse if mse else None
        differences = pd.DataFrame({"date": frame.target_date, "diff": losses["ridge"] - losses[base]}).groupby("date")["diff"].mean()
        result["loss_difference_vs_" + base] = nw_mean_se(differences.to_numpy())
    p = frame.ridge.to_numpy()
    pc = p - p.mean()
    denominator = float(pc @ pc)
    result["ridge_calibration_slope"] = float(pc @ (y - y.mean()) / denominator) if denominator > 0 else None
    result["ridge_nominal80_coverage"] = float(((y >= frame.lower80) & (y <= frame.upper80)).mean())
    return result


def run(acquisition_dir, cohort_path, protocol_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    acquisition, protocol, frames, axis, binding = verify_inputs(acquisition_dir, cohort_path, protocol_path)
    data, coverage = feature_matrix(frames, acquisition["admitted"], axis, protocol)
    usable = data.loc[data.target_date >= protocol["test_start"], "asset_id"].nunique()
    if usable < protocol["minimum_eligible_series"]:
        save(output / "insufficient-coverage.json", {"usable": usable, "coverage": coverage, "binding": binding})
        raise ValueError("INSUFFICIENT_TEST_ASSET_COVERAGE")
    rows, models = walk_forward(data, protocol)
    rows.sort(key=lambda row: (row["target_date"], row["asset_id"], row["head"]))
    with (output / "predictions.jsonl").open("xb") as stream:
        for row in rows:
            stream.write(canonical(row) + b"\n")
    save(output / "models.json", models)
    save(output / "coverage.json", {"series": coverage, "eligible_at_acquisition": len(acquisition["admitted"]),
                                     "eligible_forecast_series": usable, "feature_rows": len(data),
                                     "pretest_feature_rows": int((data.target_date < protocol["test_start"]).sum())})
    metrics = {"schema": "research.numerical-forecast-metrics/1", "binding": binding,
               "features": FEATURES, "model_count": len(models), "heads": {}}
    for head in HEADS:
        selected = [row for row in rows if row["head"] == head]
        months = sorted({row["target_date"][:7] for row in selected})
        metrics["heads"][head] = {"all": metric_block(selected), "months": {
            month: metric_block([row for row in selected if row["target_date"].startswith(month)]) for month in months}}
    metrics["software"] = {"numpy": np.__version__, "pandas": pd.__version__}
    save(output / "metrics.json", metrics)
    save(output / "run.json", {"status": "COMPLETE", "forecast_only": True, "production_contacted": False,
                               "models": len(models), "prediction_rows": len(rows),
                               "predictions_sha256": digest((output / "predictions.jsonl").read_bytes()),
                               "metrics_sha256": digest((output / "metrics.json").read_bytes())})
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.acquisition, args.cohort, args.protocol, args.output)
    print(json.dumps({"status": "COMPLETE", "models": result["model_count"], "heads": {
        head: result["heads"][head]["all"]["methods"]["ridge"] for head in HEADS}}))


if __name__ == "__main__":
    main()
