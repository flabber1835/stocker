"""Only metadata, authenticated historical file reads and process stubs."""
import json,sys
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
import system_campaign_progress_observer as p

def DTO():return dict(schema='research.unverified-session-progress/1',run_id='123',head='a'*40,arm='P06',phase='worker',phase_state='ACTIVE',elapsed_seconds=12,observed_utc='2026-11-07T19:00:00+00:00',checkpoint_completed=1677,checkpoint_session='2024-08-30',constructor_marker_seen=True,writer_stopped=None,verified=False,financial_sessions_admitted=0,observer_sha256='b'*64)

def test_metadata_is_closed_unverified_and_cannot_admit_sessions():
 assert p.validate(DTO())['financial_sessions_admitted']==0
 for key,value in [('verified',True),('financial_sessions_admitted',1),('checkpoint_completed',True),('writer_stopped',1),('constructor_marker_seen','yes')]:
  v=DTO();v[key]=value
  with pytest.raises(ValueError):p.validate(v)
 v=DTO();v['EXPLICIT_NONCANONICAL_PRICE_FIELD_DTO']=3.23
 with pytest.raises(ValueError):p.validate(v)


def test_observational_credit_guard_removal_falsifier():
 import ast
 value=DTO();value['financial_sessions_admitted']=1
 with pytest.raises(ValueError):p.validate(value)
 node=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
 assert isinstance(node.body[0],ast.If) and 'PROGRESS_CLOSED_METADATA_ONLY' in ast.unparse(node.body[0])
 node.body.pop(0);scope=dict(vars(p))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<noncanonical-progress-guard-removal-falsifier>','exec'),scope)
 assert scope['validate'](value)['financial_sessions_admitted']==1

@pytest.mark.parametrize('value',[{},[],dict(completed=True,source_cursor='2024-08-30'),dict(completed=2157,source_cursor='2026-08-03'),dict(completed=1,source_cursor='PRIVATE_UNRELATED_DATA')])
def test_unknown_or_invalid_counter_stays_unknown(value):assert p.counters(value)==(None,None)

def test_real_existing_historical_gzip_is_only_read():
 root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001/verified-output')
 if not root.exists():pytest.skip('authenticated existing artifact required')
 file=root/'book/checkpoint.json.gz';before=p.hashlib.sha256(file.read_bytes()).hexdigest()
 n,day,marker=p.observe(root);assert (n,day,marker)==(1677,'2024-08-30',True)
 assert p.hashlib.sha256(file.read_bytes()).hexdigest()==before

def test_no_book_is_unknown_without_any_creation(tmp_path):
 assert p.observe(tmp_path)==(None,None,False) and not list(tmp_path.iterdir())

def test_observation_failure_cannot_change_original_result(monkeypatch):
 import probe
 monkeypatch.setattr(probe,'check_context',lambda env:None)
 class Bad:
  def __init__(self,*a):pass
  def start(self):pass
  def finish(self,result):raise RuntimeError('OBSERVATION_FAILURE_DTO')
 monkeypatch.setattr(p,'Observer',Bad);value=dict(EXPLICIT_NONCANONICAL_STOP_DTO=True,stopped=True)
 assert p.run(lambda *a,**k:value,[], 'dto',Path('dto')) is value

def test_original_unknown_stop_exception_is_preserved(monkeypatch):
 import probe
 monkeypatch.setattr(probe,'check_context',lambda env:(_ for _ in ()).throw(ValueError('NO_OBSERVER_DTO')))
 error=RuntimeError('EXPLICIT_NONCANONICAL_UNKNOWN_STOP_DTO')
 def original(*a,**k):raise error
 with pytest.raises(RuntimeError) as caught:p.run(original,[],'dto',Path('dto'))
 assert caught.value is error

def test_upload_has_one_metadata_path_no_shell_and_bounded_wait(monkeypatch,tmp_path):
 calls=[];monkeypatch.setattr(p,'ACTION',SimpleNamespace(is_file=lambda:True,__str__=lambda self:'ACTION_DTO'))
 monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:calls.append((a,k)))
 path=tmp_path/'progress.json';p.upload(path,'progress-123')
 args,kwargs=calls[0];assert args[0][0]=='node' and kwargs['env']['INPUT_PATH']==str(path)
 assert kwargs['shell'] is False and kwargs['timeout']==25 and kwargs['env']['INPUT_RETENTION_DAYS']=='1'

def test_launch_wrapper_restores_original_stopped_runner_on_error(monkeypatch):
 stop=lambda *a,**k:None;module=SimpleNamespace(stopped_run=stop)
 def original(args):
  assert module.stopped_run is not stop
  raise RuntimeError('EXPLICIT_NONCANONICAL_ABORT_DTO')
 with pytest.raises(RuntimeError):p.bind_launch(original,module)(None)
 assert module.stopped_run is stop
