"""Production source -> publication -> GO preview -> state -> daily restart."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sentinel import rolling_initialization as init, rolling_checkpoint as origin
from sentinel import rolling_daily as daily, rolling_daily_checkpoint as checkpoint
from sentinel import schema, shadow_runtime, observation_authority
from sentinel.core import rolling_continuity, window_policy
from sentinel.feed import operational_snapshot as op
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.strategy import production_strategy
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_daily import refresh, OBS


@pytest.fixture
def ready(conn, operational_source, monkeypatch, request):
    schema.ensure_schema(conn)
    data = operational_source
    options = getattr(request, 'param', {})
    end = '2026-09-29' if options.get('observed') else '2026-09-14'
    axis = list(map(str, PriceWindow.through(end).sessions))
    template = deepcopy(data['TICKERS'][0])
    template['relatedtickers'] = 'AAA BBB'
    symbols = ['AAA', 'BBB', *[f'S{i:03}' for i in range(3, options.get('names', 25)+1)]]
    data['TICKERS'] = [{**template, 'ticker': symbol, 'permaticker': str(i), 'firstpricedate': axis[0], 'lastpricedate': end}
                       for i, symbol in enumerate(symbols, 1)]
    data['SEP'] = [{'ticker': symbol, 'date': day, 'open': str(50+i*.2+j*.03),
        'close': str(50+i*.2+j*.03), 'closeunadj': str((50+i*.2+j*.03)*2),
        'volume': '1000000', 'lastupdated': '2026-09-15'}
        for i, day in enumerate(axis) for j, symbol in enumerate(symbols)]
    data['SFP'] = [{**data['SFP'][0], 'date': day, 'ticker': ticker, 'closeadj': str(600+i)}
                   for i, day in enumerate(axis) for ticker in ('SPY', 'BIL')]
    if options.get('observed'):
        probe = json.loads((Path(__file__).parent/'fixtures/current_window_go_20260930.json').read_text())['probe']
        rename = options.get('rename', False)
        def renamed(value):
            text = json.dumps(value)
            if rename:
                text = text.replace('FJDIU', 'PROBEU').replace('FJDI', 'PROBE').replace('6401378', '9001378').replace('6400999', '9000999')
            return json.loads(text)
        data['TICKERS'].extend(renamed(probe['tickers']['rows']))
        data['ACTIONS'].extend(renamed(probe['actions']['rows']))
        observed = renamed(probe['sep']['rows'])
        # The diagnostic only contains five sessions. Older primary-class rows
        # below are synthetic background, not a claim about the NAS corpus.
        primary = 'PROBE' if rename else 'FJDI'
        data['SEP'].extend(dict(ticker=primary, date=day, open='10', close='10',
            closeunadj='10', volume='1000', lastupdated=end)
            for day in axis if '2026-08-04' <= day < '2026-09-23')
        data['SEP'].extend(observed)
        from sentinel.feed import calendar
        monkeypatch.setattr(calendar, 'latest_closed_session', lambda now=None: end)
    now = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    from datetime import timedelta
    now += timedelta(days=1, hours=4)
    monkeypatch.setattr(op, '_now', lambda: now)
    _, strategy = production_strategy()
    job = op.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest('window fixture'))
    conn.commit()
    binding = op.prepare(conn, job)
    with op.pinned(conn) as (pub, _):
        subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: {
        'schema': 'test-reviewed-runtime/1', 'validated_data_publication_sha256': subject})
    monkeypatch.setattr(init, '_now', lambda conn: now)
    return binding


def start(conn):
    return init.initialize(conn, observation_id=OBS, starting_cash=50_000)


def advance(conn):
    return daily.advance(conn, observation_id=OBS, starting_cash=50_000)


def test_fresh_start_matches_go_then_daily_and_restart(conn, ready, operational_source, monkeypatch):
    evidence = observation_authority.current_warmup_evidence(conn, starting_cash=50_000)
    conn.commit()
    first = start(conn)
    assert window_policy.enabled(first.state.strategy_identity)
    assert evidence['measured_sessions'] == 300
    assert evidence['result_state_sha256'] == first.state.state_hash
    assert first.state.wealth_core['cash'] == 50_000
    assert not first.state.wealth_core['episodes'] and first.state.pending
    assert first.state.ledger['events'] == []
    assert origin.read(conn).status == 'COLD_START_COMMITTED'
    conn.commit()
    assert init.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == first.state.state_hash
    refresh(conn, operational_source, monkeypatch)
    second = advance(conn)
    assert second.state.wealth_core['episodes'] and second.state.wealth_core['cash'] < 50_000
    assert checkpoint.read(conn).input_value['current_window_continuity']['prior_state_sha256'] == first.state.state_hash
    conn.commit()
    assert daily.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == second.state.state_hash
    assert not advance(conn).appended


def test_unheld_history_revision_does_not_replay_ownership(conn, ready, operational_source, monkeypatch):
    first = start(conn)
    live = {p['security_id'] for p in first.state.pending}
    ticker = next(r['ticker'] for r in operational_source['TICKERS'] if r['permaticker'] not in live)
    row = next(r for r in operational_source['SEP'] if r['ticker'] == ticker and r['date'] == '2026-09-10')
    row['volume'] = '1234567'
    refresh(conn, operational_source, monkeypatch)
    second = advance(conn)
    assert second.session == '2026-09-15'
    assert all(e['session'] == second.session for e in second.state.ledger['events'])


def test_feature_commitment_cannot_be_rebound(conn, ready, operational_source, monkeypatch):
    first = start(conn)
    previous = origin.read(conn).snapshot
    conn.commit()
    refresh(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (pub, binding):
        material, anchors, proof = rolling_continuity.prepare(conn, prior=first.state,
            previous_binding=previous, publication=pub, binding=binding)
        published = replace(init._published(material, pub), history_proof=proof, signal_basis_anchors=anchors)
        broken = deepcopy(published.window_features)
        broken['signals'][0]['eligible'] = not broken['signals'][0]['eligible']
        from sentinel.core.kernel import advance_session
        with pytest.raises(ValueError, match='FEATURE_PROOF_CHANGED'):
            advance_session(first.state, replace(published, window_features=broken),
                controller_config=production_strategy()[0], strategy_identity=first.state.strategy_identity)


@pytest.mark.parametrize('ready', [{'observed': True, 'names': 200},
                                  {'observed': True, 'names': 200, 'rename': True}], indirect=True)
def test_observed_onset_gap_and_renamed_equivalent_publish_and_trade(conn, ready, operational_source, monkeypatch):
    from sentinel.feed import rolling_store
    sha = conn.execute('SELECT validation_sha256 FROM sentinel_snapshot_validations WHERE candidate_id=%s',
                       (ready['candidate_id'],)).fetchone()[0]
    validation = rolling_store.load_evidence(conn, sha)
    first = start(conn)
    assert first.state.pending
    assert not {'6401378', '6400999', '9001378', '9000999'} & {p['security_id'] for p in first.state.pending}
    assert validation['coverage']['schema'] == 'sentinel.current-window-coverage/1'
    assert validation['coverage']['missing_eligible_total'] == 2
    assert validation['coverage']['reviewed_exceptions_applied_total'] == 0
    refresh(conn, operational_source, monkeypatch)
    second = advance(conn)
    assert len(second.state.wealth_core['episodes']) == 20
    assert daily.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == second.state.state_hash


@pytest.mark.parametrize('ready', [{'names': 101}], indirect=True)
def test_missing_held_mark_preserves_book_and_blocks_admissions(conn, ready, operational_source, monkeypatch):
    first = start(conn)
    refresh(conn, operational_source, monkeypatch)
    held = advance(conn)
    sid = next(iter(held.state.wealth_core['episodes'].values()))['security_id']
    ticker = next(r['ticker'] for r in operational_source['TICKERS'] if r['permaticker'] == sid)
    # Remove the row that refresh would clone, but retain the prior publication
    # anchor row. Build the next source day then remove only its held mark.
    original = op.prepare
    def missing(*args, **kwargs):
        data = operational_source
        day = max(r['date'] for r in data['SEP'])
        data['SEP'][:] = [r for r in data['SEP'] if (r['date'], r['ticker']) != (day, ticker)]
        return original(*args, **kwargs)
    monkeypatch.setattr(op, 'prepare', missing)
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    assert any(e['security_id'] == sid for e in result.state.wealth_core['episodes'].values())
    assert not any(p['kind'] == 'BUY' for p in result.state.pending)


def test_lost_commit_reply_resumes_without_duplicate_fills(conn, ready, operational_source, monkeypatch):
    start(conn)
    refresh(conn, operational_source, monkeypatch)
    original = checkpoint.write
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        conn.commit()
        raise ConnectionError('commit reply lost')
    monkeypatch.setattr(checkpoint, 'write', lost)
    with pytest.raises(ConnectionError, match='reply lost'):
        advance(conn)
    expected = checkpoint.read(conn).state_sha256
    conn.commit()
    recovered = advance(conn)
    assert recovered.state.state_hash == expected and not recovered.appended
