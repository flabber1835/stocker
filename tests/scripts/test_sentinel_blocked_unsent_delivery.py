"""A fenced software repair cannot become readiness or financial recovery."""
from copy import deepcopy
import inspect
import io
import json
import sys
from types import SimpleNamespace
import urllib.request

import pytest

from tests.scripts import test_sentinel_local_delivery_evidence as readers
from tests.scripts import test_sentinel_local_delivery_coordinator as flow


def blocked_host():
    host=readers.Host()
    host.supports_blocked_unsent=True
    host.request['handoff_mode']='BLOCKED_UNSENT'
    host.request['predecessor']['postgres']={'command':['archive_command=archive %p %f']}
    host.load_values=lambda:{'SENTINEL_LOCAL_PAPER_ACCOUNT_ID':'PAPER-Z',
        'SENTINEL_LOCAL_PAPER_BACKUP_POLICY':'REQUIRED_V1'}
    state=host.state
    state.update(plan=None,authority_md5=None,archive_mode='on',archive_command='archive %p %f',
        repair=dict(lease_live=0,kill_event='KILL_ENGAGED',plain_kill=True,
                    scoped_plans=0,scoped_commands=0,transport_events=0))
    state['control'].update(generation=100,kill_switch_engaged=True,authority_verdict=None)
    state['cycle'].update(cycle_id='b'*64,state='BLOCKED',plan_id=None,historical_state_only=False,
        completed_at='2031-04-21T21:00:00+00:00',failure_code='NonRetryableCallbackRefused',
        failure_detail=readers.checks.PUBLICATION_CHANGED_FAILURE,
        diagnostic=dict(retry_phase='REFRESH',callback_failure='PERMANENT_OPERATIONAL_REFUSAL',
            terminal_reason='PERMANENT_OPERATIONAL_REFUSAL',
            exception_type='sentinel.automation.model.NonRetryableCallbackRefused'))
    return host


def test_exact_fenced_unsent_snapshot_has_no_plan_and_keeps_existing_history_domains():
    host=blocked_host()
    assert readers.evidence.snapshot(host)==host.state
    sql=host.calls[0]
    assert 'LEFT JOIN sentinel_execution_plans p ON p.plan_id=s.plan_id' in sql
    assert 's.control_generation=c.generation-1 AND' in sql
    assert "s.diagnostic->>'retry_phase'='REFRESH'" in sql
    assert 'scoped_plans' in sql and 'scoped_commands' in sql and 'transport_events' in sql
    assert "'commands_md5'" in sql and "'fills_md5'" in sql and "'issuer_evidence'" in sql
    assert "'plans_md5'" in sql and "'control_events_md5'" in sql
    for mode in ('PRE_OPEN','POST_TRADE'):
        normal=readers.checks.snapshot_sql(mode)
        assert 'LEFT JOIN sentinel_execution_plans p ON p.plan_id=s.plan_id' not in normal
        assert 's.control_generation=c.generation AND' in normal


@pytest.mark.parametrize('path,value',[
    (('control','kill_switch_engaged'),False), (('control','enabled'),False),
    (('control','generation'),101), (('cycle','control_generation'),100),
    (('cycle','state'),'SUPERSEDED'), (('cycle','plan_id'),'plan'),
    (('cycle','historical_state_only'),True), (('cycle','completed_at'),None),
    (('cycle','failure_detail'),'ROLLING_RUNTIME_PUBLICATION_CHANGED'),
    (('cycle','diagnostic','retry_phase'),'PREPARE'),
    (('cycle','diagnostic','exception_type'),'builtins.RuntimeError'),
    (('cycle','diagnostic','terminal_reason'),None),
    (('repair','lease_live'),1), (('repair','plain_kill'),False),
    (('repair','kill_event'),'KILL_RELEASED'), (('repair','scoped_plans'),1),
    (('repair','scoped_commands'),1), (('repair','transport_events'),1),
    (('repair','scoped_plans'),False), (('plan',),{'plan_id':'existing'}),
    (('inflight',),1), (('other_active',),1), (('jobs_active',),1),
    (('job_live_owners',),1), (('ready',),False),
    (('source_binding','job_state'),'READY'), (('source_binding','job_publication'),86),
])
def test_finite_repair_admission_refuses_every_unproved_boundary(path,value):
    host=blocked_host();selected=host.state
    for key in path[:-1]:selected=selected[key]
    selected[path[-1]]=value
    with pytest.raises(readers.model.DeliveryRefused):readers.evidence.snapshot(host)


