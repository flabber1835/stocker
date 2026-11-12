"""Publication cadence, bounded retries and concurrent read-only renewal."""
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from test_recurring_maintenance import Boundary, IMAGE, SYSTEM, media, retention
from test_maintenance_integrity_bridge import proof, status
from sentinel.panel import model
from sentinel.panel.sources import _backup_valid_until
import sentinel_backup_maintenance as coordinator
import sentinel_backup_renewal as renewal
import sentinel_backup_integrity_report as report
import sentinel_maintenance_process as process

BASE = datetime(2031,1,1,tzinfo=timezone.utc)


class Clock:
    now = 0.
    def monotonic(self): return self.now
    def wall(self): return BASE+timedelta(seconds=self.now)
    def publication(self,seconds=None):
        return (BASE+timedelta(seconds=self.now if seconds is None else seconds)).isoformat()
    def schedule(self):
        return renewal.Schedule(self.publication(0),clock=self.monotonic,wallclock=self.wall)


def typed(code='BUSY', *, cleanup='REMOVED',origin='HOST'):
    return report.failure(origin=origin,code=code,stage='OWNER_WAIT',
        cause_type='BackupIntegrityBusy' if code=='BUSY' else 'BackupIntegrityProofExpired',
        elapsed_seconds=20,owner_wait_seconds=20,proof_lock='NOT_ACQUIRED',worker_container=cleanup,
        proof_completed_uptime=1000. if code=='PROOF_WINDOW_EXPIRED' else None,
        proof_observed_uptime=1300. if code=='PROOF_WINDOW_EXPIRED' else None)


def retry(publication,code='BUSY'):
    failure = typed(code)
    return renewal.result(outcome='RETRYABLE',phase='VERIFY_CHAIN',code=code,
        publication_at=publication,cause_type='Refused',failure=failure)


def row(publication):
    at = renewal.timestamp(publication)
    return model.Row('backup_restore','Backup','PROVED',model.OK,as_of=at,
        valid_until=_backup_valid_until(at),required_current=True)


def test_success_tail_does_not_add_another_five_minute_sleep():
    clock = Clock(); schedule = clock.schedule()
    clock.now = 120
    schedule.consume(renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',
        publication_at=clock.publication(0)))
    assert schedule.delay() == 180 and schedule.deadline == 600


def test_byte_refresh_is_early_and_owned_by_original_maintenance_proof():
    clock = Clock()
    schedule = clock.schedule()
    clock.now = 100
    published = clock.publication()
    byte_due = renewal.byte_renewal_at(published,
        dict(proof(), integrity_observed_uptime=1010), '1020.0')
    assert byte_due == clock.publication(200)
    # Reproduce the observed time from scheduled wake to proof publication.
    completion = renewal.timestamp(byte_due) + timedelta(seconds=142.84)
    original_expiry = renewal.timestamp(clock.publication(380))
    assert (original_expiry-completion).total_seconds() == pytest.approx(37.16)
    value = renewal.result(outcome='SUCCESS', phase='COMPLETE', code='OK',
        publication_at=published, byte_due_at=byte_due)
    schedule.consume(renewal.parse(renewal.PASS_PREFIX+json.dumps(value)))
    assert schedule.next_at() == 200
    assert schedule.deadline == 700
    clock.now = 105
    schedule.accept(clock.publication())
    assert schedule.next_at() == 200
    assert schedule.deadline == 705
    assert schedule.timing()['byte_due_at'] is None
    clock.now = 110
    schedule.consume(renewal.result(outcome='SUCCESS', phase='COMPLETE', code='OK',
        publication_at=clock.publication()))
    assert schedule.next_at() == 410


def test_invalid_byte_timing_neither_advances_nor_invents_a_renewal():
    clock = Clock()
    publication = clock.publication()
    assert renewal.byte_renewal_at(publication, proof(), 1199) is None
    assert renewal.byte_renewal_at(publication, proof(), 'missing') is None
    assert renewal.byte_renewal_at(publication, {}, 1200) is None
    with pytest.raises(ValueError, match='bounded publication clock'):
        renewal.result(outcome='SUCCESS', phase='COMPLETE', code='OK',
            publication_at=publication, byte_due_at=clock.publication(301))


