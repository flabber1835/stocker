"""Unit and source-contract tests for retained-research causal certification."""
from __future__ import annotations

from collections import defaultdict
import gzip
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from backtester.research_causal_instrumentation import (
    instrument_research_source,
    static_leakage_audit,
)
from backtester.research_causal_runtime import (
    CausalAccessError,
    CausalPITDataset,
    CausalSessionGuard,
    CausalTrace,
    GuardedSessionMap,
)
from backtester.run_research_causal_single import _inject_poison_dtype_compat


class ResearchCausalRuntimeTests(unittest.TestCase):
    def test_guard_rejects_future_metadata(self) -> None:
        guard = CausalSessionGuard(("2006-01-03", "2006-01-04"), mode="baseline", cutoff=None)
        guard.begin("2006-01-03", 0)
        with self.assertRaises(CausalAccessError):
            guard.assert_asof(
                domain="metadata",
                requested_session="2006-01-03",
                source_session="2006-01-04",
            )

    def test_guard_rejects_same_session_close_fill(self) -> None:
        guard = CausalSessionGuard(("2006-01-03",), mode="baseline", cutoff=None)
        guard.begin("2006-01-03", 0)
        with self.assertRaises(CausalAccessError):
            guard.assert_fill_after_signal(
                kind="buy",
                signal_index=0,
                fill_index=0,
                security_id="SID",
            )

    def test_guard_accepts_only_chronological_session_groups(self) -> None:
        guard = CausalSessionGuard(("2006-01-03", "2006-01-04"), mode="baseline", cutoff=None)
        guard.begin("2006-01-03", 0)
        guard.assert_observation_group(pd.DataFrame({"date": ["2006-01-03"]}), "2006-01-03")
        with self.assertRaises(CausalAccessError):
            guard.begin("2006-01-04", 2)

    def test_guarded_session_map_rejects_other_dates(self) -> None:
        guard = CausalSessionGuard(("2006-01-03",), mode="baseline", cutoff=None)
        values = GuardedSessionMap(
            guard,
            "corporate_actions",
            {pd.Timestamp("2006-01-03"): {"X": []}, pd.Timestamp("2006-01-04"): {}},
        )
        guard.begin("2006-01-03", 0)
        self.assertEqual(values.get(pd.Timestamp("2006-01-03")), {"X": []})
        with self.assertRaises(CausalAccessError):
            values.get(pd.Timestamp("2006-01-04"))

    def test_trace_bytes_do_not_encode_view_identity(self) -> None:
        class Dataset:
            dataset_hash = "hash"
            mode = "baseline"
            cutoff = None
            manifest = {"dataset_id": "dataset"}

            def poison_manifest(self):
                return {"mode": self.mode, "cutoff": self.cutoff, "changed_rows": {}}

        with tempfile.TemporaryDirectory() as td:
            paths = []
            for mode, cutoff in (("baseline", None), ("prefix", "2006-01-03")):
                dataset = Dataset()
                dataset.mode = mode
                dataset.cutoff = cutoff
                guard = CausalSessionGuard(("2006-01-03",), mode=mode, cutoff=cutoff)
                guard.begin("2006-01-03", 0)
                path = Path(td) / f"{mode}.jsonl.gz"
                with mock.patch.dict(
                    os.environ,
                    {"CAUSAL_GUARD_REPORT_PATH": str(Path(td) / f"{mode}.json")},
                ):
                    trace = CausalTrace(path, guard, dataset)
                    trace.emit({"date": "2006-01-03", "value": 1.25})
                    trace.close()
                paths.append(path)
            with gzip.open(paths[0], "rb") as left, gzip.open(paths[1], "rb") as right:
                self.assertEqual(left.read(), right.read())

    def test_future_poison_preserves_prefix_and_structural_validity(self) -> None:
        dataset = CausalPITDataset.__new__(CausalPITDataset)
        dataset.mode = "poison"
        dataset.cutoff = "2006-01-03"
        dataset.poison_seed = 7
        dataset._poison_counts = defaultdict(int)
        frame = pd.DataFrame(
            {
                "session": ["2006-01-03", "2006-01-04"],
                "security_id": ["A", "A"],
                "ticker": ["AAA", "AAA"],
                "issuer_id": ["I", "I"],
                "issuer_source": ["S", "S"],
                "security_type": ["common", "common"],
                "security_type_source": ["S", "S"],
                "security_type_eligible": [True, True],
                "sic": ["1000", "1000"],
                "ff12": ["1", "1"],
                "sector_source": ["S", "S"],
                "listing_active": [True, True],
                "raw_open": [10.0, 10.0],
                "raw_close": [10.0, 10.0],
                "signal_close": [10.0, 10.0],
                "reported_volume": [100.0, 100.0],
                "raw_compatible_volume": [100.0, 100.0],
                "split_ratio": [1.0, 2.0],
                "dividend_per_share": [0.0, 0.5],
                "tradeable": [True, True],
                "metadata_admitted": [True, True],
                "identity_source": ["S", "S"],
            }
        )
        poisoned = dataset._poison_observations(frame)
        pd.testing.assert_series_equal(poisoned.iloc[0], frame.iloc[0], check_names=False)
        for column in (
            "raw_open",
            "raw_close",
            "signal_close",
            "reported_volume",
            "raw_compatible_volume",
            "split_ratio",
        ):
            self.assertTrue(np.isfinite(float(poisoned.iloc[1][column])))
            self.assertGreater(float(poisoned.iloc[1][column]), 0.0)
        self.assertNotEqual(float(poisoned.iloc[1]["raw_close"]), 10.0)
        self.assertEqual(dataset._poison_counts["price_rows"], 1)
        self.assertEqual(dataset._poison_counts["eligibility_rows"], 1)

    def test_static_audit_rejects_known_leakage_constructs(self) -> None:
        source = """
import pandas as pd
x = pd.Series([1, 2, 3])
a = x.shift(-1)
b = x.rolling(3, center=True).mean()
c = x.bfill()
"""
        audit = static_leakage_audit(source)
        self.assertEqual(audit["status"], "FAIL")
        constructs = {
            row["construct"]
            for row in audit["findings"]
            if row["classification"] == "FORBIDDEN"
        }
        self.assertIn("negative_shift", constructs)
        self.assertIn("centered_rolling", constructs)
        self.assertIn("backward_fill", constructs)

    def test_final_generated_source_is_instrumented_and_compiles(self) -> None:
        from backtester import run_research_strict_pit_20y as replay

        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
            os.environ,
            {
                "CANONICAL_PIT_DATASET": str(Path(td) / "canonical"),
                "CERTIFICATION_END_SESSION": "2007-12-31",
            },
        ):
            source = replay.corrected.transformed_source("fullpit", Path(td) / "out")
            instrumented = instrument_research_source(source)
        self.assertIn("_CANONICAL=CausalPITDataset(", instrumented)
        self.assertIn("_GUARD.begin(ds,gday)", instrumented)
        self.assertIn("STOP_PRECEDENCE", instrumented)
        self.assertIn("assert_fill_after_signal", instrumented)
        self.assertIn("assert_entry_basis", instrumented)
        self.assertIn("trace.emit(", instrumented)
        self.assertIn("s.entry_sig=float(opsig[tid])", instrumented)
        self.assertNotIn("s.entry_sig=float(clsig[tid])", instrumented)
        compile(instrumented, "<causal-research>", "exec")
        audit = static_leakage_audit(instrumented)
        self.assertEqual(audit["status"], "PASS", audit)

        poison_source = _inject_poison_dtype_compat(instrumented)
        self.assertIn("_causal_dtype_safe_poison_observations", poison_source)
        self.assertIn("frame[_causal_bool_column].astype(bool)", poison_source)
        compile(poison_source, "<causal-research-poison>", "exec")


if __name__ == "__main__":
    unittest.main()