def test_removing_negative_transport_proof_is_detected(monkeypatch):
    original=readers.evidence.require
    monkeypatch.setattr(readers.evidence,'require',lambda ok,reason:
        None if reason=='BLOCKED_UNSENT_NOT_FENCED_OR_UNSENT' else original(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_finite_repair_admission_refuses_every_unproved_boundary(('repair','scoped_commands'),1)


def test_no_plan_program_is_canonical_read_only_and_never_runs_schema_installation():
    checks=readers.checks
    compile(checks.BLOCKED_CANONICAL,'blocked-canonical','exec')
    compile(checks.BLOCKED_PANEL,'blocked-panel','exec')
    assert checks.BLOCKED_CANONICAL.count('rolling_runtime.status(')==1
    assert 'authority.rederive_plan(' not in checks.BLOCKED_CANONICAL
    assert 'default_transaction_read_only=on' in checks.BLOCKED_CANONICAL
    assert "'operational_ready':False" not in checks.CANONICAL
    assert 'operational_ready=False' in checks.BLOCKED_CANONICAL
    assert 'require_schema(c)' in checks.READ_OPERATIONAL_SCHEMA
    assert 'install_quiescent' not in checks.READ_OPERATIONAL_SCHEMA
    assert 'BEGIN TRANSACTION READ ONLY' in checks.READ_OPERATIONAL_SCHEMA
    assert 'not page[\'source_errors\']' in checks.BLOCKED_PANEL


operation=flow.operation


def repair_operation(operation,monkeypatch):
    host,journal,_=operation
    host.request['handoff_mode']='BLOCKED_UNSENT'
    (journal.folder/'request.json').write_text(json.dumps(host.request))
    journal=flow.model.Journal(journal.folder)
    host.items['sentinel-automation']['State']['Running']=False
    host.postgres_after_restart=lambda *_:pytest.fail('repair accepted a PostgreSQL restart')
    monkeypatch.setattr(flow.coordinator.evidence,'leader',lambda h:dict(current=False,
        holder=None,generation=77,fence=8,heartbeat=0))
    delivery=flow.coordinator.Delivery(host,journal,monotonic=lambda:host.clock,sleep=host.sleep)
    return host,journal,delivery


def test_complete_repair_finishes_software_only_with_same_fence_and_no_recovery(operation,monkeypatch):
    host,journal,delivery=repair_operation(operation,monkeypatch)
    before=deepcopy(host.state)
    receipt=delivery.advance()
    assert receipt['stage']=='VERIFIED' and host.state==before
    assert receipt['artifacts']['operational_ready'] is False
    assert receipt['artifacts']['installation_scope']=='FENCED_BLOCKED_UNSENT_SOFTWARE_ONLY'
    assert receipt['artifacts']['leader']['current'] is False
    assert host.canonical_count==2 and host.heartbeat==0
    assert not any('authorize' in str(call) or 'kill-switch' in str(call)
                   or 'postgres' in str(call) or 'backup' in str(call) for call in host.calls)
    assert all(item['Image']==host.request['candidate']['image'] for item in host.items.values())
    assert delivery.advance()==receipt


def test_repair_refuses_running_old_writer_before_any_handoff_mutation(operation,monkeypatch):
    host,journal,delivery=repair_operation(operation,monkeypatch)
    host.items['sentinel-automation']['State']['Running']=True
    with pytest.raises(flow.model.DeliveryRefused,match='WRITER_NOT_STOPPED'):delivery.advance()
    assert journal.read()['stage']=='NEW'
    assert not any(isinstance(call,tuple) for call in host.calls)


def test_repair_final_check_refuses_a_new_live_leader(operation,monkeypatch):
    host,journal,delivery=repair_operation(operation,monkeypatch)
    while journal.read()['stage']!='APPLICATIONS_STARTED':delivery.step()
    monkeypatch.setattr(flow.coordinator.evidence,'leader',lambda h:dict(current=True))
    with pytest.raises(flow.model.DeliveryRefused,match='LEADER_IS_ACTIVE'):delivery.step()
    assert journal.read()['stage']=='APPLICATIONS_STARTED'


def test_normal_modes_keep_green_panel_and_advancing_leader_contract():
    assert "assert not any(row.get('color')=='red'" in readers.checks.PANEL
    source=inspect.getsource(flow.coordinator.Delivery.step)
    assert "leader=self._leader(artifacts['preserved']['control']['generation'])" in source
    assert "if repair:" in source and "'operational_ready':False" in source


@pytest.mark.parametrize('fault',[None,'rw','other_mount','environment','neighbor','unqualified'])
def test_backed_compose_allows_only_exact_qualified_readonly_worker_mount(tmp_path,fault):
    from tests.scripts.test_sentinel_backed_local_patch import patch
    source=tmp_path/'source';source.mkdir()
    installed=tmp_path/'installed';installed.mkdir()
    originals={name:b'services:\n  unchanged: {}\n' for name in patch.COMPOSE}
    name='docker-compose.sentinel-automation.yml'
    originals[name]=b'services:\n  sentinel-automation:\n'+patch._AUTOMATION_ENTRY+b'    environment:\n      EXISTING: value\n'
    candidates=dict(originals)
    candidates[name]=originals[name].replace(patch._AUTOMATION_ENTRY,
        patch._AUTOMATION_ENTRY+patch._WORKER_READ_MOUNT)
    if fault=='rw':candidates[name]=candidates[name].replace(b':ro\n',b':rw\n')
    elif fault=='other_mount':candidates[name]=candidates[name].replace(b'/var/lib/sentinel:ro',b'/other:ro')
    elif fault=='environment':candidates[name]=candidates[name].replace(b'EXISTING: value',b'EXISTING: changed')
    elif fault=='neighbor':candidates[name]=candidates[name].replace(b'  sentinel-automation:',b'  other:')
    for key in originals:
        (source/key).write_bytes(candidates[key]);(installed/key).write_bytes(originals[key])
    host=object.__new__(patch.BackedHost);host.source=source;host.deployment=installed
    host.request=dict(predecessor={'commit':'a'*40},allowed_delta=[] if fault=='unqualified' else [name],
        qualification={'source_files':{key:patch.sha256_file(source/key) for key in originals}})
    host.git_bytes=lambda *args:originals[args[-1].split(':',1)[1]]
    if fault:
        with pytest.raises(patch.DeliveryRefused,match='COMPOSITION_CHANGE_REFUSED'):host.install_compose()
        assert (installed/name).read_bytes()==originals[name]
    else:
        host.verify_compose('predecessor');host.install_compose();host.verify_compose('candidate')
        assert (installed/name).read_bytes()==candidates[name]
        with pytest.raises(patch.DeliveryRefused,match='COMPOSITION_CHANGE_REFUSED'):
            host.verify_compose('predecessor')
        host.install_compose()  # Lost acknowledgement only repeats the same bytes.


@pytest.mark.parametrize('role',['predecessor','candidate'])
@pytest.mark.parametrize('fault',[None,'rw','other_mount','environment','neighbor','unqualified','hash'])
def test_colocated_checkout_accepts_only_already_qualified_exact_mount(tmp_path,role,fault):
    from tests.scripts.test_sentinel_backed_local_patch import patch
    root=tmp_path/'source-and-deployment';root.mkdir()
    name='docker-compose.sentinel-automation.yml'
    originals={key:b'services:\n  unchanged: {}\n' for key in patch.COMPOSE}
    originals[name]=b'services:\n  sentinel-automation:\n'+patch._AUTOMATION_ENTRY+b'    environment:\n      EXISTING: value\n'
    candidates=dict(originals)
    candidates[name]=originals[name].replace(patch._AUTOMATION_ENTRY,
        patch._AUTOMATION_ENTRY+patch._WORKER_READ_MOUNT)
    if fault=='rw':candidates[name]=candidates[name].replace(b':ro\n',b':rw\n')
    elif fault=='other_mount':candidates[name]=candidates[name].replace(b'/var/lib/sentinel:ro',b'/other:ro')
    elif fault=='environment':candidates[name]=candidates[name].replace(b'EXISTING: value',b'EXISTING: changed')
    elif fault=='neighbor':candidates[name]=candidates[name].replace(b'  sentinel-automation:',b'  other:')
    for key,raw in candidates.items():(root/key).write_bytes(raw)
    host=object.__new__(patch.BackedHost);host.source=root;host.deployment=root
    hashes={key:patch.sha256_file(root/key) for key in originals}
    if fault=='hash':hashes[name]='0'*64
    host.request=dict(predecessor={'commit':'a'*40},allowed_delta=[] if fault=='unqualified' else [name],
        qualification={'source_files':hashes})
    host.git_bytes=lambda *args:originals[args[-1].split(':',1)[1]]
    if fault:
        with pytest.raises(patch.DeliveryRefused,match='COMPOSITION_CHANGE_REFUSED'):host.verify_compose(role)
    else:
        host.verify_compose(role)
        assert (root/name).read_bytes()==candidates[name]


def test_removing_colocated_layout_gate_is_detected(tmp_path,monkeypatch):
    from tests.scripts.test_sentinel_backed_local_patch import patch
    import textwrap
    source=textwrap.dedent(inspect.getsource(patch.BackedHost.verify_compose))
    guard='and self.source.resolve()==self.deployment.resolve()'
    assert source.count(guard)==1
    namespace=dict(vars(patch))
    exec(source.replace(guard,'and True'),namespace)
    monkeypatch.setattr(patch.BackedHost,'verify_compose',namespace['verify_compose'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_backed_compose_allows_only_exact_qualified_readonly_worker_mount(tmp_path,None)


@pytest.mark.parametrize('fault',[None,'false_green','new_plan','source_error','unrelated_red',
    'foreign_certificate','revoked_certificate','generic_authority_unknown','wrong_mode',
    'wrong_exposure','adopted_exposure','wrong_decision','generic_exposure_unknown',
    'missing_certificate','missing_exposure','feed_unknown'])
def test_fenced_panel_program_retains_red_and_refuses_unrelated_failures(monkeypatch,capsys,fault):
    from datetime import datetime,timezone
    expected=dict(decision='2031-04-21',effective='2031-04-22',cycle_id='b'*64,plan=None,
        certificate='a4be'+'0'*60,core_exposure='0.55')
    def row(key,value,status='ok'):
        return dict(key=key,value=value,status=status,color='red' if status=='fail' else 'green')
    rows=[row('automation','ENABLED · KILLED','fail'),row('automation_leader','INACTIVE BY POLICY','pending'),
        row('automation_cycle','BLOCKED','fail'),row('paper_plan','NOT PREPARED','pending'),
        row('shadow_verification','SHADOW VERIFIED THROUGH '+expected['decision']),
        row('feed',expected['decision']+' · 0 sessions behind'),row('alert_dispatcher','HEALTHY')]
    authority=dict(key='authority',value='UNKNOWN',status='unknown',color='red',detail=(
        'no durable runtime authority verdict; lifecycle-only: ACTIVE · certificate '
        +expected['certificate'][:12]+' · expires 2031-04-22T13:30:00+00:00'
        +' · mode PAPER_OBSERVATION_ONLY · historical causality UNESTABLISHED'
        +' · maximum exposure 1 · authority generation 4'))
    exposure=dict(key='exposure',value='0.55 NOT ADOPTED',status='fail',color='red',
        detail='canonical controller decision has no current plan · decision '+expected['decision'])
    rows.extend([authority,exposure])
    page=dict(as_of=datetime.now(timezone.utc).isoformat(),color='red',source_errors=[],rows=rows)
    if fault=='false_green':page['color']='green'
    elif fault=='new_plan':rows[3]['paper_plan']={'plan_id':'invented'}
    elif fault=='source_error':page['source_errors']=['read failure']
    elif fault=='unrelated_red':rows.append(row('broker','UNKNOWN','fail'))
    elif fault=='foreign_certificate':authority['detail']=authority['detail'].replace(expected['certificate'][:12],'f'*12)
    elif fault=='revoked_certificate':authority['detail']=authority['detail'].replace('lifecycle-only: ACTIVE','lifecycle-only: REVOKED')
    elif fault=='generic_authority_unknown':authority['detail']='execution authority could not be read'
    elif fault=='wrong_mode':authority['detail']=authority['detail'].replace('PAPER_OBSERVATION_ONLY','unknown')
    elif fault=='wrong_exposure':exposure['value']='0.65 NOT ADOPTED'
    elif fault=='adopted_exposure':exposure['value']='0.55'
    elif fault=='wrong_decision':exposure['detail']=exposure['detail'].replace(expected['decision'],'2031-04-20')
    elif fault=='generic_exposure_unknown':exposure.update(value='UNKNOWN',status='unknown',detail='read failure')
    elif fault=='missing_certificate':expected.pop('certificate')
    elif fault=='missing_exposure':expected.pop('core_exposure')
    elif fault=='feed_unknown':rows[5].update(status='unknown',color='red',value='UNREADABLE')
    monkeypatch.setattr(sys,'argv',['program',json.dumps(expected)])
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**kw:io.BytesIO(json.dumps(page).encode()))
    if fault:
        with pytest.raises(AssertionError):exec(readers.checks.BLOCKED_PANEL,{})
    else:
        exec(readers.checks.BLOCKED_PANEL,{})
        assert json.loads(capsys.readouterr().out)['operational_ready'] is False


@pytest.mark.parametrize('fault',[None,'generation','killed','disabled','certificate','ready_generation',
    'ready_decision','kind','binding','fingerprints','incident'])
def test_later_normal_build_accepts_only_exact_recovery_lineage(monkeypatch,fault):
    from tests.scripts.test_sentinel_backed_local_patch import patch
    from sentinel_local_delivery import evidence
    host=readers.Host()
    host.load_values=lambda:{}
    ready=host.state
    ready['cycle']['cycle_id']='d'*64
    binding={key:ready['control'][key] for key in ('deployment_id','broker','broker_account_id',
        'takeover_epoch','certificate_sha256','rollout_mode','rollout_version','config_sha256')}
    repair=dict(generation=97,cycle_id='b'*64,fingerprints={'b'*64:'f'*64},binding=binding,
        decision=ready['cycle']['decision_session'],effective=ready['cycle']['effective_session'])
    record=dict(repair_predecessor=repair,system='123456789',postgres={'unchanged':True})
    state=dict(generation=99,certificate=binding['certificate_sha256'],enabled=True,killed=False)
    if fault=='generation':state['generation']=100
    elif fault=='killed':state['killed']=True
    elif fault=='disabled':state['enabled']=False
    elif fault=='certificate':state['certificate']='foreign'
    elif fault=='ready_generation':ready['control']['generation']=98
    elif fault=='ready_decision':ready['cycle']['decision_session']='2031-04-20'
    monkeypatch.setattr(evidence,'snapshot',lambda subject:deepcopy(ready))
    calls=[]
    def compose(values,*args,**kwargs):
        calls.append(args)
        expected=json.loads(args[-1])
        assert args[-2]==readers.checks.RECOVERY_LINEAGE
        assert expected['ready_cycle_id']=='d'*64 and expected['plan_id']=='future-plan'
        proof=dict(generation=99,blocked_cycle_id=repair['cycle_id'],certificate=binding['certificate_sha256'],
            fingerprints=repair['fingerprints'],kind='ROLLING_PUBLICATION_ADVANCE_MISCLASSIFIED',binding=binding)
        if fault=='kind':proof['kind']='LOCAL_CONTENTION_MISCLASSIFIED'
        elif fault=='binding':proof['binding']={**binding,'takeover_epoch':10}
        elif fault=='fingerprints':proof['fingerprints']={'b'*64:'e'*64}
        elif fault=='incident':proof['blocked_cycle_id']='e'*64
        return SimpleNamespace(stdout=json.dumps(proof).encode())
    host.compose=compose
    if fault:
        with pytest.raises(patch.DeliveryRefused):patch.recovered_baseline_generation(host,record,state)
    else:
        assert patch.recovered_baseline_generation(host,record,state)==99
        assert len(calls)==1
    assert 'rolling_runtime.status' not in readers.checks.RECOVERY_LINEAGE
    assert 'unsent_recovery.validate_authorization(' in readers.checks.RECOVERY_LINEAGE
    assert 'BEGIN TRANSACTION READ ONLY' in readers.checks.RECOVERY_LINEAGE


@pytest.mark.parametrize('fault',[None,'missing','ambiguous','record','state','decision','nonfinite',
    'negative','above_one','missing_value','receipt_hash'])
def test_repair_exposure_is_one_bound_scalar_read_not_a_book_replay(tmp_path,monkeypatch,fault):
    from tests.scripts.test_sentinel_backed_local_patch import patch
    state=dict(cycle={'decision_session':'2031-04-21'})
    book=dict(session='2031-04-21',record_sha256='a'*64,state_sha256='b'*64)
    proof=dict(book=book,book_state_sha256='b'*64)
    receipt=dict(stage='APPLICATIONS_STARTED',artifacts=dict(canonical_proof=proof,
        successor_proof_sha256=patch.digest(proof),preserved=state))
    if fault=='receipt_hash':receipt['artifacts']['successor_proof_sha256']='changed'
    monkeypatch.setattr(patch,'Journal',lambda folder:SimpleNamespace(read=lambda:receipt))
    row=dict(session='2031-04-21',decision_session='2031-04-21',record_sha256='a'*64,
        state_sha256='b'*64,core_exposure='0.55')
    if fault=='record':row['record_sha256']='c'*64
    elif fault=='state':row['state_sha256']='c'*64
    elif fault=='decision':row['decision_session']='2031-04-20'
    elif fault=='nonfinite':row['core_exposure']='NaN'
    elif fault=='negative':row['core_exposure']='-0.1'
    elif fault=='above_one':row['core_exposure']='1.1'
    elif fault=='missing_value':row['core_exposure']=None
    rows=[] if fault=='missing' else [row,row] if fault=='ambiguous' else [row]
    host=object.__new__(patch.BackedHost);host.operation_dir=tmp_path
    host.request={'handoff_mode':'BLOCKED_UNSENT'};host.load_values=lambda:{'SENTINEL_SHADOW_OBSERVATION_ID':'primary'}
    queries=[]
    host.sql=lambda sql:queries.append(sql) or rows
    if fault:
        with pytest.raises(patch.DeliveryRefused):host.repair_core_exposure(state)
    else:
        assert host.repair_core_exposure(state)=='0.55' and len(queries)==1
    if queries:
        assert 'LIMIT 2' in queries[0] and "state->>'record_sha256'='"+'a'*64 in queries[0]
        assert "state->>'state_sha256'='"+'b'*64 in queries[0]
        assert 'last_decision' in queries[0] and 'md5' not in queries[0]
        assert 'state::text' not in queries[0] and 'SELECT state ' not in queries[0]


def test_repair_panel_receives_actual_bound_certificate_and_scalar(monkeypatch):
    host=blocked_host()
    host.state['control']['certificate_sha256']='a4be'+'0'*60
    calls=[]
    host.container=lambda name:{'Id':'exact-panel'}
    host.repair_core_exposure=lambda state:calls.append(state) or '0.55'
    def run(argv,**kwargs):
        expected=json.loads(argv[-1])
        assert expected['certificate']==host.state['control']['certificate_sha256']
        assert expected['core_exposure']=='0.55' and expected['plan'] is None
        return SimpleNamespace(stdout=b'{"operational_ready":false}')
    host.run=run
    assert readers.evidence.panel(host,host.state)=={'operational_ready':False}
    assert calls==[host.state]


@pytest.fixture(scope='module')
def leader_postgres():
    from tests.support.postgres import _EphemeralPostgres
    pg=_EphemeralPostgres()
    try:
        pg.start()
        yield pg.sync_dsn
    finally:
        pg.stop()


@pytest.mark.parametrize('case,current',[
    ('cleared',False),('current',True),('no_holder',False),('no_heartbeat',False),
    ('no_expiry',False),('stale',False),('expired',False),
])
def test_private_postgres_leader_current_is_a_real_boolean(leader_postgres,case,current):
    from datetime import datetime,timedelta,timezone
    import psycopg
    now=datetime.now(timezone.utc)
    holder=None if case in {'cleared','no_holder'} else 'actual-holder'
    heartbeat=None if case in {'cleared','no_heartbeat'} else now-timedelta(seconds=120 if case=='stale' else 0)
    expiry=None if case in {'cleared','no_expiry'} else now+timedelta(seconds=-120 if case=='expired' else 600)
    with psycopg.connect(leader_postgres,autocommit=True) as conn:
        conn.execute('CREATE TEMP TABLE sentinel_automation_lease(id integer,holder_id text,'
            'fence_token integer,control_generation integer,heartbeat_at timestamptz,expires_at timestamptz)')
        conn.execute('INSERT INTO sentinel_automation_lease VALUES (1,%s,8,51,%s,%s)',
            (holder,heartbeat,expiry))
        host=SimpleNamespace(sql=lambda sql:conn.execute(sql).fetchone()[0])
        proof=readers.evidence.leader(host)
        assert proof['current'] is current,'lease current flag must not be NULL'
        assert proof['holder']==holder and proof['generation']==51
        conn.execute('DELETE FROM sentinel_automation_lease')
        host.sql=lambda sql:(row[0] if (row:=conn.execute(sql).fetchone()) is not None else None)
        assert readers.evidence.leader(host) is None  # No invented cleared-lease row.


def test_removing_null_safe_lease_proof_is_detected(leader_postgres,monkeypatch):
    source=inspect.getsource(readers.evidence.leader)
    assert source.count('COALESCE(holder_id IS NOT NULL AND ')==1
    source=source.replace('COALESCE(holder_id IS NOT NULL AND ','').replace(
        'expires_at>clock_timestamp(),FALSE))','expires_at>clock_timestamp())')
    namespace=dict(vars(readers.evidence))
    exec(source,namespace)
    monkeypatch.setattr(readers.evidence,'leader',namespace['leader'])
    with pytest.raises(AssertionError,match='must not be NULL'):
        test_private_postgres_leader_current_is_a_real_boolean(leader_postgres,'cleared',False)
