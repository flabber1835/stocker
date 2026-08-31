from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from backtester.compiled_pit_research import _FeatureState, CompiledYear


class FeatureStateTests(unittest.TestCase):
    def test_future_mutation_cannot_change_prefix_features(self):
        prefix = []
        for day in range(150):
            tids = np.array([0, 1], dtype=np.int32)
            close = np.array([100.0 + day * 0.1, 50.0 + day * 0.05])
            volume = np.array([1_000_000.0 + day, 2_000_000.0 + day])
            prefix.append((tids, close, volume))

        left = _FeatureState(2)
        right = _FeatureState(2)
        for tids, close, volume in prefix:
            a = left.step(tids, close, volume)
            b = right.step(tids, close, volume)
            for key in a:
                np.testing.assert_array_equal(a[key], b[key])

        left.step(np.array([0, 1], np.int32), np.array([116.0, 58.0]), np.array([1e6, 2e6]))
        right.step(np.array([0, 1], np.int32), np.array([1000.0, 1.0]), np.array([9e9, 1.0]))
        self.assertEqual(left.gday, right.gday)

    def test_missing_security_is_session_causal(self):
        state = _FeatureState(2)
        for day in range(130):
            if day == 63:
                tids = np.array([0], dtype=np.int32)
                close = np.array([106.3])
                volume = np.array([1_000_000.0])
            else:
                tids = np.array([0, 1], dtype=np.int32)
                close = np.array([100.0 + day * 0.1, 50.0 + day * 0.1])
                volume = np.full(len(tids), 1_000_000.0)
            result = state.step(tids, close, volume)
        self.assertTrue(np.isfinite(result["recent"][0]))


class CompiledYearTests(unittest.TestCase):
    def test_year_groups_preserve_offsets_and_end_clipping(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "research-2006.npz"
            sessions = np.array([
                np.datetime64("2006-01-03", "ns").astype(np.int64),
                np.datetime64("2006-01-04", "ns").astype(np.int64),
            ], dtype=np.int64)
            offsets = np.array([0, 2, 3], dtype=np.int64)
            row_count = 3
            payload = {
                "session_ns": sessions,
                "offsets": offsets,
                "tid": np.array([0, 1, 0], dtype=np.int32),
                "close": np.array([1.0, 2.0, 1.1]),
                "closeunadj": np.array([1.0, 2.0, 1.1]),
                "open": np.array([1.0, 2.0, 1.1]),
                "volume": np.ones(row_count),
                "dividend_per_share": np.zeros(row_count),
                "split_ratio": np.ones(row_count),
                "recent": np.full(row_count, np.nan),
                "mom": np.full(row_count, np.nan),
                "r63": np.full(row_count, np.nan),
                "score": np.full(row_count, np.nan),
                "adv": np.full(row_count, np.nan),
                "fvol": np.full(row_count, np.nan),
                "day_dv": np.ones(row_count),
                "continuous": np.zeros(row_count, dtype=bool),
                "security_type_code": np.ones(row_count, dtype=np.int8),
            }
            np.savez_compressed(path, **payload)
            year = CompiledYear(path, end="2006-01-03")
            self.assertEqual(len(year), 2)
            groups = list(year.groupby("date", sort=True))
            self.assertEqual(len(groups), 1)
            np.testing.assert_array_equal(groups[0][1].tid.to_numpy(np.int32), np.array([0, 1], np.int32))


class TransformTests(unittest.TestCase):
    def test_fast_transform_removes_slow_feature_and_classification_loops(self):
        os.environ["COMPILED_PIT_RESEARCH_DATASET"] = "/tmp/compiled-pit-transform-selftest"
        import backtester.run_research_strict_pit_20y_fast as fast

        text = fast._fast_transform("fullpit", Path("/tmp/out"))
        self.assertIn("_FAST_TAPE.year(y,end=str(END.date()))", text)
        self.assertIn("security_type_code.to_numpy", text)
        self.assertNotIn("_CANONICAL.research_observations(y)", text)
        self.assertNotIn("close_ring[(gday-21)", text)
        self.assertNotIn("common_key(int(t)", text)


if __name__ == "__main__":
    unittest.main()
