"""Real immutable attempt storage, legacy recovery and daily projection guards."""
from datetime import datetime, timedelta, timezone

import pytest

from sentinel import trial, trial_attempts
from sentinel.automation import store
from sentinel.automation.model import CycleState
from tests.sentinel.test_automation_service import pg, conn
from tests.sentinel.test_automation_generation import retained


def pair(conn, *, succeeded=False):
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
    old,current=pair(conn,succeeded=True)
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
