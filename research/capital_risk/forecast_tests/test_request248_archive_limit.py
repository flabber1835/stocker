"""Exact large saved-export option; original crypto and default bounds preserved."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REQUEST248_ARCHIVE_METADATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_partial as p

def target():return json.loads((C/'P07-request248-positive-transport-target.json').read_bytes())

def test_only_exact_current_qualified_export_gets_existing_one_GiB_option():
 value=target();assert p.reviewed_archive_limit(value)==1024**3
 other=deepcopy(value);other['run_id']+=1;assert p.reviewed_archive_limit(other)==512*1024**2
 other=deepcopy(value);other['zip_sha256']='0'*64;assert p.reviewed_archive_limit(other)==512*1024**2

@pytest.mark.parametrize('change',['zip','manifest','gzip','endpoint','date','preflight','reviewer','format','authority','predecessor'])
def test_wrong_commitment_or_scope_cannot_borrow_archive_option(change):
 value=target()
 if change=='zip':value['zip_bytes']+=1
 elif change=='manifest':value['manifest']['raw_member_bytes']-=1
 elif change=='gzip':value['selected_file']['sha256']='0'*64
 elif change=='endpoint':value['measured_closes']+=1
 elif change=='date':value['selected_session']='2023-10-04'
 elif change=='preflight':value['prior_stops']['preflight']['exit_code']=1
 elif change=='reviewer':value['prior_stops']['reviewer']['exit_code']=1
 elif change=='format':value['archive_format']='WRONG_FORMAT_DTO'
 elif change=='authority':value['financial_authority']=True
 else:value['financial_predecessor_admitted']=True
 with pytest.raises(ValueError,match='P07_REQUEST248'):p.reviewed_archive_limit(value)

def test_archive_commitment_guard_has_meaningful_removal_falsifier():
 value=target();value['zip_bytes']+=1
 with pytest.raises(ValueError,match='EXACT_ONE_GIB_COMMITMENTS'):p.reviewed_archive_limit(value)
 fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='reviewed_archive_limit')
 branch=next(n for n in fn.body if isinstance(n,ast.If) and "42477533629"in ast.unparse(n.test))
 call=next(n for n in branch.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='PARTIAL_P07_REQUEST248_EXACT_ONE_GIB_COMMITMENTS' for a in n.value.args))
 branch.body.remove(call);scope=dict(vars(p));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-exact-archive-option-DATA-guard>','exec'),scope)
 assert scope['reviewed_archive_limit'](value)==1024**3

def test_original_crypto_source_is_unchanged():assert p.sha(Path(p.crypto.__file__).read_bytes())==p.CRYPTO_SHA

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
