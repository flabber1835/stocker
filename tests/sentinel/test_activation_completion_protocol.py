"""Actual host reader corruption probes; no engine or service started."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
import sentinel_autonomous_deploy_install_entry as install

GOOD=dict(schema='sentinel.dual-plan-shadow-reconciliation/1',verdict='MATCH',
 state_sha256='a'*64,shadow_runtime_authority_sha256='b'*64,
 sizing_authority_sha256='c'*64,plan_fingerprint='d'*64)
MARKER='SENTINEL_DUAL_RECONCILIATION='

def reader(raw):
 obj=install.InstallAnytimeDeploy(SimpleNamespace(),SimpleNamespace(env={}),Path('/tmp'))
 obj.phase=lambda *a:None
 obj._authorized_compose=lambda:[]
 obj.runner.run=lambda *a,**k:SimpleNamespace(returncode=0,stdout=raw)
 return obj._verify_dual_plan_shadow_reconciliation()

def test_exact_reconciliation_marker_is_accepted():
 assert reader('routine output\n'+MARKER+json.dumps(GOOD))==GOOD

@pytest.mark.parametrize('corruption',[
 'duplicate-verdict','nonfinite','duplicate-marker','malformed-then-valid',
 'nonobject','malformed','wrong-fingerprint','mismatch'])
def test_remaining_reconciliation_wire_corruption_refuses(corruption):
 raw=json.dumps(GOOD)
 if corruption=='duplicate-verdict':raw=raw.replace('"verdict": "MATCH"','"verdict":"MISMATCH","verdict":"MATCH"')
 elif corruption=='nonfinite':raw=raw[:-1]+',"extra":NaN}'
 elif corruption=='duplicate-marker':raw=raw+'\n'+MARKER+raw
 elif corruption=='malformed-then-valid':raw='{invalid\n'+MARKER+raw
 elif corruption=='nonobject':raw='[]'
 elif corruption=='malformed':raw='{invalid'
 elif corruption=='wrong-fingerprint':raw=raw.replace('d'*64,'foreign')
 elif corruption=='mismatch':raw=raw.replace('MATCH','MISMATCH')
 with pytest.raises(install.core.DeployRefused):reader(MARKER+raw)

REVIEWED=SimpleNamespace(runtime_image_digest='sha256:'+'1'*64,
 source_identity_sha256='2'*64,shadow_configuration_sha256='3'*64,
 data_publication_sha256='4'*64,bundle_sha256='5'*64,mode='dual',git_commit='6'*40)
DATA=dict(transaction_read_only=True,binding=dict(publication_fingerprint='7'*64,visible_frontier='2026-10-08'))
PREFLIGHT=dict(schema='sentinel.shadow-service-preflight/1',mode='BROKER_FREE_SHADOW',status='VERIFIED',broker_mutations_authorized=False)

def invoke_result(raw,code=0):
 def invoke(argv,**kwargs):
  assert not any(kwargs.get('env',{}).get(k) for k in ('ALPACA_API_KEY','ALPACA_SECRET_KEY','SENTINEL_PAPER_ACCOUNT_ID'))
  return SimpleNamespace(returncode=0,stdout='-f fixture.yml') if '--explain' in argv else SimpleNamespace(returncode=code,stdout=raw)
 return invoke

def test_adjacent_publication_and_lineage_positive_contracts():
 actual=install.core._current_data_publication_subject(REVIEWED,env={},invoke=invoke_result('SENTINEL_DEPLOY_DATA_BINDING='+json.dumps(DATA)))
 assert json.loads(actual)['publication_fingerprint']=='7'*64
 install.core._reviewed_shadow_lineage_preflight(REVIEWED,env={},invoke=invoke_result(json.dumps(PREFLIGHT)))

@pytest.mark.parametrize('corruption',['duplicate-key','nonfinite','duplicate-marker','malformed-then-valid','nonobject','failed-command'])
def test_adjacent_publication_reader_refuses_corrupt_result(corruption):
 marker='SENTINEL_DEPLOY_DATA_BINDING='
 raw=json.dumps(DATA);code=0
 if corruption=='duplicate-key':raw=raw.replace('"transaction_read_only": true','"transaction_read_only":false,"transaction_read_only":true')
 elif corruption=='nonfinite':raw=raw[:-1]+',"extra":Infinity}'
 elif corruption=='duplicate-marker':raw=raw+'\n'+marker+raw
 elif corruption=='malformed-then-valid':raw='{bad\n'+marker+raw
 elif corruption=='nonobject':raw='[]'
 elif corruption=='failed-command':code=2
 with pytest.raises(install.core.DeployRefused):
  install.core._current_data_publication_subject(REVIEWED,env={},invoke=invoke_result(marker+raw,code))

@pytest.mark.parametrize('raw',[json.dumps(PREFLIGHT).replace('"broker_mutations_authorized": false','"broker_mutations_authorized":true,"broker_mutations_authorized":false'),
 json.dumps(PREFLIGHT)[:-1]+',"extra":-Infinity}', '[]','{bad'])
def test_adjacent_lineage_reader_refuses_corrupt_result(raw):
 with pytest.raises(install.core.DeployRefused):
  install.core._reviewed_shadow_lineage_preflight(REVIEWED,env={},invoke=invoke_result(raw))
