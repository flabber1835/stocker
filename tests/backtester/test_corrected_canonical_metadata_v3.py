import csv
import gzip
import json
from pathlib import Path

from backtester import rebuild_corrected_canonical_metadata_v3 as m


def _write_gzip(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_corrected_observation_audit_is_strict_prior_and_fail_closed(tmp_path: Path):
    canonical = tmp_path / "canonical"
    v2 = tmp_path / "v2"
    v3 = tmp_path / "v3"
    corrected = tmp_path / "corrected"
    output = tmp_path / "output"
    canonical.mkdir()
    (v2 / "timeline").mkdir(parents=True)
    v3.mkdir()
    corrected.mkdir()

    _write_gzip(
        canonical / "observations-2006.csv.gz",
        ["session", "security_id", "ticker", "issuer_id", "security_type", "sic", "ff12"],
        [
            {"session": "2006-01-03", "security_id": "OLD", "ticker": "AAA", "issuer_id": "SEC_UNKNOWN:OLD", "security_type": "unknown", "sic": "", "ff12": ""},
            {"session": "2006-01-04", "security_id": "OLD", "ticker": "AAA", "issuer_id": "SEC_UNKNOWN:OLD", "security_type": "unknown", "sic": "", "ff12": ""},
        ],
    )
    _write_gzip(
        v2 / "timeline" / "identity_events.csv.gz",
        ["security_id", "ticker", "filed", "usable_after", "cik", "accession", "source_kind", "source_url", "source_sha256"],
        [{"security_id": "OLD", "ticker": "AAA", "filed": "2006-01-03", "usable_after": "2006-01-03", "cik": "123", "accession": "acc", "source_kind": "test", "source_url": "", "source_sha256": ""}],
    )
    _write_gzip(
        v2 / "timeline" / "security_type_events.csv.gz",
        ["security_id", "ticker", "filed", "usable_after", "cik", "accession", "classification", "authority", "source_url", "source_sha256"],
        [{"security_id": "OLD", "ticker": "AAA", "filed": "2006-01-03", "usable_after": "2006-01-03", "cik": "123", "accession": "acc", "classification": "common", "authority": "test", "source_url": "", "source_sha256": ""}],
    )
    _write_gzip(
        v2 / "timeline" / "sic_events.csv.gz",
        ["security_id", "ticker", "filed", "usable_after", "identity_proof_filed", "cik", "sic", "source_kind", "accession", "source_url", "source_sha256"],
        [{"security_id": "OLD", "ticker": "AAA", "filed": "2006-01-03", "usable_after": "2006-01-03", "identity_proof_filed": "2006-01-03", "cik": "123", "sic": "3571", "source_kind": "test", "accession": "acc", "source_url": "", "source_sha256": ""}],
    )
    (v2 / "canonical_coverage.json").write_text(
        json.dumps({"totals": {"unknown_type_observations": 2, "missing_sector_observations": 2}}),
        encoding="utf-8",
    )

    _write_gzip(
        corrected / "corrected_episode_guard.csv.gz",
        ["security_id", "ticker", "first_session", "last_session", "observations", "episode", "identity_authority"],
        [{"security_id": "NEW", "ticker": "AAA", "first_session": "2006-01-03", "last_session": "2006-12-31", "observations": "2", "episode": "0", "identity_authority": "test"}],
    )
    _write_gzip(
        corrected / "old_to_corrected_episode_mapping.csv.gz",
        ["old_security_id", "ticker", "old_first_session", "old_last_session", "old_observations", "old_observed_ciks", "corrected_security_id", "disposition", "overlapping_corrected_security_ids"],
        [{"old_security_id": "OLD", "ticker": "AAA", "old_first_session": "2006-01-03", "old_last_session": "2006-01-04", "old_observations": "2", "old_observed_ciks": "", "corrected_security_id": "NEW", "disposition": "CONTAINED", "overlapping_corrected_security_ids": "NEW"}],
    )
    (corrected / "summary.json").write_text(
        json.dumps({
            "status": "PASS",
            "blocking_identity_conflicts": 0,
            "candidate_mapping_anomalies": 0,
            "security_type_conflict_episodes": 0,
            "exact_resolution_count_available": True,
            "old_guard_rows": 1,
            "prospective_unresolved_corrected_topology": 1,
            "prospective_unresolved_observations": 2,
        }),
        encoding="utf-8",
    )

    candidate = v3 / "candidate_evidence.csv.gz"
    _write_gzip(
        candidate,
        ["ticker", "candidate_cik", "candidate_kind", "candidate_quality", "filed", "accession", "source_sha256", "classification", "sic", "cik_authority", "security_id", "source_url"],
        [],
    )
    (v3 / "summary.json").write_text(
        json.dumps({"status": "PASS", "candidate_only": True, "candidate_rows": 22140}),
        encoding="utf-8",
    )

    original_hash = m.V3_SHA256
    m.V3_SHA256 = m.topo.sha256_file(candidate)
    try:
        summary = m.build(
            canonical=canonical,
            v2_root=v2,
            v3_root=v3,
            corrected_root=corrected,
            output=output,
        )
    finally:
        m.V3_SHA256 = original_hash

    assert summary["status"] == "PASS"
    assert summary["admission_status"] == "REVIEW_REQUIRED"
    assert summary["resolved_by_corrected_overlay"]["unknown_type_observations"] == 1
    assert summary["unresolved_after_corrected_overlay"]["unknown_type_observations"] == 1
    assert summary["resolved_by_corrected_overlay"]["missing_sector_observations"] == 1
    assert summary["unresolved_after_corrected_overlay"]["missing_sector_observations"] == 1
    assert summary["unresolved_after_corrected_overlay"]["episodes"] == 1


def test_exact_sec_source_key_is_ticker_scoped():
    base = {
        "candidate_cik": "2098242",
        "filed": "2026-02-25",
        "accession": "0001104659-26-019717",
        "source_sha256": "4e30cc349a5791e373b07ad03863a09740d35e86db4a2aa1ccf1b243653564d3",
    }
    assert m.topo.exact_ticker_source_key(dict(base, ticker="SVIV")) != m.topo.exact_ticker_source_key(dict(base, ticker="SVIVU"))
