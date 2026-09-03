import csv
import hashlib
from pathlib import Path

from backtester.historical_metadata_2007_closure import build_ledger, certify_ledger, read_csv


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _fixture(tmp_path: Path, *, second_status="RESOLVED", same_security=False):
    ev = tmp_path / "evidence"
    ev.mkdir()
    membership = ev / "membership.pdf"
    identity1 = ev / "sec-1.txt"
    identity2 = ev / "sec-2.txt"
    membership.write_bytes(b"official 2007 membership")
    identity1.write_bytes(b"SEC identity one")
    identity2.write_bytes(b"SEC identity two")

    source = tmp_path / "source.csv"
    _write(
        source,
        ["source_row_id", "company_name", "ticker", "membership_authority", "membership_source_member", "membership_source_sha256", "decision_session"],
        [
            {"source_row_id": "1", "company_name": "Alpha", "ticker": "AAA", "membership_authority": "OFFICIAL_FILED_HOLDINGS", "membership_source_member": "membership.pdf", "membership_source_sha256": _sha(membership), "decision_session": "2007-06-25"},
            {"source_row_id": "2", "company_name": "Beta", "ticker": "BBB", "membership_authority": "OFFICIAL_FILED_HOLDINGS", "membership_source_member": "membership.pdf", "membership_source_sha256": _sha(membership), "decision_session": "2007-06-25"},
        ],
    )
    adj = tmp_path / "adj.csv"
    sid2 = "S1" if same_security else "S2"
    _write(
        adj,
        ["source_row_id", "resolution_status", "ticker", "security_id", "candidate_cik", "classification", "form_authority", "form", "accession", "filed", "usable_after", "source_member", "source_sha256"],
        [
            {"source_row_id": "1", "resolution_status": "RESOLVED", "ticker": "AAA", "security_id": "S1", "candidate_cik": "10", "classification": "common", "form_authority": "SEC_FORM_8A", "form": "8-A12B", "accession": "A1", "filed": "2007-05-01", "usable_after": "2007-05-01", "source_member": "sec-1.txt", "source_sha256": _sha(identity1)},
            {"source_row_id": "2", "resolution_status": second_status, "ticker": "BBB", "security_id": sid2, "candidate_cik": "20", "classification": "common" if second_status != "UNCLASSIFIED" else "unknown", "form_authority": "SEC_FORM_8A", "form": "8-A12B", "accession": "A2", "filed": "2007-05-02", "usable_after": "2007-05-02", "source_member": "sec-2.txt", "source_sha256": _sha(identity2)},
        ],
    )
    return source, adj, ev


def test_accepts_only_complete_unique_strict_prior_corpus(tmp_path):
    source, adj, ev = _fixture(tmp_path)
    built = tmp_path / "built"
    assert build_ledger(source, adj, built)["resolution_counts"]["RESOLVED"] == 2
    out = tmp_path / "accepted"
    summary = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, out, expected_rows=2)
    assert summary["status"] == "ACCEPTED"
    assert summary["resolved_rows"] == 2
    assert (out / "2007_constituents.csv.gz").is_file()
    assert len(read_csv(out / "2007_constituents.csv.gz")) == 2


def test_unclassified_row_blocks_acceptance(tmp_path):
    source, adj, ev = _fixture(tmp_path, second_status="UNCLASSIFIED")
    built = tmp_path / "built"
    build_ledger(source, adj, built)
    summary = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, tmp_path / "out", expected_rows=2)
    assert summary["status"] == "REVIEW_REQUIRED"
    assert summary["unclassified_rows"] == 1
    assert not (tmp_path / "out" / "2007_constituents.csv.gz").exists()


def test_multiple_candidate_security_identities_become_ambiguous(tmp_path):
    source, adj, ev = _fixture(tmp_path)
    rows = list(csv.DictReader(adj.open()))
    extra = dict(rows[0])
    extra["security_id"] = "OTHER"
    extra["ticker"] = "AAX"
    rows.append(extra)
    _write(adj, rows[0].keys(), rows)
    built = tmp_path / "built"
    summary = build_ledger(source, adj, built)
    assert summary["resolution_counts"]["AMBIGUOUS"] == 1
    result = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, tmp_path / "out", expected_rows=2)
    assert result["ambiguous_rows"] == 1
    assert result["status"] == "REVIEW_REQUIRED"


def test_duplicate_security_assignment_blocks_acceptance(tmp_path):
    source, adj, ev = _fixture(tmp_path, same_security=True)
    built = tmp_path / "built"
    build_ledger(source, adj, built)
    summary = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, tmp_path / "out", expected_rows=2)
    assert summary["status"] == "REVIEW_REQUIRED"
    assert len(summary["duplicate_security_assignments"]) == 1


def test_same_day_identity_evidence_is_not_strict_prior(tmp_path):
    source, adj, ev = _fixture(tmp_path)
    rows = list(csv.DictReader(adj.open()))
    rows[0]["filed"] = rows[0]["usable_after"] = "2007-06-25"
    _write(adj, rows[0].keys(), rows)
    built = tmp_path / "built"
    build_ledger(source, adj, built)
    summary = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, tmp_path / "out", expected_rows=2)
    assert summary["status"] == "REVIEW_REQUIRED"
    assert summary["blockers"]["temporal_failures"] == 1


def test_identity_hash_mismatch_blocks_acceptance(tmp_path):
    source, adj, ev = _fixture(tmp_path)
    built = tmp_path / "built"
    build_ledger(source, adj, built)
    (ev / "sec-1.txt").write_bytes(b"tampered")
    summary = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, tmp_path / "out", expected_rows=2)
    assert summary["status"] == "REVIEW_REQUIRED"
    assert summary["blockers"]["identity_evidence_failures"] == 1


def test_missing_adjudication_stays_no_authority(tmp_path):
    source, adj, ev = _fixture(tmp_path)
    rows = list(csv.DictReader(adj.open()))[:1]
    _write(adj, rows[0].keys(), rows)
    built = tmp_path / "built"
    build = build_ledger(source, adj, built)
    assert build["resolution_counts"]["NO_AUTHORITY"] == 1
    summary = certify_ledger(built / "2007_resolution_ledger.csv.gz", ev, tmp_path / "out", expected_rows=2)
    assert summary["no_authority_rows"] == 1
    assert summary["status"] == "REVIEW_REQUIRED"


def test_outputs_are_deterministic(tmp_path):
    source, adj, ev = _fixture(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_ledger(source, adj, a)
    build_ledger(source, adj, b)
    assert (a / "2007_resolution_ledger.csv.gz").read_bytes() == (b / "2007_resolution_ledger.csv.gz").read_bytes()
    oa = tmp_path / "oa"
    ob = tmp_path / "ob"
    certify_ledger(a / "2007_resolution_ledger.csv.gz", ev, oa, expected_rows=2)
    certify_ledger(b / "2007_resolution_ledger.csv.gz", ev, ob, expected_rows=2)
    for name in ("2007_resolution_ledger.csv.gz", "2007_constituents.csv.gz", "2007_closure_diagnostics.csv.gz"):
        assert (oa / name).read_bytes() == (ob / name).read_bytes()
