import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from sentinel.execution import journal, alpaca, reconcile
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.feed_inputs import BrokerSecurityResolver
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState, RuntimeState
from tests.sentinel.test_journal_and_reconcile import conn, pg, cmd, DEPLOY


def _record(conn, *, count=1, positions=14):
    broker = SimulatedBroker()
    for index in range(positions):
        broker.seed_position(BrokerInstrument(f's{index}', f'S{index}', f'asset-{index}'), '10')
    observation = asyncio.run(broker.observe())
    result = []
    for index in range(count):
        result.append(journal.record_observation(conn, replace(observation,
            observed_at=observation.observed_at+timedelta(seconds=index)), 'RUNNING'))
    return result


def _edit(conn, table, sql, params):
    assert table in {'sentinel_observations', 'sentinel_observation_provenance',
                     'sentinel_processed_sessions'}
    conn.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
    conn.execute(sql, params)
    conn.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
    conn.commit()


def test_compact_witness_reconstructs_full_recovery_payload_and_saves_bytes(conn):
    seq = _record(conn)[0]
    full = alpaca.load_provenance(conn, seq)
    witness = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
        (f'broker-observation:v4:{seq}',)).fetchone()[0]
    assert full['kind'] == 'broker-observation/v4'
    assert witness['kind'] == journal.OBSERVATION_WITNESS_KIND
    assert 'positions' not in witness and 'orders' not in witness
    assert len(full['positions']) == 14
    assert len(json.dumps(witness)) < len(json.dumps(full)) / 2
    journal.require_observation_integrity(conn)


def test_legacy_full_observation_payload_remains_readable(conn):
    seq = _record(conn)[0]
    full = journal.load_observation_payload(conn, seq)
    _edit(conn, 'sentinel_processed_sessions',
        'UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
        (json.dumps(full), f'broker-observation:v4:{seq}'))
    assert alpaca.load_provenance(conn, seq) == full
    journal.require_observation_integrity(conn)


@pytest.mark.parametrize('fault', ['missing_witness', 'missing_provenance', 'primary',
    'provenance', 'witness_digest', 'provenance_digest', 'cross_account', 'extra_field'])
