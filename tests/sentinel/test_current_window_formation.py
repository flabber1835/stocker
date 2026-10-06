"""Selected production formation and bounded source/restart falsifiers."""
import os
import pytest

from sentinel import rolling_checkpoint as origin, rolling_initialization as init
from sentinel import formation_bootstrap, observation_authority, observation_startup
from sentinel.core import formation_features, formation_preview, window_features, window_policy
from sentinel.core.formation_inputs import FormationInputs
from sentinel.core.history import FormationWindowProof, require_history_compatible
from sentinel.feed import operational_snapshot as op, rolling_store
from sentinel.feed.rolling_contract import CurrentFormationWindow, PriceWindow, digest
from tests.sentinel.test_current_window_production import ready, start, advance  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_daily import refresh, OBS


def test_window_and_identity_cannot_silently_use_cash_start():
    from sentinel.strategy import production_strategy
    from sentinel.core.formation import FormationPlan
    _, strategy = production_strategy()
    assert window_policy.formed(strategy)
    window = CurrentFormationWindow.through('2026-09-14')
    assert len(window.sessions) == 426
    with pytest.raises(ValueError):
        PriceWindow(sessions=window.sessions)
    with pytest.raises(ValueError, match='warmup differs'):
        FormationPlan(end='2026-09-11', strategy=strategy, source_sha256='a'*64)


def test_same_snapshot_proof_cannot_cross_publication_or_skip_session():
    args = dict(prior_version=3, version=3, last_processed_session='2026-09-11',
                session='2026-09-14', prior_state_sha256='a'*64)
    proof = FormationWindowProof(prior_version=3, publication_version=3,
        prior_session='2026-09-11', session='2026-09-14', prior_state_sha256='a'*64,
        snapshot_sha256='b'*64, features_sha256='c'*64, protected_economics_sha256='d'*64)
    require_history_compatible(**args, proof=proof.model_dump(by_alias=True))
    for change in ({'version':4}, {'session':'2026-09-15'}, {'prior_state_sha256':'e'*64}):
        with pytest.raises(ValueError, match='BINDING_CHANGED'):
            require_history_compatible(**{**args, **change}, proof=proof.model_dump(by_alias=True))
    # Even a self-consistent proof cannot make formation cross generations.
    changed = proof.model_copy(update={'publication_version':4})
    with pytest.raises(ValueError, match='BINDING_CHANGED'):
        require_history_compatible(**{**args, 'version':4}, proof=changed.model_dump(by_alias=True))


