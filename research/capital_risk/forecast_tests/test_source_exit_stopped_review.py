"""Actual FIN366 metadata and a complete noncanonical host-launch assembly."""
import ast,base64,json,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('FIN366_READONLY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_stopped_review as p


def request():return json.loads((C/p.REQUEST).read_bytes())


def test_actual_capture_and_review_source_delta_are_exact():
 fact,captured=p.validate(request());target=fact['target']
 assert len(captured['sources'])==716 and len(request()['sources'])==721
 assert target['measured_closes']==1821 and len(target['repairs'])==13
 capture=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial366-source-snapshot/authenticated-artifact-13587599730/authenticated-manifest.json')
 if capture.is_file():assert target['selected_file']['sha256']==json.loads(capture.read_bytes())['members']['book/checkpoint.json.gz']['sha256']
 from system_campaign_financial_partial import root_spec
 assert p.profile_request(captured,root_spec('P06',p.ROOT)) is True


@pytest.mark.parametrize('field,value',[('financial_authority',True),('input_adopted',True),('maximum_parallel_financial_workers',1),('maximum_parallel_readonly_workers',2),('review_profile','OTHER')])
def test_request_cannot_enable_finance_or_other_profile(field,value):
 v=request();v[field]=value
 with pytest.raises(ValueError):p.validate(v)


def test_financial_authority_guard_removal_falsifier(monkeypatch):
 v=request();v['financial_authority']=True
 with pytest.raises(ValueError):p.validate(v)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='FIN366_ZERO_FINANCIAL_AUTHORITY' else original(value,label))
 assert p.validate(v)[0]['financial_authority'] is False


@pytest.mark.parametrize('change',['missing_source','extra_source','missing_delta','extra_delta','old_pin','unlisted_source'])
def test_source_differences_cannot_be_hidden_or_expanded(change):
 v=request()
 if change=='missing_source':v['sources'].pop('system_campaign_progress_observer.py')
 elif change=='extra_source':v['sources']['unreviewed.py']='f'*64
 elif change=='missing_delta':v['review_source_changes'].pop('system_campaign_source_exit_observer.py')
 elif change=='extra_delta':v['review_source_changes']['system_campaign_financial_future.py']=dict(original='a'*64,review='b'*64)
 elif change=='old_pin':v['review_source_changes']['system_campaign_source_exit_observer.py']['original']='f'*64
 else:v['sources']['system_campaign_financial_branches.py']='f'*64
 with pytest.raises(ValueError):p.validate(v)


@pytest.mark.parametrize('change',['complete','admitted','wrong_archive','changed_stop'])
def test_actual_failed_target_cannot_be_relabelled(monkeypatch,change):
 fact=json.loads((C/p.FACT).read_bytes());v=fact['target']
 if change=='complete':v['receipt_status']='FINANCIAL_COMPLETE'
 elif change=='admitted':v['financial_predecessor_admitted']=True
 elif change=='wrong_archive':v['zip_bytes']+=1
 else:v['prior_stops']['reviewer']['exit_code']=0
 read=p.Path.read_bytes
 def patched(path):return p.encoded(fact) if path==C/p.FACT else read(path)
 monkeypatch.setattr(p.Path,'read_bytes',patched)
 # The unchanged request pin must fail before changed target metadata is used.
 with pytest.raises(ValueError):p.validate(request())


def test_local_worker_refuses_before_financial_imports(monkeypatch):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):p.worker()


def test_worker_fences_both_entry_points_until_all_review_and_reporting_exit():
 node=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='worker')
 body=ast.unparse(node)
 assert 'backtest.main = financial.advance = refuse' in body
 block=next(n for n in node.body if isinstance(n,ast.Try))
 assert 'entry.context' in ast.unparse(block) and 'review_entry' in ast.unparse(block)
 assert 'backtest.main, financial.advance, runtime.request_financial, runtime.selected = saved' in ast.unparse(block.finalbody[0])
 assignment=next(i for i,n in enumerate(node.body) if ast.unparse(n)=='runtime.selected = review_selection')
 fence=next(i for i,n in enumerate(node.body) if ast.unparse(n)=='backtest.main = financial.advance = refuse')
 assert fence<assignment<node.body.index(block)
 assert not any(isinstance(n,ast.Call) and ast.unparse(n.func) in ('backtest.main','financial.advance','runtime.run') for n in ast.walk(node))


def test_actual_REVIEW367_archived_profile_mismatch_and_strict_readonly_provenance():
 from system_campaign_financial_partial import root_spec
 import system_campaign_source_exit_runtime as runtime
 captured=json.loads((C/p.CAPTURED).read_bytes());spec=root_spec('P06',p.ROOT)
 assert runtime.selected(spec,captured) is False
 assert p.review_selection(spec,captured) is True
 for key in ('financial_resume_authorized','selected_source_exit_successors','admitted_checkpoints'):
  bad=deepcopy(captured);bad.pop(key)
  with pytest.raises(ValueError):p.review_selection(spec,bad)


