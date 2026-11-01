"""Real immutable attempt storage, legacy recovery and daily projection guards."""
from datetime import datetime, timedelta, timezone
import inspect

import pytest

from sentinel import trial, trial_attempts
from sentinel.automation import integrity, store
from sentinel.automation.model import CycleState
from sentinel.execution.states import CommandState
from tests.sentinel.test_automation_service import pg, conn
from tests.sentinel.test_automation_generation import retained, recovered_planless_preflight


def pair(conn, *, succeeded=False, recovered=False, repeats=2):
    if recovered:
        _service, old, spec, permit, now = recovered_planless_preflight(conn, repeats=repeats)
    else:
        _service, old, spec, permit, now = retained(conn)
    current = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    states = [CycleState.REFRESHING_DATA]
    if succeeded:
        states += [CycleState.PREPARING, CycleState.PLAN_READY,
                   CycleState.EXECUTING, CycleState.RECONCILING, CycleState.SUCCEEDED]
    else:states += [CycleState.BLOCKED]
    for state in states:
        current = store.transition_cycle(conn, permit=permit, cycle_id=current.cycle_id,
            to_state=state, **({'plan_id':'fresh-attempt-plan'} if state is CycleState.PLAN_READY else {}))
    return old, current


def record(cycle):
    value = trial._terminal_failure(cycle, datetime.now(timezone.utc))
    value['evidence_sha256'] = trial._sha(value)
    return value


def test_cycle_records_preserve_legacy_failure_and_restart_idempotently(conn):
    old, current = pair(conn)
    legacy = record(old)
    name = trial.VERIFICATION_PREFIX+str(old.effective_session)
    trial._insert_immutable(conn, name=name, session=old.effective_session, state=legacy)
    actual = trial.record_cycle_verification(conn, cycle_id=current.cycle_id)
    assert trial._stored(conn, name)[1] == legacy
    assert trial._stored(conn, trial_attempts.key(current.effective_session,current.cycle_id))[1] == actual
    assert trial.record_cycle_verification(conn,cycle_id=current.cycle_id) == actual
    attempts = trial.load_attempt_verifications(conn)
    assert len(attempts) == 2
    assert {item['cycle']['cycle_id'] for item in attempts} == {old.cycle_id,current.cycle_id}
    assert trial.load_verifications(conn) == [actual]


def test_missing_unsent_terminal_callback_is_reconstructed_as_failure_only(conn):
    old, current = pair(conn)
    trial.record_cycle_verification(conn, cycle_id=current.cycle_id)
    recovered = trial_attempts.stored(conn,session=old.effective_session,cycle_id=old.cycle_id)[1]
    assert recovered['recovered_terminal_callback'] is True
    assert recovered['verdict']=='NOT_VERIFIED' and 'CYCLE_SUPERSEDED' in recovered['reason_codes']
    assert trial._terminal_verification_debt(conn,current.model_copy(
        update={'effective_session':current.effective_session+timedelta(days=1)})) == ()


@pytest.mark.parametrize('succeeded', [False, True])
@pytest.mark.parametrize('repeats', [2, 21])
def test_authenticated_planless_preflight_is_unsent_for_trial_projection(conn, succeeded, repeats):
    old, current = pair(conn, succeeded=succeeded, recovered=True, repeats=repeats)
    events = conn.execute('SELECT * FROM sentinel_automation_cycle_events '
        'WHERE cycle_id=%s ORDER BY seq', (old.cycle_id,)).fetchall()
    assert old.plan_id is None and old.failure_code == 'STALE_PREFLIGHT_RECOVERED'
    edges = conn.execute("SELECT count(*) FROM sentinel_automation_cycle_events WHERE cycle_id=%s "
        "AND (from_state='RECONCILING' OR to_state='RECONCILING')", (old.cycle_id,)).fetchone()[0]
    assert edges == (repeats - 1) * 2
    integrity.validate_cycle_lineage(conn, old)
    assert trial_attempts._unsent(conn, old)
    attempts = [record(old), record(current)]
    assert trial_attempts.select(conn, attempts) == [attempts[1]]
    assert trial_attempts.select(conn, list(reversed(attempts))) == [attempts[1]]
    assert all(item['verdict'] == 'NOT_VERIFIED' for item in attempts)
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events '
        'WHERE cycle_id=%s ORDER BY seq', (old.cycle_id,)).fetchall() == events


