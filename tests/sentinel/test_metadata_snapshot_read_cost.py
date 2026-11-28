"""Measure complete, independently pinned native reads of a signed metadata input."""
from dataclasses import replace

import psycopg
import pytest

from sentinel import observation_authority as authority
from sentinel.feed import normalized_layout, operational_snapshot, publication
from tests.sentinel.test_publication_read_cost import alpaca_path, conn, pg, published  # noqa: F401


def test_one_header_validation_per_independent_read_and_changed_publication_refuses(conn, published, monkeypatch):
    expected = authority.current_metadata_snapshot_identity(conn)
    conn.rollback()
    seen = []
    headers = normalized_layout._candidate_headers

    def count(reader, candidate):
        seen.append(candidate)
        return headers(reader, candidate)

    monkeypatch.setattr(normalized_layout, '_candidate_headers', count)
    with psycopg.connect(conn.info.dsn, options='-c default_transaction_read_only=on') as reader:
        for ordinal in (1, 2):
            assert authority.current_metadata_snapshot_identity(reader) == expected
            assert seen == [published['candidate_id']] * ordinal
            reader.rollback()
        original = publication._core.require_current

        def changed(connection):
            pub = original(connection)
            binding = dict(pub.evidence['rolling_snapshot'], candidate_id='different-publication-candidate')
            return replace(pub, evidence={**pub.evidence, 'rolling_snapshot': binding})

        monkeypatch.setattr(publication._core, 'require_current', changed)
        with pytest.raises(operational_snapshot.OperationalSnapshotRefused, match='OPERATIONAL_BINDING_MISMATCH'):
            authority.current_metadata_snapshot_identity(reader)


def test_committed_write_during_read_revalidates_every_header(conn, published, monkeypatch):
    # Produce a real intervening commit, then have the instrumented reader show
    # a changed header on its second read. The first result must never escape.
    conn.execute('CREATE TABLE private_metadata_tick(id integer)')
    conn.commit()
    candidate = published['candidate_id']
    headers = normalized_layout._candidate_headers
    measure = authority._reference_metadata_identity
    visits = []

    def read(connection, identity):
        rows = headers(connection, identity)
        visits.append(identity)
        if len(visits) > 1:
            rows[0] = (*rows[0][:-1], 'changed-calendar')
        return rows

    def publish_change(connection, refs):
        result = measure(connection, refs)
        conn.execute('INSERT INTO private_metadata_tick VALUES(1)')
        conn.commit()
        return result

    monkeypatch.setattr(normalized_layout, '_candidate_headers', read)
    monkeypatch.setattr(authority, '_reference_metadata_identity', publish_change)
    with psycopg.connect(conn.info.dsn, options='-c default_transaction_read_only=on') as reader:
        with pytest.raises(normalized_layout.LayoutRefused, match='NORMALIZED_LAYOUT_BLOCK_HEADER_CHANGED'):
            authority.current_metadata_snapshot_identity(reader)
    assert visits == [candidate, candidate]
    assert conn.execute('SELECT id FROM private_metadata_tick').fetchall() == [(1,)]
