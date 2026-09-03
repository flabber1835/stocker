from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

from backtester.canonical_pit_metadata_v2 import HistoricalMetadataV2Authority


def _write_gz(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _package(root: Path, *, status: str = "PASS") -> Path:
    timeline = root / "timeline"
    timeline.mkdir(parents=True)
    (timeline / "timeline_coverage.json").write_text(
        json.dumps(
            {
                "schema": "backtester.historical-metadata-reconstruction-v2.guarded-timeline/1",
                "status": status,
                "admission_status": "REVIEW_REQUIRED",
                "causal_rule": "filed/usable_after < decision_session",
                "ticker_alias_policy": "disabled_without_independent_historical_alias_proof",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_gz(
        timeline / "identity_events.csv.gz",
        ["security_id", "ticker", "usable_after", "cik"],
        [{"security_id": "SID1", "ticker": "ABC", "usable_after": "2006-02-01", "cik": "0000123456"}],
    )
    _write_gz(
        timeline / "security_type_events.csv.gz",
        ["security_id", "ticker", "usable_after", "classification"],
        [{"security_id": "SID1", "ticker": "ABC", "usable_after": "2006-02-01", "classification": "common"}],
    )
    _write_gz(
        timeline / "sic_events.csv.gz",
        ["security_id", "ticker", "usable_after", "sic"],
        [{"security_id": "SID1", "ticker": "ABC", "usable_after": "2006-02-01", "sic": "3571"}],
    )
    for name, columns in (
        ("unresolved_episodes.csv.gz", ["security_id"]),
        ("ambiguous_identity_events.csv.gz", ["security_id"]),
        ("security_type_conflicts.csv.gz", ["security_id"]),
    ):
        _write_gz(timeline / name, columns, [])
    return root


class _TypeAuthority:
    def __init__(self):
        self.auto_common = 0
        self.manual_common = 0
        self.manual_non_common = 0
        self.unknown = 1


def _legacy() -> dict[str, str]:
    return {
        "issuer_id": "SEC_UNKNOWN:SID1",
        "issuer_source": "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON",
        "security_type": "unknown",
        "security_type_source": "NO_STRICT_PRIOR_POSITIVE_EVIDENCE",
        "security_type_eligible": "0",
        "sic": "",
        "ff12": "UNKNOWN:SID1",
        "sector_source": "SEC_STRICT_PRIOR_SIC_UNKNOWN_SINGLETON",
        "listing_first_session": "2006-01-03",
        "metadata_admitted": "0",
    }


def test_same_day_metadata_is_not_visible(tmp_path: Path) -> None:
    authority = HistoricalMetadataV2Authority(_package(tmp_path / "p"))
    type_authority = _TypeAuthority()
    result = authority.apply(
        security_id="SID1",
        ticker="ABC",
        session="2006-02-01",
        legacy=_legacy(),
        type_authority=type_authority,
        ff12_for_sic=lambda value: f"FF12:{value}",
    )
    assert result == _legacy()
    assert type_authority.unknown == 1


def test_next_session_metadata_resolves_without_changing_security_identity(tmp_path: Path) -> None:
    authority = HistoricalMetadataV2Authority(_package(tmp_path / "p"))
    type_authority = _TypeAuthority()
    result = authority.apply(
        security_id="SID1",
        ticker="ABC",
        session="2006-02-02",
        legacy=_legacy(),
        type_authority=type_authority,
        ff12_for_sic=lambda value: "BusEq" if value == 3571 else "OTHER",
    )
    assert result["issuer_id"] == "SEC_CIK:123456"
    assert result["issuer_source"] == "SEC_V2_GUARDED_STRICT_PRIOR_CIK"
    assert result["security_type"] == "common"
    assert result["security_type_eligible"] == "1"
    assert result["metadata_admitted"] == "1"
    assert result["sic"] == "3571"
    assert result["ff12"] == "BusEq"
    assert type_authority.unknown == 0
    assert authority.stats["security_type_unknown_observations_resolved"] == 1


def test_known_legacy_classification_is_accounted_then_replaced(tmp_path: Path) -> None:
    root = _package(tmp_path / "p")
    type_path = root / "timeline/security_type_events.csv.gz"
    _write_gz(
        type_path,
        ["security_id", "ticker", "usable_after", "classification"],
        [{"security_id": "SID1", "ticker": "ABC", "usable_after": "2006-02-01", "classification": "non_common"}],
    )
    authority = HistoricalMetadataV2Authority(root)
    type_authority = _TypeAuthority()
    type_authority.unknown = 0
    type_authority.auto_common = 1
    legacy = _legacy()
    legacy.update(
        {
            "security_type": "common",
            "security_type_source": "SEC_POSITIVE_STRICT_PRIOR_CIK_MATCH",
            "security_type_eligible": "1",
            "metadata_admitted": "1",
        }
    )
    result = authority.apply(
        security_id="SID1",
        ticker="ABC",
        session="2006-02-02",
        legacy=legacy,
        type_authority=type_authority,
        ff12_for_sic=lambda _value: "BusEq",
    )
    assert result["security_type"] == "non_common"
    assert result["metadata_admitted"] == "0"
    assert type_authority.auto_common == 0
    assert authority.stats["security_type_known_observations_replaced"] == 1


def test_conflicting_same_date_v2_rows_fail_closed(tmp_path: Path) -> None:
    root = _package(tmp_path / "p")
    _write_gz(
        root / "timeline/security_type_events.csv.gz",
        ["security_id", "ticker", "usable_after", "classification"],
        [
            {"security_id": "SID1", "ticker": "ABC", "usable_after": "2006-02-01", "classification": "common"},
            {"security_id": "SID1", "ticker": "ABC", "usable_after": "2006-02-01", "classification": "non_common"},
        ],
    )
    with pytest.raises(RuntimeError, match="conflicting same-date"):
        HistoricalMetadataV2Authority(root)


def test_partial_timeline_is_rejected_before_canonical_build(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not conflict-free"):
        HistoricalMetadataV2Authority(_package(tmp_path / "p", status="PARTIAL"))