def test_due_base_seeds_existing_freshness_schedule_from_qualified_current_clock():
    clock = Clock()
    schedule = clock.schedule()
    selected = Boundary().selected()
    actual = dict(proof(), integrity_observed_uptime=1010)
    observation = dict(system_id=SYSTEM, segment_size=actual['wal_segment_bytes'],
        maintenance_byte_timing=dict(proof=actual, sample_at=clock.publication(), primary_uptime='1020.0'))
    coordinator._prime_bulk_byte_renewal(schedule, observation, dict(selected, name='foreign'))
    assert schedule.next_at() == 300
    coordinator._prime_bulk_byte_renewal(schedule, observation, selected)
    assert schedule.next_at() == 100
    assert schedule.deadline == 600
    assert schedule.timing()['byte_due_at'] is None


@pytest.mark.parametrize('outcome',('RETRYABLE','STANDBY'))
def test_failed_or_standby_tick_recovers_before_actual_row_expiry(outcome):
    clock = Clock(); schedule = clock.schedule(); original = schedule.deadline
    clock.now = 320
    failure = retry(clock.publication(0)) if outcome=='RETRYABLE' else renewal.result(
        outcome='STANDBY',phase='PREFLIGHT',code='TARGET_BUSY',publication_at=clock.publication(0))
    schedule.consume(failure)
    assert schedule.delay() == 1 and schedule.deadline == original
    clock.now += schedule.delay()+12
    schedule.consume(renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',
        publication_at=clock.publication()))
    assert row(schedule.publication()).effective_status(BASE+timedelta(seconds=638)) == model.OK
    assert row(clock.publication(0)).effective_status(BASE+timedelta(seconds=638)) == model.FAIL


def test_repeated_typed_failures_do_not_renew_original_deadline_or_retry_forever():
    clock = Clock(); schedule = clock.schedule(); clock.now = 320
    for _ in range(40):
        schedule.consume(retry(clock.publication(0)))
        assert schedule.deadline == 600
        if clock.now >= 600: break
        clock.now += schedule.delay()
    assert clock.now == 600 and schedule.delay() == 300
    assert row(schedule.publication()).effective_status(BASE+timedelta(seconds=600.1)) == model.FAIL


def test_hard_unknown_and_failed_cleanup_are_not_rapid_retries():
    clock = Clock(); schedule = clock.schedule(); clock.now = 320
    failure = typed(cleanup='FAILED')
    value = renewal.result(outcome='BLOCKED',phase='VERIFY_CHAIN',code='BUSY',
        publication_at=clock.publication(0),cause_type='Refused',failure=failure)
    schedule.consume(value)
    assert schedule.delay() == 300 and schedule.deadline == 600
    with pytest.raises(ValueError,match='contradictory|unclassified'):
        renewal.result(outcome='RETRYABLE',phase='VERIFY_CHAIN',code='BUSY',failure=failure)


def test_later_retention_error_keeps_successful_publication_deadline():
    clock = Clock(); schedule = clock.schedule(); clock.now = 650
    schedule.consume(renewal.result(outcome='BLOCKED',phase='RETENTION',code='CHILD_FAILED',
        publication_at=clock.publication(500)))
    assert schedule.deadline == 1100 and schedule.next_at() == 800
    assert schedule.delay() == 150


def test_old_or_future_publication_cannot_gain_a_new_lifetime():
    clock = Clock(); schedule = clock.schedule(); clock.now = 500
    schedule.accept(clock.publication(0)); assert schedule.deadline == 600
    with pytest.raises(ValueError,match='future'): schedule.accept(clock.publication(501))
    with pytest.raises(ValueError,match='regressed'): schedule.accept(clock.publication(-1))
    assert schedule.deadline == 600


def test_unknown_initial_evidence_does_not_gain_a_retry_lifetime():
    clock = Clock(); schedule = renewal.Schedule(clock=clock.monotonic,wallclock=clock.wall)
    schedule.consume(renewal.result(outcome='STANDBY',phase='PREFLIGHT',code='TARGET_BUSY'))
    assert schedule.deadline is None and schedule.delay() == 300


