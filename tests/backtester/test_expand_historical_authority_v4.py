from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path

from backtester.expand_historical_authority_v4 import (
    analyze_filing,
    build_discovery_url,
    build_plan,
    display_name_matches_ticker,
    parse_efts,
)


def _write_inventory(path: Path) -> None:
    fields = [
        "security_id", "ticker", "first_session", "last_session", "bucket",
        "type_unresolved", "type_first", "sector_unresolved", "sector_first",
        "issuer_unresolved",
    ]
    rows = [
        {
            "security_id": "1", "ticker": "LYG", "first_session": "2006-01-03",
            "last_session": "2026-07-31", "bucket": "TYPE_AND_SECTOR",
            "type_unresolved": "5176", "type_first": "2006-01-03",
            "sector_unresolved": "5176", "sector_first": "2006-01-03",
            "issuer_unresolved": "5176",
        },
        {
            "security_id": "2", "ticker": "DB", "first_session": "2006-01-03",
            "last_session": "2026-07-31", "bucket": "TYPE_AND_SECTOR",
            "type_unresolved": "4201", "type_first": "2009-07-06",
            "sector_unresolved": "881", "sector_first": "2006-01-03",
            "issuer_unresolved": "881",
        },
    ]
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _read_csv_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_v4_plan_uses_earliest_unresolved_observation_and_strict_prior_end(tmp_path: Path):
    inventory = tmp_path / "unresolved.csv.gz"
    output = tmp_path / "plan"
    _write_inventory(inventory)
    summary = build_plan(inventory, output, limit=2, include_tickers=["LYG"])
    rows = {row["ticker"]: row for row in _read_csv_gz(output / "plan.csv.gz")}

    assert summary["status"] == "PASS"
    assert summary["planned_rows"] == 2
    assert rows["LYG"]["authority_before"] == "2006-01-03"
    assert rows["LYG"]["search_end"] == "2006-01-02"
    assert rows["DB"]["authority_before"] == "2006-01-03"
    assert rows["DB"]["search_end"] == "2006-01-02"
    assert rows["LYG"]["search_start"] == "2001-01-01"
    assert (output / "SHA256SUMS.txt").is_file()


def test_efts_parser_and_display_ticker_match_are_discovery_only():
    payload = json.dumps({
        "timed_out": False,
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [{
                "_id": "0000950117-05-002637:a40046.htm",
                "_source": {
                    "ciks": ["0001160106"],
                    "display_names": ["Lloyds TSB Group plc (LYG) (CIK 0001160106)"],
                    "form": "20-F",
                    "file_date": "2005-03-31",
                    "adsh": "0000950117-05-002637",
                },
            }],
        },
    }).encode()
    total, hits = parse_efts(payload)
    assert total == 1
    assert hits[0]["ciks"] == ["0001160106"]
    assert display_name_matches_ticker(hits[0]["display_names"], "LYG")
    assert not display_name_matches_ticker(hits[0]["display_names"], "YG")
    url = build_discovery_url({
        "ticker": "LYG", "search_start": "2001-01-01", "search_end": "2006-01-02"
    })
    assert "efts.sec.gov/LATEST/search-index?" in url
    assert "startdt=2001-01-01" in url
    assert "enddt=2006-01-02" in url


def test_exact_archived_filing_can_emit_candidate_but_never_admission():
    filing = b"""
CONFORMED SUBMISSION TYPE: 20-F
FILED AS OF DATE: 20050331
ACCESSION NUMBER: 0000950117-05-002637
STANDARD INDUSTRIAL CLASSIFICATION: SERVICES-COMPUTER PROGRAMMING [7374]
Common Shares
Trading Symbol: GIB
"""
    row = {
        "security_id": "3", "ticker": "GIB", "bucket": "TYPE_AND_SECTOR",
        "authority_before": "2006-01-03", "_hit_filed": "2005-03-31", "_hit_form": "20-F",
    }
    candidate = analyze_filing(
        row, "0001061574", "0000950117-05-002637", filing,
        "https://www.sec.gov/Archives/edgar/data/1061574/x.txt",
        "https://efts.sec.gov/LATEST/search-index?q=GIB", "d" * 64,
        "sources/filings/x.bin",
    )
    assert candidate is not None
    assert candidate["candidate_cik"] == "0001061574"
    assert candidate["filed"] == "2005-03-31"
    assert candidate["sic"] == "7374"
    assert candidate["classification"] == "common"
    assert candidate["form_authority"] == "CURRENT_AUTHORITY_FORM"
    assert candidate["admission_effect"] == "NONE_CANDIDATE_ONLY"


def test_same_day_or_future_filing_is_rejected():
    filing = b"""
CONFORMED SUBMISSION TYPE: 20-F
FILED AS OF DATE: 20060103
ACCESSION NUMBER: 0000950117-06-000001
STANDARD INDUSTRIAL CLASSIFICATION: SERVICES-COMPUTER PROGRAMMING [7374]
Common Shares
Trading Symbol: GIB
"""
    row = {
        "security_id": "3", "ticker": "GIB", "bucket": "TYPE_AND_SECTOR",
        "authority_before": "2006-01-03", "_hit_filed": "2006-01-03", "_hit_form": "20-F",
    }
    assert analyze_filing(
        row, "0001061574", "0000950117-06-000001", filing,
        "https://www.sec.gov/Archives/edgar/data/1061574/x.txt",
        "https://efts.sec.gov/LATEST/search-index?q=GIB", "d" * 64,
        "sources/filings/x.bin",
    ) is None
