"""Production formation, interrupted acknowledgements and economic baselines."""
from copy import deepcopy
from decimal import Decimal

import pytest

from sentinel import formation_bootstrap as bootstrap, formed_origin
from sentinel import rolling_checkpoint as cp, rolling_initialization as init
from sentinel.feed import rolling_store
from sentinel.feed.rolling_contract import FormationWindow, PriceWindow, canonical_json, digest
from tests.sentinel.test_rolling_initialization import ready, start, OBS  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


def test_startup_window_does_not_relax_the_rolling_contract():
    startup = FormationWindow.through('2026-09-14')
    assert len(startup.sessions) == 252 + 126 + 1
    assert len(PriceWindow.through('2026-09-14').sessions) == 300
    with pytest.raises(ValueError, match='exactly 300'):
        PriceWindow(sessions=startup.sessions)
    with pytest.raises(ValueError, match='exactly 379'):
        FormationWindow(sessions=startup.sessions[:-1])


@pytest.mark.parametrize('stop', [0, 1, 63, 126])
def test_progress_commit_reply_loss_resumes_exactly_once(conn, ready, monkeypatch, stop):
    original = bootstrap.write
    committed = []
    def interrupted(conn, name, formed, context):
        original(conn, name, formed, context)
        committed.append((formed.count, formed.state.state_hash))
        if formed.count == stop:
            raise ConnectionError('formation acknowledgement lost')
    monkeypatch.setattr(bootstrap, 'write', interrupted)
    with pytest.raises(ConnectionError, match='acknowledgement lost'):
        start(conn, starting_cash=50_000)
    assert cp.read(conn) is None and cp.lineage_names(conn) == set()
    for table in ('sentinel_commands', 'sentinel_execution_plans', 'sentinel_fills'):
        assert conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0
    conn.rollback()
    def continue_once(conn, name, formed, context):
        assert formed.count > stop
        original(conn, name, formed, context)
        committed.append((formed.count, formed.state.state_hash))
    monkeypatch.setattr(bootstrap, 'write', continue_once)
    result = start(conn, starting_cash=50_000)
    assert [c for c, _ in committed] == list(range(127))
    assert result.strategy_nav == '50000' and result.strategy_cumulative_return == '0'
    assert result.state.wealth_core['episodes']
    identity = cp.read(conn).warmup_input_identity
    assert identity['initial_state_sha256'] == committed[-1][1]
    assert identity['plan']['metadata_policy'] == formed_origin.POLICY
    manifest = rolling_store.manifest(conn, ready['candidate_id'])
    assert len(manifest.window.sessions) == 379
    # After origin commitment, even a lost acknowledgement cannot rerun history.
    monkeypatch.setattr(bootstrap, 'prepare', lambda *a, **k: pytest.fail('formation repeated'))
    assert start(conn, starting_cash=50_000).state.state_hash == result.state.state_hash


@pytest.mark.parametrize('fault', ['context', 'rehashed_state', 'cursor'])
def test_progress_cannot_be_self_rehashed_or_rebound(conn, ready, monkeypatch, fault):
    original = bootstrap.write
    def interrupted(*args):
        original(*args)
        raise ConnectionError('stopped after warmup')
    monkeypatch.setattr(bootstrap, 'write', interrupted)
    with pytest.raises(ConnectionError):
        start(conn)
    name = 'formation-progress:v1:' + OBS
    row = conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()
    value = deepcopy(row[1])
    if fault == 'context':
        value['context']['snapshot_id'] = '0' * 64
    elif fault == 'rehashed_state':
        checkpoint = value['checkpoint']
        checkpoint['state']['wealth_core']['cash'] += 1
        checkpoint['state_sha256'] = digest(checkpoint['state'])
        checkpoint['sha256'] = digest({k: v for k, v in checkpoint.items() if k != 'sha256'})
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb,session=%s WHERE cursor_name=%s',
        (canonical_json(value), '2026-09-14' if fault == 'cursor' else row[0], name))
    conn.commit()
    monkeypatch.setattr(bootstrap, 'write', original)
    with pytest.raises(ValueError, match='FORMATION_PROGRESS_'):
        start(conn)
    assert cp.read(conn) is None


