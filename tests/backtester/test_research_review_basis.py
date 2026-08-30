"""Regression checks for the retained-research age-119 review basis."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from backtester import run_research_ldrc_nonpit_vs_fullpit as research


class ResearchReviewBasisTest(unittest.TestCase):
    def test_transform_records_adjusted_execution_open_and_never_entry_close(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            text = research.transformed_source("fullpit", Path(td) / "out")

        self.assertIn("opraw[tids]=rawop; opsig[tids]=oo; clsig[tids]=c", text)
        self.assertIn("s.entry_sig=float(opsig[tid])", text)
        self.assertIn("if finite(px) and px>0: s.peak=float(px)", text)
        self.assertNotIn("s.entry_sig=float(clsig[tid])", text)
        self.assertNotIn("s.peak=float(px); s.entry_sig=float(px)", text)
        compile(text, "<generated-research-replay>", "exec")

    def test_strict_canonical_transform_preserves_review_basis_contract(self) -> None:
        from backtester import run_research_strict_pit_certification as strict

        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
            os.environ, {"CANONICAL_PIT_DATASET": str(Path(td) / "canonical")}
        ):
            text = strict.old.transformed_source("fullpit", Path(td) / "out")

        self.assertIn(
            "d['open']=d['canonical_raw_open'].astype(float)*d['close'].astype(float)/d['closeunadj'].astype(float)",
            text,
        )
        self.assertIn("opraw[tids]=rawop; opsig[tids]=oo; clsig[tids]=c", text)
        self.assertIn("s.entry_sig=float(opsig[tid])", text)
        self.assertNotIn("s.entry_sig=float(clsig[tid])", text)
        self.assertNotIn("s.peak=float(px); s.entry_sig=float(px)", text)
        compile(text, "<generated-strict-research-replay>", "exec")


if __name__ == "__main__":
    unittest.main()
