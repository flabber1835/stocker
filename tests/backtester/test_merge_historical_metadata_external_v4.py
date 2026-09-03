from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

from backtester.merge_historical_metadata_external_v4 import (
    EXTERNAL_EVIDENCE_FIELDS,
    EXTERNAL_EVIDENCE_SCHEMA,
    EXTERNAL_PLAN_SCHEMA,
    FIELDS,
    MANIFEST_FIELDS,
    OWNERSHIP_STRICT_MERGE_SCHEMA,
    PLAN_FIELDS,
    RESULT_FIELDS,
    combine,
    merge_external,
    sha256_file,
    write_checksums,
    write_csv_gz,
)


def _source(root: Path, data: bytes, category: str = "filings") -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    member = f"sources/{category}/{digest}.bin"
    path = root / member
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return member, digest


def _shard(root: Path, shard: int, *, sid: str, ticker: str, proof: str,
           form: str = "20-F", filed: str = "2005-03-31") -> None:
    plan_root = root / f"backtester-results/v4-external-sec-plan-{shard}"
    evidence_root = root / f"backtester-results/v4-external-sec-evidence-{shard}"
    plan_root.mkdir(parents=True)
    evidence_root.mkdir(parents=True)
    plan = {
        "security_id": sid, "ticker": ticker, "first_session": "2006-01-03",
        "last_session": "2008-01-01", "bucket": "TYPE_AND_SECTOR",
        "type_unresolved": "100", "sector_unresolved": "100", "issuer_unresolved": "100",
        "authority_before": "2006-01-03", "search_start": "2001-01-01", "search_end": "2006-01-02",
        "impact": "300", "issuer_resolved": "10", "issuer_state": "PARTIAL_CAUSAL_IDENTITY",
        "source_inventory_sha256": "a" * 64,
    }
    write_csv_gz(plan_root / "plan.csv.gz", PLAN_FIELDS, [plan])
    (plan_root / "plan_summary.json").write_text(json.dumps({
        "schema": EXTERNAL_PLAN_SCHEMA, "status": "PASS", "identity_scope": "known-or-partial",
        "shard_index": shard, "shard_count": 2, "cohort_rows": 2, "planned_rows": 1,
        "source_inventory_sha256": "a" * 64,
    }) + "\n")
    write_checksums(plan_root)

    data = f"FORM {form} TICKER {ticker}".encode()
    member, digest = _source(evidence_root, data)
    source_url = "https://www.sec.gov/Archives/edgar/data/123456/0000123456-05-000001.txt"
    candidate = {
        "security_id": sid, "ticker": ticker, "bucket": "TYPE_AND_SECTOR", "authority_before": "2006-01-03",
        "candidate_cik": "0000123456", "accession": "0000123456-05-000001", "form": form, "filed": filed,
        "identity_proof_kind": proof, "identity_proof_excerpt": f"Trading Symbol: {ticker}",
        "classification": "common", "classification_excerpt": "Common Stock", "sic": "7374",
        "form_authority": "CURRENT_AUTHORITY_FORM", "source_url": source_url, "source_sha256": digest,
        "source_member": member, "discovery_url": "https://efts.sec.gov/x", "discovery_sha256": "b" * 64,
        "admission_effect": "NONE_CANDIDATE_ONLY", "source_cik": "0000123456",
        "issuer_cik_source": "SOURCE_URL_CIK_NON_OWNERSHIP" if form not in {"3", "3/A", "4", "4/A", "5", "5/A"} else "OWNERSHIP_XML_ISSUER_CIK",
        "issuer_cik_matches_source": "true",
    }
    write_csv_gz(evidence_root / "candidate_evidence.csv.gz", EXTERNAL_EVIDENCE_FIELDS, [candidate])
    result = {
        "security_id": sid, "ticker": ticker, "authority_before": "2006-01-03", "discovery_hits": "1",
        "display_name_exact_hits": "1", "candidate_accessions": "1", "filings_fetched": "1",
        "admissible_identity_ciks": "0000123456", "candidate_rows": "1", "status": "CANDIDATE_FOUND",
        "reason": "strict_prior_exact_archived_filing_evidence",
    }
    write_csv_gz(evidence_root / "episode_results.csv.gz", RESULT_FIELDS, [result])
    manifest = {
        "security_id": sid, "ticker": ticker, "role": "ARCHIVED_FILING_AUTHORITY_CANDIDATE",
        "url": source_url, "status": "200", "sha256": digest, "bytes": str(len(data)),
        "retrieved_at": "2026-09-03T00:00:00Z", "artifact_member": member,
    }
    write_csv_gz(evidence_root / "source_manifest.csv.gz", MANIFEST_FIELDS, [manifest])
    (evidence_root / "summary.json").write_text(json.dumps({
        "schema": EXTERNAL_EVIDENCE_SCHEMA, "status": "PASS", "candidate_only": True, "episodes": 1,
        "candidate_found": 1, "ambiguous": 0, "no_discovery_match": 0, "no_archived_proof": 0,
        "transport": {"attempts": 2, "success": 2},
    }) + "\n")
    write_checksums(evidence_root, include_sources=True)


