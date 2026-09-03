from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from backtester.mine_historical_metadata_candidates_v3 import mine, read_gzip_csv


def _gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checksums(root: Path) -> None:
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        lines.append(f"{_sha(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_v3_candidate_miner_is_evidence_only_and_can_bootstrap_discovery_hint(tmp_path: Path) -> None:
    shard = tmp_path / "shard"
    shard.mkdir()
    raw = b"""<SEC-HEADER>\nACCESSION NUMBER: 0000000001-20-000001\nCONFORMED SUBMISSION TYPE: S-3\nFILED AS OF DATE: 20200115\nSTANDARD INDUSTRIAL CLASSIFICATION: TEST COMPANY [3571]\n</SEC-HEADER>\nTrading Symbol: XYZ\nCommon Stock, par value $0.01 per share\n"""
    member = "sources/filings/example.bin"
    source = shard / member
    source.parent.mkdir(parents=True)
    source.write_bytes(raw)
    digest = _sha(source)
    _gz(
        shard / "web_source_manifest.csv.gz",
        ["url", "status", "path", "sha256", "bytes", "attempts", "terminal_absence", "retrieved_at", "artifact_member"],
        [{
            "url": "https://www.sec.gov/Archives/edgar/data/1/000000000120000001/example.txt",
            "status": "200",
            "path": "",
            "sha256": digest,
            "bytes": str(len(raw)),
            "attempts": "1",
            "terminal_absence": "false",
            "retrieved_at": "2020-01-15T00:00:00Z",
            "artifact_member": member,
        }],
    )
    (shard / "shard_runner_coverage.json").write_text(
        json.dumps({"status": "PASS", "shard": "00"}), encoding="utf-8"
    )
    (shard / "web_coverage.json").write_text(
        json.dumps({"status": "PASS", "complete": True}), encoding="utf-8"
    )
    _checksums(shard)

    inventory = tmp_path / "inventory.csv.gz"
    _gz(
        inventory,
        [
            "security_id", "ticker", "first_session", "last_session", "observed_ciks",
            "timeline_identity_ciks", "web_plan_ciks", "resolution_route",
        ],
        [{
            "security_id": "SEC1",
            "ticker": "XYZ",
            "first_session": "2019-01-01",
            "last_session": "2021-12-31",
            "observed_ciks": "",
            "timeline_identity_ciks": "",
            "web_plan_ciks": "0000000001",
            "resolution_route": "IDENTITY_CIK_DISCOVERY",
        }],
    )

    output = tmp_path / "out"
    summary = mine(shard, inventory, output, "00")
    assert summary["status"] == "PASS"
    assert summary["candidate_only"] is True
    assert summary["admission_effect"] == "NONE"

    rows = read_gzip_csv(output / "candidate_evidence.csv.gz")
    identity = [row for row in rows if row["candidate_kind"] == "IDENTITY_EXACT_TICKER"]
    types = [row for row in rows if row["candidate_kind"] == "SECURITY_TYPE_EXACT_TICKER_CLASS"]
    sics = [row for row in rows if row["candidate_kind"] == "SIC_HEADER"]
    assert len(identity) == 1
    assert identity[0]["cik_authority"] == "DISCOVERY_ONLY_HINT"
    assert identity[0]["admission_effect"] == "NONE_CANDIDATE_ONLY"
    assert len(types) == 1
    assert types[0]["classification"] == "common"
    assert types[0]["candidate_quality"] == "EXTENDED_FORM_EXACT_TICKER_CLASS_CANDIDATE"
    assert len(sics) == 1
    assert sics[0]["sic"] == "3571"
    assert sics[0]["candidate_quality"] == "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP"
