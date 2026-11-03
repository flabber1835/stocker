"""Independent price/feature/KKT/metric review; no baseline implementation import."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

import numpy as np

FIELDS = ["momentum5", "momentum21", "momentum63", "vol21", "vol63", "drawdown63",
          "volume_relative21", "intraday", "price_gap", "spy_momentum21", "spy_momentum63",
          "spy_vol21", "beta63", "correlation63"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def require(value, message):
    if not value:
        raise ValueError("REFUSED_REVIEW_" + message)


def close(a, b, label, tolerance=1e-9):
    require(math.isfinite(float(a)) and math.isfinite(float(b)) and
            math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=1e-11), label)


def direct_rows(acquisition, root, protocol):
    bars = {"raw": defaultdict(dict), "split": defaultdict(dict)}
    for receipt in acquisition["provider_receipts"]:
        raw = (root / receipt["file"]).read_bytes()
        require(len(raw) == receipt["bytes"] and sha(raw) == receipt["sha256"], "SOURCE_BYTES")
        if receipt["endpoint"] != "https://data.alpaca.markets/v2/stocks/bars":
            require(receipt["endpoint"] in {"https://paper-api.alpaca.markets/v2/assets", "https://api.openfigi.com/v3/mapping"}, "PROVIDER")
            continue
        kind = receipt["params"]["adjustment"]
        require(kind in bars and receipt["params"]["feed"] == "sip", "PRICE_DOMAIN")
        for symbol, batch in json.loads(raw)["bars"].items():
            for record in batch:
                day = datetime.fromisoformat(record["t"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date().isoformat()
                require(day not in bars[kind][symbol], "DUPLICATE_BAR")
                bars[kind][symbol][day] = record
    axis = sorted(bars["raw"]["SPY"])
    spy = [float(bars["split"]["SPY"][day]["c"]) for day in axis]
    sret = [None] + [spy[i] / spy[i - 1] - 1 for i in range(1, len(axis))]
    result = []
    for identity in acquisition["admitted"]:
        symbol = identity["ticker"]
        if symbol == "SPY":
            continue
        raw, split = bars["raw"][symbol], bars["split"][symbol]
        for i in range(protocol["minimum_history"] - 1, len(axis) - 1):
            if not all(day in raw and day in split for day in axis[i - 126:i + 2]):
                continue
            c = [float(split[day]["c"]) for day in axis[i - 126:i + 1]]
            r = [c[j] / c[j - 1] - 1 for j in range(1, len(c))]
            v = [float(raw[day]["v"]) for day in axis[i - 20:i + 1]]
            intra = [float(raw[axis[j]]["c"]) / float(raw[axis[j]]["o"]) - 1 for j in range(i - 20, i + 1)]
            gaps = [float(split[axis[j]]["o"]) / float(split[axis[j - 1]]["c"]) - 1 for j in range(i - 20, i + 1)]
            sr = sret[i - 62:i + 1]
            rm, sm = statistics.fmean(r[-63:]), statistics.fmean(sr)
            covariance = math.fsum((a - rm) * (b - sm) for a, b in zip(r[-63:], sr)) / 63
            rv, sv = statistics.pvariance(r[-63:]), statistics.pvariance(sr)
            if rv <= 0 or sv <= 0:
                continue
            features = [c[-1] / c[-1 - n] - 1 for n in (5, 21, 63)]
            features += [statistics.pstdev(r[-21:]), statistics.pstdev(r[-63:]), c[-1] / max(c[-63:]) - 1,
                         math.log1p(v[-1]) - math.log1p(statistics.fmean(v)), intra[-1], gaps[-1],
                         spy[i] / spy[i - 21] - 1, spy[i] / spy[i - 63] - 1, statistics.pstdev(sret[i - 20:i + 1]),
                         covariance / sv, covariance / math.sqrt(rv * sv)]
            day, future = axis[i], axis[i + 1]
            result.append({"asset_id": identity["asset_id"], "ticker": symbol, "decision_date": day,
                           "target_date": future, "features": features,
                           "intraday": float(raw[future]["c"]) / float(raw[future]["o"]) - 1,
                           "price_gap": float(split[future]["o"]) / float(split[day]["c"]) - 1,
                           "intraday_scale": max(protocol["target_scale_floor"], statistics.pstdev(intra)),
                           "price_gap_scale": max(protocol["target_scale_floor"], statistics.pstdev(gaps))})
    return result


def metric_check(rows, expected):
    n = len(rows)
    require(n == expected["rows"] and len({r["target_date"] for r in rows}) == expected["target_dates"], "METRIC_AXIS")
    require(len({r["asset_id"] for r in rows}) == expected["assets"], "METRIC_ASSETS")
    loss = {}
    for method in ("zero", "historical_mean", "ridge"):
        loss[method] = [(r["actual"] - r[method]) ** 2 for r in rows]
        values = expected["methods"][method]
        close(statistics.fmean(loss[method]), values["mse"], "MSE")
        close(statistics.fmean(abs(r["actual"] - r[method]) for r in rows), values["mae"], "MAE")
        sign = lambda x: (x > 0) - (x < 0)
        close(statistics.fmean(sign(r["actual"]) == sign(r[method]) for r in rows), values["direction_accuracy"], "DIRECTION")
    for base in ("zero", "historical_mean"):
        skill = 1 - statistics.fmean(loss["ridge"]) / statistics.fmean(loss[base])
        close(skill, expected["methods"]["ridge"]["skill_vs_" + base], "SKILL")
        daily = defaultdict(list)
        for row, er, eb in zip(rows, loss["ridge"], loss[base]):
            daily[row["target_date"]].append(er - eb)
        values = [statistics.fmean(daily[day]) for day in sorted(daily)]
        mean, count = statistics.fmean(values), len(values)
        centered = [v - mean for v in values]
        variance = math.fsum(v * v for v in centered) / count
        for lag in range(1, min(5, count - 1) + 1):
            variance += 2 * (1 - lag / 6) * math.fsum(centered[j] * centered[j - lag] for j in range(lag, count)) / count
        check = expected["loss_difference_vs_" + base]
        close(mean, check["daily_mean_loss_difference"], "DAILY_LOSS")
        close(math.sqrt(max(variance, 0) / count), check["newey_west_standard_error"], "DEPENDENT_SE")
    close(statistics.fmean(r["lower80"] <= r["actual"] <= r["upper80"] for r in rows), expected["ridge_nominal80_coverage"], "INTERVAL_COVERAGE")
    pm, ym = statistics.fmean(r["ridge"] for r in rows), statistics.fmean(r["actual"] for r in rows)
    slope = math.fsum((r["ridge"] - pm) * (r["actual"] - ym) for r in rows) / math.fsum((r["ridge"] - pm) ** 2 for r in rows)
    close(slope, expected["ridge_calibration_slope"], "CALIBRATION")


def review(acquisition_root, output_root, protocol_path, cohort_path, destination):
    root, out = Path(acquisition_root), Path(output_root)
    protocol_raw = Path(protocol_path).read_bytes()
    protocol = json.loads(protocol_raw)
    acquisition = json.loads((root / "acquisition.json").read_bytes())
    require(acquisition["protocol_sha256"] == sha(protocol_raw), "PROTOCOL")
    require(acquisition["cohort_sha256"] == sha(Path(cohort_path).read_bytes()), "COHORT")
    require(acquisition["status"] == "COMPLETE" and acquisition["pagination_complete"], "COMPLETE_INPUT")
    direct = direct_rows(acquisition, root, protocol)
    lookup = {(r["asset_id"], r["target_date"]): r for r in direct}
    models = json.loads((out / "models.json").read_bytes())
    model_lookup = {}
    max_kkt = 0.0
    for evidence in models:
        model_id = evidence["model_sha256"]
        require(sha(encoded({k: v for k, v in evidence.items() if k != "model_sha256"})) == model_id, "MODEL_HASH")
        require(evidence["features"] == FIELDS and evidence["lambda"] == protocol["ridge_lambda"], "MODEL_SPECIFICATION")
        head, month = evidence["head"], evidence["month"]
        train = [r for r in direct if r["target_date"] < month + "-01"]
        require(len(train) == evidence["train_rows"] and len({r["target_date"] for r in train}) == evidence["train_target_dates"], "TRAINING_ROWS")
        require(max(r["target_date"] for r in train) == evidence["train_last_target"] < month + "-01", "TRAINING_CUTOFF")
        x = np.array([r["features"] for r in train])
        scales = np.array([r[head + "_scale"] for r in train])
        y = np.array([r[head] for r in train])
        m = evidence["model"]
        np.testing.assert_allclose(np.mean(x, axis=0), m["center"], rtol=1e-8, atol=1e-10)
        spread = np.std(x, axis=0)
        np.testing.assert_allclose(np.where(spread > 1e-12, spread, 1), m["spread"], rtol=1e-8, atol=1e-10)
        z, b = (x - np.array(m["center"])) / np.array(m["spread"]), np.array(m["beta"])
        fitted = z @ b + m["intercept"]
        residual = fitted - y / scales
        gradient = z.T @ residual / len(x) + evidence["lambda"] * b
        kkt = max(float(np.max(np.abs(gradient))), abs(float(residual.mean())))
        max_kkt = max(max_kkt, kkt)
        require(kkt < 1e-8, "RIDGE_OPTIMALITY")
        close(float(y.mean()), evidence["training_mean"], "TRAINING_MEAN")
        np.testing.assert_allclose(np.quantile(y - fitted * scales, [0.1, 0.9]), evidence["raw_residual_quantiles"], rtol=1e-8, atol=1e-10)
        model_lookup[model_id] = evidence
    predictions = [json.loads(line) for line in (out / "predictions.jsonl").read_bytes().splitlines()]
    seen = set()
    for row in predictions:
        key = row["head"], row["asset_id"], row["target_date"]
        require(key not in seen, "DUPLICATE_PREDICTION")
        seen.add(key)
        actual = lookup[(row["asset_id"], row["target_date"])]
        e = model_lookup[row["model_sha256"]]
        m, head = e["model"], row["head"]
        require(e["head"] == head and row["target_date"].startswith(e["month"]), "MODEL_HORIZON")
        require(row["ticker"] == actual["ticker"] and row["decision_date"] == actual["decision_date"], "ACTUAL_IDENTITY")
        require(row["train_last_target"] == e["train_last_target"] < e["month"] + "-01", "PREDICTION_CUTOFF")
        estimate = m["intercept"] + math.fsum((x - mu) / sd * beta for x, mu, sd, beta in
                                               zip(actual["features"], m["center"], m["spread"], m["beta"]))
        close(actual[head], row["actual"], "ACTUAL_PRICE_LABEL")
        close(actual[head + "_scale"], row["lagged_scale"], "CAUSAL_SCALE")
        close(estimate * actual[head + "_scale"], row["ridge"], "ACTUAL_PREDICTION", 1e-8)
        close(row["historical_mean"], e["training_mean"], "MEAN_COMPARATOR")
        close(row["lower80"], row["ridge"] + e["raw_residual_quantiles"][0], "LOWER_INTERVAL")
        close(row["upper80"], row["ridge"] + e["raw_residual_quantiles"][1], "UPPER_INTERVAL")
    expected = {(h, r["asset_id"], r["target_date"]) for r in direct if r["target_date"] >= protocol["test_start"] for h in ("intraday", "price_gap")}
    require(seen == expected, "COMPLETE_TEST_AXIS")
    metrics = json.loads((out / "metrics.json").read_bytes())
    blocks = 0
    for head, evidence in metrics["heads"].items():
        rows = [r for r in predictions if r["head"] == head]
        metric_check(rows, evidence["all"])
        blocks += 1
        for month, block in evidence["months"].items():
            metric_check([r for r in rows if r["target_date"].startswith(month)], block)
            blocks += 1
    result = {"schema": "research.numerical-forecast-independent-calculation-review/1", "status": "PASS",
              "reviewer": "separate calculation implementation by same agent; no external review claimed",
              "direct_feature_rows": len(direct), "prediction_rows": len(predictions), "models": len(models),
              "metric_blocks": blocks, "maximum_ridge_kkt_residual": max_kkt,
              "every_label_from_actual_provider_prices": True, "every_prediction_from_independent_features": True,
              "all_monthly_cutoffs_and_model_identities": True, "all_reported_metrics_recomputed": True,
              "protocol_sha256": sha(protocol_raw), "metrics_sha256": sha((out / "metrics.json").read_bytes()),
              "predictions_sha256": sha((out / "predictions.jsonl").read_bytes()), "production_contacted": False}
    with Path(destination).open("xb") as stream:
        stream.write(encoded(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for flag in ("acquisition", "output", "protocol", "cohort", "review"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.acquisition, args.output, args.protocol, args.cohort, args.review)))
