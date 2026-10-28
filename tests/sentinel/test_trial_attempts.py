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


def test_transport_predecessor_cannot_disappear_and_guard_has_executed_falsifier(conn,monkeypatch):
    old,current=pair(conn,succeeded=True)
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