def test_worker_origin_and_duplicate_result_cannot_borrow_host_retry():
    failure = typed(origin='WORKER',cleanup='NOT_OBSERVED')
    with pytest.raises(ValueError,match='contradictory'):
        renewal.result(outcome='RETRYABLE',phase='VERIFY_CHAIN',code='BUSY',failure=failure)
    value = renewal.result(outcome='BLOCKED',phase='PREFLIGHT',code='INVALID_RESULT')
    line = renewal.PASS_PREFIX+json.dumps(value)
    with pytest.raises(ValueError,match='ambiguous'): renewal.parse(line+'\n'+line)


def test_runner_preserves_only_authenticated_host_failure_classification(monkeypatch):
    failure = typed()
    monkeypatch.setattr(coordinator,'run_bounded',lambda *args,**kwargs:process.Result(
        75,'',report.FAILURE_PREFIX+json.dumps(failure)))
    with pytest.raises(coordinator.Refused) as caught: coordinator.run(['fixture'])
    assert caught.value.failure == failure
    monkeypatch.setattr(coordinator,'run_bounded',lambda *args,**kwargs:process.Result(4,'','busy but unclassified'))
    with pytest.raises(coordinator.Refused) as caught: coordinator.run(['fixture'])
    assert caught.value.failure is None


class FreshBoundary(Boundary):
    def __call__(self,command,**kwargs):
        if command[:2] in (['docker','rm'],['docker','ps']):
            self.calls.append(command); return ''
        if command[:2] == ['bash','scripts/sentinel-backup-status.sh']:
            self.calls.append(command)
            assert '--shared-integrity' in command
            if '--timeout-seconds' in command:
                assert command.index('--timeout-seconds') < command.index('--backup')
            return status(proof(0,False))
        return super().__call__(command,**kwargs)


def prepare_tick(monkeypatch,tmp_path):
    monkeypatch.setattr(coordinator,'ROOT',tmp_path)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_REF',IMAGE)
    monkeypatch.setenv('SENTINEL_BACKUP_SHARED_INTEGRITY','REQUIRED_V1')


def test_read_only_freshness_uses_same_chain_guards_and_no_writer(monkeypatch,tmp_path,capsys):
    prepare_tick(monkeypatch,tmp_path)
    boundary = FreshBoundary()
    value = coordinator.tick('/media',boundary,freshness=True,budget=120)
    result = renewal.parse(capsys.readouterr().out,refresh=True)
    assert value['runtime_chain_current'] and result['outcome'] == 'SUCCESS'
    assert result['publication_at'] is not None
    assert not any('retain' in command or 'scripts/sentinel-base-backup.sh' in command for command in boundary.calls)
    created = next(command for command in boundary.calls if 'observe-current' in command)
    name = created[created.index('--name')+1]
    assert name.startswith('sentinel-maintenance-observe-')
    assert ['docker','rm','-f',name] in boundary.calls
    assert '/media/base:/backup/base:ro' in created and '/media/wal:/backup/wal:ro' in created


def test_actual_publication_carries_native_byte_clock_through_pass_result(monkeypatch,tmp_path,capsys):
    prepare_tick(monkeypatch,tmp_path)
    boundary = FreshBoundary()
    actual = dict(proof(), integrity_observed_uptime=1010)

    def runner(command, **options):
        value = boundary(command, **options)
        if command[:2] == ['bash', 'scripts/sentinel-backup-status.sh']:
            return status(actual)
        if "SELECT 'RUNTIME_CHAIN'" in command[-1]:
            assert "'primary_uptime',split_part(pg_read_file('/proc/uptime'" in command[-1]
            return json.dumps(dict(json.loads(value), primary_uptime='1020.0'))
        return value

    coordinator.tick('/media', runner, freshness=True, budget=120)
    result = renewal.parse(capsys.readouterr().out, refresh=True)
    assert (renewal.timestamp(result['byte_renewal_at']) -
            renewal.timestamp(result['publication_at'])).total_seconds() == 100