def test_compact_witness_refuses_tampering_and_partial_restore(conn, fault):
    seq = _record(conn)[0]
    key = f'broker-observation:v4:{seq}'
    if fault == 'missing_witness':
        _edit(conn, 'sentinel_processed_sessions',
            'DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (key,))
    elif fault == 'missing_provenance':
        _edit(conn, 'sentinel_observation_provenance',
            'DELETE FROM sentinel_observation_provenance WHERE observation_seq=%s', (seq,))
    elif fault == 'primary':
        _edit(conn, 'sentinel_observations',
            'UPDATE sentinel_observations SET positions=%s::jsonb WHERE seq=%s',
            (json.dumps({'s0': '11'}), seq))
    elif fault == 'provenance':
        raw = conn.execute('SELECT positions FROM sentinel_observation_provenance WHERE observation_seq=%s',
            (seq,)).fetchone()[0]
        raw['positions'][0]['quantity'] = '11'
        _edit(conn, 'sentinel_observation_provenance',
            'UPDATE sentinel_observation_provenance SET positions=%s::jsonb WHERE observation_seq=%s',
            (json.dumps(raw), seq))
    elif fault == 'provenance_digest':
        _edit(conn, 'sentinel_observation_provenance',
            'UPDATE sentinel_observation_provenance SET canonical_payload_sha256=%s WHERE observation_seq=%s',
            ('f'*64, seq))
    else:
        patch = {'canonical_payload_sha256': 'f'*64} if fault == 'witness_digest' else (
            {'account_id': 'other'} if fault == 'cross_account' else {'unexpected': True})
        _edit(conn, 'sentinel_processed_sessions',
            'UPDATE sentinel_processed_sessions SET state=state || %s::jsonb WHERE cursor_name=%s',
            (json.dumps(patch), key))
    with pytest.raises(journal.ObservationEvidenceUncertifiable):
        journal.require_observation_integrity(conn)
    with pytest.raises(journal.ObservationEvidenceUncertifiable):
        alpaca.load_provenance(conn, seq)


def test_full_scrub_finds_early_and_late_page_corruption(conn, monkeypatch):
    monkeypatch.setattr(journal, 'OBSERVATION_INTEGRITY_PAGE_SIZE', 2)
    seqs = _record(conn, count=5)
    _edit(conn, 'sentinel_processed_sessions',
        "UPDATE sentinel_processed_sessions SET state=state || %s::jsonb WHERE cursor_name=ANY(%s)",
        (json.dumps({'account_id': 'other'}), [f'broker-observation:v4:{seqs[0]}',
                                               f'broker-observation:v4:{seqs[-1]}']))
    assert journal.observation_integrity_gaps(conn) == (seqs[0], seqs[-1])


@pytest.mark.parametrize('observed_uuid', ['new-provider', 'unproven-provider'])
def test_reconciliation_uses_authenticated_current_uuid_and_retains_old_commands(
        conn, observed_uuid):
    old = BrokerInstrument('SEC-AAA', 'AAA', 'old-provider')
    command = replace(cmd(instrument=old, state=CommandState.FILLED, filled='10'),
        filled_average_price=Decimal('100'), broker_order_id='old-order')
    journal.save_command(conn, command)
    broker = SimulatedBroker()
    broker._resolve = BrokerSecurityResolver('ALPACA_OPENFIGI',
        lambda *_args: 'SEC-AAA', {'SEC-AAA': 'new-provider'})
    broker.seed_position(replace(old, broker_id=observed_uuid), '10')
    result = asyncio.run(reconcile.reconcile(broker=broker, conn=conn,
        binding=None, deployment=DEPLOY, informational_current_book=True))
    expected = (RuntimeState.RUNNING if observed_uuid == 'new-provider'
                else RuntimeState.RECONCILING)
    assert result.runtime_state is expected
    assert journal.load_commands(conn, DEPLOY)[0].instrument.broker_id == 'old-provider'


@pytest.mark.parametrize('loss', ['interior', 'all'])
@pytest.mark.parametrize('legacy', [False, True])
def test_observation_scrub_refuses_witnesses_after_primary_rows_are_lost(conn, loss, legacy):
    sequences = _record(conn, count=3)
    missing = [sequences[1]] if loss == 'interior' else sequences
    if legacy:
        for seq in missing:
            full = journal.load_observation_payload(conn, seq)
            _edit(conn, 'sentinel_processed_sessions',
                'UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
                (json.dumps(full), f'broker-observation:v4:{seq}'))
    conn.execute('DELETE FROM sentinel_observation_provenance WHERE observation_seq=ANY(%s)',
                 (missing,))
    conn.execute('DELETE FROM sentinel_observations WHERE seq=ANY(%s)', (missing,))
    conn.commit()
    assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions '
                        'WHERE cursor_name=ANY(%s)',
                        ([f'broker-observation:v4:{seq}' for seq in missing],)).fetchone()[0] == len(missing)
    with pytest.raises(journal.ObservationEvidenceUncertifiable, match='MISSING_PRIMARY_OBSERVATION'):
        journal.require_observation_integrity(conn)