def test_recovered_preflight_callbacks_preserve_legacy_verdict_and_restart_readback(conn):
    old, current = pair(conn, recovered=True, repeats=21)
    legacy = record(old)
    name = trial.VERIFICATION_PREFIX + str(old.effective_session)
    trial._insert_immutable(conn, name=name, session=old.effective_session, state=legacy)
    result = trial.record_cycle_verification(conn, cycle_id=current.cycle_id)
    assert trial.record_cycle_verification(conn, cycle_id=current.cycle_id) == result
    assert trial._stored(conn, name)[1] == legacy
    assert len(trial.load_attempt_verifications(conn)) == 2
    assert trial.load_verifications(conn) == [result]
    previous = trial._previous_verification(conn, current.effective_session + timedelta(days=1))
    assert previous['cycle']['cycle_id'] == current.cycle_id
    assert previous['verdict'] == result['verdict'] == legacy['verdict'] == 'NOT_VERIFIED'
    assert store.load_cycle(conn, old.cycle_id) == old


def test_recovered_preflight_missing_callback_is_reconstructed_only_as_failure(conn):
    old, current = pair(conn, recovered=True, repeats=21)
    result = trial.record_cycle_verification(conn, cycle_id=current.cycle_id)
    recovered = trial_attempts.stored(conn, session=old.effective_session, cycle_id=old.cycle_id)[1]
    assert recovered['recovered_terminal_callback'] is True
    assert recovered['verdict'] == result['verdict'] == 'NOT_VERIFIED'
    assert 'STALE_PREFLIGHT_RECOVERED' in recovered['reason_codes']
    assert trial.load_verifications(conn) == [result]
    assert trial._terminal_verification_debt(conn, current.model_copy(update={
        'effective_session': current.effective_session + timedelta(days=1)})) == ()
    assert store.load_cycle(conn, old.cycle_id) == old


@pytest.mark.parametrize('command_state', [state.value for state in CommandState])
def test_every_durable_command_state_blocks_trial_projection_and_failure_recovery(conn, command_state):
    old, current = pair(conn)
    conn.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,deployment_id,broker,"
        "broker_account_id,takeover_epoch,symbol,side,quantity,state) "
        "VALUES('trial-command',%s,'sec','sentinel-a','alpaca-paper','paper-account-1',1,'TEST','BUY',1,%s)",
        (old.plan_id, command_state))
    conn.commit()
    with pytest.raises(trial.TrialEvidenceRefused, match='transport evidence'):
        trial_attempts.select(conn, [record(old), record(current)])
    trial_attempts.recover_unsent_failures(conn, current, now=datetime.now(timezone.utc))
    assert trial_attempts.stored(conn, session=old.effective_session, cycle_id=old.cycle_id) is None
    assert conn.execute('SELECT state FROM sentinel_commands WHERE client_key=%s',
        ('trial-command',)).fetchone()[0] == command_state


@pytest.mark.parametrize('recovered', [False, True])
def test_actual_execution_history_cannot_become_an_unsent_trial_attempt(conn, recovered):
    if recovered:
        _, old, _, _, _ = recovered_planless_preflight(conn, transport_history=True)
    else:
        _, old, _, _, _ = retained(conn, state=CycleState.EXECUTING)
    integrity.validate_cycle_lineage(conn, old)
    assert not trial_attempts._unsent(conn, old)


def test_removing_native_transport_classifier_is_detected(conn, monkeypatch):
    source = inspect.getsource(trial_attempts._unsent)
    guard = 'if integrity.predecessors_reached_transport(conn, [cycle]):'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if False:'), '<removed-trial-transport-proof>', 'exec'),
        vars(trial_attempts), namespace)
    monkeypatch.setattr(trial_attempts, '_unsent', namespace['_unsent'])
    with pytest.raises(AssertionError):
        test_actual_execution_history_cannot_become_an_unsent_trial_attempt(conn, True)