@pytest.mark.parametrize('bad_metadata',(False,True))
def test_metadata_helper_failed_cleanup_preserves_primary_cause_and_is_hard(monkeypatch,tmp_path,capsys,bad_metadata):
    prepare_tick(monkeypatch,tmp_path); boundary = FreshBoundary()
    def runner(command,**kwargs):
        if command[:2] == ['docker','rm']: raise coordinator.Refused('private cleanup failure')
        if command[:2] == ['docker','ps']: return 'still-present-private-helper'
        if bad_metadata and 'observe-current' in command: return 'malformed private result'
        return boundary(command,**kwargs)
    with pytest.raises(coordinator.Refused): coordinator.tick('/media',runner,freshness=True,budget=120)
    value = renewal.parse(capsys.readouterr().out,refresh=True)
    assert value['outcome'] == 'BLOCKED' and value['phase'] == 'OBSERVE'
    assert value['failure']['cleanup'] == dict(proof_lock='NOT_ACQUIRED',worker_container='FAILED')
    assert value['failure']['cause_type'] == ('ValueError' if bad_metadata else 'PROTOCOL')
    assert value['failure']['code'] == 'TRANSPORT_FAILURE'


def test_retention_failure_preserves_already_published_fact(monkeypatch,tmp_path,capsys):
    prepare_tick(monkeypatch,tmp_path); boundary = FreshBoundary()
    boundary.fail = 'sentinel.backup_retention retain'
    with pytest.raises(coordinator.Refused): coordinator.tick('/media',boundary)
    result = renewal.parse(capsys.readouterr().out)
    assert result['phase'] == 'RETENTION' and result['publication_at'] is not None
    assert result['outcome'] == 'BLOCKED'


def test_observe_current_succeeds_during_exclusive_writer_without_mutation(media):
    before = media.selected()
    with retention.media_lock(media.base):
        result = subprocess.run([sys.executable,'-B','-m','sentinel.backup_retention','observe-current',
            '--root',str(media.base.parent),'--system-id',SYSTEM,'--timeout-seconds','5'],
            capture_output=True,text=True,timeout=3)
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout) == before
    assert len(media.inventory()) == 72 and not (media.base/retention.JOURNAL).exists()


def test_periodic_hook_drains_bulk_pipes_and_joins_one_reader(tmp_path):
    complete = tmp_path/'bulk-finished'
    class Hook:
        minimum_seconds = .01
        due = 0
        calls = 0
        active = 0
        def next_at(self): return self.due
        def __call__(self,remaining):
            self.calls += 1; self.active += 1
            try:
                deadline = time.monotonic()+1
                while not complete.exists():
                    assert time.monotonic() < deadline,'bulk pipe was not drained during callback'
                    time.sleep(.01)
                self.due = float('inf')
            finally: self.active -= 1
    hook = Hook()
    code = "import os,pathlib;os.write(1,b'x'*200000);pathlib.Path("+repr(str(complete))+").touch()"
    result = process.run_bounded([sys.executable,'-c',code],timeout=3,on_wait=hook)
    assert result.returncode == 0 and len(result.stdout) == 200000
    assert hook.calls == 1 and hook.active == 0


def test_callback_fault_cannot_interrupt_active_bulk_write(tmp_path):
    complete = tmp_path/'write-finished'
    class Hook:
        minimum_seconds = .01
        def next_at(self): return 0
        def __call__(self,remaining): raise ValueError('private callback failed')
    code = "import time,pathlib;time.sleep(.15);pathlib.Path("+repr(str(complete))+").touch()"
    with pytest.raises(ValueError,match='callback failed'):
        process.run_bounded([sys.executable,'-c',code],timeout=3,on_wait=Hook())
    assert complete.exists()


def test_closed_bulk_pipes_do_not_disable_periodic_reader(tmp_path):
    refreshed = tmp_path/'refreshed'
    class Hook:
        minimum_seconds = .01
        due = time.monotonic()+.1
        def next_at(self): return self.due
        def __call__(self,remaining):
            refreshed.touch(); self.due = float('inf')
    code = 'import os,time;os.close(1);os.close(2);time.sleep(.3)'
    result = process.run_bounded([sys.executable,'-c',code],timeout=2,on_wait=Hook())
    assert result.returncode == 0 and refreshed.exists()


