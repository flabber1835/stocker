"""Qualified bytes, immutable requests and explicit resumable host operations."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import importlib.util
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT/'scripts'/'sentinel_local_delivery'
SPEC = importlib.util.spec_from_file_location('delivery_cli_fixture',PACKAGE/'__init__.py',
    submodule_search_locations=[str(PACKAGE)])
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
cli = importlib.import_module(SPEC.name+'.cli')
builder = importlib.import_module(SPEC.name+'.builder')
qualification = importlib.import_module(SPEC.name+'.qualification')
model = importlib.import_module(SPEC.name+'.model')

OLD, NEW = 'a'*40, 'b'*40
OLD_IMAGE, NEW_IMAGE = 'sha256:'+'c'*64, 'sha256:'+'d'*64


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    source, deployment, folder = (tmp_path/name for name in ('source','deployment','operation'))
    for path in (source,deployment,folder): path.mkdir()
    files = {'sentinel/module.py': 'value = 1\n','scripts/example.py':'pass\n',
             'tests/test_example.py':'def test_example(): assert True\n',
             'docs/current.md':'Current contract\n','Dockerfile.sentinel':'FROM exact-runtime\n'}
    for name,content in files.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    approved=['sentinel/module.py']
    def git(root,*args):
        assert Path(root)==source
        if args==('ls-files','-z'): return '\0'.join(files)+'\0'
        if args==('rev-parse','HEAD'): return NEW
        if args==('status','--porcelain'): return ''
        if args==('branch','--show-current'): return 'codex/simplify'
        if args==('merge-base',OLD,NEW): return OLD
        if args==('diff','--name-only',OLD,NEW): return '\n'.join(approved)
        if args==('diff','--name-status','--no-renames',OLD,NEW):
            return '\n'.join('M\t'+name for name in approved)
        raise AssertionError(args)
    monkeypatch.setattr(qualification,'git',git)
    monkeypatch.setattr(builder,'git',git)
    log=tmp_path/'qualification.log';log.write_text('..... [100%]\n5 passed in 0.32s\n')
    report=dict(schema=qualification.SCHEMA,commit=NEW,predecessor_commit=OLD,
        at='2031-04-21T21:00:00+00:00',source_files=qualification.source_files(source),
        source_files_unchanged=True,final=True,results=[dict(name='affected',exit_code=0,
            passed=5,skipped=0,deselected=0,log=str(log),log_sha256=qualification.sha256_file(log),
            command=['python','-m','pytest','tests/test_example.py'])])
    report_path=tmp_path/'qualification.json';model.write_new(report_path,report)
    postgres=dict(command=['postgres','-c','archive_mode=off','-c','archive_command='],
        container='postgres-container',image='postgres-image',source='/docker/volume',
        started='2031-01-01T00:00:00Z',volume='sentinel_sentinel_pgdata')
    previous=tmp_path/'installed.json'
    model.write_new(previous,dict(stage='APPLICATIONS_HEALTHY_LEADERSHIP_ADVANCING',
        leadership_advancing=True,completed_at='2031-04-20T20:00:00+00:00',
        commit=OLD,image=OLD_IMAGE,postgres=postgres,preserved={'system':'12345678'}))
    delta=tmp_path/'allowed.json';model.write_new(delta,approved)
    return SimpleNamespace(source=source,deployment=deployment,folder=folder,report=report,
        report_path=report_path,report_sha=qualification.sha256_file(report_path),log=log,
        previous=previous,delta=delta,approved=approved,files=files,git=git)


def validate(value):
    return qualification.validate_report(value.report_path,value.report_sha,value.source,NEW,OLD)


def request(inputs, paths):
    return dict(schema=model.SCHEMA,operation_id='reviewed-inputs',source=str(inputs.source),
        deployment=str(inputs.deployment),predecessor=builder.baseline(inputs.previous),
        candidate=dict(commit=NEW,image=NEW_IMAGE,
            source_identity={'source':'2'*64,'wealth':'4'*64,'shadow_config':'3'*64}),
        qualification=dict(report_path=str(inputs.report_path),report_sha256=inputs.report_sha,
            commit=NEW,passed=True,source_files=inputs.report['source_files']),
        allowed_delta=paths,created_at=model.utcnow().isoformat())


def qualified_tool_change(inputs, *, approved):
    name='tools/sentinel_rolling_publisher_falsifiers.py'
    inputs.files[name]='def qualification_only(): return True\n'
    path=inputs.source/name;path.parent.mkdir();path.write_text(inputs.files[name])
    # The fake Git diff follows the actual changed files independently of the
    # separately reviewed on-disk allowed list.
    inputs.approved.append(name)
    if approved:
        inputs.delta.write_bytes(model.canonical(inputs.approved))
    inputs.report['source_files']=qualification.source_files(inputs.source)
    inputs.report_path.write_bytes(model.canonical(inputs.report))
    inputs.report_sha=qualification.sha256_file(inputs.report_path)
    return name


def test_report_is_bound_to_complete_actual_tracked_inputs_and_retained_log(inputs):
    assert validate(inputs)==inputs.report
    (inputs.source/'scripts/example.py').write_text('changed\n')
    with pytest.raises(model.DeliveryRefused,match='QUALIFIED_SOURCE_BYTES_CHANGED'):
        validate(inputs)


@pytest.mark.parametrize('damage', ['digest','result','count','skip','deselect','command','log','partial-map','not-final'])
def test_report_cannot_be_an_arbitrary_pass_claim(inputs,damage):
    value=deepcopy(inputs.report)
    if damage=='digest': inputs.report_sha='f'*64
    elif damage=='result': value['results'][0]['exit_code']=1
    elif damage=='count': value['results'][0]['passed']=999
    elif damage=='skip': value['results'][0]['skipped']=1
    elif damage=='deselect': value['results'][0]['deselected']=1
    elif damage=='command': value['results'][0]['command'].append('--deselect=tests/guard.py::test_guard')
    elif damage=='log': inputs.log.write_text('5 passed, 1 failed in 0.3s\n')
    elif damage=='partial-map': value['source_files'].pop('Dockerfile.sentinel')
    else: value['final']=False
    if damage not in {'digest','log'}:
        inputs.report_path.write_bytes(model.canonical(value))
        inputs.report_sha=qualification.sha256_file(inputs.report_path)
    with pytest.raises(model.DeliveryRefused): validate(inputs)


@pytest.mark.parametrize('branch', ['main','master',''])
def test_build_qualification_requires_clean_committed_feature_branch(inputs,monkeypatch,branch):
    def git(root,*args):
        return branch if args==('branch','--show-current') else inputs.git(root,*args)
    monkeypatch.setattr(qualification,'git',git)
    with pytest.raises(model.DeliveryRefused,match='FEATURE_BRANCH_REQUIRED'): validate(inputs)


def test_removed_qualified_source_check_is_detected(inputs,monkeypatch):
    source=inspect.getsource(qualification.validate_report)
    needle="report['source_files'] == source_files(source)"
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,'True'),'removed-qualified-source-check','exec'),
        vars(qualification),namespace)
    monkeypatch.setattr(qualification,'validate_report',namespace['validate_report'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_report_is_bound_to_complete_actual_tracked_inputs_and_retained_log(inputs)


def images():
    configuration=dict(Env=['PATH=/bin','SENTINEL_IMAGE_SOURCE_REVISION='+OLD],
        Labels={'org.opencontainers.image.revision':OLD,'sentinel.delivery':'owner-local'},
        Cmd=['python','-m','sentinel'],Entrypoint=None,User='sentinel',WorkingDir='/app')
    old=dict(Id=OLD_IMAGE,Config=configuration,RootFS={'Layers':['foundation-layer']})
    new=deepcopy(old);new['Id']=NEW_IMAGE;new['RootFS']['Layers'].append('source-layer')
    new['Config']['Env']=['PATH=/bin','SENTINEL_IMAGE_SOURCE_REVISION='+NEW]
    new['Config']['Labels']['org.opencontainers.image.revision']=NEW
    return old,new


def fake_host(inputs):
    old,new=images()
    class Host:
        calls=[]
        def __init__(self,request,folder): self.request=request;self.clean={};self.folder=folder
        @contextmanager
        def owned(self):
            self.calls.append('lock')
            yield
            self.calls.append('unlock')
        def run(self,command,**kwargs):
            self.calls.append(command)
            if command[:3]==['docker','image','inspect']:
                image=old if command[-1]=='sentinel-local-paper:'+OLD[:8] else new
                return SimpleNamespace(stdout=json.dumps([image]).encode())
            assert command[:2]==['docker','run']
            assert '--network' in command and command[command.index('--network')+1]=='none'
            assert 'production_strategy()[1]' in command[-1]
            return SimpleNamespace(stdout=json.dumps({'strategy':'e'*64}).encode())
        def probe(self,commit,image):
            return dict(source=('1' if commit==OLD else '2')*64,shadow_config='3'*64,wealth='4'*64)
    return Host


def run_build(inputs,monkeypatch):
    calls=[]
    def build(command,**kwargs):
        calls.append(command)
        assert command[:2]==['docker','build']
        assert '--network' in command and command[command.index('--network')+1]=='none'
        assert '--pull=false' in command
        kwargs['stdout'].write(b'Completed source-only Docker build\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(builder.subprocess,'run',build)
    host=fake_host(inputs)
    result=builder.build(source=inputs.source,deployment=inputs.deployment,
        predecessor_receipt=inputs.previous,qualification=inputs.report_path,
        qualification_sha256=inputs.report_sha,approved_delta=inputs.delta,
        approved_delta_sha256=qualification.sha256_file(inputs.delta),
        operation_dir=inputs.folder,commit=NEW,host_type=host)
    return result,calls,host


def test_offline_build_has_only_exact_tracked_runtime_source_and_retained_evidence(inputs,monkeypatch):
    result,calls,host=run_build(inputs,monkeypatch)
    assert result['image']==NEW_IMAGE and result['source_identity']['wealth']=='4'*64
    assert len(calls)==1
    context=Path(result['context'])
    assert sorted(str(path.relative_to(context)).replace('\\','/') for path in context.rglob('*') if path.is_file()) == [
        'Dockerfile','sentinel/module.py']
    assert (context/'Dockerfile').read_text().startswith('FROM sentinel-local-paper:'+OLD[:8]+'\n')
    assert model.read_json(inputs.folder/'build.json')==result
    assert host.calls[0]=='lock' and host.calls[-1]=='unlock'
    with pytest.raises(model.DeliveryRefused,match='ALREADY_STARTED'):
        run_build(inputs,monkeypatch)


def test_reviewed_qualification_tool_is_accepted_without_entering_runtime_image(inputs,monkeypatch):
    tool=qualified_tool_change(inputs,approved=True)
    result,_,_=run_build(inputs,monkeypatch)
    assert result['allowed_delta']==result['changed_files']==sorted(inputs.approved)
    assert tool in inputs.report['source_files']
    context=Path(result['context'])
    assert sorted(path.relative_to(context).as_posix() for path in context.rglob('*') if path.is_file())==[
        'Dockerfile','sentinel/module.py']
    class Candidate:
        def __init__(self,selected,folder): self.request=selected
        def verify_candidate(self):
            assert self.request['allowed_delta']==sorted(inputs.approved)
    path=inputs.folder/'build.json'
    journal=cli.prepare(operation_dir=inputs.folder,build_record=path,
        build_sha256=qualification.sha256_file(path),operation_id='reviewed-tool',host_type=Candidate)
    assert tool in journal.request['allowed_delta']
    assert journal.request['qualification']['source_files'][tool]==qualification.sha256_file(inputs.source/tool)


@pytest.mark.parametrize('gate',['build','candidate'])
def test_unapproved_extra_qualification_tool_refuses_before_any_host_operation(inputs,monkeypatch,gate):
    qualified_tool_change(inputs,approved=False)
    if gate=='build':
        def forbidden_host(*args): pytest.fail('unapproved delta constructed a host')
        with pytest.raises(model.DeliveryRefused,match='CANDIDATE_DELTA_CHANGED'):
            builder.build(source=inputs.source,deployment=inputs.deployment,
                predecessor_receipt=inputs.previous,qualification=inputs.report_path,
                qualification_sha256=inputs.report_sha,approved_delta=inputs.delta,
                approved_delta_sha256=qualification.sha256_file(inputs.delta),
                operation_dir=inputs.folder,commit=NEW,host_type=forbidden_host)
        assert not (inputs.folder/'build-started.json').exists()
    else:
        host=cli.Host.__new__(cli.Host)
        host.request=model.validate_request(request(inputs,model.read_json(inputs.delta)))
        host.source=inputs.source
        host.git=lambda *args: inputs.git(inputs.source,*args)
        host.run=lambda *args,**kwargs: pytest.fail('unapproved delta launched a host operation')
        with pytest.raises(model.DeliveryRefused,match='CANDIDATE_DELTA_CHANGED'):
            host.verify_candidate()


def test_reviewed_tool_bytes_remain_bound_to_completed_qualification(inputs):
    tool=qualified_tool_change(inputs,approved=True)
    assert validate(inputs)==inputs.report
    (inputs.source/tool).write_text('def qualification_only(): return False\n')
    with pytest.raises(model.DeliveryRefused,match='QUALIFIED_SOURCE_BYTES_CHANGED'):
        validate(inputs)


@pytest.mark.parametrize('gate',['build','request'])
@pytest.mark.parametrize('name',[
    'tools/../.env','tools/sub/../../outside.py','tools\\escape.py','/tools/absolute.py',
    'tools/.env','tools/.env.production','tools/private.env','tools/sub/.env.local',
    'Dockerfile.sentinel','docker-compose.sentinel.yml','requirements.txt','pyproject.toml',
    'unreviewed/extra.py',
])
def test_tools_input_root_does_not_admit_unsafe_or_unreviewed_path_classes(inputs,gate,name):
    if gate=='build':
        inputs.delta.write_bytes(model.canonical([name]))
        with pytest.raises(model.DeliveryRefused,match='APPROVED_DELTA_PATH'):
            builder.allowed_delta(inputs.delta,qualification.sha256_file(inputs.delta))
    else:
        with pytest.raises(model.DeliveryRefused,match='REQUEST_DELTA_PATH'):
            model.validate_request(request(inputs,[name]))


@pytest.mark.parametrize('damage',['layer','environment','user','label'])
def test_source_layer_cannot_change_foundation_or_execution_configuration(damage):
    old,new=images()
    if damage=='layer': new['RootFS']['Layers'][0]='another-foundation'
    elif damage=='environment': new['Config']['Env'].append('ALPACA_BASE_URL=https://api.alpaca.markets')
    elif damage=='user': new['Config']['User']='root'
    else: new['Config']['Labels']['org.opencontainers.image.revision']=OLD
    with pytest.raises(model.DeliveryRefused): builder._foundation_preserved(old,new,NEW)


def test_prepare_uses_completed_baseline_and_verified_build_then_refuses_replacement(inputs,monkeypatch):
    result,_,_=run_build(inputs,monkeypatch)
    class Candidate:
        checks=[]
        def __init__(self,request,folder): self.request=request
        def verify_candidate(self): self.checks.append(self.request)
    path=inputs.folder/'build.json'
    journal=cli.prepare(operation_dir=inputs.folder,build_record=path,
        build_sha256=qualification.sha256_file(path),operation_id='one-reviewed-operation',host_type=Candidate)
    assert journal.read()['stage']=='NEW'
    assert journal.request['predecessor']['commit']==OLD
    assert journal.request['candidate']['image']==result['image']
    assert journal.request['qualification']['report_sha256']==inputs.report_sha
    assert Candidate.checks==[journal.request]
    with pytest.raises(model.DeliveryRefused,match='ALREADY_PREPARED'):
        cli.prepare(operation_dir=inputs.folder,build_record=path,
            build_sha256=qualification.sha256_file(path),operation_id='another',host_type=Candidate)


def test_status_does_not_construct_a_host_or_launch_a_child(inputs,monkeypatch):
    run_build(inputs,monkeypatch)
    class Candidate:
        def __init__(self,*args): pass
        def verify_candidate(self): pass
    path=inputs.folder/'build.json'
    cli.prepare(operation_dir=inputs.folder,build_record=path,build_sha256=qualification.sha256_file(path),
        operation_id='status-only',host_type=Candidate)
    monkeypatch.setattr(cli,'Host',lambda *args: pytest.fail('status constructed a host'))
    assert cli.main(['status','--operation-dir',str(inputs.folder)])==0
    assert cli.status(inputs.folder)['stage']=='NEW'


@pytest.mark.parametrize('command',['advance','resume'])
@pytest.mark.parametrize('one',[False,True])
def test_cli_delegates_only_supported_stage_progression(inputs,monkeypatch,command,one):
    events=[]
    class Host:
        def __init__(self,*args): events.append('host')
        @contextmanager
        def owned(self):
            events.append('lock');yield;events.append('unlock')
    class Delivery:
        def __init__(self,*args): pass
        def step(self): events.append('step')
        def advance(self): events.append('advance')
    monkeypatch.setattr(cli,'Journal',lambda folder: SimpleNamespace(request={},folder=folder))
    monkeypatch.setattr(cli,'Host',Host);monkeypatch.setattr(cli,'Delivery',Delivery)
    monkeypatch.setattr(cli,'status',lambda folder: {'stage':'NEW'})
    args=[command,'--operation-dir',str(inputs.folder)]+(['--one-stage'] if one else [])
    assert cli.main(args)==0
    assert events==(['host','lock','step','unlock'] if one else ['host','advance'])


def test_importing_entrypoint_performs_no_operation(monkeypatch):
    monkeypatch.setattr(builder.subprocess,'run',lambda *args,**kwargs: pytest.fail('import launched a child'))
    spec=importlib.util.spec_from_file_location('local_delivery_entrypoint',ROOT/'scripts/sentinel_local_delivery.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
