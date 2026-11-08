"""Exact authentic saved-result metadata and transport bounds; no restoration."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('REQUEST228_ADMISSION_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_partial as p
ROOT='3d0a107ee7e00a4f8345d21a268ce7f5d097b0e57ccc3620f4ba7c23d2f633cf'
OLD='27c4e51a5fc479b418668a7950a4146129380eb73dc029840b0a62a9a0163da0'

def test_current_exact2050_root_and_unchanged1821_ancestry():
 spec=p.root_spec('P06');a=spec['root_admission'];old=p.root_spec('P06',OLD)
 assert spec['root_admission_sha256']==ROOT and a['parent_root_admission_sha256']==OLD
 assert (a['completed'],a['source_cursor'],a['new_daily_records'],a['independent_accounting_snapshots'])==(2050,'2026-02-27',229,458)
 assert len(a['repairs'])==14 and a['same_artifact_successful_original_review'] is True
 assert [a['original_financial_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,0]
 assert (old['measured_closes'],len(old['repairs']))==(1821,13)
 assert [old['root_admission']['original_failed_financial_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,1]
 assert not any(k.startswith(('fresh_readonly_','original_failed_financial_')) for k in a)
 assert a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is a['local_canonical_runtime_executed'] is False
 assert a['uncommitted_tail_commitments']['daily']['unadmitted_tail']['bytes']>0

def test_exact_original_transport_selects_existing_one_gib_option():
 spec=p.root_spec('P06')
 with pytest.raises(ValueError,match='ENCRYPTED_DOWNLOAD_BOUND'):p.crypto.archive_bound(spec,512*1024**2)
 assert p.reviewed_archive_limit(spec)==1024**3
 p.crypto.archive_bound(spec,1024**3)
 assert p.sha(Path(p.crypto.__file__).read_bytes())==p.CRYPTO_SHA
 assert p.reviewed_archive_limit(p.root_spec('P07','b134772ff8128b4f97a16dabbc357f07e019351c529c03419cb778726fad5a59'))==512*1024**2

@pytest.mark.parametrize('mutation',['manifest','selected','stopped','oom','review','bool_exit'])
def test_changed_commitments_and_unknown_or_failed_writers_refuse(mutation):
 spec=deepcopy(p.root_spec('P06'))
 if mutation=='manifest':spec['manifest']['member_count']+=1
 elif mutation=='selected':spec['selected_file']['sha256']='0'*64
 elif mutation=='stopped':spec['prior_stops']['worker']['stopped']=False
 elif mutation=='oom':spec['prior_stops']['worker']['oom_killed']=True
 elif mutation=='review':spec['prior_stops']['reviewer']['exit_code']=1
 else:spec['prior_stops']['worker']['exit_code']=True
 with pytest.raises(ValueError):p.reviewed_archive_limit(spec)

def test_unknown_clock_retains_original_default_limit():
 spec=deepcopy(p.root_spec('P06'));spec['artifact_id']+=1
 assert p.reviewed_archive_limit(spec)==512*1024**2

def test_positive_stop_guard_removal_falsifier():
 spec=deepcopy(p.root_spec('P06'));spec['prior_stops']['worker']['oom_killed']=True
 with pytest.raises(ValueError,match='ORIGINAL_POSITIVE_REVIEW_STOP_SCOPE'):p.reviewed_archive_limit(spec)
 fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='reviewed_archive_limit')
 branch=next(n for n in fn.body if isinstance(n,ast.If) and any(isinstance(v,ast.Constant) and v.value=='P06' for v in ast.walk(n.test)))
 guard=next(n for n in branch.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
  and any(isinstance(v,ast.Constant) and v.value=='PARTIAL_P06_REQUEST228_ORIGINAL_POSITIVE_REVIEW_STOP_SCOPE' for v in n.value.args))
 branch.body.remove(guard);scope=dict(vars(p))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<DATA-only-stop-guard-falsifier>','exec'),scope)
 assert scope['reviewed_archive_limit'](spec)==1024**3