@pytest.mark.parametrize('failure',('next_at','submit'))
def test_callback_start_failure_is_deferred_until_writer_finishes(tmp_path,monkeypatch,failure):
    complete = tmp_path/'write-completed'
    class Hook:
        minimum_seconds = .01
        def next_at(self):
            if failure=='next_at': raise RuntimeError('private due failure')
            return 0
        def __call__(self,remaining): pass
    if failure=='submit':
        def submit(*args,**kwargs): raise RuntimeError('private thread resource failure')
        monkeypatch.setattr(process.ThreadPoolExecutor,'submit',submit)
    code = "import time,pathlib;time.sleep(.15);pathlib.Path("+repr(str(complete))+").touch()"
    with pytest.raises(RuntimeError,match='private'):
        process.run_bounded([sys.executable,'-c',code],timeout=3,on_wait=Hook())
    assert complete.exists()


@pytest.mark.parametrize('remaining,expected',[(1000,280),(110,90)])
def test_freshness_budget_uses_original_publication_and_bulk_deadlines(monkeypatch,remaining,expected):
    clock = Clock(); schedule = clock.schedule(); clock.now = 300
    reader = coordinator.FreshnessReader(schedule)
    def child(command,**options):
        assert schedule.deadline == 600
        assert command[-1] == str(expected) and options['timeout'] == expected+5
        clock.now = 330
        value = renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',publication_at=clock.publication())
        return process.Result(0,renewal.REFRESH_PREFIX+json.dumps(value))
    monkeypatch.setattr(coordinator,'run_bounded',child)
    reader(remaining)
    assert schedule.deadline == 930 and schedule.next_at() == 630


def test_renewal_budget_exhaustion_is_not_a_fresh_proof(monkeypatch):
    clock = Clock(); schedule = clock.schedule(); clock.now = 590
    monkeypatch.setattr(coordinator,'run_bounded',lambda *args,**kwargs:pytest.fail('no read budget remains'))
    coordinator.FreshnessReader(schedule)(1000)
    assert schedule.deadline == 600 and schedule.publication() == clock.publication(0)


def test_long_retention_observes_periodic_publication_without_another_writer(monkeypatch,tmp_path,capsys):
    prepare_tick(monkeypatch,tmp_path)
    clock = Clock(); cls = renewal.Schedule
    monkeypatch.setattr(renewal,'Schedule',lambda:cls(clock.publication(0),clock=clock.monotonic,wallclock=clock.wall))
    boundary = FreshBoundary()
    def child(command,**kwargs):
        assert '--freshness-only' in command
        clock.now = 330
        value = renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',publication_at=clock.publication())
        return process.Result(0,renewal.REFRESH_PREFIX+json.dumps(value))
    monkeypatch.setattr(coordinator,'run_bounded',child)
    def runner(command,**options):
        joined = ' '.join(command)
        if "SELECT 'RUNTIME_CHAIN'" in joined:
            record = json.loads(boundary(command,**options));record['observed_at'] = clock.publication()
            return json.dumps(record)
        if 'retain' in command:
            clock.now = 300
            options['on_wait'](300)
            clock.now = 650
        return boundary(command,**options)
    coordinator.tick('/media',runner)
    result = renewal.parse(capsys.readouterr().out)
    assert result['publication_at'] == clock.publication(330)
    assert row(result['publication_at']).effective_status(clock.wall()) == model.OK
    assert sum('retain' in call for call in boundary.calls) == 1


def test_retry_sleep_guard_removal_reproduces_actual_expired_row():
    clock = Clock(); schedule = clock.schedule(); clock.now = 320
    schedule.consume(retry(clock.publication(0)))
    assert schedule.delay() == 1
    # The former completion-based retry makes the positive row expire first.
    former_next_success = clock.now+300+17.669414
    assert row(clock.publication(0)).effective_status(BASE+timedelta(seconds=former_next_success)) == model.FAIL
    recovered_at = clock.now+schedule.delay()+17.669414
    assert row(clock.publication(0)).effective_status(BASE+timedelta(seconds=recovered_at)) == model.OK


