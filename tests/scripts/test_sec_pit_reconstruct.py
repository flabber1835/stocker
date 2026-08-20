from __future__ import annotations

import csv
import importlib.util
import io
import tempfile
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "sec_pit_reconstruct.py"
spec = importlib.util.spec_from_file_location("sec_pit_reconstruct", MODULE_PATH)
sec = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sec
assert spec.loader is not None
spec.loader.exec_module(sec)


def submission_tsv(rows):
    fields = [
        "ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE",
        "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL",
    ]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, dialect="excel-tab", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().encode("utf-8")


def write_archive(directory: Path, year: int, quarter: int, rows, *, member="SUBMISSION.tsv") -> Path:
    path = directory / f"{year}q{quarter}_form345.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, submission_tsv(rows))
        zf.writestr("REPORTINGOWNER.tsv", "ACCESSION_NUMBER\tRPTOWNERCIK\n")
    return path


def row(accession, filing_date, cik="1652044", symbol="GOOG", name="Alphabet Inc."):
    return {
        "ACCESSION_NUMBER": accession,
        "FILING_DATE": filing_date,
        "PERIOD_OF_REPORT": filing_date,
        "DOCUMENT_TYPE": "4",
        "ISSUERCIK": cik,
        "ISSUERNAME": name,
        "ISSUERTRADINGSYMBOL": symbol,
    }


class SecPitReconstructTests(unittest.TestCase):
    def test_quarter_sequence_and_gap_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_archive(root, 2006, 1, [row("A", "02-JAN-2006")])
            write_archive(root, 2006, 3, [row("B", "03-JUL-2006")])
            with self.assertRaises(sec.SecPitError) as ctx:
                sec.reconstruct(root, root / "out", sec.Quarter(2006, 1), sec.Quarter(2006, 3))
            self.assertIn("2006Q2", str(ctx.exception))

    def test_normalizes_as_filed_submission_and_retains_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_archive(root, 2025, 1, [
                row("0001652044-25-000001", "03-JAN-2025", symbol="goog"),
                row("0001652044-25-000002", "06-JAN-2025", symbol="GOOGL"),
            ], member="nested/SUBMISSION.tsv")
            coverage = sec.reconstruct(root, root / "out", sec.Quarter(2025, 1), sec.Quarter(2025, 1))
            self.assertEqual(coverage["archive_count"], 1)
            self.assertEqual(coverage["observation_count"], 2)
            self.assertTrue(coverage["alphabet_control"]["both_symbols_observed"])

            with (root / "out" / "observations.csv").open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["issuer_cik"], "0001652044")
            self.assertEqual(rows[0]["issuer_trading_symbol"], "GOOG")
            self.assertEqual(rows[0]["filing_date"], "2025-01-03")
            self.assertEqual(rows[0]["archive"], "2025q1_form345.zip")
            self.assertEqual(rows[0]["submission_member"], "nested/SUBMISSION.tsv")
            self.assertEqual(rows[0]["row_number"], "2")

    def test_duplicate_accession_refuses_even_if_rows_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_archive(root, 2025, 1, [row("DUP", "03-JAN-2025")])
            write_archive(root, 2025, 2, [row("DUP", "03-JAN-2025")])
            with self.assertRaises(sec.SecPitError) as ctx:
                sec.reconstruct(root, root / "out", sec.Quarter(2025, 1), sec.Quarter(2025, 2))
            self.assertIn("duplicate accession", str(ctx.exception))

    def test_conflicting_duplicate_accession_refuses_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_archive(root, 2025, 1, [row("DUP", "03-JAN-2025", symbol="GOOG")])
            write_archive(root, 2025, 2, [row("DUP", "03-JAN-2025", symbol="GOOGL")])
            with self.assertRaises(sec.SecPitError) as ctx:
                sec.reconstruct(root, root / "out", sec.Quarter(2025, 1), sec.Quarter(2025, 2))
            self.assertIn("conflicts across archives", str(ctx.exception))

    def test_missing_required_submission_field_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "2025q1_form345.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\nA\t03-JAN-2025\n")
            with self.assertRaises(sec.SecPitError) as ctx:
                sec.reconstruct(root, root / "out", sec.Quarter(2025, 1), sec.Quarter(2025, 1))
            self.assertIn("missing required fields", str(ctx.exception))

    def test_evidence_span_never_claims_pre_first_filing_validity(self):
        rows = [
            sec.Observation("2025-02-01", "0000000123", "X", "ABC", "A1", "4", "", "a.zip", "SUBMISSION.tsv", 2),
            sec.Observation("2025-03-01", "0000000123", "X", "ABC", "A2", "4", "", "b.zip", "SUBMISSION.tsv", 2),
        ]
        evidence = sec.build_symbol_cik_evidence(rows)
        self.assertEqual(evidence[0]["first_public_date"], "2025-02-01")
        self.assertEqual(evidence[0]["last_public_date"], "2025-03-01")
        self.assertNotIn("valid_from", evidence[0])


if __name__ == "__main__":
    unittest.main()
