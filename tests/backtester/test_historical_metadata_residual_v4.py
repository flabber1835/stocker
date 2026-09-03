from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path


def _load():
    path = Path(__file__).parents[2] / "backtester" / "plan_historical_metadata_residual_v4.py"
    spec = importlib.util.spec_from_file_location("v4", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _gzip_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _manifest(root: Path, members: list[str]) -> None:
    lines = []
    for relative in members:
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_v4_routes_only_exact_existing_authority(tmp_path: Path) -> None:
    v4 = _load()
    audit, v2, v3, corrected, output = [tmp_path / name for name in ("audit", "v2", "v3", "corrected", "out")]
    for root in (audit, v2, v3, corrected):
        root.mkdir(parents=True)

    unresolved = [
        {"security_id": "c1", "ticker": "AAA", "first_session": "2006-01-03", "last_session": "2006-12-29", "rows": "10", "old_security_ids": "o1", "type_base": "10", "type_resolved": "0", "type_unresolved": "10", "type_first": "", "type_last": "", "sector_base": "10", "sector_resolved": "0", "sector_unresolved": "10", "sector_first": "", "sector_last": "", "issuer_base": "10", "issuer_resolved": "0", "issuer_unresolved": "10", "bucket": "TYPE_AND_SECTOR", "reasons": "unknown_security_type_after_overlay;missing_sector_after_overlay"},
        {"security_id": "c2", "ticker": "BBB", "first_session": "2007-01-03", "last_session": "2007-12-31", "rows": "8", "old_security_ids": "o2", "type_base": "8", "type_resolved": "0", "type_unresolved": "8", "type_first": "", "type_last": "", "sector_base": "8", "sector_resolved": "0", "sector_unresolved": "8", "sector_first": "", "sector_last": "", "issuer_base": "8", "issuer_resolved": "0", "issuer_unresolved": "8", "bucket": "TYPE_AND_SECTOR", "reasons": "unknown_security_type_after_overlay;missing_sector_after_overlay"},
        {"security_id": "c3", "ticker": "CCC", "first_session": "2008-01-02", "last_session": "2008-12-31", "rows": "6", "old_security_ids": "o3", "type_base": "0", "type_resolved": "0", "type_unresolved": "0", "type_first": "", "type_last": "", "sector_base": "6", "sector_resolved": "0", "sector_unresolved": "6", "sector_first": "", "sector_last": "", "issuer_base": "6", "issuer_resolved": "0", "issuer_unresolved": "6", "bucket": "SECTOR_ONLY", "reasons": "missing_sector_after_overlay"},
        {"security_id": "c4", "ticker": "DDD", "first_session": "2009-01-02", "last_session": "2009-12-31", "rows": "5", "old_security_ids": "o4", "type_base": "5", "type_resolved": "0", "type_unresolved": "5", "type_first": "", "type_last": "", "sector_base": "0", "sector_resolved": "0", "sector_unresolved": "0", "sector_first": "", "sector_last": "", "issuer_base": "5", "issuer_resolved": "0", "issuer_unresolved": "5", "bucket": "TYPE_ONLY", "reasons": "unknown_security_type_after_overlay"},
    ]
    fields = list(unresolved[0])
    _gzip_csv(audit / "definitive_unresolved_episodes.csv.gz", fields, unresolved)
    (audit / "summary.json").write_text(json.dumps({"status": "PASS", "admission_status": "REVIEW_REQUIRED", "unresolved_after_corrected_overlay": {"episodes": 4}}), encoding="utf-8")
    _manifest(audit, ["definitive_unresolved_episodes.csv.gz", "summary.json"])

    mapping = [
        {"old_security_id": "o1", "ticker": "AAA", "old_first_session": "", "old_last_session": "", "old_observations": "", "old_observed_ciks": "1", "corrected_security_id": "c1", "disposition": "CONTAINED", "overlapping_corrected_security_ids": "c1"},
        {"old_security_id": "o2", "ticker": "BBB", "old_first_session": "", "old_last_session": "", "old_observations": "", "old_observed_ciks": "", "corrected_security_id": "c2", "disposition": "CONTAINED", "overlapping_corrected_security_ids": "c2"},
        {"old_security_id": "o3", "ticker": "CCC", "old_first_session": "", "old_last_session": "", "old_observations": "", "old_observed_ciks": "", "corrected_security_id": "c3", "disposition": "CONTAINED", "overlapping_corrected_security_ids": "c3"},
        {"old_security_id": "o4", "ticker": "DDD", "old_first_session": "", "old_last_session": "", "old_observations": "", "old_observed_ciks": "", "corrected_security_id": "c4", "disposition": "CONTAINED", "overlapping_corrected_security_ids": "c4"},
    ]
    _gzip_csv(corrected / "old_to_corrected_episode_mapping.csv.gz", list(mapping[0]), mapping)
    (corrected / "summary.json").write_text(json.dumps({"status": "PASS", "blocking_identity_conflicts": 0, "candidate_mapping_anomalies": 0, "security_type_conflict_episodes": 0}), encoding="utf-8")
    _manifest(corrected, ["old_to_corrected_episode_mapping.csv.gz", "summary.json"])

    _gzip_csv(v2 / "timeline" / "identity_events.csv.gz", ["security_id", "cik"], [{"security_id": "o4", "cik": "4"}])
    _gzip_csv(v2 / "web-plan" / "web_plan.csv.gz", ["security_id", "cik", "discovery_only_cik_hint"], [{"security_id": "o2", "cik": "2", "discovery_only_cik_hint": "true"}])
    _gzip_csv(v2 / "web" / "web_source_manifest.csv.gz", ["url", "status"], [
        {"url": "https://data.sec.gov/submissions/CIK0000000001.json", "status": "200"},
        {"url": "https://data.sec.gov/submissions/CIK0000000002.json", "status": "200"},
        {"url": "https://data.sec.gov/submissions/CIK0000000004.json", "status": "200"},
    ])
    _manifest(v2, ["timeline/identity_events.csv.gz", "web-plan/web_plan.csv.gz", "web/web_source_manifest.csv.gz"])

    v3_rows = [{"security_id": "o2", "candidate_cik": "2", "candidate_kind": "SIC_HEADER", "candidate_quality": "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP", "cik_authority": "DISCOVERY_ONLY_HINT"}]
    _gzip_csv(v3 / "candidate_evidence.csv.gz", list(v3_rows[0]), v3_rows)
    (v3 / "summary.json").write_text(json.dumps({"status": "PASS", "candidate_only": True}), encoding="utf-8")

    summary = v4.build(audit_root=audit, v2_root=v2, v3_root=v3, corrected_root=corrected, output=output)
    assert summary["definitive_unresolved_episodes"] == 4
    assert summary["episodes_with_causal_cik"] == 2
    assert summary["episodes_without_causal_cik"] == 2
    assert summary["resolution_routes"] == {
        "HISTORICAL_IDENTITY_DISCOVERY_REQUIRED": 1,
        "REMINE_RETAINED_SEC_CAUSAL_CIK": 2,
        "REMINE_RETAINED_SEC_DISCOVERY_HINT": 1,
    }

    rows = list(v4.iter_gzip_csv(output / "residual_recovery_inventory.csv.gz"))
    by_sid = {row["security_id"]: row for row in rows}
    assert by_sid["c1"]["resolution_route"] == "REMINE_RETAINED_SEC_CAUSAL_CIK"
    assert by_sid["c2"]["resolution_route"] == "REMINE_RETAINED_SEC_DISCOVERY_HINT"
    assert by_sid["c2"]["timeline_identity_ciks"] == ""
    assert by_sid["c2"]["web_plan_ciks"] == "0000000002"
    assert by_sid["c3"]["resolution_route"] == "HISTORICAL_IDENTITY_DISCOVERY_REQUIRED"
    assert by_sid["c4"]["resolution_route"] == "REMINE_RETAINED_SEC_CAUSAL_CIK"


def test_exact_ticker_identity_candidate_can_bootstrap_causal_cik(tmp_path: Path) -> None:
    v4 = _load()
    assert v4.valid_cik("123") == "0000000123"
    assert v4.valid_cik("bad") == ""
    assert "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML" in v4.IDENTITY_QUALITIES