def test_feature_loader_fences_future_and_expired_rows(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from sentinel.feed import calendar
    from sentinel.feed.rolling_contract import CanonicalBar
    from stock_strategy_shared.wealth_core.feed import SecurityMeta
    window = CurrentFormationWindow.through('2026-09-14')
    day = str(window.sessions[-2])
    rows = [CanonicalBar(security_id='1',ticker='ABC',session=s,close_signal=10.,
        close_unadjusted=20.,open_unadjusted=20.,volume=1e6,split_ratio=1.,dividend_per_share=0.)
        for s in (window.sessions[0],window.sessions[-2],window.sessions[-1])]
    def stream(conn, query, params):
        selected = rows if 'session BETWEEN %s AND %s' not in query else [
            r for r in rows if params[1] <= str(r.session) <= params[2]]
        return nullcontext(iter([tuple(getattr(r,c) for c in rolling_store.BAR_COLUMNS) for r in selected]))
    monkeypatch.setattr(window_features.store,'streaming_cursor',stream)
    refs = SimpleNamespace(candidate_id='candidate',manifest=SimpleNamespace(window=window,snapshot_id='b'*64),
        current_metadata=lambda **kw:({'1':SecurityMeta('1','ABC','Domestic Common Stock','1',
            first_session=str(window.start))},{}),resolver=SimpleNamespace(resolve=lambda *a:'1'))
    prior = SimpleNamespace(state_hash='a'*64,wealth_core={},pending=[],median5={})
    value = window_features.load(None,prior=prior,refs=refs,
        publication=SimpleNamespace(window_end=str(window.end),version=1),session=day)
    assert value.sessions == tuple(calendar.previous_sessions(day,300))
    assert len(value.signals)==1 and value.signals[0].raw_close==20.


def test_kernel_requires_formation_policy_for_same_snapshot_proof():
    from types import SimpleNamespace
    from sentinel.controller.machine import Controller
    from sentinel.core.kernel import advance_session
    from sentinel.core.session import SessionState
    from sentinel.core.history import FORMATION_SCHEMA
    from sentinel.strategy import production_strategy
    config, identity = production_strategy()
    identity = {k:v for k,v in identity.items() if k != 'startup_policy'}
    prior = SessionState.fresh(starting_cash=50000, controller=Controller(config), strategy_identity=identity)
    published = SimpleNamespace(session='2026-09-14', data_version=1,
                                history_proof={'schema':FORMATION_SCHEMA})
    with pytest.raises(ValueError, match='CURRENT_WINDOW_FORMATION_POLICY_REQUIRED'):
        advance_session(prior, published, controller_config=config, strategy_identity=identity)


@pytest.mark.parametrize('fault',[None,'cold','short_axis','missing_formation','different_controller'])
def test_selected_observation_requires_formed_proof(fault):
    from sentinel.strategy import production_strategy
    from sentinel.authority import AuthorityRefused
    from sentinel.feed import calendar
    config,strategy=production_strategy()
    axis=calendar.previous_sessions('2026-09-14',426)
    value=dict(schema=observation_startup.WINDOW_FORMED_SCHEMA,warmup_sessions=299,
        measured_sessions=426,decision_session=axis[-1],first_session=axis[0],
        formation=dict(schema='sentinel.formation-parity/1',policy='CURRENT_INFORMATION_INITIALIZATION_V1',
            sessions=126,end=axis[-2],chain_sha256='a'*64,state_sha256='b'*64,source_sha256='c'*64))
    controller=config.digest
    if fault=='cold':
        value['schema']=observation_startup.WINDOW_SCHEMA
    elif fault=='short_axis':
        value['measured_sessions']=300
    elif fault=='missing_formation':
        value.pop('formation')
    elif fault=='different_controller':
        controller='d'*64
    if fault:
        with pytest.raises(AuthorityRefused):
            observation_startup.require(value,strategy_sha256=digest(strategy),controller_sha256=controller)
    else:
        observation_startup.require(value,strategy_sha256=digest(strategy),controller_sha256=controller)


@pytest.mark.parametrize('ready', [{'formed': True, 'illiquid_last': True, 'names':26}], indirect=True)
def test_selected_formation_go_restart_and_daily_preserve_simplifications(conn, ready, operational_source, monkeypatch):
    from tools import sentinel_operational_parity as parity
    from pathlib import Path
    from sentinel.authority import AuthorityRefused
    from sentinel.core.kernel import advance_session
    from sentinel.strategy import production_strategy
    from sentinel.feed import calendar
    config, strategy = production_strategy()
    slices = []
    original_load = formation_features.FormationFeatures.load
    def bounded(loader, **kwargs):
        result = original_load(loader, **kwargs)
        assert list(result.sessions) == calendar.previous_sessions(result.sessions[-1], 300)
        assert all(len(ring.indices) <= 300 for ring in loader.rings.values())
        assert all(loader.axis[index] in result.sessions
                   for ring in loader.rings.values() for index in ring.indices)
        slices.append(result.sessions)
        return result
    monkeypatch.setattr(formation_features.FormationFeatures, 'load', bounded)
    with op.pinned(conn) as (pub, binding):
        source = FormationInputs(conn, binding, pub)
        seed, warmup, published, formation = formation_preview.run(
            source, capital=50000, strategy=strategy, data_version=pub.version)
        assert len(slices) == 127 and len(set(slices)) == 127
        assert seed.last_processed_session == source.axis[-2]
        assert seed.wealth_core['episodes'] and seed.shadow_nav_history
        assert warmup['session_count'] == 299 and formation['sessions'] == 126
        expected = advance_session(seed, published, controller_config=config, strategy_identity=strategy)
        # SQL must exclude old/future rows before materialization.
        inspected = []
        original_cursor = window_features.store.streaming_cursor
        def cursor(conn, sql, params):
            inspected.append(params)
            assert 'session BETWEEN %s AND %s' in sql
            return original_cursor(conn, sql, params)
        with monkeypatch.context() as scoped:
            scoped.setattr(window_features.store, 'streaming_cursor', cursor)
            window_features.load(conn, prior=seed, refs=source.refs, publication=pub, session=source.axis[-2])
        assert inspected[-1][1:] == (calendar.previous_sessions(source.axis[-2], 300)[0], source.axis[-2])
    evidence = observation_authority.current_warmup_evidence(conn, starting_cash=50000)
    conn.commit()
    assert evidence['schema'] == observation_startup.WINDOW_FORMED_SCHEMA
    assert evidence['measured_sessions'] == 426 and evidence['result_state_sha256'] == expected.state_hash
    for field, value in [('formation', None), ('measured_sessions',300), ('schema', observation_startup.WINDOW_SCHEMA)]:
        broken = {**evidence, field:value}
        with pytest.raises(AuthorityRefused):
            observation_startup.require(broken, strategy_sha256=digest(strategy), controller_sha256=config.digest)
    commit = 'a'*40
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', commit)
    monkeypatch.setattr(parity.identity, 'rehearsal_identity', lambda: {
        'identity_hash':'b'*64, 'environment':{'compatible':True, 'pins_match':True,
        'sources_known':True, 'pin_drift':{}, 'lock_present':True,
        'sentinel_source':{'hash':'c'*64}, 'wealth_core_source':{'hash':'d'*64}}})
    report = parity.run_proof(conn, starting_cash='50000', expected_commit=commit)
    root = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
    monkeypatch.syspath_prepend(str(root/'scripts'))
    import sentinel_go_validate as host
    assert host._operational_parity_report_valid(report, commit=commit, starting_cash='50000')
    assert report['proof']['result_state_sha256'] == expected.state_hash
    # Lose a committed progress reply, then resume rather than replay the prefix.
    # Exercise the database checkpoint fallback with no disposable preview cache.
    # Cache reuse itself is covered by test_unattended_formation_recovery.
    from sentinel import formation_cache
    monkeypatch.setattr(formation_cache, 'location', lambda plan: None)
    original_write = formation_bootstrap.write
    seen = []
    def lose(conn, name, formed, context):
        original_write(conn, name, formed, context)
        seen.append(formed.count)
        if formed.count == 63:
            raise ConnectionError('lost formation reply')
    monkeypatch.setattr(formation_bootstrap, 'write', lose)
    with pytest.raises(ConnectionError):
        start(conn)
    assert origin.read(conn) is None
    def resume(conn, name, formed, context):
        assert formed.count > 63
        original_write(conn, name, formed, context)
        seen.append(formed.count)
    monkeypatch.setattr(formation_bootstrap, 'write', resume)
    first = start(conn)
    assert seen == list(range(127))
    assert first.state.state_hash == expected.state_hash and first.strategy_nav == '50000'
    assert origin.read(conn).status == 'FORMED_START_COMMITTED'
    for table in ('sentinel_commands', 'sentinel_execution_plans', 'sentinel_fills'):
        assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
    conn.commit()
    monkeypatch.setattr(formation_bootstrap, 'prepare', lambda *a, **k: pytest.fail('formation repeated'))
    assert init.resume(conn, observation_id=OBS, starting_cash=50000).state.state_hash == first.state.state_hash
    from sentinel.feed import rolling_go_inputs
    from sentinel.rolling_checkpoint import RollingColdStartRefused
    with pytest.raises(RollingColdStartRefused, match='EXISTING_STRATEGY_STATE_REQUIRES_ADMISSION'):
        rolling_go_inputs.prepare(conn, target_session=first.session)
    # A revised unheld historical row is still allowed after formation.
    live = window_features.protected(first.state)
    ticker = next(r['ticker'] for r in operational_source['TICKERS'] if r['permaticker'] not in live)
    next(r for r in operational_source['SEP'] if r['ticker']==ticker and r['date']=='2026-09-10')['volume']='1234567'
    refresh(conn, operational_source, monkeypatch)
    second = advance(conn)
    assert second.session == '2026-09-15'
    with op.pinned(conn) as (_, binding):
        assert len(rolling_store.manifest(conn, binding['candidate_id']).window.sessions) == 300
    assert not advance(conn).appended
