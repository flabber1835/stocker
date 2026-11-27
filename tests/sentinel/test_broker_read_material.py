"""Only canonical sealed values may survive identical committed visibility."""
import psycopg
import pytest

from sentinel.feed import broker_read_material, normalized_layout, operational_snapshot, rolling_store
from tests.sentinel.test_publication_read_cost import alpaca_path, conn, pg, published  # noqa: F401


def test_unrelated_loader_cannot_supply_sealed_material():
    with pytest.raises(TypeError, match='only the sealed manifest'):
        broker_read_material.sealed(lambda reader, key: 'forged')


def test_exact_read_source_transition_rejects_substitutions(monkeypatch):
    from sentinel import economic_manifest as economic
    originals = {module: economic._module_raw(module) for module in economic._BROKER_READ_BASE}
    prior = economic._before_broker_reads(originals)
    assert all(economic._sha(prior[name]) == expected for name, (_, expected) in economic._BROKER_READ_BASE.items())
    for name in originals:
        with pytest.raises(economic.EconomicManifestRefused, match='PREDECESSOR_CHANGED'):
            economic._before_broker_reads({**originals, name: originals[name] + b'\n# substituted\n'})
    canonical = economic._module_raw
    monkeypatch.setattr(economic, '_module_raw', lambda name: canonical(name) + b'\n'
                        if name == 'sentinel.feed.broker_read_material' else canonical(name))
    with pytest.raises(economic.EconomicManifestRefused, match='MATERIAL_SOURCE_CHANGED'):
        economic._before_broker_reads(originals)


def test_same_visibility_reuses_only_detached_sealed_material(conn, pg, published, monkeypatch):
    pub = operational_snapshot._current(conn)
    candidate = published['candidate_id']
    conn.rollback()
    scope = broker_read_material.ReadScope()
    grant = object()
    scans = []
    canonical = normalized_layout._candidate_headers

    def counted(reader, candidate_id):
        scans.append(candidate_id)
        return canonical(reader, candidate_id)

    monkeypatch.setattr(normalized_layout, '_candidate_headers', counted)
    with psycopg.connect(conn.info.dsn) as reader:
        reader.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
        reader.commit()
        with scope.enter(grant):
            first, manifest = operational_snapshot._bound_and_manifest(reader, pub)
            first['snapshot_id'] = 'forged'
            second, other_manifest = operational_snapshot._bound_and_manifest(reader, pub)
            assert second['snapshot_id'] == manifest.snapshot_id == other_manifest.snapshot_id
            assert rolling_store.manifest(reader, candidate_id=candidate) == manifest
            assert scans == [candidate]
            with psycopg.connect(pg.sync_dsn) as other:
                other.execute('SET TRANSACTION READ ONLY')
                with pytest.raises(psycopg.errors.UndefinedTable):
                    rolling_store.manifest(other, candidate)
            with scope.enter(None):
                rolling_store.manifest(reader, candidate)
            assert len(scans) == 2
        with scope.enter(object()):
            rolling_store.manifest(reader, candidate)
            assert len(scans) == 3
            conn.execute('CREATE ROLE guard_read_test NOLOGIN')
            conn.commit()
            reader.execute('SET LOCAL ROLE guard_read_test')
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                rolling_store.manifest(reader, candidate)
            reader.rollback()
            reader.execute('SET LOCAL search_path=pg_catalog')
            with pytest.raises(psycopg.errors.UndefinedTable):
                rolling_store.manifest(reader, candidate)


def test_unrelated_commits_keep_pinned_material_and_changed_evidence_invalidates_it(conn, published, monkeypatch):
    from sentinel.execution import feed_inputs
    candidate = published['candidate_id']
    pub = operational_snapshot._current(conn)
    conn.rollback()
    grant = object()
    scope = broker_read_material.ReadScope()
    calls = []
    original = normalized_layout._candidate_headers
    def counted(connection, candidate_id):
        calls.append(candidate_id)
        return original(connection, candidate_id)
    monkeypatch.setattr(normalized_layout, '_candidate_headers', counted)
    conn.execute('CREATE TABLE private_unrelated_tick (id int)')
    conn.commit()
    with psycopg.connect(conn.info.dsn) as reader:
        reader.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
        reader.commit()
        with feed_inputs.pinned(reader, commit=False), scope.enter(grant):
            assert operational_snapshot._bound(reader, pub)['candidate_id'] == str(candidate)
            initial = len(calls)
            for i in range(3):
                conn.execute('INSERT INTO private_unrelated_tick VALUES (%s)', (i,))
                conn.commit()
                assert rolling_store.manifest(reader, candidate).snapshot_id == pub.evidence['rolling_snapshot']['snapshot_id']
                assert operational_snapshot._bound(reader, pub)['candidate_id'] == str(candidate)
            assert len(calls) == initial
            # An out-of-band writer changes a sealed layout despite the publication pin.
            conn.execute("SET LOCAL session_replication_role='replica'")
            from sentinel.feed.rolling_contract import canonical_json, digest
            changed = conn.execute('SELECT layout FROM sentinel_candidate_layouts WHERE candidate_id=%s',
                                   (candidate,)).fetchone()[0]
            changed['unrecognized'] = True
            encoded = canonical_json(changed)
            conn.execute('UPDATE sentinel_candidate_layouts SET layout=%s::jsonb, canonical_layout=%s, '
                         'layout_sha256=%s WHERE candidate_id=%s', (encoded, encoded, digest(changed), candidate))
            conn.commit()
            with pytest.raises(normalized_layout.LayoutRefused, match='NORMALIZED_LAYOUT_BINDING_CHANGED'):
                operational_snapshot._bound(reader, pub)
