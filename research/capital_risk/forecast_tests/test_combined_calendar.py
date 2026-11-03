"""Pure merge and exact source/job contracts; no canonical replay."""
import ast,inspect,json,os,subprocess,sys
from copy import deepcopy
from pathlib import Path
import pytest
import system_campaign_combined_calendar as c

ROOT=Path(c.__file__).parent


def doc(sid):
    return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='own',
        source_evidence=[dict(reference='source:'+sid,sha256=None,description='original')],
        suppress=[dict(session='2022-02-22',security_id=sid,term_sha256='native')],
        add=[dict(session='2022-02-23',security_id=sid,cash_per_share=79.25,exchange_ratio=None)])


def test_merge_preserves_every_original_term_and_reference_without_aliasing():
    a,b=doc('one'),doc('two');old=deepcopy([a,b]);r=c.combine_documents([a,b],'own')
    assert [a,b]==old and r['add']==a['add']+b['add'] and r['source_evidence']==a['source_evidence']+b['source_evidence']
    a['add'][0]['cash_per_share']=0
    assert r['add'][0]['cash_per_share']==79.25


@pytest.mark.parametrize('kind',('predecessor','native','effective','reference'))
def test_inconsistent_component_or_duplicate_keys_refuse(kind):
    a,b=doc('one'),doc('two')
    if kind=='predecessor':b['predecessor_checkpoint_sha256']='wrong'
    if kind=='native':b['suppress']=deepcopy(a['suppress'])
    if kind=='effective':b['add']=deepcopy(a['add'])
    if kind=='reference':b['source_evidence']=[{**a['source_evidence'][0],'sha256':'wrong'}]
    with pytest.raises(ValueError):c.combine_documents([a,b],'own')


def test_predecessor_guard_removal_is_detected():
    a=doc('one');a['predecessor_checkpoint_sha256']='wrong'
    with pytest.raises(ValueError):c.combine_documents([a],'own')
    tree=ast.parse(inspect.getsource(c.combine_documents));loop=next(n for n in tree.body[0].body if isinstance(n,ast.For))
    loop.body.pop(0);scope=dict(vars(c));exec(compile(ast.fix_missing_locations(tree),'<merge-guard-removed>','exec'),scope)
    assert scope['combine_documents']([a],'own')['predecessor_checkpoint_sha256']=='own'


def test_new_job_request_dependency_closure_and_latest_own_large_predecessor():
    import system_campaign_p02_february_job as j
    from forecast_tests.test_basis_job_sources import dependencies
    assert not dependencies(j.SOURCES)-set(j.SOURCES)
    request=j.expected_request();assert request==json.loads((ROOT/'system-campaign-p02-february-request.json').read_bytes())
    spec=json.loads((ROOT/request['predecessor_file']).read_bytes())
    assert spec['selected_session']=='2022-01-31' and spec['run_id']==41144048233 and len(spec['repairs'])==25
    assert spec['zip_bytes']>1024**3 and request['source_archive_limit_bytes']==2*1024**3
    assert request['only_candidate']=='P02' and request['concurrent_candidate_limit']==1
    assert not request['new_origin'] and request['reconstruction_mode']=='ORIGINAL_COLD_WITH_QUALIFIED_FAST_TRANSACTION_SCOPE'


def test_new_job_imports_without_any_replay_only_packages():
    script='''import importlib.abc,sys
class DenyReplay(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'pydantic','numpy','pandas','research','sentinel'}:raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0,DenyReplay())
import system_campaign_p02_february_job
'''
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT)
    p=subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,env=env,timeout=30)
    assert p.returncode==0,p.stderr


def test_all_component_probes_use_actual_combined_object_and_all_old_inputs():
    text=Path(c.__file__).read_text();ast.parse(text)
    assert "cash.qualify(loaded,old_objects" in text and "stock.qualify(loaded,old_objects" in text
    wrapper=(ROOT/'system_campaign_p02_february_run.py').read_text()
    assert "before='2022-02-22'" in wrapper and "current['repairs'][:-1]==cp['repairs']" in wrapper
    assert 'FirstMaterial(' not in wrapper and 'Reconstruction(' not in wrapper
    workflow=(ROOT.parents[1]/'.github/workflows/capital-system-p02-february.yml').read_text()
    assert "paths: ['research/capital_risk/system-campaign-p02-february-request.json']" in workflow
    assert 'system-optimization-002-p02-only' in workflow and 'cancel-in-progress: false' in workflow
