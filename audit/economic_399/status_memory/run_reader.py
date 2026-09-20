"""Run a fresh, capped reader in the offline fixture's network namespace."""
import argparse
from pathlib import Path
import subprocess
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--memory', default='512m')
    parser.add_argument('--diagnostic-bound-context', action='store_true',
                        help='Profiling only: use retained context after source edits; never acceptance.')
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--surface', choices=['shadow', 'http'], default='shadow')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--cpus', default='2')
    parser.add_argument('--mutant-retain-seed', action='store_true', help='Negative resource control only.')
    args = parser.parse_args()
    code = '''import json
from pathlib import Path
from audit.economic_399.full_status import probe
v=json.loads(Path('/evidence/fixture.json').read_text())
from datetime import datetime,timedelta,timezone
original_fixture=probe.fixture_context
def dated_fixture(mp,subject=None):
    original_fixture(mp,subject)
    session=v.get('session','2026-09-14')
    now=datetime.fromisoformat(session).replace(tzinfo=timezone.utc)+timedelta(days=1,hours=4)
    mp.setattr(probe.op.calendar,'latest_closed_session',lambda now=None:session)
    mp.setattr(probe.op,'_now',lambda:now)
    mp.setattr(probe.initial,'_now',lambda conn:now)
probe.fixture_context=dated_fixture
'''
    if args.diagnostic_bound_context:
        code += '''import os
os.environ['SENTINEL_PUBLICATION_RECEIPT_KEY']='test-only-receipt-key-'*4
from sentinel import rolling_checkpoint, rolling_initialization
original=rolling_initialization._context
with probe.store.connect(v['dsn']) as c:
    retained=rolling_checkpoint.read(c)
def diagnostic_context(*args,_original_context=original):
    context=_original_context(*args)
    assert context['controller'].digest==retained.strategy_identity['controller_rule_sha256']
    context['strategy']=retained.strategy_identity
    return context
rolling_initialization._context=diagnostic_context
print('DIAGNOSTIC_BOUND_CONTEXT_ONLY: source identity gate replaced for profiling; NOT acceptance',flush=True)
'''
    if args.detail:
        code += '''from sentinel import shadow_observation
for cls,names in [(shadow_observation.ShadowObserver, ['__init__','_persist_and_verify_genesis','_history']),
                  (shadow_observation.PostgresShadowObservationStore,['genesis','records','matches_genesis'])]:
    for name in names:
        original=getattr(cls,name)
        def measured(*a,_original=original,_name=cls.__name__+'.'+name,**kw):
            probe.emit('before:'+_name,**probe.memory())
            result=_original(*a,**kw)
            probe.emit('after:'+_name,**probe.memory())
            return result
        setattr(cls,name,measured)
'''
    if args.mutant_retain_seed:
        code += '''from sentinel import rolling_runtime
real_closure=rolling_runtime._closure
def retaining_closure(conn,context,**kwargs):
    return real_closure(conn,context,status_only=False)
rolling_runtime._closure=retaining_closure
print('MUTANT: status uses the reusable advancement observer',flush=True)
'''
    if args.surface == 'shadow':
        code += f"for _ in range({args.repeats}):\n    probe.read(v['dsn'],v['subject'],v['state_sha256'])\n"
    else:
        code += '''import importlib,time
from fastapi.testclient import TestClient
with probe.pytest.MonkeyPatch.context() as mp:
    probe.fixture_context(mp,v['subject'])
    mp.setenv('SENTINEL_DATABASE_URL',v['dsn'])
    mp.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    mp.setenv('SENTINEL_SHADOW_OBSERVATION_ID',probe.OBS)
    mp.setenv('SENTINEL_SHADOW_STARTING_CASH','100000')
    mp.setenv('SENTINEL_STATE_DIR','/tmp/absent-status-fixture-state')
    app=importlib.import_module('sentinel.panel.app')
    started=time.monotonic()
    with TestClient(app.app) as client:
        response=client.get('/panel.json')
    assert response.status_code==200,response.text
    result=response.json()
    row=next(row for row in result['rows'] if row['key']=='shadow_verification')
    assert row['status']=='ok',row
    probe.emit('complete_http',seconds=time.monotonic()-started,shadow=row,
               overall=result['overall'],**probe.memory())
'''
    code += "probe.emit('cgroup',peak=Path('/sys/fs/cgroup/memory.peak').read_text().strip(),events=Path('/sys/fs/cgroup/memory.events').read_text())\n"
    name = 'sentinel-status-reader-' + uuid4().hex[:12]
    command = ['docker', 'run', '--name', name, '--network', 'container:sentinel-status-memory-fixture',
        '--memory', args.memory, '--memory-swap', args.memory, '--cpus', args.cpus,
        '--mount', f'type=bind,source={args.source.resolve().as_posix()},target=/source,readonly',
        '--mount', f'type=bind,source={args.evidence.resolve().as_posix()},target=/evidence,readonly',
        '--workdir', '/source', '--env', 'PYTHONPATH=/source:/source/shared:/source/scripts',
        '--env', 'SENTINEL_REPO_ROOT=/source', '--env', 'PYTHONDONTWRITEBYTECODE=1',
        '--entrypoint', 'python', 'sentinel-test:ci', '-u', '-c', code]
    print(command, flush=True)
    result = subprocess.run(command)
    subprocess.run(['docker', 'inspect', '--format',
        '{{json .State}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.Image}}', name], check=True)
    subprocess.run(['docker', 'rm', name], check=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
