from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from backtester.analyze_unresolved_metadata_v2 import analyze


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _package(tmp_path: Path) -> Path:
    root = tmp_path / "pkg"
    unresolved_fields = [
        "security_id",
        "ticker",
        "first_session",
        "last_session",
        "observations",
        "unknown_type_observations",
        "missing_sector_observations",
        "observed_ciks",
        "reasons",
    ]
    _write(
        root / "timeline" / "unresolved_episodes.csv.gz",
        unresolved_fields,
        [
            {
                "security_id": "1",
                "ticker": "AAA",
                "first_session": "2006-01-03",
                "last_session": "2007-01-03",
                "observations": "3000",
                "unknown_type_observations": "3000",
                "missing_sector_observations": "3000",
                "observed_ciks": "",
                "reasons": "no_unambiguous_historical_identity_proof;no_admitted_security_type_evidence;no_admitted_sic_evidence",
            },
            {
                "security_id": "2",
                "ticker": "BBB",
                "first_session": "2018-01-03",
                "last_session": "2020-01-03",
                "observations": "600",
                "unknown_type_observations": "600",
                "missing_sector_observations": "0",
                "observed_ciks": "0000000002",
                "reasons": "no_admitted_security_type_evidence",
            },
            {
                "security_id": "3",
                "ticker": "CCC",
                "first_session": "2024-01-03",
                "last_session": "2024-03-03",
                "observations": "40",
                "unknown_type_observations": "0",
                "missing_sector_observations": "40",
                "observed_ciks": "0000000003",
                "reasons": "no_admitted_sic_evidence",
            },
        ],
    )
    _write(
        root / "web-plan" / "web_plan.csv.gz",
        ["security_id", "cik"],
        [
            {"security_id": "2", "cik": "0000000002"},
            {"security_id": "3", "cik": "0000000003"},
        ],
    )
    _write(
        root / "web" / "web_identity_sources.csv.gz",
        ["security_id_hint"],
        [{"security_id_hint": "2"}],
    )
    _write(
        root / "web" / "web_security_type_sources.csv.gz",
        ["security_id_hint"],
        [],
    )
    _write(
        root / "web" / "web_security_type_rejected.csv.gz",
        ["security_id_hint", "reason"],
        [
            {
                "security_id_hint": "2",
                "reason": "missing_same_filing_exact_ticker_identity_proof",
            }
        ],
    )
    _write(
        root / "web" / "web_sic_sources.csv.gz",
        ["cik"],
        [{"cik": "0000000003"}],
    )
    _write(
        root / "timeline" / "identity_events.csv.gz",
        ["security_id"],
        [{"security_id": "2"}, {"security_id": "3"}],
    )
    _write(root / "timeline" / "security_type_events.csv.gz", ["security_id"], [])
    _write(root / "timeline" / "sic_events.csv.gz", ["security_id"], [])
    return root


def test_analyze_routes_and_never_converts_unknown_to_ineligible(tmp_path: Path) -> None:
    root = _package(tmp_path)
    output = tmp_path / "out"
    summary = analyze(root, output)

    assert summary["status"] == "PASS"
    assert summary["admission_status"] == "REVIEW_REQUIRED"
    assert summary["unresolved_episode_records"] == 3
    assert summary["episodes_without_observed_cik"] == 1
    assert summary["resolution_routes"] == {
        "IDENTITY_CIK_DISCOVERY": 1,
        "TYPE_FROM_KNOWN_IDENTITY": 1,
        "SIC_FROM_KNOWN_IDENTITY": 1,
    }
    assert summary["automation_hints"]["HIGH_REJECTED_TYPE_EVIDENCE_PRESENT"] == 1
    assert summary["automation_hints"]["HIGH_SIC_EVIDENCE_PRESENT_REVIEW_ALLOCATION"] == 1
    assert summary["policy"]["unknown_never_means_ineligible"] is True

    with gzip.open(output / "unresolved_episode_analysis.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {row["strategy_entry_relevance"] for row in rows} == {
        "UNKNOWN_REQUIRES_EXACT_UNIVERSE_REPLAY"
    }
    assert {row["triage_priority"] for row in rows} == {"P0", "P1", "P2"}

    persisted = json.loads((output / "unresolved_analysis_summary.json").read_text())
    assert persisted == summary
