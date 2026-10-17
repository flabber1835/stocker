import asyncio
import json
from dataclasses import replace
from datetime import timedelta
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
