"""Real SQL/restore/leader/receipt completion, with external authority fixtures.

Plan economics, cryptographic admission, shadow service/attestation/reconciliation,
Compose, operator HTTP and the market clock are explicit boundaries. The separate
leader process contains no scheduler or broker transport. Small physical/logical
restore copies use the unmodified read-only semantic validator. These tests grant
no software certification, GO, paper authority or production PITR proof.
"""
import contextlib
import asyncio
import dataclasses
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
FIXTURE_COMMIT=os.environ.get('QUALIFIED_COMMIT','e'*40)
import sentinel_autonomous_deploy_install_entry as install
from sentinel import authority, binding, restore_validation
from sentinel.automation import store
from sentinel.automation.health import read_health
from sentinel.automation.model import AutomationConfig, AutomationRefused
from sentinel.cli import automation as cli
from sentinel.execution import journal
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import store as feed
from tests.support.postgres import (_EphemeralPostgres, _find_pg_bin, _as_pg_user)
from tests.sentinel.test_automation_store import conn, pg
from tests.sentinel.test_paper_activation import _state, _plan, _persist_state, _publish, DECISION

core = install.core
CERT = 'c' * 64
WORKER = r'''
import json,sys,time
from pathlib import Path
from sentinel.automation import store
from sentinel.feed import store as feed
c=feed.connect(sys.argv[1]); mode=sys.argv[3]
p=store.acquire_lease(c,holder_id='isolated-remainder-leader',lease_seconds=60)
store.record_authority_verdict(c,verdict='PASS',detail='EXPLICIT TEST AUTHORITY FIXTURE',
 holder_id=p.holder_id,fence_token=p.fence_token,control_generation=p.control_generation)
store.register_instance(c,instance_id=p.holder_id,state='WAITING')
Path(sys.argv[2]).write_text(p.model_dump_json())
started=time.monotonic();changed=False
while True:
 time.sleep(.15)
 if mode=='leader-stall':continue
 if not changed and time.monotonic()-started>.8 and mode in {'leader-changed','revoked'}:
  if mode=='leader-changed':
   c.execute('UPDATE sentinel_automation_lease SET fence_token=fence_token+1 WHERE id=1')
  else:
   c.execute("INSERT INTO sentinel_execution_certificate_revocations (certificate_sha256,reason) VALUES (%s,'offline fault')",('c'*64,))
  c.commit();changed=True
 if mode=='leader-changed' and changed:continue
 p=store.heartbeat_lease(c,permit=p,lease_seconds=60)
 store.register_instance(c,instance_id=p.holder_id,state='WAITING')
'''