def test_authenticated_origin_cannot_change_context_or_seed(conn, ready):
    result = start(conn, starting_cash=50_000)
    store = init.shadow.PostgresShadowObservationStore(conn, observation_id=OBS)
    genesis = store.genesis()
    identity = genesis['warmup_input_identity']
    assert formed_origin.validate(identity, first_session=result.session) == identity
    # Start with a well-shaped field whose truth needs authentication, so the
    # signature falsifier cannot be masked by another semantic consistency gate.
    for field in ('formation_chain', 'initial_state_sha256', 'runtime_sha256', 'starting_cash'):
        forged = deepcopy(identity)
        forged[field] = '60000' if field == 'starting_cash' else '0' * 64
        forged['warmup_input_sha256'] = digest({k: v for k, v in forged.items() if k != 'warmup_input_sha256'})
        with pytest.raises(ValueError, match='AUTHENTICATION'):
            formed_origin.validate(forged, first_session=result.session)
    state = init.SessionState.from_dict(genesis['initial_state'])
    state.wealth_core['cash'] += 1
    with pytest.raises(ValueError, match='CONTEXT_CHANGED'):
        formed_origin.require_seed(identity, state=state, observation_id=OBS, starting_cash='50000',
            strategy=state.strategy_identity, runtime=genesis['runtime_identity'])


def test_first_funded_open_accounts_for_entry_and_preserves_formed_identity(conn, ready, operational_source, monkeypatch):
    from sentinel import rolling_daily, shadow_observation
    from tests.sentinel.test_rolling_daily import refresh
    first = start(conn)
    refresh(conn, operational_source, monkeypatch)
    second = rolling_daily.advance(conn, observation_id=OBS, starting_cash=100_000)
    store = shadow_observation.PostgresShadowObservationStore(conn, observation_id=OBS)
    row = store.records()[-1]
    economic = row['strategy_economics']
    assert economic['initial_deployment'] is True
    assert first.strategy_nav == '100000'
    assert set(economic['formed_startup_marks']) == {
        e['security_id'] for e in second.state.wealth_core['episodes'].values()}
    notional = sum((Decimal(str(e['current_shares'])) * Decimal(economic['formed_startup_marks'][e['security_id']])
                    for e in second.state.wealth_core['episodes'].values()), Decimal(0))
    allocation = Decimal(economic['held_allocation'])
    fee = Decimal('.001') * (allocation * notional / Decimal(economic['parent_core_open_equity']) + 1 - allocation)
    assert Decimal(economic['net_factor']) == Decimal(economic['gross_factor']) - fee
    assert Decimal(economic['net_factor']) < Decimal(economic['gross_factor'])
    conn.commit()
    assert rolling_daily.resume(conn, observation_id=OBS, starting_cash=100_000).strategy_nav == second.strategy_nav


def test_valid_obsolete_generation_is_retained_then_reformed_not_spliced(conn, ready, monkeypatch):
    original = bootstrap.write
    def interrupted(*args):
        original(*args)
        raise ConnectionError('stopped after first progress commit')
    monkeypatch.setattr(bootstrap, 'write', interrupted)
    with pytest.raises(ConnectionError):
        start(conn)
    name = 'formation-progress:v1:' + OBS
    row = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()[0]
    from sentinel.core.formation import FormationPlan
    plan = FormationPlan.model_validate(row['checkpoint']['plan'])
    # The migration helper accepts only authenticated prior progress. A new
    # publication's actual acquisition/admission remains the GO caller's job.
    next_plan = plan.model_copy(update={'source_sha256': '1' * 64})
    context = {**row['context'], 'plan_sha256': digest(next_plan.model_dump(by_alias=True)),
               'publication_sha256': '2' * 64, 'snapshot_id': '3' * 64}
    bootstrap.retire_previous_generation(conn, name, context, next_plan)
    assert conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone() is None
    retained = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
        ('formation-previous:v1:' + OBS,)).fetchone()[0]
    assert retained == row
    assert bootstrap.read(conn, name, context, next_plan) is None
    assert cp.read(conn) is None
