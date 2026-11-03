"""Pure admission falsifiers and source/workflow boundary checks; no replay."""
import ast,gzip,hashlib,inspect,json,os,subprocess,sys
from copy import deepcopy
from pathlib import Path
import pytest
import system_campaign_reconstruction_admit as a

ROOT=Path(a.__file__).parent


def selection():
    return (json.loads((ROOT/'system-campaign-reconstruction-admission.json').read_bytes()),
            json.loads((ROOT/'system-campaign-p02-december-predecessor.json').read_bytes()))


@pytest.mark.parametrize('field',('outer_sha256','selected_session','run_id'))
def test_exact_own_financial_boundary_mutation_refuses(field):
    admission,spec=selection();a.require_scope(admission,spec)
    spec[field]='wrong'
    with pytest.raises(ValueError):a.require_scope(admission,spec)


def test_actual_boundary_guard_removal_falsifier():
    admission,spec=selection();spec['outer_sha256']='wrong'
    with pytest.raises(ValueError):a.require_scope(admission,spec)
    tree=ast.parse(inspect.getsource(a.require_scope));tree.body[0].body=[ast.Pass()]
    scope=dict(vars(a));exec(compile(ast.fix_missing_locations(tree),'<removed-boundary>','exec'),scope)
    scope['require_scope'](admission,spec)


def test_later_only_cash_scope_preserves_checkpoint_and_next_market_packet():
    catalog=json.loads((ROOT/'system-campaign-december-cash-calendar-terminal-facts.json').read_bytes())
    a.require_later_cash(catalog,'2021-12-01')
    bad=deepcopy(catalog);bad['terms'][0]['native_session']='2021-12-01'
    with pytest.raises(ValueError):a.require_later_cash(bad,'2021-12-01')
    bad=deepcopy(catalog);bad['provider_metadata_upgraded']=True
    with pytest.raises(ValueError):a.require_later_cash(bad,'2021-12-01')


def test_external_review_original_bytes_and_qualified_implementations_are_bound():
    admission,_=selection()
    from hashlib import sha256
    assert sha256(admission['independent_review_raw_utf8'].encode()).hexdigest()==admission['independent_review_sha256']
    assert json.loads(admission['independent_review_raw_utf8'])==admission['independent_review']
    for name,expected in admission['qualified_reconstruction_source_sha256'].items():
        assert sha256((ROOT/name).read_bytes()).hexdigest()==expected


def test_no_local_reconstruction_material_or_cloud_admission():
    with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):a.FirstMaterial({},None).__enter__()
    with pytest.raises(ValueError):a.admit({}, {},None,None,b'0'*32)


def test_source_closure_request_and_single_isolated_workflow():
    import system_campaign_p02_december_job as job
    from forecast_tests.test_basis_job_sources import dependencies
    assert not dependencies(job.SOURCES)-set(job.SOURCES)
    r=job.expected_request()
    assert r==json.loads((ROOT/'system-campaign-p02-december-request.json').read_bytes())
    assert r['only_candidate']=='P02' and r['concurrent_candidate_limit']==1 and not r['new_origin']
    assert r['execution_mode']=='QUALIFIED_RECONSTRUCTION_DECEMBER_CASH_SUFFIX'
    workflow=(ROOT.parents[1]/'.github/workflows/capital-system-p02-december.yml').read_text()
    assert "paths: ['research/capital_risk/system-campaign-p02-december-request.json']" in workflow
    assert 'cancel-in-progress: false' in workflow and 'retention-days: 7' in workflow
    assert 'system_campaign_p02_december_job.py' in workflow


def test_actual_first_material_is_checked_before_returning_to_runtime():
    tree=ast.parse(inspect.getsource(a.FirstMaterial));nodes={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    prepare=nodes['prepare'];text=ast.unparse(prepare)
    assert text.index('self.prepare(')<text.index('fingerprint(plain(value))')<text.index('return value')
    wrapper=(ROOT/'system_campaign_p02_december_run.py').read_text()
    assert 'FirstMaterial(admission,out),reconstruction:' in wrapper
    assert "financial_driver_total',backtest.main,args+['--repair-overlay',str(overlay)]" in wrapper
    assert "spec['run_id']==41134805155" in wrapper and "spec['selected_session']=='2021-11-30'" in wrapper


def test_host_job_imports_in_a_fresh_transfer_only_interpreter():
    script='''import importlib.abc,sys
class NoReplayPackages(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'pydantic','numpy','pandas','research','sentinel'}:
            raise ModuleNotFoundError('Replay-only import forbidden in transfer process: '+fullname)
sys.meta_path.insert(0,NoReplayPackages())
import system_campaign_p02_december_job as job
assert len(job.SOURCES)==140
'''
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT)
    result=subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,env=env,timeout=30)
    assert result.returncode==0,result.stderr
    old=subprocess.check_output(['git','show','9ecce2dd8d45dd67717e8f33bd425d447d39428f:research/capital_risk/system_campaign_reconstruction_admit.py']).decode()
    broken=script.split('import system_campaign_p02_december_job')[0]+"exec("+repr(old)+", {'__name__':'prior_failed_import'})\n"
    failure=subprocess.run([sys.executable,'-B','-c',broken],capture_output=True,text=True,env=env,timeout=30)
    assert failure.returncode!=0 and 'pydantic' in failure.stderr


def test_exact_qualified_pure_comparator_runs_without_replay_imports(tmp_path):
    cp=dict(journals={'daily':dict(bytes=4)},sha256='synthetic',completed=1,cash=50)
    for name in ('cold','bounded'):
        root=tmp_path/name;(root/'book').mkdir(parents=True)
        (root/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
        (root/'book/daily.jsonl').write_bytes(b'row\n')
        (root/'correlation-inputs.jsonl.gz').write_bytes(gzip.compress(b'correlation\n'))
        (root/'uncertainty-certificate.jsonl').write_bytes(b'certificate\n')
    source=ROOT/'system_campaign_resume_qualification.py';h=hashlib.sha256(source.read_bytes()).hexdigest()
    assert a.compare_stopped_books(tmp_path/'cold',tmp_path/'bounded',source,h)['all_next_checkpoint_fields_and_journal_bytes_equal']
    with pytest.raises(ValueError):a.compare_stopped_books(tmp_path/'cold',tmp_path/'bounded',source,'0'*64)
    cp['cash']=51;(tmp_path/'bounded/book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    with pytest.raises(ValueError):a.compare_stopped_books(tmp_path/'cold',tmp_path/'bounded',source,h)


@pytest.mark.parametrize('field',('NetworkMode','MemorySwap','ReadonlyRootfs'))
def test_actual_known_inspection_fence_mutation_refuses(field):
    # An inspection is metadata, not Docker or financial execution.
    admission,_=selection();v=dict(Name=admission['worker_identity']['name'],Id=admission['worker_identity']['id'],
        Image=__import__('runtime_identity').EXECUTION_IMAGE,State=dict(Running=False,OOMKilled=False,ExitCode=0),
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
                        PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in ('/variant','/frozen','/driver','/out','/old')],
        Config=dict(WorkingDir='/variant',User=admission['worker_identity']['user'],
                    Labels={'research.study':'full-system-search-20261029','research.role':'worker'},Env=[],
                    Cmd=['-B','-u','/driver/system_campaign_resume_qualification.py','--spec','/out/spec.json',
                         '--request','/driver/system-campaign-reconstruction-request.json']))
    a.require_stopped(v,admission['worker_identity']);v['HostConfig'][field]=None
    with pytest.raises(ValueError):a.require_stopped(v,admission['worker_identity'])