@pytest.fixture(autouse=True)
def transport_tripwire(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('BROKER TRANSPORT MUST NEVER BE CALLED')
    monkeypatch.setattr(SimulatedBroker, 'submit', forbidden)
    monkeypatch.setattr(SimulatedBroker, 'cancel', forbidden)


def book_fingerprint(c):
    value = c.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name').fetchall()
    c.rollback()
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def checkpoint_restore(c, directory, *, physical=False, corrupt=False):
    """Actual isolated PostgreSQL copy + unmodified read-only semantic validator."""
    c.rollback()
    baseline = book_fingerprint(c)
    before_binding = binding.require(c).to_dict()
    c.rollback()
    restored = _EphemeralPostgres()
    try:
        if physical:
            shutil.rmtree(restored.datadir)
            command = [_find_pg_bin('pg_basebackup'), '-D', restored.datadir,
                       '-h', '127.0.0.1', '-p', str(c.info.port), '-U', c.info.user,
                       '-X', 'stream', '-c', 'fast', '--no-password']
            subprocess.run(_as_pg_user(command), check=True, capture_output=True, text=True, timeout=90)
            result = subprocess.run(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', restored.datadir,
                '-o', f'-p {restored.port} -h 127.0.0.1 -k {restored.datadir}',
                '-l', str(Path(restored.datadir)/'restored.log'), '-w', '-t', '30', 'start']),
                capture_output=True, text=True, timeout=45)
            assert result.returncode == 0, result.stderr
            restored._started = True
        else:
            dump = directory / 'state.dump'
            subprocess.run([_find_pg_bin('pg_dump'), '-Fc', '-f', str(dump), c.info.dsn],
                           check=True, capture_output=True, timeout=60)
            restored.start()
            subprocess.run([_find_pg_bin('pg_restore'), '--exit-on-error', '--no-owner',
                '--no-privileges', '--dbname', restored.sync_dsn, str(dump)],
                check=True, capture_output=True, timeout=60)
        # A physical cluster copy retains the source database name, including
        # the per-test rolling databases. A logical dump targets the fresh DB.
        restored_dsn = (restored.sync_dsn.rsplit('/', 1)[0] + '/' + c.info.dbname
                        if physical else restored.sync_dsn)
        with feed.connect(restored_dsn) as copy:
            assert binding.require(copy).to_dict() == before_binding
            copy.rollback()
            assert book_fingerprint(copy) == baseline
            assert journal.latest_plan(copy).plan_id == journal.latest_plan(c).plan_id
            copy.rollback(); c.rollback()
            if corrupt:
                copy.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{last_processed_session}','\"2000-01-01\"')")
                copy.commit()
            result = restore_validation.validate_restored_database(copy)
            assert result['automation_enabled'] is True and result['kill_switch_engaged'] is True
            assert result['plan_count'] == 1 and result['command_count'] == 0
            assert result['restart_state_present'] is True
            assert result['transaction_read_only'] is True
            assert book_fingerprint(copy) == baseline
            return result
    finally:
        restored.stop()


