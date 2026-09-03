import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "pit_russell_archive_probe.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_archive_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class RussellArchiveProbeTests(unittest.TestCase):
    def capture(self, timestamp, digest, original="http://www.russell.com/list.pdf", query="q"):
        return probe.Capture(
            query_url=query,
            timestamp=timestamp,
            original=original,
            statuscode="200",
            mimetype="application/pdf",
            digest=digest,
            reported_length="123",
        )

    def test_build_cdx_url_is_bounded_and_collapses_digest(self):
        url = probe.build_cdx_url("http://example.test/file.pdf", 2006, 2008)
        self.assertIn("from=2006", url)
        self.assertIn("to=2008", url)
        self.assertIn("collapse=digest", url)
        self.assertIn("statuscode%3A200", url)

    def test_parse_cdx_payload(self):
        payload = json.dumps(
            [
                list(probe.CDX_FIELDS),
                [
                    "20070629120000",
                    "http://www.russell.com/list.pdf",
                    "200",
                    "application/pdf",
                    "ABC",
                    "1000",
                ],
            ]
        ).encode()
        rows = probe.parse_cdx_payload("query", payload)
        self.assertEqual(1, len(rows))
        self.assertEqual(2007, rows[0].year)
        self.assertEqual("ABC", rows[0].digest)
        self.assertIn("20070629120000id_", rows[0].raw_archive_url)

    def test_dedupe_overlapping_queries(self):
        a = self.capture("20070629120000", "ABC", query="http")
        b = self.capture("20070629120000", "ABC", query="wildcard")
        rows = probe.dedupe_captures([a, b])
        self.assertEqual(1, len(rows))

    def test_choose_downloads_prefers_reconstitution_window(self):
        rows = [
            self.capture("20070102000000", "JAN"),
            self.capture("20070629120000", "JUNE"),
            self.capture("20071201000000", "DEC"),
        ]
        selected = probe.choose_downloads(rows, 2007, 2007, 1)
        self.assertEqual("JUNE", selected[0].digest)

    def test_choose_downloads_limits_unique_digests(self):
        rows = [
            self.capture("20070625120000", "A"),
            self.capture("20070626120000", "A"),
            self.capture("20070627120000", "B"),
            self.capture("20070628120000", "C"),
        ]
        selected = probe.choose_downloads(rows, 2007, 2007, 2)
        self.assertEqual(2, len(selected))
        self.assertEqual(2, len({row.digest for row in selected}))

    def test_summary_distinguishes_capture_from_recoverable_pdf(self):
        capture = self.capture("20080630120000", "A")
        download = probe.DownloadEvidence(
            query_url=capture.query_url,
            timestamp=capture.timestamp,
            original=capture.original,
            raw_archive_url=capture.raw_archive_url,
            cdx_statuscode="200",
            cdx_mimetype="application/pdf",
            cdx_digest="A",
            cdx_reported_length="123",
            fetch_ok=True,
            http_status=200,
            response_content_type="application/pdf",
            byte_length=100,
            sha256="f" * 64,
            pdf_signature=True,
            error=None,
        )
        summary = probe.summarize([capture], [download], 2008, 2008)
        self.assertEqual("RECOVERABLE_PDF", summary["years"][0]["status"])
        self.assertEqual(1, summary["totals"]["pdf_payloads"])


if __name__ == "__main__":
    unittest.main()
