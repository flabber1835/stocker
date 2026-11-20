"""Real published prices with independently committed SHADOW observations."""

import json

import pytest

from sentinel import backup_runtime_authority, identity, operational_ddl_epoch
from sentinel.execution import feed_inputs
from sentinel.feed import operational_snapshot, rolling_go_inputs, rolling_store, shadow_readiness_memo, store
from sentinel.feed.rolling_contract import canonical_json, digest
from tests.sentinel.test_alpaca_operational_snapshot import alpaca_path  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


@pytest.fixture
def published(conn, alpaca_path, monkeypatch, tmp_path):
    # The fixture publishes synthetic Alpaca prices in a private database.
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-read-cost-test-key-' * 2)
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path / 'absent-policy')
    monkeypatch.setattr(identity, 'require_feed_producer_identity', lambda: {
        'schema': 'sentinel.feed-producer/1', 'git_commit': 'a' * 40,
        'runtime_image_digest': 'sha256:' + 'b' * 64, 'image_source_revision': 'a' * 40,
    })
    job = operational_snapshot.enqueue(conn, strategy_sha256=digest('test-strategy'),
        dependencies_sha256=digest('test-deps'), budget_seconds=240)
    conn.commit()
    result = operational_snapshot.prepare(conn, job)
    operational_ddl_epoch.install(conn)
    conn.commit()
    monkeypatch.setattr(rolling_go_inputs, 'production_strategy', lambda: (None, 'test-strategy'))
    return result


def test_resolver_does_not_verify_unrelated_price_rows(conn, published, monkeypatch):
    seen = []
    verify = rolling_store.verify_content

    def track(connection, candidate_id):
        seen.append(candidate_id)
        return verify(connection, candidate_id)

    monkeypatch.setattr(rolling_store, 'verify_content', track)
    pub = feed_inputs.current(conn)
    resolver = feed_inputs.resolver(conn, pub, session='2026-09-15')
    chosen = resolver('AAA')
    assert chosen == 'uuid-AAA' and resolver.provider_asset_ids[chosen] == 'uuid-AAA'
    assert feed_inputs.opening_resolver(conn, session='2026-09-15').resolve('AAA', '2026-09-15') == chosen
    assert seen == []
    marks, _ = feed_inputs.marks(conn, pub, session='2026-09-14', security_ids=[chosen], tickers={})
    assert marks[chosen] == 51
    assert seen == [published['candidate_id']]


def _substitute_block(conn, candidate_id):
    conn.execute("SET LOCAL session_replication_role='replica'")
    keys = conn.execute('SELECT kind,session,block_sha256,normalization_version,calendar_version,row_count,'
        'canonical_payload FROM sentinel_candidate_blocks JOIN sentinel_normalized_blocks USING(block_sha256,kind,session) '
        "WHERE candidate_id=%s AND kind='BARS' ORDER BY session LIMIT 1", (candidate_id,)).fetchone()
    kind, session, old_sha, normalization, calendar, count, text = keys
    data = json.loads(text)
    data['rows'][0]['close_unadjusted'] += 1
    new_sha = digest(data)
    conn.execute('INSERT INTO sentinel_normalized_blocks (block_sha256,kind,session,normalization_version,'
        'calendar_version,row_count,canonical_payload) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (new_sha, kind, session, normalization, calendar, count, canonical_json(data)))
    conn.execute('UPDATE sentinel_candidate_blocks SET block_sha256=%s WHERE candidate_id=%s AND block_sha256=%s',
                 (new_sha, candidate_id, old_sha))
    layout = conn.execute('SELECT layout FROM sentinel_candidate_layouts WHERE candidate_id=%s',
                          (candidate_id,)).fetchone()[0]
    for ref in layout['references']:
        if ref['block_sha256'] == old_sha:
            ref['block_sha256'] = new_sha
    conn.execute('UPDATE sentinel_candidate_layouts SET block_references=%s::jsonb,layout=%s::jsonb,layout_sha256=%s,'
                 'canonical_layout=%s WHERE candidate_id=%s', (canonical_json(layout['references']),
                 canonical_json(layout), digest(layout), canonical_json(layout), candidate_id))
    conn.commit()


def test_shadow_reuses_exact_material_only_until_expiry_or_database_change(conn, published, monkeypatch):
    memo = shadow_readiness_memo.ReadinessMemo()
    clock = [1.0, 200.0]
    monkeypatch.setattr(shadow_readiness_memo, '_clock', lambda: tuple(clock))
    scans = []
    verify = rolling_store._verify_content_uncached

    def track(connection, candidate_id):
        scans.append(candidate_id)
        return verify(connection, candidate_id)

    monkeypatch.setattr(rolling_store, '_verify_content_uncached', track)

    def check(*, owner=memo):
        token = shadow_readiness_memo.current_memo.set(owner)
        try:
            with store.connect(conn.info.dsn) as reader:
                reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                return rolling_go_inputs.readiness(reader)
        finally:
            shadow_readiness_memo.current_memo.reset(token)

    first = check()
    assert first.ready and first.checks == check().checks and len(scans) == 1
    # A standalone reader (including execution) does its own complete work.
    assert check(owner=None).ready and len(scans) == 2
    clock[0] += shadow_readiness_memo.SCRUB_SECONDS
    assert check().ready and len(scans) == 3
    with store.connect(conn.info.dsn) as writer:
        writer.autocommit = True
        writer.execute('VACUUM FULL sentinel_normalized_blocks')
    assert check().ready and len(scans) == 4
    # An exact-count substitution which updates the physical layout still
    # disagrees with the historical price hash in the sealed publication.
    _substitute_block(conn, published['candidate_id'])
    for count in (5, 6):
        with pytest.raises(rolling_store.SnapshotStorageRefused, match='content differs'):
            check()
        assert len(scans) == count
