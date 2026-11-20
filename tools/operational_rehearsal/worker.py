"""Manual production-function rehearsal, with explicit external authority fixtures."""
import argparse
import faulthandler
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
import signal

import httpx
from pytest import MonkeyPatch

from sentinel import backup_runtime_authority, identity, mirror_projection, operational_schema, schema, shadow_runtime
from sentinel import rolling_initialization as initial, rolling_runtime, formation_bootstrap
from sentinel.execution import journal
from sentinel.feed import calendar, normalized_layout, operational_snapshot as snapshots
from sentinel.feed import rolling_go_inputs as inputs, rolling_go_health, rolling_store, store
from tools.acquisition_resources.measurement import Measurement
from tools.acquisition_resources.fixture_transport import install_fixture
from tools.acquisition_resources.worker import source_identity
from tools import sentinel_operational_parity as parity

OBS = 'joint-local-rehearsal'
FIXTURES = ['synthetic HTTP provider', 'source-final and execution clocks',
            'reviewed producer/runtime authority', 'paper certificate authority',
            'simulated broker', 'no NAS backup medium']


def run(*, small, days):
    start = time.monotonic()
    state = Path('/var/lib/sentinel')
    state.mkdir(exist_ok=True)
    clock = [datetime(2026, 9, 24, 4, tzinfo=timezone.utc)]
    dsn = os.environ['RESOURCE_DSN']
    revision = os.environ['SENTINEL_IMAGE_SOURCE_REVISION']
    health, rows, results = None, None, []
    fixtures = list(FIXTURES)
    actual_identity = identity.rehearsal_identity()
    with MonkeyPatch.context() as patch, Measurement(state) as measure:
        from sentinel.core.formation import Formation
        advance_formation = Formation.advance
        def formation_progress(formed, published):
            result = advance_formation(formed, published)
            if formed.count % 10 == 0 or formed.complete:
                print(json.dumps(dict(event='formation_progress', phase=measure.phase_name,
                    sessions=formed.count, total=formed.plan.formation_sessions)), flush=True)
            return result
        patch.setattr(Formation, 'advance', formation_progress)
        patch.setattr(backup_runtime_authority, 'POLICY_MARKER', state/'no-backup-policy')
        patch.setattr(snapshots, '_now', lambda: clock[0])
        patch.setattr(initial, '_now', lambda conn: clock[0])
        patch.setattr(identity, 'require_feed_producer_identity', lambda: {
            'schema': 'local-rehearsal-producer/1', 'source_sha256': source_identity()})
        if small:
            from sentinel.feed import rolling_builder
            patch.setattr(rolling_builder, 'MIN_ADMITTED_COMMON_STOCKS', 30)
            fixtures.append('30-stock breadth floor for reduced-size rehearsal')
        install_fixture('http://provider:8080')
        conn = store.connect(dsn)
        if conn.execute("SELECT to_regclass('sentinel_snapshot_jobs')").fetchone()[0]:
            raise RuntimeError('requires a fresh disposable database')
        conn.rollback()
        with measure.phase('schema'):
            schema.ensure_schema(conn)
            from sentinel.feed import runtime_schema
            runtime_schema.migrate_feed_schema(conn)
            from tools.operational_rehearsal.paper import bind_fixture_account
            bind_fixture_account(conn)
            conn.commit()
            operational_schema.install_quiescent(conn)
            # Start tracking before initial publication produces mirror changes.
            for bootstrap in (journal.bootstrap_observation_integrity, mirror_projection.bootstrap_step):
                for _ in range(100):
                    progress = bootstrap(conn, limit=128)
                    conn.commit()
                    if progress['body']['stage'] == 'COMPLETE':
                        break
                else:
                    raise AssertionError('private account coverage bootstrap did not complete')
        with measure.phase('GO:acquisition-publication'):
            acquired = inputs.prepare(conn, target_session='2026-09-23', budget_seconds=7200)
            manifest = rolling_store.manifest(conn, acquired['candidate_id'])
            assert len(manifest.window.sessions) == 426
            table = normalized_layout.read_table(conn, 'BARS')
            rows = conn.execute(f'SELECT count(*) FROM {table} WHERE candidate_id=%s',
                                (acquired['candidate_id'],)).fetchone()[0]
            assert rows == (30 if small else 6000)*426
            payload_size = conn.execute('SELECT coalesce(octet_length(canonical_payload),pg_column_size(payload)),payload IS NULL '
                'FROM sentinel_snapshot_evidence WHERE evidence_sha256=%s',
                (manifest.reference_sha256,)).fetchone()
            assert manifest.provider == 'ALPACA_OPENFIGI' and payload_size[0] > 0
            conn.commit()
            print(json.dumps(dict(event='published', rows=rows, reference=payload_size)), flush=True)
        with measure.phase('GO:database-health'):
            conn.execute('ANALYZE sentinel_normalized_blocks')
            conn.execute('ANALYZE sentinel_candidate_blocks')
            conn.commit()
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            health = rolling_go_health.inspect(conn, database_url=dsn)
            assert all(health['checks'].values()), health
            conn.rollback()
        with measure.phase('GO:publication-coverage'):
            version, through = conn.execute(
                'SELECT version,window_end FROM sentinel_corpus_publications ORDER BY version DESC LIMIT 1').fetchone()
            for _ in range(100):
                proof = mirror_projection.advance(conn, checked_through=through,
                                                  publication_version=version, limit=128)
                conn.commit()
                if proof['body']['checked_publication'] == version:
                    mirror_projection.require_current(conn, current_frontier=through,
                                                      current_publication_version=version)
                    conn.rollback()
                    break
            else:
                raise AssertionError('private cold publication coverage did not catch up')
        # The dependency image is not a deployable certified image. Record its
        # actual environment separately; only the external certification gate is
        # supplied as a fixture, not any financial or storage calculation.
        patch.setattr(parity.identity, 'rehearsal_identity', lambda: {
            **actual_identity, 'environment': {**actual_identity['environment'],
                                              'compatible': True, 'lock_present': True}})
        with measure.phase('GO:formation-parity'):
            proof = parity.run_proof(conn, starting_cash='50000', expected_commit=revision)
            assert proof['verdict'] == 'PASS'
        with snapshots.pinned(conn) as (pub, _):
            subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
        patch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: {
            'schema': 'local-rehearsal-runtime/1', 'source_sha256': source_identity(),
            'validated_data_publication_sha256': subject})
        with measure.phase('runtime:formed-start-restart'):
            original = formation_bootstrap.write
            lost = [False]
            counts = []
            def write(c, name, formed, context):
                original(c, name, formed, context)
                counts.append(formed.count)
                # The parity pass has already sealed complete formation work.
                # Lose the acknowledgement of its actual durable adoption.
                if formed.complete and not lost[0]:
                    lost[0] = True
                    raise ConnectionError('deliberate lost formation acknowledgement')
            patch.setattr(formation_bootstrap, 'write', write)
            try:
                rolling_runtime.advance(conn, through='2026-09-23', observation_id=OBS, starting_cash=50000)
            except ConnectionError as exc:
                assert str(exc) == 'deliberate lost formation acknowledgement'
            else:
                raise AssertionError('lost-ack fault was not reached')
            conn.close()
            conn = store.connect(dsn)
            first = rolling_runtime.advance(conn, through='2026-09-23', observation_id=OBS, starting_cash=50000)
            assert counts == [126], 'completed parity work was replayed: ' + str(counts)
            assert first.state.state_hash == proof['proof']['result_state_sha256']
            assert first.state.wealth_core['episodes'], 'fixture must exercise held securities'
        for index in range(days+1):
            if index:
                day = calendar.next_session(first.session)
                clock[0] = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)+timedelta(days=1,hours=4)
                with measure.phase(f'daily-{index}:automatic-topup-transition'):
                    first = rolling_runtime.service_advance(conn, through=day, observation_id=OBS,
                        starting_cash=50000)
                    with snapshots.pinned(conn) as (_, bound):
                        assert len(rolling_store.manifest(conn, bound['candidate_id']).window.sessions) == 300
            with measure.phase(f'daily-{index}:paper-execute-reconcile-restart'):
                response = httpx.post('http://automation:8081/cycle', timeout=7200, json={
                    'session': first.session, 'now': clock[0].isoformat(),
                    'state_sha256': first.state.state_hash})
                response.raise_for_status()
                cycle = response.json()
                if index == 0:
                    assert cycle['commands'] > 0, 'initial held targets must exercise the execution membrane'
                print(json.dumps(dict(event='paper_cycle_complete', session=first.session,
                                      commands=cycle['commands'], guard_calls=cycle['guard_calls'])), flush=True)
                results.append(cycle)
            with measure.phase(f'daily-{index}:duplicate-wake'):
                before = conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0]
                conn.commit()
                conn.close()
                conn = store.connect(dsn)
                repeated = rolling_runtime.service_advance(conn, through=first.session,
                    observation_id=OBS, starting_cash=50000)
                assert repeated.state.state_hash == first.state.state_hash
                assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == before
                conn.rollback()
        httpx.post('http://automation:8081/complete', json={'cycles': days + 1}, timeout=30).raise_for_status()
        conn.close()
    return dict(event='result', verdict='PASS_SYNTHETIC_FUNCTION_COMPOSITION',
        seconds=time.monotonic()-start, fixtures=fixtures, source_sha256=source_identity(),
        actual_environment=actual_identity, price_rows=rows, daily_cycles=results,
        database_health=health, measurement=measure.result())


def main():
    faulthandler.register(signal.SIGUSR1)
    parser = argparse.ArgumentParser()
    parser.add_argument('--small', action='store_true')
    parser.add_argument('--days', type=int, choices=(1,2,3), default=2)
    args = parser.parse_args()
    print(json.dumps(run(small=args.small, days=args.days), sort_keys=True, default=str), flush=True)


if __name__ == '__main__':
    main()