def _retained(root: Path) -> str:
    root.mkdir(parents=True)
    row = {field: "" for field in FIELDS}
    row.update({
        "shard": "00", "security_id": "retained", "ticker": "RET", "first_session": "2006-01-03",
        "last_session": "2008-01-01", "resolution_route": "TYPE_FROM_KNOWN_IDENTITY",
        "candidate_cik": "0000999999", "cik_authority": "CAUSALLY_ESTABLISHED", "source_cik": "0000999999",
        "source_cik_target_relation": "CAUSAL_TARGET", "issuer_cik_source": "SOURCE_URL_CIK_NON_OWNERSHIP",
        "issuer_cik_matches_source": "true", "candidate_kind": "IDENTITY_EXACT_TICKER",
        "candidate_quality": "SEC_EXPLICIT_TRADING_SYMBOL_LABEL", "form": "10-K", "filed": "2005-12-01",
        "accession": "x", "source_url": "https://sec.example/x", "source_sha256": "c" * 64,
        "artifact_member": "sources/x.bin", "admission_effect": "NONE_CANDIDATE_ONLY",
    })
    write_csv_gz(root / "candidate_evidence.csv.gz", FIELDS, [row])
    (root / "summary.json").write_text(json.dumps({
        "schema": OWNERSHIP_STRICT_MERGE_SCHEMA, "status": "PASS", "candidate_only": True,
        "merged_shards": 32, "candidate_rows": 1,
    }) + "\n")
    return sha256_file(root / "candidate_evidence.csv.gz")


def test_external_merge_authenticates_disjoint_shards_and_sources(tmp_path: Path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _shard(inputs, 0, sid="1", ticker="AAA", proof="SEC_EXCHANGE_QUALIFIED_TICKER")
    _shard(inputs, 1, sid="2", ticker="BBB", proof="SEC_EXPLICIT_TRADING_SYMBOL_LABEL")
    output = tmp_path / "merged"
    summary = merge_external(inputs, output, expected_shards=2, expected_cohort=2,
                             source_run_id="77", source_sha="d" * 40)
    assert summary["status"] == "PASS" and summary["episodes"] == 2
    assert summary["candidate_evidence_rows"] == 2
    assert "sources/filings/" in (output / "SHA256SUMS.txt").read_text()


def test_external_merge_rejects_same_day_candidate(tmp_path: Path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _shard(inputs, 0, sid="1", ticker="AAA", proof="SEC_EXPLICIT_TRADING_SYMBOL_LABEL", filed="2006-01-03")
    _shard(inputs, 1, sid="2", ticker="BBB", proof="SEC_EXPLICIT_TRADING_SYMBOL_LABEL")
    try:
        merge_external(inputs, tmp_path / "out", expected_shards=2, expected_cohort=2,
                       source_run_id="77", source_sha="d" * 40)
    except RuntimeError as exc:
        assert "strict-prior" in str(exc)
    else:
        raise AssertionError("same-day evidence was accepted")


def test_combine_normalizes_exchange_proof_and_preserves_ownership_strict(tmp_path: Path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _shard(inputs, 0, sid="1", ticker="AAA", proof="SEC_EXCHANGE_QUALIFIED_TICKER")
    _shard(inputs, 1, sid="2", ticker="BBB", proof="SEC_EXPLICIT_TRADING_SYMBOL_LABEL", form="4")
    external = tmp_path / "external"
    merge_external(inputs, external, expected_shards=2, expected_cohort=2,
                   source_run_id="77", source_sha="d" * 40)
    retained = tmp_path / "retained"
    retained_sha = _retained(retained)
    combined = tmp_path / "combined"
    summary = combine(retained, external, combined, expected_retained_sha256=retained_sha)
    rows = list(csv.DictReader(gzip.open(combined / "candidate_evidence.csv.gz", "rt")))
    aaa = [r for r in rows if r["security_id"] == "1"]
    bbb = [r for r in rows if r["security_id"] == "2"]
    assert {r["candidate_kind"] for r in aaa} == {"IDENTITY_EXACT_TICKER", "SECURITY_TYPE_EXACT_TICKER_CLASS", "SIC_HEADER"}
    assert next(r for r in aaa if r["candidate_kind"] == "IDENTITY_EXACT_TICKER")["candidate_quality"] == "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
    assert bbb == []
    assert summary["external_transform_counts"]["evidence_without_ownership_strict_identity_proof"] == 1
