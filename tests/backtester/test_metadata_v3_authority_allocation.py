import json
from pathlib import Path

from backtester import admit_historical_metadata_candidates_v3 as v3


def _row(
    sid: str,
    ticker: str,
    first: str,
    last: str,
    cik: str,
    kind: str,
    quality: str,
    filed: str,
    source_sha: str,
    *,
    classification: str = "",
    sic: str = "",
    form: str = "10-K",
    accession: str = "acc",
):
    return {
        "shard": "00",
        "security_id": sid,
        "ticker": ticker,
        "first_session": first,
        "last_session": last,
        "resolution_route": "",
        "candidate_cik": cik,
        "cik_authority": "CAUSALLY_ESTABLISHED",
        "candidate_kind": kind,
        "candidate_quality": quality,
        "form": form,
        "filed": filed,
        "accession": accession,
        "classification": classification,
        "sic": sic,
        "evidence_excerpt": "proof",
        "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}.txt",
        "source_sha256": source_sha,
        "artifact_member": f"raw/{source_sha}.txt",
        "admission_effect": "NONE_CANDIDATE_ONLY",
    }


def test_v3_authority_gate_is_fail_closed_and_guard_bounded(tmp_path: Path):
    package = tmp_path / "package"
    candidate_root = tmp_path / "candidates-v3"
    output = tmp_path / "output"
    for name in ("timeline", "candidates", "guard"):
        (package / name).mkdir(parents=True, exist_ok=True)

    candidate_episodes = [
        {
            "security_id": "S1",
            "ticker": "AAA",
            "first_session": "2006-01-03",
            "last_session": "2006-12-31",
            "observed_ciks": "",
            "observations": "100",
            "unknown_type_observations": "100",
            "missing_sector_observations": "100",
        },
        {
            "security_id": "S2",
            "ticker": "AAA",
            "first_session": "2007-01-02",
            "last_session": "2007-12-31",
            "observed_ciks": "",
            "observations": "100",
            "unknown_type_observations": "0",
            "missing_sector_observations": "0",
        },
        {
            "security_id": "S3",
            "ticker": "BBB",
            "first_session": "2006-01-03",
            "last_session": "2006-12-31",
            "observed_ciks": "0000000003",
            "observations": "100",
            "unknown_type_observations": "100",
            "missing_sector_observations": "100",
        },
    ]
    candidate_fields = list(candidate_episodes[0])
    v3.write_gzip_csv(
        package / "candidates" / "candidate_episodes.csv.gz",
        candidate_fields,
        candidate_episodes,
    )
    guard = [
        {
            "security_id": row["security_id"],
            "ticker": row["ticker"],
            "first_session": row["first_session"],
            "last_session": row["last_session"],
        }
        for row in candidate_episodes
    ]
    v3.write_gzip_csv(
        package / "guard" / "canonical_ticker_episode_guard.csv.gz",
        list(guard[0]),
        guard,
    )

    unresolved = [
        dict(candidate_episodes[0])
        | {
            "reasons": (
                "no_unambiguous_historical_identity_proof;"
                "no_admitted_security_type_evidence;no_admitted_sic_evidence"
            )
        },
        dict(candidate_episodes[1]) | {"reasons": "no_unambiguous_historical_identity_proof"},
        dict(candidate_episodes[2])
        | {"reasons": "no_admitted_security_type_evidence;no_admitted_sic_evidence"},
    ]
    v3.write_gzip_csv(
        package / "timeline" / "unresolved_episodes.csv.gz",
        list(unresolved[0]),
        unresolved,
    )
    v3.write_gzip_csv(
        package / "timeline" / "identity_events.csv.gz",
        ["security_id", "ticker", "filed", "usable_after", "cik", "extra"],
        [
            {
                "security_id": "S3",
                "ticker": "BBB",
                "filed": "2005-12-15",
                "usable_after": "2005-12-15",
                "cik": "0000000003",
                "extra": "",
            }
        ],
    )
    (package / "timeline" / "timeline_coverage.json").write_text(
        json.dumps({"status": "PASS"}), encoding="utf-8"
    )

    a = "a" * 64
    b = "b" * 64
    c = "c" * 64
    d = "d" * 64
    e = "e" * 64
    rows = [
        _row(
            "S1", "AAA", "2006-01-03", "2006-12-31", "0000000001",
            "IDENTITY_EXACT_TICKER", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
            "2006-02-01", a, accession="a1",
        ),
        _row(
            "S1", "AAA", "2006-01-03", "2006-12-31", "0000000001",
            "SECURITY_TYPE_EXACT_TICKER_CLASS", "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE",
            "2006-02-01", a, classification="common", accession="a1",
        ),
        _row(
            "S1", "AAA", "2006-01-03", "2006-12-31", "0000000001",
            "SIC_HEADER", "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP",
            "2006-02-01", a, sic="1234", accession="a1",
        ),
        # Target says S1, but this filing belongs to the later AAA episode S2.
        _row(
            "S1", "AAA", "2006-01-03", "2006-12-31", "0000000002",
            "IDENTITY_EXACT_TICKER", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
            "2007-02-01", b, accession="bad",
        ),
        _row(
            "S3", "BBB", "2006-01-03", "2006-12-31", "0000000003",
            "IDENTITY_EXACT_TICKER", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
            "2006-03-01", c, accession="b1",
        ),
        _row(
            "S3", "BBB", "2006-01-03", "2006-12-31", "0000000003",
            "SECURITY_TYPE_EXACT_TICKER_CLASS", "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE",
            "2006-03-01", c, classification="common", accession="b1",
        ),
        # Ownership-form class is supplementary and cannot become listed-class authority.
        _row(
            "S3", "BBB", "2006-01-03", "2006-12-31", "0000000003",
            "SECURITY_TYPE_EXACT_TICKER_CLASS", "OWNERSHIP_FORM_SUPPLEMENTARY_CLASS_ONLY",
            "2006-03-02", d, classification="non_common", form="4", accession="own",
        ),
        _row(
            "S3", "BBB", "2006-01-03", "2006-12-31", "0000000003",
            "SIC_HEADER", "HEADER_SIC_CAUSAL_CIK", "2006-01-15", e,
            sic="5678", accession="sic",
        ),
    ]
    candidate_root.mkdir(parents=True)
    v3.write_gzip_csv(candidate_root / "candidate_evidence.csv.gz", list(rows[0]), rows)
    (candidate_root / "summary.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "candidate_only": True,
                "admission_effect": "NONE",
                "merged_shards": 32,
                "candidate_rows": len(rows),
            }
        ),
        encoding="utf-8",
    )

    summary = v3.admit(package, candidate_root, output)
    assert summary["status"] == "PASS"
    assert summary["fully_resolved_episode_delta"] == 2
    assert summary["unresolved_episode_records_after_v3"] == 1
    assert summary["ownership_form_type_candidates_admitted"] == 0
    assert summary["extended_form_type_candidates_admitted"] == 0

    identity = v3.read_gzip_csv(output / "identity_events_v3.csv.gz")
    assert {row["security_id"] for row in identity} == {"S1"}

    security_types = v3.read_gzip_csv(output / "security_type_events_v3.csv.gz")
    assert {(row["security_id"], row["classification"]) for row in security_types} == {
        ("S1", "common"),
        ("S3", "common"),
    }

    sic = v3.read_gzip_csv(output / "sic_events_v3.csv.gz")
    assert {row["security_id"] for row in sic} == {"S1", "S3"}
    assert next(row for row in sic if row["security_id"] == "S3")["usable_after"] == "2006-01-15"

    review = v3.read_gzip_csv(output / "identity_guard_review.csv.gz")
    assert any(
        row["target_security_id"] == "S1" and row["mapped_security_id"] == "S2"
        for row in review
    )

    remaining = v3.read_gzip_csv(output / "unresolved_episodes_after_v3.csv.gz")
    assert [row["security_id"] for row in remaining] == ["S2"]
    assert summary["policy"]["unknown_never_means_ineligible"] is True
    assert summary["policy"]["guard_mismatch_never_retargets_or_admits_automatically"] is True