@pytest.mark.parametrize('fault,reason', [
    ('key', 'CANONICAL_SEQUENCE_DISAGREEMENT'),
    ('sequence', 'CANONICAL_SEQUENCE_DISAGREEMENT'),
    ('account', 'CANONICAL_IDENTITY_DISAGREEMENT'),
    ('time', 'MALFORMED_CANONICAL_EVIDENCE'),
    ('backdated_session', 'PROCESSED_SESSION_DISAGREEMENT'),
    ('backdated_observed', 'MALFORMED_CANONICAL_EVIDENCE'),
])
def test_orphan_witness_metadata_cannot_hide_loss(conn, fault, reason):
    seq = _record(conn)[0]
    key = f'broker-observation:v4:{seq}'
    conn.execute('DELETE FROM sentinel_observation_provenance WHERE observation_seq=%s', (seq,))
    conn.execute('DELETE FROM sentinel_observations WHERE seq=%s', (seq,))
    if fault == 'key':
        conn.execute('UPDATE sentinel_processed_sessions SET cursor_name=%s WHERE cursor_name=%s',
                     ('broker-observation:v4:noncanonical', key))
    elif fault == 'backdated_session':
        conn.execute('UPDATE sentinel_processed_sessions SET session=session-1 WHERE cursor_name=%s',
                     (key,))
    else:
        observed_at = conn.execute(
            "SELECT state->>'observed_at' FROM sentinel_processed_sessions WHERE cursor_name=%s",
            (key,)).fetchone()[0]
        patch = ({'observation_seq': seq+1} if fault == 'sequence' else
                 {'account_id': 'foreign'} if fault == 'account' else
                 {'observed_at': (datetime.fromisoformat(observed_at)
                                  - timedelta(days=1)).isoformat()}
                 if fault == 'backdated_observed' else {'observed_at': 'invalid'})
        conn.execute('UPDATE sentinel_processed_sessions SET state=state || %s::jsonb '
                     'WHERE cursor_name=%s', (json.dumps(patch), key))
    conn.commit()
    issues = journal.observation_integrity_issues(conn)
    assert len(issues) == 1
    assert 'MISSING_PRIMARY_OBSERVATION' in issues[0].reasons
    assert reason in issues[0].reasons


def test_prebinding_orphan_from_previous_account_stays_outside_current_scrub(conn):
    seq = _record(conn)[0]
    observed_at = conn.execute('SELECT observed_at FROM sentinel_observations WHERE seq=%s',
                               (seq,)).fetchone()[0]
    conn.execute('DELETE FROM sentinel_observation_provenance WHERE observation_seq=%s', (seq,))
    conn.execute('DELETE FROM sentinel_observations WHERE seq=%s', (seq,))
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s,broker_account_id=%s WHERE id=1',
                 (observed_at + timedelta(seconds=1), 'next-account'))
    conn.commit()
    journal.require_observation_integrity(conn)


def test_unused_sequence_numbers_are_not_missing_observations(conn):
    _record(conn)
    conn.execute("SELECT nextval(pg_get_serial_sequence('sentinel_observations','seq'))")
    conn.commit()
    _record(conn)
    journal.require_observation_integrity(conn)


@pytest.mark.parametrize('current_copy', ['primary', 'provenance', 'witness', 'missing_witness'])
def test_each_retained_observation_copy_preserves_current_account_scope(conn, current_copy):
    seq = _record(conn)[0]
    key = f'broker-observation:v4:{seq}'
    observed_at = conn.execute('SELECT observed_at FROM sentinel_observations WHERE seq=%s',
                               (seq,)).fetchone()[0]
    old_time = observed_at - timedelta(days=1)
    if current_copy != 'primary':
        _edit(conn, 'sentinel_observations',
              'UPDATE sentinel_observations SET observed_at=%s WHERE seq=%s', (old_time, seq))
    if current_copy not in ('provenance', 'missing_witness'):
        _edit(conn, 'sentinel_observation_provenance',
              'UPDATE sentinel_observation_provenance SET observed_at=%s WHERE observation_seq=%s',
              (old_time, seq))
    if current_copy == 'missing_witness':
        _edit(conn, 'sentinel_processed_sessions',
              'DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (key,))
    elif current_copy != 'witness':
        patch = json.dumps({'observed_at': old_time.isoformat(), 'started_at': old_time.isoformat()})
        _edit(conn, 'sentinel_processed_sessions',
              'UPDATE sentinel_processed_sessions SET session=%s,state=state || %s::jsonb '
              'WHERE cursor_name=%s', (old_time.date(), patch, key))
    with pytest.raises(journal.ObservationEvidenceUncertifiable):
        journal.require_observation_integrity(conn)


def test_concordant_prebinding_observations_stay_outside_current_account_scrub(conn):
    seq = _record(conn)[0]
    observed_at = conn.execute('SELECT observed_at FROM sentinel_observations WHERE seq=%s',
                               (seq,)).fetchone()[0]
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s,broker_account_id=%s WHERE id=1',
                 (observed_at + timedelta(seconds=1), 'next-account'))
    conn.commit()
    journal.require_observation_integrity(conn)
