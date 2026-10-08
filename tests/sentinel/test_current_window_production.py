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
    if not options.get('formed'):
        # Preserve the original cash-start acceptance as a named historical
        # policy; formed production startup has its own integration witnesses.
        import sys
        from sentinel import strategy, automation_runtime
        from sentinel.feed import rolling_go_inputs
        from tools import sentinel_operational_parity
        config, identity = strategy.production_strategy()
        identity = {k:v for k,v in identity.items() if k != 'startup_policy'}
        cold = lambda: (config, identity)
        for module in (strategy, automation_runtime, rolling_go_inputs,
                       sentinel_operational_parity, sys.modules[__name__]):
            monkeypatch.setattr(module, 'production_strategy', cold)
    end = '2026-09-29' if options.get('observed') else '2026-09-14'
    from sentinel.feed.rolling_contract import CurrentFormationWindow
    cls = CurrentFormationWindow if options.get('formed') else PriceWindow
    axis = list(map(str, cls.through(end).sessions))
    template = deepcopy(data['TICKERS'][0])
    template['relatedtickers'] = 'AAA BBB'
    symbols = ['AAA', 'BBB', *[f'S{i:03}' for i in range(3, options.get('names', 25)+1)]]
    data['TICKERS'] = [{**template, 'ticker': symbol, 'permaticker': str(i), 'firstpricedate': axis[0], 'lastpricedate': end}
                       for i, symbol in enumerate(symbols, 1)]
    data['SEP'] = [{'ticker': symbol, 'date': day, 'open': str(50+i*.2+j*.03),
        'close': str(50+i*.2+j*.03), 'closeunadj': str((50+i*.2+j*.03)*2),
        'volume': '1' if options.get('illiquid_last') and symbol == symbols[-1] else '1000000',
        'lastupdated': '2026-09-15'}
        for i, day in enumerate(axis) for j, symbol in enumerate(symbols)]
    data['SFP'] = [{**data['SFP'][0], 'date': day, 'ticker': ticker, 'closeadj': str(600+i)}
                   for i, day in enumerate(axis) for ticker in ('SPY', 'BIL')]
    if options.get('bad_action'):
        data['ACTIONS'].append({
            'ticker': 'AAA', 'date': axis[-2], 'action': 'dividend',
            'name': 'unusable amount', 'value': '0',
            'contraticker': None, 'contraname': None})
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
    from sentinel.feed import snapshot_export
    probe_snapshot, download_snapshot = snapshot_export.probe_snapshot, snapshot_export.download_snapshot
    def probe(*args, **kwargs):
        return replace(probe_snapshot(*args, **kwargs), snapshot=now, refreshed=now)
    def download(*args, **kwargs):
        rows, evidence = download_snapshot(*args, **kwargs)
        return rows, dict(evidence, last_refreshed_time=now.isoformat())
    monkeypatch.setattr(snapshot_export, 'probe_snapshot', probe)
    monkeypatch.setattr(snapshot_export, 'download_snapshot', download)
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
    from tools import sentinel_operational_parity as parity
    from sentinel.feed import rolling_go_health
    from sentinel import rolling_runtime
    commit = 'a'*40
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', commit)
    monkeypatch.setattr(parity.identity, 'rehearsal_identity', lambda: {
        'identity_hash': 'b'*64, 'environment': {'compatible': True, 'pins_match': True,
        'sources_known': True, 'pin_drift': {}, 'lock_present': True,
        'sentinel_source': {'hash': 'c'*64}, 'wealth_core_source': {'hash': 'd'*64}}})
    report = parity.run_proof(conn, starting_cash='50000', expected_commit=commit)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'scripts'))
    import sentinel_go_validate as host
    assert host._operational_parity_report_valid(report, commit=commit, starting_cash='50000')
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    health = rolling_go_health.inspect(conn, database_url=conn.info.dsn)
    assert all(health['checks'].values()), health
    conn.rollback()
    evidence = observation_authority.current_warmup_evidence(conn, starting_cash=50_000)
    conn.commit()
    first = rolling_runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=50_000)
    assert window_policy.enabled(first.state.strategy_identity)
    assert evidence['measured_sessions'] == 300
    assert evidence['result_state_sha256'] == first.state.state_hash
    assert report['proof']['result_state_sha256'] == first.state.state_hash
    assert first.verification == 'VERIFIED'
    assert first.state.wealth_core['cash'] == 50_000
    assert not first.state.wealth_core['episodes'] and first.state.pending
    assert first.state.ledger['events'] == []
    assert origin.read(conn).status == 'COLD_START_COMMITTED'
    conn.commit()
    assert init.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == first.state.state_hash
    refresh(conn, operational_source, monkeypatch)
    second = rolling_runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=50_000)
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