def test_removing_trial_command_existence_guard_is_detected(conn, monkeypatch):
    source = inspect.getsource(trial_attempts._unsent)
    guard = 'return not cur.fetchone()[0]'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'return True'), '<removed-trial-command-proof>', 'exec'),
        vars(trial_attempts), namespace)
    monkeypatch.setattr(trial_attempts, '_unsent', namespace['_unsent'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_every_durable_command_state_blocks_trial_projection_and_failure_recovery(conn, 'UNKNOWN')


def test_state_name_only_trial_classifier_reproduces_the_preflight_regression(conn, monkeypatch):
    def state_name_only(connection, cycle):
        with connection.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_automation_cycle_events "
                "WHERE cycle_id=%s AND (from_state IN ('EXECUTING','RECONCILING') "
                "OR to_state IN ('EXECUTING','RECONCILING'))) OR "
                "EXISTS(SELECT 1 FROM sentinel_commands WHERE plan_id=%s)",
                (cycle.cycle_id, cycle.plan_id))
            return not cur.fetchone()[0]
    monkeypatch.setattr(trial_attempts, '_unsent', state_name_only)
    with pytest.raises(AssertionError):
        test_authenticated_planless_preflight_is_unsent_for_trial_projection(conn, False, 21)


def test_one_success_does_not_count_unsent_attempts_as_extra_economic_days(conn):
    old, current = pair(conn,succeeded=True)
    first,last=record(old),record(current)
    chosen=trial_attempts.select(conn,[first,last])
    assert chosen==[last] and last['verdict']=='NOT_VERIFIED'
    assert trial_attempts.select(conn,[last,first])==chosen


@pytest.mark.parametrize('succeeded',[False,True])
def test_transport_predecessor_cannot_disappear_and_guard_has_executed_falsifier(conn,monkeypatch,succeeded):
    old,current=pair(conn,succeeded=succeeded)
    conn.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,deployment_id,broker,"
        "broker_account_id,takeover_epoch,symbol,side,quantity,state) "
        "VALUES('retained-transport',%s,'sec','sentinel-a','alpaca-paper','paper-account-1',1,'TEST','BUY',1,'UNKNOWN')",(old.plan_id,))
    conn.commit()
    attempts=[record(old),record(current)]
    def refusal():
        with pytest.raises(trial.TrialEvidenceRefused,match='transport evidence'):
            trial_attempts.select(conn,attempts)
    refusal()
    with monkeypatch.context() as broken:
        broken.setattr(trial_attempts,'_unsent',lambda *_a:True)
        with pytest.raises(AssertionError):
            assert trial_attempts.select(conn,attempts) != [attempts[1]], 'transported predecessor was hidden'


@pytest.mark.parametrize('field,value',[('broker_account_id','foreign-account'),('takeover_epoch',99)])
def test_foreign_attempt_cannot_join_the_daily_projection(conn,field,value):
    old,current=pair(conn,succeeded=True)
    invalid=record(old);invalid['binding'][field]=value
    with pytest.raises(trial.TrialEvidenceRefused,match='scope/state'):
        trial_attempts.select(conn,[invalid,record(current)])


def test_scoped_storage_key_cannot_name_another_cycle(conn):
    old,current=pair(conn)
    trial._insert_immutable(conn,name=trial_attempts.key(current.effective_session,current.cycle_id),
        session=current.effective_session,state=record(old))
    with pytest.raises(trial.TrialEvidenceRefused,match='another immutable cycle'):
        trial.record_cycle_verification(conn,cycle_id=current.cycle_id)


def test_daily_projection_refuses_two_successes_even_if_lineage_guard_is_bypassed(conn,monkeypatch):
    from sentinel.automation import integrity
    old,current=pair(conn,succeeded=True)
    corrupted=old.model_copy(update={'state':CycleState.SUCCEEDED})
    real=store.load_cycle
    # Independent defense: a broken upstream lineage validator cannot make two
    # successful economic cycles into one day's certified result.
    monkeypatch.setattr(store,'load_cycle',lambda c,k:corrupted if k==old.cycle_id else real(c,k))
    monkeypatch.setattr(integrity,'validate_cycle_lineage',lambda *_a:None)
    with pytest.raises(trial.TrialEvidenceRefused,match='multiple successful'):
        trial_attempts.select(conn,[record(corrupted),record(current)])


