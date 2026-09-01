import json
import tempfile
import unittest
import urllib.error
import zipfile
from email.message import Message
from pathlib import Path
from unittest import mock

from backtester import historical_metadata_reconstruction_v2 as hm


def write_gz(path: Path, fields, rows):
    hm.write_gzip_csv(path, fields, rows)


def write_candidate_file(root: Path, rows):
    path = root / "candidate_episodes.csv.gz"
    fields = [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks",
        "alias_symbol", "alias_safe",
    ]
    write_gz(path, fields, rows)
    return path


def write_bulk_dir(root: Path, identities=(), types=()):
    root.mkdir(parents=True, exist_ok=True)
    write_gz(root / "bulk_identity_sources.csv.gz", [
        "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind",
        "archive", "archive_sha256", "member", "member_sha256",
    ], identities)
    write_gz(root / "bulk_security_type_sources.csv.gz", [
        "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "security_title_evidence", "authority", "archive", "archive_sha256",
    ], types)


def write_sic(path: Path, rows):
    write_gz(path, ["filing_date", "cik", "sic"], rows)


class FakeResponse:
    def __init__(self, data=b"ok", status=200, headers=None):
        self.data = data
        self.status = status
        self.headers = headers or Message()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


class HistoricalMetadataV2Tests(unittest.TestCase):
    def test_validate_cik_and_issuer_authority_fail_closed(self):
        self.assertEqual(hm.validate_cik("12345"), "0000012345")
        self.assertEqual(hm.parse_issuer_authority("SEC_CIK:12345"), "0000012345")
        self.assertEqual(hm.parse_issuer_authority("SEC_UNKNOWN:247195603529201713"), "")
        self.assertEqual(hm.validate_cik("247195603529201713"), "")
        self.assertEqual(hm.validate_cik("CIK1234"), "")
        self.assertEqual(hm.validate_cik("0"), "")

    def test_vendor_alias_is_fail_closed_on_collision(self):
        rows = [
            hm.CandidateEpisode("1", "ABC1", "2007-01-01", "2007-12-31", 1, 1, 1, ()),
            hm.CandidateEpisode("2", "ABC2", "2008-01-01", "2008-12-31", 1, 1, 1, ()),
        ]
        marked = hm.mark_safe_aliases(rows)
        self.assertFalse(marked[0].alias_safe)
        self.assertFalse(marked[1].alias_safe)

    def test_ticker_reuse_remains_separate_by_security_episode(self):
        candidates = [
            hm.CandidateEpisode("sid1", "ABC", "2006-01-01", "2006-12-31", 1, 1, 1, ("0000000001",)),
            hm.CandidateEpisode("sid2", "ABC", "2008-01-01", "2008-12-31", 1, 1, 1, ("0000000002",)),
        ]
        rows = [
            {"accession": "a1", "filed": "2006-06-01", "cik": "0000000001", "sec_symbol": "ABC"},
            {"accession": "a2", "filed": "2008-06-01", "cik": "0000000002", "sec_symbol": "ABC"},
        ]
        allocated, ambiguous = hm.allocate_identity_events(candidates, rows)
        self.assertEqual({row["security_id"] for row in allocated}, {"sid1", "sid2"})
        self.assertEqual(ambiguous, [])

    def test_pre_identity_sic_uses_later_identity_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates = write_candidate_file(root, [{
                "security_id": "sid", "ticker": "ABC", "first_session": "2006-01-03",
                "last_session": "2006-12-31", "observations": 250,
                "unknown_type_observations": 250, "missing_sector_observations": 250,
                "observed_ciks": "0000000001", "alias_symbol": "", "alias_safe": "false",
            }])
            bulk = root / "bulk"
            write_bulk_dir(bulk, identities=[{
                "accession": "id1", "filed": "2006-03-01", "cik": "0000000001",
                "sec_symbol": "ABC", "document_type": "4", "source_kind": "bulk",
            }], types=[{
                "accession": "id1", "filed": "2006-03-01", "cik": "0000000001",
                "sec_symbol": "ABC", "document_type": "4", "classification": "common",
                "security_title_evidence": "Common Stock", "authority": "bulk",
            }])
            sic = root / "sic.csv.gz"
            write_sic(sic, [{"filing_date": "2006-01-15", "cik": "1", "sic": "3571"}])
            out = root / "timeline"
            hm.derive_timeline(candidates, bulk, sic, out)
            sics = hm.read_gzip_csv(out / "sic_events.csv.gz")
            self.assertEqual(len(sics), 1)
            self.assertEqual(sics[0]["filed"], "2006-01-15")
            self.assertEqual(sics[0]["usable_after"], "2006-03-01")

    def test_classification_conflict_is_unknown(self):
        classification, _ = hm.classify_titles(["Common Stock", "Series A Preferred Stock"])
        self.assertEqual(classification, "unknown")
        classification, _ = hm.classify_titles(["Employee Option to Purchase Common Stock"])
        self.assertEqual(classification, "non_common")

    def test_bulk_zip_parser_uses_submission_and_nonderivative_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sec = root / "sec"
            sec.mkdir()
            archive = sec / "2006q1_form345.zip"
            submission = (
                "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
                "0001-06-000001\t15-JAN-2006\t4\t1\tABC\n"
            ).encode()
            trans = (
                "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tSECURITY_TITLE\n"
                "0001-06-000001\t1\tCommon Stock\n"
            ).encode()
            holding = "ACCESSION_NUMBER\tNONDERIV_HOLDING_SK\tSECURITY_TITLE\n".encode()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("SUBMISSION.tsv", submission)
                zf.writestr("NONDERIV_TRANS.tsv", trans)
                zf.writestr("NONDERIV_HOLDING.tsv", holding)
            candidates = write_candidate_file(root, [{
                "security_id": "sid", "ticker": "ABC", "first_session": "2006-01-01",
                "last_session": "2006-12-31", "observations": 1,
                "unknown_type_observations": 1, "missing_sector_observations": 0,
                "observed_ciks": "", "alias_symbol": "", "alias_safe": "false",
            }])
            with mock.patch.object(hm, "expected_archive_names", return_value=[archive.name]):
                out = root / "bulk"
                result = hm.parse_bulk_archives(sec, candidates, out)
            self.assertEqual(result["identity_sources"], 1)
            types = hm.read_gzip_csv(out / "bulk_security_type_sources.csv.gz")
            self.assertEqual(types[0]["classification"], "common")
            self.assertEqual(types[0]["cik"], "0000000001")

    def test_expected_inventory_is_complete_2006q1_through_2026q2(self):
        names = hm.expected_archive_names()
        self.assertEqual(len(names), 82)
        self.assertEqual(names[0], "2006q1_form345.zip")
        self.assertEqual(names[-1], "2026q2_form345.zip")

    def test_404_is_terminal_and_not_retried(self):
        with tempfile.TemporaryDirectory() as td:
            headers = Message()
            error = urllib.error.HTTPError("https://x", 404, "not found", headers, None)
            with mock.patch("urllib.request.urlopen", side_effect=error) as urlopen, mock.patch("time.sleep") as sleep:
                client = hm.SecHttpTransport(Path(td), min_interval=0, max_attempts=5)
                data, result = client.get("https://x")
            self.assertIsNone(data)
            self.assertTrue(result.terminal_absence)
            self.assertEqual(urlopen.call_count, 1)
            sleep.assert_not_called()

    def test_429_honors_retry_then_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            headers = Message()
            headers["Retry-After"] = "0"
            error = urllib.error.HTTPError("https://x", 429, "slow", headers, None)
            with mock.patch("urllib.request.urlopen", side_effect=[error, FakeResponse(b"ok")]) as urlopen, mock.patch("time.sleep") as sleep:
                client = hm.SecHttpTransport(Path(td), min_interval=0, max_attempts=3)
                data, _ = client.get("https://x")
            self.assertEqual(data, b"ok")
            self.assertEqual(urlopen.call_count, 2)
            self.assertEqual(client.counters["retries"], 1)
            self.assertEqual(client.counters["throttle_retries"], 1)
            self.assertEqual(sleep.call_count, 1)

    def test_5xx_final_attempt_has_no_trailing_sleep(self):
        with tempfile.TemporaryDirectory() as td:
            headers = Message()
            first = urllib.error.HTTPError("https://x", 500, "bad", headers, None)
            final = urllib.error.HTTPError("https://x", 500, "bad", headers, None)
            with mock.patch("urllib.request.urlopen", side_effect=[first, final]), mock.patch("time.sleep") as sleep:
                client = hm.SecHttpTransport(Path(td), min_interval=0, max_attempts=2)
                with self.assertRaises(hm.ReconstructionError):
                    client.get("https://x")
            self.assertEqual(sleep.call_count, 1)

    def test_resume_rejects_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan.csv.gz"
            write_gz(plan, [
                "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type",
                "need_sic", "discovery_only_cik_hint", "first_session", "last_session",
            ], [])
            out = root / "out"
            out.mkdir()
            (out / "checkpoint.json").write_text(
                json.dumps({"identity": {"source_sha": "wrong"}, "completed_ciks": []}), encoding="utf-8"
            )
            with self.assertRaises(hm.ReconstructionError):
                hm.fetch_web_fallback(plan, out, "src", "canon", "cand", "parser", min_interval=0)

    def test_network_incompleteness_cannot_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan.csv.gz"
            write_gz(plan, [
                "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type",
                "need_sic", "discovery_only_cik_hint", "first_session", "last_session",
            ], [{
                "security_id": "sid", "ticker": "ABC", "alias_symbol": "", "cik": "0000000001",
                "need_identity": "true", "need_type": "true", "need_sic": "true",
                "discovery_only_cik_hint": "false", "first_session": "2006-01-01",
                "last_session": "2006-12-31",
            }])
            with mock.patch.object(
                hm, "_load_submission_history_retained", side_effect=hm.ReconstructionError("network")
            ):
                result = hm.fetch_web_fallback(
                    plan, root / "out", "src", "canon", "cand", "parser", min_interval=0
                )
            self.assertEqual(result["status"], "PARTIAL")
            self.assertFalse(result["complete"])

    def test_checkpoint_cache_hash_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan.csv.gz"
            fields = [
                "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type",
                "need_sic", "discovery_only_cik_hint", "first_session", "last_session",
            ]
            write_gz(plan, fields, [])
            out = root / "out"
            (out / ".http-cache").mkdir(parents=True)
            identity = hm.checkpoint_identity(
                "src", "canon", "cand", hm.sha256_file(plan), "parser"
            )
            (out / "checkpoint.json").write_text(json.dumps({
                "identity": identity, "completed_ciks": [], "cache_manifest_sha256": "deadbeef"
            }), encoding="utf-8")
            with self.assertRaises(hm.ReconstructionError):
                hm.fetch_web_fallback(plan, out, "src", "canon", "cand", "parser", min_interval=0)

    def test_normalized_evidence_hash_is_order_independent(self):
        rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
        first = hm.normalized_web_evidence_hash(rows, [], [])
        second = hm.normalized_web_evidence_hash(list(reversed(rows)), [], [])
        self.assertEqual(first, second)

    def test_cover_page_ambiguous_common_and_preferred_fails_closed(self):
        text = "Title of each class Common Stock and Preferred Stock Trading Symbol ABC"
        classification, _ = hm._web_cover_type(text, "ABC")
        self.assertEqual(classification, "unknown")

    def test_cover_page_ticker_proof_requires_trading_symbol_context(self):
        self.assertTrue(
            hm._cover_ticker_evidence("Title of each class Common Stock Trading Symbol ABC", "ABC")
        )
        self.assertFalse(hm._cover_ticker_evidence("ABC appears in narrative only", "ABC"))


if __name__ == "__main__":
    unittest.main()
