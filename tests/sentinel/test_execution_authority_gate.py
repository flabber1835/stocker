"""Publication-chain and fresh broker-authority falsifiers."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinel.authority import AuthorityRefused
from sentinel.execution import authority_gate
from sentinel.feed import publication


def _row(version, previous, *, evidence=None):
    return (
        version, previous, f"00000000-0000-0000-0000-{version:012d}",
        datetime(2026, 8, version, 20, 0, tzinfo=timezone.utc),
        None, None, evidence or {"version": version})


def _receipted_rows(count):
    rows = []
    previous_digest = None
    for version in range(1, count + 1):
        previous = version - 1 if version > 1 else None
        bare = _row(version, previous)
        body = publication._receipt_body(
            version=version, previous_version=previous, run_id=bare[2],
            published_at=bare[3], window_start=None, window_end=None,
            evidence=bare[6], origin_run_status="success",
            previous_receipt_sha256=previous_digest)
        digest = publication._receipt_digest(body)
        authentication = publication._receipt_hmac(body)
        evidence = {
            **bare[6],
            publication.RECEIPT_EVIDENCE_KEY: {
                "schema": publication.RECEIPT_SCHEMA,
                "previous_receipt_sha256": previous_digest,
                "receipt_sha256": digest,
                "receipt_hmac_sha256": authentication,
            },
        }
        rows.append((*bare[:6], evidence))
        previous_digest = digest
    return rows


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=None):
        if "sentinel_publication_validation_policy" in sql:
            self.query = "policy"
        elif "sentinel_publication_validation_receipts" in sql:
            self.query = "receipts"
        else:
            assert "sentinel_corpus_publications" in sql
            self.query = "publications"

    def fetchall(self):
        if self.query == "policy":
            return [(0,)]
        if self.query == "receipts":
            result = []
            for row in self.rows:
                embedded = row[6][publication.RECEIPT_EVIDENCE_KEY]
                unsigned = dict(row[6])
                unsigned.pop(publication.RECEIPT_EVIDENCE_KEY)
                result.append((
                    *row, "success", row[1], row[2], row[3], row[4], row[5],
                    unsigned, "success", embedded["previous_receipt_sha256"],
                    embedded["receipt_sha256"],
                    embedded["receipt_hmac_sha256"]))
            return result
        return list(self.rows)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)


def test_signed_root_must_reach_current_publication_without_a_gap():
    rows = _receipted_rows(3)
    root = authority_gate.publication_row_sha256(rows[0])

    assert authority_gate.require_publication_chain(
        _Conn(rows), expected_root_sha256=root, current_version=3) == root


def test_false_predecessor_after_signed_root_refuses():
    rows = [_row(1, None), _row(2, 99)]
    root = authority_gate.publication_row_sha256(rows[0])

    with pytest.raises(AuthorityRefused, match="chain has a gap"):
        authority_gate.require_publication_chain(
            _Conn(rows), expected_root_sha256=root,
            current_version=int(rows[-1][0]))


def test_sequence_value_gap_with_exact_predecessor_is_valid():
    rows = _receipted_rows(2)
    second = (3, 1, *rows[1][2:])
    unsigned = dict(second[6])
    unsigned.pop(publication.RECEIPT_EVIDENCE_KEY)
    prior = rows[0][6][publication.RECEIPT_EVIDENCE_KEY]["receipt_sha256"]
    body = publication._receipt_body(
        version=3, previous_version=1, run_id=second[2],
        published_at=second[3], window_start=None, window_end=None,
        evidence=unsigned, origin_run_status="success",
        previous_receipt_sha256=prior)
    second[6][publication.RECEIPT_EVIDENCE_KEY] = {
        "schema": publication.RECEIPT_SCHEMA,
        "previous_receipt_sha256": prior,
        "receipt_sha256": publication._receipt_digest(body),
        "receipt_hmac_sha256": publication._receipt_hmac(body),
    }
    rows = [rows[0], second]
    root = authority_gate.publication_row_sha256(rows[0])

    assert authority_gate.require_publication_chain(
        _Conn(rows), expected_root_sha256=root, current_version=3) == root


def test_missing_or_tampered_signed_publication_root_refuses():
    rows = [_row(1, None), _row(2, 1)]
    original = authority_gate.publication_row_sha256(rows[0])
    tampered = [_row(1, None, evidence={"version": "tampered"}), rows[1]]

    with pytest.raises(AuthorityRefused, match="exactly one"):
        authority_gate.require_publication_chain(
            _Conn(tampered), expected_root_sha256=original,
            current_version=2)


def test_publication_policy_identity_is_versioned_and_source_bound(monkeypatch):
    identity = authority_gate.publication_policy_implementation_identity()

    assert identity["schema"] == "sentinel.publication-chain-policy/1"
    assert len(identity["sources"]) == 5
    assert all(len(digest) == 64 for digest in identity["sources"].values())
    original = authority_gate.publication_policy_implementation_sha256()
    monkeypatch.setattr(
        authority_gate, "publication_policy_implementation_identity",
        lambda: {**identity, "chain": {**identity["chain"],
                                       "row_digest": "changed"}})
    assert authority_gate.publication_policy_implementation_sha256() != original