def test_actual_archive_uses_an_existing_crypto_option_without_relaxing_actual_size():
 from system_campaign_factual_admit import archive_bound
 target=p.validate(request())[0]['target']
 with pytest.raises(ValueError,match='ENCRYPTED_DOWNLOAD_BOUND'):archive_bound(target,512*1024**2)
 with pytest.raises(ValueError,match='DECLARED_ARCHIVE_LIMIT'):archive_bound(target,target['zip_bytes'])
 archive_bound(target,1024**3)
 node=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='failed_admit')
 assert "FIN366_ONLY_EXACT_ARCHIVE_USES_ONE_GIB_OPTION" in ast.unparse(node)
 assert "ast.parse('1024 ** 3'" in ast.unparse(node)


@pytest.mark.parametrize('unknown',[False,True])
def test_whole_host_launch_uses_readonly_mounts_and_preserves_unknown_without_export(tmp_path,monkeypatch,unknown):
 import probe,stage,full_system_trials_job,alpaca_fit_job
 import system_campaign_financial_resume as resume
 import system_campaign_source_exit_runtime as runtime
 import system_campaign_stopped_parent as loader
 import system_campaign_variants as variants
 monkeypatch.setattr(probe,'check_context',lambda env:None)
 monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_RUN_ID','777')
 monkeypatch.setenv('GITHUB_SHA','a'*40);monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
 monkeypatch.setenv(stage.SECRET,base64.b64encode(b'x'*32).decode())
 monkeypatch.setenv('GH_TOKEN','EXPLICIT_NONCANONICAL_TOKEN_DTO')
 monkeypatch.setattr(resume,'stage_valid',lambda value:None)
 staging=tmp_path/'noncanonical-staging.json';staging.write_text('{}')
 old=tmp_path/'noncanonical-old';evidence=tmp_path/'noncanonical-evidence'
 binding=dict(parameters=dict(EXPLICIT_NONCANONICAL_DTO=True))
 for folder in (old,evidence):folder.mkdir();(folder/'source-bindings.json').write_bytes(p.encoded(binding))
 monkeypatch.setattr(p,'failed_admit',lambda target,root,key:evidence)
 monkeypatch.setattr(resume,'admit_partial',lambda *a:old)
 @contextmanager
 def context(spec,captured,*,profile_validator):
  assert profile_validator(captured,spec) is True
  yield
 monkeypatch.setattr(loader,'context',context)
 def build(frozen,source,parameters):
  assert parameters==binding['parameters'];source.mkdir();return binding
 monkeypatch.setattr(variants,'build',build)
 monkeypatch.setattr(full_system_trials_job,'command',lambda *a:['docker','run','--entrypoint','python3','image','-B','original'])
 calls=[]
 def stopped(values,name,out,*,deadline,inspector):
  assert name=='capital-system-resume-p06-review-777-1' and inspector is p.inspect and deadline==2400
  assert f'type=bind,source={old},target=/old,readonly' in values
  assert f'type=bind,source={evidence},target=/evidence,readonly' in values
  assert '/driver/system_campaign_source_exit_stopped_review.py' in values
  assert 'GH_TOKEN' not in p.os.environ and stage.SECRET not in p.os.environ
  calls.append('stopped')
  if unknown:raise alpaca_fit_job.StopUnknown('EXPLICIT_NONCANONICAL_UNKNOWN_DTO')
  return dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
 monkeypatch.setattr(alpaca_fit_job,'stopped_run',stopped)
 def seal(*a,**k):calls.append('sealed');return dict(EXPLICIT_NONCANONICAL_ASSET_DTO=True)
 monkeypatch.setattr(full_system_trials_job,'seal',seal)
 output=tmp_path/'receipt.json'
 if unknown:
  with pytest.raises(alpaca_fit_job.StopUnknown):p.launch(C/p.REQUEST,staging,output)
  assert calls==['stopped'] and json.loads(output.read_bytes())['status']=='REVIEW_UNKNOWN_NO_MUTABLE_EXPORT'
 else:
  assert p.launch(C/p.REQUEST,staging,output)==0 and calls==['stopped','sealed']
  assert json.loads(output.read_bytes())['financial_sessions_advanced']==0
 # These are explicit noncanonical test files, never a financial book.
 for folder in (old,evidence):
  folder.chmod(0o700)
  for f in folder.iterdir():f.chmod(0o600)


def test_five_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(name)
