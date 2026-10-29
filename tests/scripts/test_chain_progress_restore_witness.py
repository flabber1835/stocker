"""Execute the actual restore witness launcher; no database or Docker access."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])


@pytest.mark.parametrize('fault',[None,'metadata','docker','witness','deadline','image'])
def test_actual_paused_restore_witness_launcher_has_no_broker_or_secret_arguments(tmp_path,fault):
    source=(ROOT/'scripts/sentinel-restore-drill.sh').read_text()
    start=source.index('\nif [ "$PHYSICAL_ONLY" -eq 1 ]; then')
    end=source.index('\ndocker exec ',start)
    launcher=source[start:end]
    fake=tmp_path/'docker.py'
    fake.write_text('''import json,os,sys
args=sys.argv[1:]
forwarded={}
for index,arg in enumerate(args[:-1]):
 if arg=='-e':
  name,sep,value=args[index+1].partition('=')
  forwarded[name]=value if sep else os.environ.get(name)
assert args[args.index('--entrypoint')+1]=='timeout'
assert '--read-only' in args and '--cap-drop' in args
assert args[args.index('--network')+1]=='private-replay'
assert args[args.index('--memory')+1]=='768m'
assert '--snapshot' in args and '--apply' not in args
assert set(forwarded)=={'SENTINEL_RESTORE_DATABASE_HOST','SENTINEL_RESTORE_DATABASE_PASSWORD','SENTINEL_PUBLICATION_RECEIPT_KEY'}
assert forwarded['SENTINEL_RESTORE_DATABASE_PASSWORD']==os.environ['SENTINEL_POSTGRES_PASSWORD']
assert not any(secret in arg for secret in (os.environ['SENTINEL_POSTGRES_PASSWORD'],os.environ['SENTINEL_PUBLICATION_RECEIPT_KEY']) for arg in args)
if os.environ.get('FAIL_DOCKER')=='yes':raise SystemExit(2)
if os.environ.get('WORKER_EXIT'):
 print('REFUSED: RecoveryRefused: exact predecessor fixture refused')
 raise SystemExit(int(os.environ['WORKER_EXIT']))
print(json.dumps({'witness':{'private_fixture':True},'hmac_sha256':'a'*64}))
''')
    output=tmp_path/'witness.json'
    env=dict(PATH=os.environ['PATH'],PHYSICAL_ONLY='1',CHAIN_PROGRESS_WITNESS=str(output),
        SENTINEL_RUNTIME_IMAGE_REF='repo/sentinel@sha256:'+'b'*64,
        METADATA_SHA256='a'*64,SENTINEL_POSTGRES_PASSWORD='synthetic-only-password',
        SENTINEL_PUBLICATION_RECEIPT_KEY='synthetic-only-key-'+'c'*32,
        NETWORK='private-replay',CONTAINER='private-replay',NAME='base-20261029T072734Z',
        MARKER='sentinel-backup-20261029T072734Z-123',PYTHON=sys.executable,
        RECORDING_PYTHON=sys.executable,RECORDING_DOCKER=str(fake),
        ALPACA_API_KEY='must-not-forward',SENTINEL_DATABASE_URL='must-not-forward')
    if fault=='image':env['SENTINEL_RUNTIME_IMAGE_REF']='mutable:latest'
    if fault=='docker':env['FAIL_DOCKER']='yes'
    if fault in ('witness','deadline'):env['WORKER_EXIT']='2' if fault=='witness' else '124'
    metadata='e'*64 if fault=='metadata' else 'a'*64
    adapter='docker() { "$RECORDING_PYTHON" "$RECORDING_DOCKER" "$@"; }\n'
    adapter+='metadata_digest() { printf "%s" "'+metadata+'"; }\n'
    result=subprocess.run(['bash','-eu','-c',adapter+launcher],cwd=ROOT,env=env,
                          capture_output=True,text=True)
    if fault:
        assert result.returncode!=0 and not output.exists()
        if fault in ('witness','deadline'):
            assert result.returncode==int(env['WORKER_EXIT'])
            assert 'REFUSED: RecoveryRefused: exact predecessor fixture refused' in result.stderr
            assert 'chain_progress_witness_ready:' not in result.stdout
    else:
        assert result.returncode==0, result.stderr
        assert json.loads(output.read_text())['witness']=={'private_fixture':True}
        assert 'chain_progress_witness_ready:'+str(output) in result.stdout