def test_cached_verdict_cannot_ignore_a_contradictory_session_sibling(conn):
    old,current=pair(conn)
    trial._insert_immutable(conn,name=trial_attempts.key(current.effective_session,current.cycle_id),
        session=current.effective_session,state=record(current))
    foreign=record(old);foreign['binding']['broker_account_id']='foreign-account'
    foreign['evidence_sha256']=trial._sha({k:v for k,v in foreign.items() if k!='evidence_sha256'})
    trial._insert_immutable(conn,name=trial_attempts.key(old.effective_session,old.cycle_id),
        session=old.effective_session,state=foreign)
    with pytest.raises(trial.TrialEvidenceRefused,match='scope/state'):
        trial.record_cycle_verification(conn,cycle_id=current.cycle_id)


@pytest.mark.parametrize('legacy_prefix',[False,True])
def test_new_attempt_namespace_is_invisible_to_the_old_daily_reader(conn,monkeypatch,legacy_prefix):
    old,current=pair(conn)
    if legacy_prefix:monkeypatch.setattr(trial_attempts,'PREFIX',trial.VERIFICATION_PREFIX)
    trial.record_cycle_verification(conn,cycle_id=current.cycle_id)
    def old_reader_sees_no_new_economic_rows():
        assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
                            (trial.VERIFICATION_PREFIX+'%',)).fetchone()[0]==0
        conn.rollback()
    if legacy_prefix:
        with pytest.raises(AssertionError):old_reader_sees_no_new_economic_rows()
    else:old_reader_sees_no_new_economic_rows()
    assert len(trial.load_attempt_verifications(conn))==2
    assert len(trial.load_verifications(conn))==1


def test_second_success_guard_has_an_executed_mutant(conn,monkeypatch):
    import inspect
    from sentinel.automation import integrity
    old,current=pair(conn,succeeded=True)
    corrupted=old.model_copy(update={'state':CycleState.SUCCEEDED})
    real=store.load_cycle
    monkeypatch.setattr(store,'load_cycle',lambda c,k:corrupted if k==old.cycle_id else real(c,k))
    monkeypatch.setattr(integrity,'validate_cycle_lineage',lambda *_a:None)
    monkeypatch.setattr(trial_attempts,'_unsent',lambda *_a:True)
    attempts=[record(corrupted),record(current)]
    with pytest.raises(trial.TrialEvidenceRefused,match='multiple successful'):
        trial_attempts.select(conn,attempts)
    source=inspect.getsource(trial_attempts.select)
    assert source.count('if len(successes) > 1:')==1
    namespace=dict(vars(trial_attempts))
    exec(source.replace('if len(successes) > 1:','if False:'),namespace)
    with pytest.raises(AssertionError):
        try:namespace['select'](conn,attempts)
        except trial.TrialEvidenceRefused:pass
        else:assert False,'two economic cycles were collapsed into one day'


def test_trial_attempt_storage_preserves_installed_operational_contract(conn,monkeypatch):
    from sentinel import operational_ddl_epoch, operational_schema
    from tests.sentinel.test_issuer_operational_compatibility import assert_predecessor_contracts
    assert_predecessor_contracts()
    from sentinel.feed import store as feed_store
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-trial-attempt-contract-key-'*4)
    feed_store.migrate_schema(conn)
    operational_schema.install_quiescent(conn)
    before_epoch=operational_ddl_epoch.current(conn)
    before_revisions=dict(conn.execute('SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    conn.rollback()
    old,current=pair(conn)
    trial.record_cycle_verification(conn,cycle_id=current.cycle_id)
    after_revisions=dict(conn.execute('SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    assert after_revisions['SHADOW']==before_revisions['SHADOW']
    assert after_revisions['PAPER']>before_revisions['PAPER']
    assert operational_ddl_epoch.current(conn)==before_epoch
    assert_predecessor_contracts()