class Campaign:
    def __init__(self, c, pg, tmp, monkeypatch, failure=None, physical=False):
        self.c, self.pg, self.tmp, self.failure = c, pg, tmp, failure
        self.events, self.worker = [], None
        self.running = dict(shadow=True, automation=False)
        self.backups = 0
        self.control_cfg = AutomationConfig()
        monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','offline-disposable-publication-receipt-key-only')
        from sentinel import backup_runtime_authority
        from sentinel.feed.runtime_schema import require_feed_schema
        monkeypatch.setattr(backup_runtime_authority,'POLICY_MARKER',tmp/'absent-production-backup-marker')
        # Keep the real read-only validator even under legacy test conftests.
        monkeypatch.setattr(feed,'require_feed_schema',require_feed_schema)
        feed.migrate_schema(c)
        feed.require_feed_schema(c)
        self.bound = binding.bind(c, deployment_id='isolated-remainder', broker='alpaca', broker_account_id='NO-REAL-ACCOUNT')
        publication = _publish(c)
        self.state = _state(session=DECISION, data_version=publication.version)
        _persist_state(c, self.state)
        self.plan = dataclasses.replace(_plan(self.state, publication, self.bound),
            rollout_mode='PINNED_1_00', rollout_version=1, rollout_certificate_sha256=None)
        self.plan = dataclasses.replace(self.plan,plan_id='sentinel-'+self.plan.fingerprint())
        self.baseline = book_fingerprint(c)
        c.execute("INSERT INTO sentinel_signed_execution_certificates (certificate_sha256,certificate_id,key_id,envelope_bytes,envelope,claims,issuer_generation,not_before,expires_at) VALUES (%s,'offline-fixture','offline-key',%s,'{}',%s::jsonb,1,NOW()-INTERVAL '1 day',NOW()+INTERVAL '1 day')",
                  (CERT, b'NOT A SIGNED CERTIFICATE', json.dumps({'authorization_mode':'PAPER_OBSERVATION_ONLY'})))
        c.execute("INSERT INTO sentinel_execution_certificate_lifecycle (certificate_sha256,status,activated_at) VALUES (%s,'ACTIVE',NOW())", (CERT,))
        c.execute('INSERT INTO sentinel_execution_authority_state (id,generation,highest_issuer_generation,active_certificate_sha256) VALUES (1,1,1,%s)', (CERT,))
        c.commit()
        monkeypatch.setattr(cli, 'require_authorized_runtime', lambda *a: None)
        import sentinel.automation_runtime as runtime
        monkeypatch.setattr(runtime, 'config_from_env', lambda: self.control_cfg)
        monkeypatch.setattr(cli, '_automation_authority', lambda c, config, ac:
            (binding.require(c), authority.load_rollout_state(c), SimpleNamespace(certificate_sha256=CERT)))
        cfg = SimpleNamespace(account_id=self.bound.broker_account_id, deployment_id=self.bound.deployment_id,
            actor='offline-test', health_timeout=1, heartbeat_seconds=0, formation_timeout_seconds=1,
            data_wait_timeout_seconds=1, allow_empty_bind=False,
            runtime_repository='offline/sentinel', test_repository='offline/test')
        reviewed = SimpleNamespace(mode='dual', source_identity_sha256='a'*64,
            shadow_configuration_sha256='b'*64, data_publication_sha256='d'*64, bundle_sha256='e'*64)
        self.obj = install.InstallAnytimeDeploy(cfg, SimpleNamespace(env={},run=self.run), tmp, reviewed)
        self.obj.base_compose = ['OFFLINE-COMPOSE']
        self.obj.phase = lambda text: self.events.append('phase:'+text)
        self.obj.commit = FIXTURE_COMMIT
        self.obj.runtime_digest = self.obj.test_digest = 'sha256:'+'1'*64
        self.obj.runtime_repo_digest = cfg.runtime_repository+'@'+self.obj.runtime_digest
        self.obj.test_repo_digest = cfg.test_repository+'@'+self.obj.test_digest
        self.obj.new_certificate = CERT
        self.obj._running_shadow_containers = lambda: ['shadow'] if self.running['shadow'] else []
        self.obj._running_automation_containers = lambda: ['automation'] if self.running['automation'] else []
        self.obj._direct_stop_shadow = lambda **kw: self.stop('shadow')
        self.obj._direct_stop_automation = lambda: self.stop('automation')
        self.obj._authorized_cli = self.obj._base_cli = self.command
        self.obj.verify_operator_services = self.operators
        self.obj.wait_shadow_process = self.shadow_health
        self.obj.assert_activation_timing = self.timing
        self.physical = physical
        self.dotenv = tmp/'private-fixture.env'
        self.dotenv.write_text('PRIVATE_TEST_VALUE=preserve\n')
        self.dotenv.chmod(0o600)
        monkeypatch.setattr(core, 'ENV_PATH', self.dotenv)
        if failure == 'persist-dotenv':
            def refuse_write(*a, **k): raise OSError('injected atomic dotenv failure')
            monkeypatch.setattr(install.bootstrap, '_safe_update_dotenv', refuse_write)
        if failure == 'receipt-conflict':
            (tmp/'activation-receipt.json').write_text('{"existing":"MUST PRESERVE"}\n')

    def stop(self, service):
        self.events.append('stop-'+service)
        if service == 'automation' and self.worker:
            self.worker.terminate()
            self.worker.wait(timeout=5)
            self.worker = None
        self.running[service] = False

    def operators(self):
        self.events.append('operators')
        fail_at = 2 if self.failure == 'final-operator-health' else 1
        if self.failure in {'operator-health','final-operator-health'} and self.events.count('operators') == fail_at:
            raise core.DeployRefused('injected operator health failure')

    def shadow_health(self):
        if self.failure == 'shadow-health': raise core.DeployRefused('injected shadow health failure')

    def timing(self, session):
        self.events.append('timing')
        if self.failure == 'cutoff' and self.events.count('timing') == 2:
            raise core.ActivationPending('injected next-open cutoff')

    def command(self, args, **kwargs):
        cmd = args[0]; self.events.append(cmd)
        if cmd in {'prepare-paper-plan','activate-paper-automation','release-paper-automation-kill-switch'}:
            assert not any(self.running.values()), 'actual control mutation collided with financial process'
        if self.failure == cmd: raise core.DeployRefused('injected CLI refusal '+cmd)
        if cmd == 'prepare-paper-plan':
            with journal.writer_lock(self.c): journal.adopt_current_plan(self.c, self.plan)
        if cmd in {'prepare-paper-plan','current-paper-plan'}:
            current = journal.latest_plan(self.c); self.c.rollback()
            payload = dict(plan=dict(plan_id=current.plan_id,decision_session=current.decision_session.isoformat()),database_authorities_match=True)
            if self.failure == 'plan-mismatch' and cmd == 'current-paper-plan': payload['plan']['plan_id']='foreign'
            if self.failure == 'plan-json' and cmd == 'prepare-paper-plan': return self.result('{"plan":{},"plan":{}}')
            return self.result(json.dumps(payload))
        if cmd == 'automation-status':
            return self.result(read_health(self.c).model_dump_json())
        if cmd == 'status':
            health=read_health(self.c)
            return self.result(json.dumps(dict(ownership='OWNED',broker='alpaca',broker_account_id=self.bound.broker_account_id,
                deployment_id=self.bound.deployment_id,takeover_epoch=self.bound.takeover_epoch,
                paper_execution_authority=dict(authority_mode='PAPER_OBSERVATION_ONLY',lifecycle_current=health.authority_lifecycle_current))))
        if cmd in {'activate-paper-automation','release-paper-automation-kill-switch'}:
            if self.failure in {'activate-noop','release-noop'} and cmd == ('activate-paper-automation' if self.failure=='activate-noop' else 'release-paper-automation-kill-switch'):
                return self.result('{}')
            parsed=SimpleNamespace(confirm_enable_unattended_alpaca_paper_automation=True,
                confirm_old_writer_fenced=True,confirm_release_unattended_paper_kill_switch=True,
                confirm_paper_account=self.bound.broker_account_id,confirm_deployment_id=self.bound.deployment_id,
                confirm_certificate_sha256=CERT,actor='offline',reason='offline integration')
            handler=cli._activate_paper_automation if cmd.startswith('activate-') else cli._release_paper_automation_kill
            buf=io.StringIO()
            with contextlib.redirect_stdout(buf):
                code=handler.__wrapped__(SimpleNamespace(database_url=self.pg.sync_dsn,base_url='https://paper-api.alpaca.markets'),parsed)
            if code: raise core.DeployRefused('actual durable control handler refused')
            if self.failure == 'wrong-certificate' and cmd.startswith('activate-'):
                self.c.execute("UPDATE sentinel_automation_control SET certificate_sha256=%s WHERE id=1", ('f'*64,)); self.c.commit()
            return self.result(buf.getvalue())
        raise AssertionError('unmapped CLI '+cmd)

    @staticmethod
    def result(text=''):
        return subprocess.CompletedProcess([],0,text,'')

    def run(self, args, **kwargs):
        if args[:2] == ['bash','scripts/sentinel-emergency-kill.sh']:
            if not store.load_control(self.c).kill_switch_engaged:
                store.engage_kill(self.c,actor='offline',reason='offline fault fence')
            return self.result('kill confirmed')
        if args[:2] == ['bash','scripts/sentinel-install-backup.sh']:
            self.backups += 1; self.events.append('restore')
            assert store.load_control(self.c).enabled and store.load_control(self.c).kill_switch_engaged
            assert not any(self.running.values())
            checkpoint_restore(self.c,self.tmp,physical=self.physical,corrupt=self.failure=='semantic-restore')
            if self.failure == 'writer-reappeared': self.running['shadow']=True
            return self.result('verified_installation_backup: /offline/one-coordinated-milestone\n')
        if args[:1] != ['OFFLINE-COMPOSE']: raise AssertionError('unmapped external command '+repr(args))
        if '-c' in args:
            self.events.append('reconciliation')
            if self.failure == 'reconciliation' or (self.failure=='resumed-reconciliation' and self.running['shadow']):
                raise core.DeployRefused('injected reconciliation failure')
            payload=dict(schema='sentinel.dual-plan-shadow-reconciliation/1',verdict='MATCH',
                state_sha256=self.state.state_hash,shadow_runtime_authority_sha256='b'*64,
                sizing_authority_sha256='d'*64,plan_fingerprint=journal.latest_plan(self.c).fingerprint())
            self.c.rollback()
            if self.failure == 'control-changed' and self.running['shadow']:
                store.engage_kill(self.c,actor='offline',reason='injected intervening fence')
            return self.result('SENTINEL_DUAL_RECONCILIATION='+json.dumps(payload))
        if 'shadow-status' in args:
            self.events.append('shadow-status')
            payload=dict(session=('2026-08-12' if self.failure=='session-advanced' else DECISION.isoformat()),shadow_verdict='SHADOW_GO',verification='VERIFIED')
            if self.failure=='shadow-json': return self.result('{"session":NaN}')
            return self.result(json.dumps(payload))
        if 'up' in args:
            service=args[-1].removeprefix('sentinel-')
            self.events.append('start-'+service)
            if self.failure=='start-'+service: raise core.DeployRefused('injected service startup failure')
            self.running[service]=True
            if service=='automation' and self.failure!='leader-absent':
                ready=self.tmp/'leader-ready.json'
                self.worker=subprocess.Popen([sys.executable,'-c',WORKER,self.pg.sync_dsn,str(ready),self.failure or 'normal'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
                deadline=time.monotonic()+5
                while not ready.exists() and time.monotonic()<deadline and self.worker.poll() is None: time.sleep(.05)
                assert ready.exists(), self.worker.stderr.read() if self.worker.poll() is not None else 'leader failed to start'
            return self.result()
        raise AssertionError('unmapped Compose action '+repr(args))

    def execute(self):
        with self.obj.activation_transition():
            self.obj.prepare_activate_start(CERT, DECISION.isoformat())
            health=self.obj.verify_operational(CERT)
            self.obj.persist_success(health)
        return health

    def preserve(self):
        assert book_fingerprint(self.c)==self.baseline
        assert binding.require(self.c).to_dict()==self.bound.to_dict()
        assert self.c.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0]==0
        self.c.rollback()


def test_remaining_sequence_actual_physical_restore_leader_and_receipt(conn,pg,tmp_path,monkeypatch):
    campaign=Campaign(conn,pg,tmp_path,monkeypatch,physical=True)
    try:
        health=campaign.execute()
        receipt=json.loads((tmp_path/'activation-receipt.json').read_text())
        assert health['operational_ready'] is True
        assert receipt['leader_holder']==health['leader_holder'] and receipt['control_generation']==health['control_generation']
        assert receipt['activation_mode']=='dual' and receipt['paper_accounting_authoritative'] is False
        assert receipt['git_commit']==FIXTURE_COMMIT
        assert receipt['post_deploy_backup']=='/offline/one-coordinated-milestone'
        assert campaign.backups==1, 'receipt persistence repeated a proved recovery milestone'
        assert 'PRIVATE_TEST_VALUE=preserve' in campaign.dotenv.read_text()
        assert campaign.dotenv.stat().st_mode & 0o777 == 0o600
        assert campaign.events.index('restore') < campaign.events.index('release-paper-automation-kill-switch')
        assert campaign.events.index('start-shadow') < campaign.events.index('start-automation')
        campaign.preserve()
    finally:
        campaign.stop('automation')


@pytest.mark.parametrize('clock', [
    '2026-08-11T22:00:00+00:00',  # just after the decision closed
    '2026-08-12T01:00:00+00:00',  # overnight
    '2026-08-12T13:00:00+00:00',  # before the next open
    '2026-08-12T13:30:00+00:00',  # exactly at the open
    '2026-08-12T18:00:00+00:00',  # already intraday
])
def test_actual_completion_with_anytime_host_guard(conn, pg, tmp_path, monkeypatch, clock):
    from sentinel.feed import calendar
    now = datetime.fromisoformat(clock)
    target = calendar.latest_closed_session(now)
    assert target == DECISION.isoformat(), 'fixture must represent the actual latest closed decision'
    effective = calendar.next_session(target)
    opening, _ = calendar.session_window(effective)
    remaining = int((opening.astimezone(timezone.utc)-now).total_seconds()*1000)
    campaign = Campaign(conn, pg, tmp_path, monkeypatch)
    # Only provider/attestation observations are fixtures; admission itself is
    # the production host method, joined to real control/restore/lease/receipt.
    campaign.obj._operational_source_only = True
    campaign.obj._causal_timing = lambda: dict(
        target=target, frontier=target, target_source_final=True,
        prospective=remaining > 0, remaining_ms=remaining)
    campaign.obj.assert_activation_timing = install.InstallAnytimeDeploy.assert_activation_timing.__get__(campaign.obj)
    try:
        health = campaign.execute()
        receipt = json.loads((tmp_path/'activation-receipt.json').read_text())
        assert health['operational_ready'] is True
        assert receipt['leader_holder'] == health['leader_holder']
        assert receipt['control_generation'] == health['control_generation']
        assert campaign.backups == 1
        assert campaign.events.index('restore') < campaign.events.index('release-paper-automation-kill-switch')
        assert store.load_control(conn).enabled and not store.load_control(conn).kill_switch_engaged
        campaign.preserve()
    finally:
        campaign.stop('automation')


@pytest.mark.parametrize('crossed', ['2026-08-12T13:30:00+00:00', '2026-08-12T20:30:00+00:00'])
def test_restore_crossing_open_or_close_has_the_right_activation_boundary(
        conn, pg, tmp_path, monkeypatch, crossed):
    from sentinel.feed import calendar
    from sentinel.automation.model import LeaderPermit, TickAction
    from tests.sentinel.test_automation_service import service_for, recovery_success
    clock = [datetime.fromisoformat('2026-08-12T13:00:00+00:00')]
    campaign = Campaign(conn, pg, tmp_path, monkeypatch)
    campaign.obj._operational_source_only = True
    def timing():
        target = calendar.latest_closed_session(clock[0])
        opening, _ = calendar.session_window(calendar.next_session(target))
        remaining = int((opening.astimezone(timezone.utc)-clock[0]).total_seconds()*1000)
        return dict(target=target, frontier=DECISION.isoformat(), target_source_final=True,
                    prospective=remaining > 0, remaining_ms=remaining)
    campaign.obj._causal_timing = timing
    campaign.obj.assert_activation_timing = install.InstallAnytimeDeploy.assert_activation_timing.__get__(campaign.obj)
    actual_run = campaign.run
    def cross_after_actual_restore(args, **kwargs):
        answer = actual_run(args, **kwargs)
        if args[:2] == ['bash', 'scripts/sentinel-install-backup.sh']:
            clock[0] = datetime.fromisoformat(crossed)
        return answer
    campaign.obj.runner.run = cross_after_actual_restore
    try:
        if calendar.latest_closed_session(datetime.fromisoformat(crossed)) != DECISION.isoformat():
            with pytest.raises(core.ActivationPending, match='current finalized decision'):
                campaign.execute()
            assert store.load_control(conn).kill_switch_engaged
            assert not (tmp_path/'activation-receipt.json').exists()
        else:
            assert campaign.execute()['operational_ready']
            # End the actual lease-owning fixture process before handing that
            # same isolated control to the production scheduler state machine.
            campaign.stop('automation')
            permit = LeaderPermit.model_validate_json((tmp_path/'leader-ready.json').read_text())
            store.release_lease(conn, permit=permit)
            callbacks = []
            def recover(context):
                callbacks.append('recover')
                return recovery_success(context)
            def forbidden(context):
                callbacks.append('new-plan-or-transport')
                raise AssertionError('restore crossing the open triggered a new same-open plan')
            service = service_for(campaign.control_cfg, refresh=forbidden,
                                  prepare=forbidden, execute=forbidden, recover=recover)
            result = asyncio.run(service.tick(conn, now=clock[0]))
            assert result.action is TickAction.SUPERSEDED
            assert callbacks == ['recover']
            assert result.cycle.failure_code == 'DISCOVERED_AFTER_SESSION_OPEN'
        assert campaign.backups == 1
        campaign.preserve()
    finally:
        campaign.stop('automation')


FAULTS=['plan-mismatch','plan-json','prepare-paper-plan','reconciliation','activate-paper-automation',
 'activate-noop','wrong-certificate','operator-health','semantic-restore','cutoff','writer-reappeared',
 'release-paper-automation-kill-switch','release-noop','start-shadow','shadow-health','session-advanced',
 'shadow-json','resumed-reconciliation','control-changed','start-automation','leader-absent','leader-stall',
 'leader-changed','revoked','final-operator-health','persist-dotenv','receipt-conflict']

@pytest.mark.parametrize('failure',FAULTS)
def test_each_remaining_failure_fences_without_success_receipt(conn,pg,tmp_path,monkeypatch,failure):
    campaign=Campaign(conn,pg,tmp_path,monkeypatch,failure=failure)
    receipt=tmp_path/'activation-receipt.json'
    before=receipt.read_bytes() if receipt.exists() else None
    try:
        with pytest.raises((core.DeployRefused,core.ActivationPending,RuntimeError,OSError)) as refusal:
            campaign.execute()
        reached = {
            'plan-mismatch':'current-paper-plan','plan-json':'prepare-paper-plan',
            'prepare-paper-plan':'prepare-paper-plan','reconciliation':'reconciliation',
            'activate-paper-automation':'activate-paper-automation','activate-noop':'activate-paper-automation',
            'wrong-certificate':'activate-paper-automation','operator-health':'operators',
            'semantic-restore':'restore','cutoff':'restore','writer-reappeared':'restore',
            'release-paper-automation-kill-switch':'release-paper-automation-kill-switch',
            'release-noop':'release-paper-automation-kill-switch','start-shadow':'start-shadow',
            'shadow-health':'start-shadow','session-advanced':'shadow-status','shadow-json':'shadow-status',
            'resumed-reconciliation':'start-shadow','control-changed':'start-shadow',
            'start-automation':'start-automation','leader-absent':'start-automation',
            'leader-stall':'start-automation','leader-changed':'start-automation','revoked':'start-automation',
            'final-operator-health':'start-automation','persist-dotenv':'start-automation','receipt-conflict':'start-automation',
        }[failure]
        assert reached in campaign.events, ('fault boundary was never reached',failure,campaign.events)
        if failure in {'final-operator-health','persist-dotenv','receipt-conflict'}:
            assert campaign.events.count('operators')==2, 'failure occurred before final completion boundary'
        if failure=='wrong-certificate':
            with pytest.raises(AutomationRefused,match='immutable history'):
                store.load_control(conn)
            assert conn.execute('SELECT kill_switch_engaged FROM sentinel_automation_control WHERE id=1').fetchone()[0] is True
            conn.rollback()
        else:
            assert store.load_control(conn).kill_switch_engaged is True
        assert not campaign.running['automation'] and campaign.worker is None
        if not isinstance(refusal.value,core.ActivationPending):
            assert not campaign.running['shadow']
        assert (receipt.read_bytes() if receipt.exists() else None)==before
        assert campaign.backups<=1
        campaign.preserve()
    finally:
        campaign.stop('automation')