@pytest.mark.parametrize('ready', [{'formed': True, 'bad_action': True}], indirect=True)
def test_unusable_source_action_excludes_one_security_and_survives_daily_refresh(
        conn, ready, operational_source, monkeypatch):
    from sentinel.feed import rolling_store

    sha = conn.execute('SELECT validation_sha256 FROM sentinel_snapshot_validations '
                       'WHERE candidate_id=%s', (ready['candidate_id'],)).fetchone()[0]
    validation = rolling_store.load_evidence(conn, sha)
    assert [item['security_id'] for item in validation['action_quarantine']] == ['1']
    first = start(conn)
    assert all(order['security_id'] != '1' for order in first.state.pending)
    refresh(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (_pub, binding):
        sha = conn.execute('SELECT validation_sha256 FROM sentinel_snapshot_validations '
                           'WHERE candidate_id=%s', (binding['candidate_id'],)).fetchone()[0]
        next_validation = rolling_store.load_evidence(conn, sha)
    assert [item['security_id'] for item in next_validation['action_quarantine']] == ['1']


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
def test_missing_held_witness_mark_refuses_and_preserves_book(conn, ready, operational_source, monkeypatch):
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
    from sentinel.shadow_observation import ShadowObservationRefused
    with pytest.raises(ShadowObservationRefused, match='unresolved recent-leadership return'):
        advance(conn)
    restored = daily.resume(conn, observation_id=OBS, starting_cash=50_000)
    assert restored.state.state_hash == held.state.state_hash
    assert any(e['security_id'] == sid for e in restored.state.wealth_core['episodes'].values())


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


def test_late_cash_event_preserves_history_and_advances_once(conn, ready, operational_source, monkeypatch):
    first = start(conn)
    refresh(conn, operational_source, monkeypatch)
    held = advance(conn)
    episode = next(iter(held.state.wealth_core['episodes'].values()))
    operational_source['ACTIONS'].append(dict(ticker=episode['ticker'], date=held.session,
        action='dividend', value='1', name='late correction', contraticker=None, contraname=None))
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    assert result.session == '2026-09-16'
    assert result.state.ledger['events'][:len(held.state.ledger['events'])] == held.state.ledger['events']
    sid = next(row['permaticker'] for row in operational_source['TICKERS'] if row['ticker'] == episode['ticker'])
    audit = next(row for row in result.state.last_evidence['cash_distributions']['observations'] if row['security_id'] == sid)
    # These shares were bought on the ex-date, so the new knowledge earns zero.
    assert audit['status'] == 'ZERO_ENTITLEMENT'
    assert not advance(conn).appended
    assert daily.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == result.state.state_hash


def test_unknown_cash_terms_continue_without_new_entitlement(conn, ready, operational_source, monkeypatch):
    start(conn)
    refresh(conn, operational_source, monkeypatch)
    held = advance(conn)
    episode = next(iter(held.state.wealth_core['episodes'].values()))
    operational_source['ACTIONS'].append(dict(ticker=episode['ticker'], date=held.session,
        action='dividend', value='0', name='unknown cash',
        contraticker=None, contraname=None))
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    assert result.session == '2026-09-16'
    assert result.state.ledger['events'][:len(held.state.ledger['events'])] == held.state.ledger['events']
    assert any(row['ticker'] == episode['ticker'] and row['reason'] == 'CASH_DISTRIBUTION_TERMS_PENDING'
               for row in result.state.last_evidence['cash_distributions']['pending'])
    assert daily.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == result.state.state_hash


def test_uniform_source_rebase_preserves_owned_quantities_and_peaks(conn, ready, operational_source, monkeypatch):
    start(conn)
    refresh(conn, operational_source, monkeypatch)
    held = advance(conn)
    refresh(conn, operational_source, monkeypatch, rebase=True)
    result = advance(conn)
    for key, episode in held.state.wealth_core['episodes'].items():
        current = result.state.wealth_core['episodes'][key]
        assert current['current_shares'] == episode['current_shares']
        assert current['episode_peak_split_adjusted_close'] == pytest.approx(episode['episode_peak_split_adjusted_close'])


def test_split_changes_shares_once_without_creating_a_stop(conn, ready, operational_source, monkeypatch):
    from decimal import Decimal
    start(conn)
    refresh(conn, operational_source, monkeypatch)
    held = advance(conn)
    key, episode = next((k, e) for k, e in held.state.wealth_core['episodes'].items() if e['ticker'] != 'AAA')
    original = op.prepare
    def split(*args, **kwargs):
        data = operational_source
        day = max(r['date'] for r in data['SEP'])
        for row in data['SEP']:
            if row['ticker'] == episode['ticker']:
                for field in ('open', 'close'):
                    row[field] = str(Decimal(row[field])/2)
                row['volume'] = str(Decimal(row['volume'])*2)
                if row['date'] == day:
                    row['closeunadj'] = str(Decimal(row['closeunadj'])/2)
        data['ACTIONS'].append(dict(ticker=episode['ticker'], date=day, action='split', value='2',
            name='fixture', contraticker=None, contraname=None))
        return original(*args, **kwargs)
    monkeypatch.setattr(op, 'prepare', split)
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    current = result.state.wealth_core['episodes'][key]
    assert current['current_shares'] == episode['current_shares']*2
    assert current['episode_peak_split_adjusted_close'] == pytest.approx(episode['episode_peak_split_adjusted_close'])
    assert not any(p['security_id'] == episode['security_id'] for p in result.state.pending)
    assert not advance(conn).appended


def test_go_replaces_unadmitted_old_policy_snapshot_on_same_frontier(conn, ready):
    from sentinel.feed import rolling_go_inputs
    job = op.enqueue(conn, strategy_sha256=digest('previous policy'), dependencies_sha256=digest('fixture'))
    conn.commit()
    previous = op.prepare(conn, job)
    current = rolling_go_inputs.prepare(conn, target_session='2026-09-14')
    assert current['status'] == 'PUBLISHED'
    assert current['data_version'] == previous['data_version'] + 1
    assert current['snapshot_id'] != previous['snapshot_id']
    again = rolling_go_inputs.prepare(conn, target_session='2026-09-14')
    assert again['status'] == 'ALREADY_CURRENT' and again['snapshot_id'] == current['snapshot_id']


def test_fresh_window_book_reaches_paper_plan_without_historical_formation(conn, ready, monkeypatch):
    from types import SimpleNamespace
    from sentinel import dual_plan_authority, rolling_runtime
    from sentinel.authority import load_rollout_state
    from tests.sentinel import test_rolling_paper_inputs as paper_checks
    monkeypatch.setattr(paper_checks, 'approve', lambda conn: rolling_runtime.advance(
        conn, through='2026-09-14', observation_id=OBS, starting_cash=50_000))
    shadow, bound, broker = paper_checks.gateway.__wrapped__(conn, ready, monkeypatch, SimpleNamespace())
    prepared = paper_checks.prepare(conn, broker, dual_shadow_starting_cash=50_000)
    assert prepared.state_fingerprint == shadow.state.state_hash
    assert shadow.state.wealth_core['cash'] == 50_000 and not shadow.state.wealth_core['episodes']
    assert prepared.plan.opening_intents
    proof = dual_plan_authority.rederive_plan(conn, plan=prepared.plan, binding=bound,
        rollout_state=load_rollout_state(conn), expected_shadow_result=shadow)
    assert proof['verdict'] == 'MATCH'
    conn.rollback()
    repeated = paper_checks.prepare(conn, broker, dual_shadow_starting_cash=50_000)
    assert repeated.plan.to_dict() == prepared.plan.to_dict()
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
