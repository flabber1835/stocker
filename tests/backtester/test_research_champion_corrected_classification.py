import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backtester import research_champion_best_effort_classification as base
from backtester import research_champion_corrected_classification as corrected


class CorrectedClassificationTests(unittest.TestCase):
    def test_pds_trust_to_corporation_boundary(self):
        value = corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18")
        self.assertEqual(value.classify("594891209465982980", "2010-06-01"), "non_common")
        self.assertEqual(value.classify("594891209465982980", "2010-06-02"), "common")

    def test_eqm_common_units_are_non_common(self):
        value = corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18")
        self.assertEqual(value.classify("192545371416014112", "2014-05-14"), "non_common")

    def test_correction_precedes_reviewed_and_inferred_classification(self):
        value = corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18")
        self.assertEqual(value.peek("594891209465982980", "2009-01-02"), "non_common")
        self.assertEqual(value.peek("192545371416014112", "2019-01-02"), "non_common")
        self.assertEqual(value.peek("804009952146469650", "2019-01-02"), "common")

    def test_provenance_distinguishes_authority_from_inference(self):
        value = corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18")
        pds = value.provenance("594891209465982980", "2010-06-02")
        self.assertEqual(pds["source_status"], "AUTHORITATIVE_HISTORICAL")
        self.assertEqual(pds["evidence_published_date"], "2010-06-01")
        self.assertEqual(pds["evidence_available_from"], "2010-06-01")
        inferred = value.provenance("804009952146469650", "2019-01-02")
        self.assertNotEqual(inferred["source_status"], "AUTHORITATIVE_HISTORICAL")

    def test_outside_admitted_interval_fails_closed(self):
        value = corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18")
        with self.assertRaisesRegex(RuntimeError, "outside admitted interval"):
            value.classify("594891209465982980", "2016-01-04")

    def test_unsupported_historical_extrapolation_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "corrections.csv"
            fields = [
                "security_id", "ticker", "classification", "effective_first_session", "effective_last_session",
                "evidence_published_date", "evidence_available_from", "evidence_kind", "evidence_url",
                "evidence_summary", "authority_status", "correction_reason",
            ]
            rows = [
                {
                    "security_id": "594891209465982980", "ticker": "PDS", "classification": "common",
                    "effective_first_session": "2010-06-02", "effective_last_session": "2015-06-04",
                    "evidence_published_date": "2010-06-01", "evidence_available_from": "2010-06-01",
                    "evidence_kind": "TEST", "evidence_url": "https://example.invalid/pds",
                    "evidence_summary": "test", "authority_status": "AUTHORITATIVE_HISTORICAL",
                    "correction_reason": "test",
                },
                {
                    "security_id": "192545371416014112", "ticker": "EQM", "classification": "non_common",
                    "effective_first_session": "2013-07-17", "effective_last_session": "2020-06-16",
                    "evidence_published_date": "2012-06-26", "evidence_available_from": "2012-06-26",
                    "evidence_kind": "TEST", "evidence_url": "https://example.invalid/eqm",
                    "evidence_summary": "test", "authority_status": "AUTHORITATIVE_HISTORICAL",
                    "correction_reason": "test",
                },
                {
                    "security_id": "594891209465982980", "ticker": "PDS", "classification": "common",
                    "effective_first_session": "2015-06-04", "effective_last_session": "2015-06-04",
                    "evidence_published_date": "2010-06-01", "evidence_available_from": "2010-06-01",
                    "evidence_kind": "TEST", "evidence_url": "https://example.invalid/pds2",
                    "evidence_summary": "test", "authority_status": "AUTHORITATIVE_HISTORICAL",
                    "correction_reason": "test",
                },
            ]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            digest = base._sha256(path)
            with patch.object(corrected, "CORRECTION_LEDGER_SHA256", digest):
                with self.assertRaisesRegex(RuntimeError, "does not cover full admitted interval"):
                    corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18", correction_ledger=path)

    def test_summary_records_correction_authority_and_calls(self):
        value = corrected.SecurityTypeEstimate(base.DEFAULT_LEDGER, "reviewed_18")
        value.classify("594891209465982980", "2010-06-02")
        result = value.summary()
        self.assertEqual(result["scenario"], corrected.CORRECTED_SCENARIO)
        self.assertEqual(result["historical_correction_calls"]["common"], 1)
        self.assertFalse(result["certification_eligible"])


if __name__ == "__main__":
    unittest.main()
