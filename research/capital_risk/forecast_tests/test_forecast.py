"""Synthetic-only tests; no financial book or provider credentials."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forecast_baseline as baseline
import forecast_collect as collector
import forecast_review as reviewer

PROTOCOL = json.loads((Path(__file__).resolve().parents[1] / "forecast-protocol.json").read_text())


def fake_matrix():
    axis = pd.bdate_range("2024-01-02", "2026-03-31").strftime("%Y-%m-%d").tolist()
    rng = np.random.default_rng(8401)
    result = pd.DataFrame(rng.normal(size=(len(axis), len(baseline.FEATURES))), columns=baseline.FEATURES)
    result["target_date"] = axis
    result["decision_date"] = pd.Series(axis).shift(1).fillna("2024-01-01")
    result["intraday_y"] = result.momentum5 * 0.001 + rng.normal(0, 0.01, len(axis))
    result["price_gap_y"] = rng.normal(0, 0.006, len(axis))
    result["intraday_scale"], result["price_gap_scale"] = 0.01, 0.006
    result["asset_id"], result["ticker"] = "synthetic-only", "SYNTHETIC"
    return result


def fake_bars():
    axis = pd.bdate_range("2024-01-02", periods=300).strftime("%Y-%m-%d").tolist()
    rng = np.random.default_rng(8411)
    frames = {"raw": {}, "split": {}}
    for ticker in ("SPY", "SYNTHETIC"):
        price = 100.0
        series = {}
        for day in axis:
            op = price * (1 + rng.normal(0, 0.004))
            price = op * (1 + rng.normal(0, 0.008))
            series[day] = dict(o=op, c=price, h=max(op, price) * 1.01,
                               l=min(op, price) * 0.99, v=100000 + rng.integers(10000))
        for kind in frames:
            frames[kind][ticker] = copy.deepcopy(series)
    return frames, [{"ticker": "SYNTHETIC", "asset_id": "synthetic-id"}], axis


class NumericalTests(unittest.TestCase):
    def test_synthetic_precision_example_and_material_falsifier(self):
        raw = dict(o=2.30, h=2.50, l=2.20, c=2.2997)
        adjusted = dict(o=46.00, h=50.00, l=44.00, c=45.99)
        self.assertTrue(baseline.common_price_scale(raw, adjusted))
        self.assertFalse(baseline.common_price_scale(raw, {**adjusted, "c": 46.10}))

    def test_ridge_constant_response_is_intercept(self):
        x = np.arange(80, dtype=float).reshape(40, 2)
        model = baseline.fit_ridge(x, np.full(40, 0.25), 1)
        np.testing.assert_allclose(baseline.predict(model, x), 0.25)
        np.testing.assert_allclose(model["beta"], 0)

    def test_ridge_mean_loss_normalization(self):
        x = np.array([[-1.0], [1.0]])
        model = baseline.fit_ridge(x, x[:, 0], 1)
        self.assertAlmostEqual(model["beta"][0], 0.5)

    def test_nonfinite_input_refuses(self):
        with self.assertRaisesRegex(ValueError, "RIDGE_INPUT"):
            baseline.fit_ridge(np.array([[float("nan")]]), np.array([1.0]), 1)

    def test_future_label_is_not_training(self):
        data = fake_matrix()
        train, test = baseline.month_partition(data, "2026-01")
        self.assertLess(train.target_date.max(), "2026-01-01")
        self.assertTrue(test.target_date.str.startswith("2026-01").all())
        self.assertFalse(set(train.index) & set(test.index))

    def test_future_mutation_cannot_change_prior_fit_or_forecast(self):
        original = fake_matrix()
        altered = original.copy()
        future = altered.target_date >= "2026-02-01"
        altered.loc[future, baseline.FEATURES] += 900
        altered.loc[future, ["intraday_y", "price_gap_y"]] += 2
        rows_a, models_a = baseline.walk_forward(original, PROTOCOL)
        rows_b, models_b = baseline.walk_forward(altered, PROTOCOL)
        self.assertEqual([m for m in models_a if m["month"] == "2026-01"],
                         [m for m in models_b if m["month"] == "2026-01"])
        self.assertEqual([r for r in rows_a if r["target_date"] < "2026-02-01"],
                         [r for r in rows_b if r["target_date"] < "2026-02-01"])

    def test_future_prices_cannot_change_prior_features(self):
        frames, admitted, axis = fake_bars()
        before, _ = baseline.feature_matrix(frames, admitted, axis, PROTOCOL)
        altered = copy.deepcopy(frames)
        for kind in altered:
            for ticker in altered[kind]:
                for day in axis[220:]:
                    for field in ("o", "h", "l", "c"):
                        altered[kind][ticker][day][field] *= 8
        after, _ = baseline.feature_matrix(altered, admitted, axis, PROTOCOL)
        fields = baseline.FEATURES + ["decision_date", "asset_id"]
        pd.testing.assert_frame_equal(before.loc[before.decision_date < axis[220], fields],
                                      after.loc[after.decision_date < axis[220], fields])

    def test_missing_session_cannot_become_next_available_label(self):
        frames, admitted, axis = fake_bars()
        for kind in frames:
            del frames[kind]["SYNTHETIC"][axis[150]]
        matrix, _ = baseline.feature_matrix(frames, admitted, axis, PROTOCOL)
        self.assertNotIn(axis[149], set(matrix.decision_date))
        self.assertNotIn(axis[151], set(matrix.target_date))
        self.assertFalse(matrix.decision_date.between(axis[150], axis[276]).any())

    def test_skill_formula_and_nominal_interval(self):
        rows = [{"actual": y, "ridge": y / 2, "zero": 0, "historical_mean": 0,
                 "target_date": f"2026-01-{i+1:02d}", "asset_id": "synthetic",
                 "lower80": -3, "upper80": 3} for i, y in enumerate((-2, -1, 1, 2))]
        block = baseline.metric_block(rows)
        self.assertAlmostEqual(block["methods"]["ridge"]["skill_vs_zero"], 0.75)
        self.assertEqual(block["ridge_nominal80_coverage"], 1)
        self.assertAlmostEqual(block["ridge_calibration_slope"], 2)

    def test_daily_dependence_is_not_row_independence(self):
        result = baseline.nw_mean_se([1, 1, 1, 1, 1], 5)
        self.assertEqual(result["days"], 5)
        self.assertEqual(result["newey_west_standard_error"], 0)

    def test_independent_reviewer_detects_economic_mutation(self):
        rows = [{"actual": y, "ridge": y / 2, "zero": 0, "historical_mean": 0,
                 "target_date": f"2026-01-{i+1:02d}", "asset_id": "synthetic",
                 "lower80": -3, "upper80": 3} for i, y in enumerate((-2, -1, 1, 2))]
        expected = baseline.metric_block(rows)
        reviewer.metric_check(rows, expected)
        corrupted = copy.deepcopy(rows)
        corrupted[0]["actual"] += 0.1
        with self.assertRaisesRegex(ValueError, "REVIEW_MSE"):
            reviewer.metric_check(corrupted, expected)


class BoundaryTests(unittest.TestCase):
    def test_account_route_refuses_before_network(self):
        with tempfile.TemporaryDirectory() as root:
            client = collector.Client(root, {})
            with self.assertRaisesRegex(ValueError, "ENDPOINT_OR_METHOD"):
                client.call("https://paper-api.alpaca.markets/v2/account")

    def test_wrong_http_method_refuses_before_network(self):
        with tempfile.TemporaryDirectory() as root:
            client = collector.Client(root, {})
            with self.assertRaisesRegex(ValueError, "ENDPOINT_OR_METHOD"):
                client.call(collector.BARS, body={"bad": "method"})

    def test_named_provider_keys_only(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "synthetic.env"
            path.write_text("OTHER_SECRET=never-export\nexport ALPACA_API_KEY='synthetic-key'\nALPACA_SECRET_KEY=synthetic-secret # comment\n")
            self.assertEqual(collector.provider_keys(path), {"ALPACA_API_KEY": "synthetic-key", "ALPACA_SECRET_KEY": "synthetic-secret"})

    def test_duplicate_or_interpolated_key_refuses(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "synthetic.env"
            path.write_text("ALPACA_API_KEY=$OTHER_SECRET\nALPACA_SECRET_KEY=synthetic\n")
            with self.assertRaisesRegex(ValueError, "KEY_FORMAT"):
                collector.provider_keys(path)

    def test_figi_ambiguity_refuses(self):
        row = dict(marketSector="Equity", exchCode="US", ticker="SYNTHETIC", securityType="Common Stock",
                   compositeFIGI="FIGI-SYNTHETIC-A", shareClassFIGI="FIGI-SYNTHETIC-B")
        self.assertIsNotNone(collector.figi_identity("SYNTHETIC", {"data": [row]}))
        changed = {**row, "compositeFIGI": "FIGI-SYNTHETIC-C"}
        self.assertIsNone(collector.figi_identity("SYNTHETIC", {"data": [row, changed]}))
        self.assertIsNone(collector.figi_identity("OTHER", {"data": [row]}))

    def test_cohort_protocol_is_frozen(self):
        self.assertEqual(PROTOCOL["providers"], ["ALPACA", "OPENFIGI_FREE"])
        self.assertEqual(PROTOCOL["cohort_size"], 64)
        self.assertEqual(PROTOCOL["ridge_lambda"], 1)


if __name__ == "__main__":
    unittest.main()
