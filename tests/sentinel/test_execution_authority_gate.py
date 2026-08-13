"""Publication-chain and fresh broker-authority falsifiers."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinel.authority import AuthorityRefused
from sentinel.execution import authority_gate


def _row(version, previous, *, evidence=None):
    return (
        version, previous, f"00000000-0000-0000-0000-{version:012d}",
        datetime(2026, 8, version, 20, 0, tzinfo=timezone.utc),
        None, None, evidence or {"version": version})


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=None):
        assert "sentinel_corpus_publications" in sql

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)


def test_signed_root_must_reach_current_publication_without_a_gap():
    rows = [_row(1, None), _row(2, 1), _row(3, 2)]
    root = authority_gate.publication_row_sha256(rows[0])

    assert authority_gate.require_publication_chain(
        _Conn(rows), expected_root_sha256=root, current_version=3) == root


@pytest.mark.parametrize("rows", [
    [_row(1, None), _row(3, 1)],
    [_row(1, None), _row(2, 99)],
])
def test_gap_or_false_predecessor_after_signed_root_refuses(rows):
    root = authority_gate.publication_row_sha256(rows[0])

    with pytest.raises(AuthorityRefused, match="chain has a gap"):
        authority_gate.require_publication_chain(
            _Conn(rows), expected_root_sha256=root,
            current_version=int(rows[-1][0]))


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