def test_callback_start_deferral_guard_removal_is_executed(tmp_path,monkeypatch):
    source = inspect.getsource(process.run_bounded)
    guard = ("except Exception as exc:\n"
        "                    # Even failure to create a thread cannot cancel a writer.\n"
        "                    callback_error = exc")
    assert source.count(guard) == 1
    namespace = dict(vars(process))
    exec(compile(source.replace(guard,'except Exception:\n                    raise'),
        '<removed-callback-deferral>','exec'),namespace)
    monkeypatch.setattr(process,'run_bounded',namespace['run_bounded'])
    with pytest.raises(AssertionError):
        test_callback_start_failure_is_deferred_until_writer_finishes(tmp_path,monkeypatch,'next_at')


def test_progress_failure_cannot_replace_initiating_closed_failure(monkeypatch,capsys):
    initiating = coordinator.Refused('private initiating refusal',failure=typed())
    def broken(root,runner,progress,started,state):
        progress.update(phase='BASE_BACKUP')
        state['phase']='BASE_BACKUP'
        raise initiating
    monkeypatch.setattr(coordinator,'_tick',broken)
    monkeypatch.setattr(coordinator,'publish_progress',lambda *args,**kwargs:
        (_ for _ in ()).throw(ValueError('private progress write failure')))
    before=datetime.now(timezone.utc)
    with pytest.raises(coordinator.Refused) as caught:coordinator.tick('/private')
    after=datetime.now(timezone.utc)
    assert caught.value is initiating
    value=renewal.parse(capsys.readouterr().out)
    assert value['failure']==initiating.failure and value['outcome']=='RETRYABLE'
    assert value['cause_type']=='Refused' and value['phase']=='BASE_BACKUP'
    assert before<=renewal.timestamp(value['started_at'])<=renewal.timestamp(value['finished_at'])<=after


def test_outer_exception_binding_guard_removal_is_executed(monkeypatch,capsys):
    source=inspect.getsource(coordinator.tick)
    guard='except Exception as progress_error:'
    assert source.count(guard)==1
    mutant=source.replace(guard,'except Exception as primary:').replace(
        'type(progress_error).__name__','type(primary).__name__')
    namespace=dict(vars(coordinator));exec(compile(mutant,'<lost-primary-exception>','exec'),namespace)
    namespace['_tick']=lambda *args,**kwargs:coordinator._tick(*args,**kwargs)
    namespace['publish_progress']=lambda *args,**kwargs:coordinator.publish_progress(*args,**kwargs)
    monkeypatch.setattr(coordinator,'tick',namespace['tick'])
    with pytest.raises(UnboundLocalError):
        test_progress_failure_cannot_replace_initiating_closed_failure(monkeypatch,capsys)


def test_buffered_forwarding_preserves_owner_times_without_restamping(monkeypatch,capsys):
    clock=Clock();schedule=clock.schedule();clock.now=300
    value=renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',publication_at=clock.publication(),
        elapsed_seconds=243,started_at='2026-11-10T09:06:34+00:00',finished_at='2026-11-10T09:10:37+00:00')
    monkeypatch.setattr(coordinator,'run_bounded',lambda *args,**kwargs:process.Result(
        0,renewal.REFRESH_PREFIX+json.dumps(value)))
    coordinator.FreshnessReader(schedule)(400)
    assert renewal.parse(capsys.readouterr().out,refresh=True)==value


@pytest.mark.parametrize('fault',('missing_start','missing_finish','naive','reversed','legacy'))
def test_pass_timing_is_closed_utc_and_versioned(fault):
    value=renewal.result(outcome='BLOCKED',phase='PREFLIGHT',code='INVALID_RESULT',
        started_at='2026-11-10T09:06:34+00:00',finished_at='2026-11-10T09:10:37+00:00')
    if fault=='missing_start':value.pop('started_at')
    elif fault=='missing_finish':value.pop('finished_at')
    elif fault=='naive':value['started_at']='2026-11-10T09:06:34'
    elif fault=='reversed':value['finished_at']='2026-11-10T09:06:33+00:00'
    else:value['schema']='sentinel.maintenance-pass-result/1'
    with pytest.raises(ValueError):renewal.validate_result(value)


def test_nonzero_elapsed_cannot_invent_absolute_start():
    with pytest.raises(ValueError,match='owner timing'):
        renewal.result(outcome='BLOCKED',phase='PREFLIGHT',code='INVALID_RESULT',elapsed_seconds=243)
