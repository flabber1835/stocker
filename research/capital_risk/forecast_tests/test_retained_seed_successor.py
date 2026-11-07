"""Actual admitted424 proof metadata, whole original seed, local factory fences."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('RETAINED_SUCCESSOR_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_retained_seed_successor as p
from system_campaign_financial_partial import root_spec as admitted_root
def root_spec(arm):return admitted_root(arm,'ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845') if arm=='P06' else admitted_root(arm)

@pytest.fixture(scope='module')
def actual():
 root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001/verified-output')
 if not root.exists():pytest.skip('authenticated FIN356 artifact required for actual DATA checks')
 root=Path('\\\\?\\'+str(root.resolve()));spec=root_spec('P06');v=p.metadata(spec)
 parent=json.loads(gzip.decompress((root/spec['selected_checkpoint']).read_bytes()));raw=(root/'uncertainty-certificate.jsonl').read_bytes()
 rows=[json.loads(n) for n in raw.splitlines()[:v['committed_rows']]];resolution=v['historical_event_resolution']
 hashes=json.loads((root/'branch-controller-qualification.json').read_bytes())['exact_controller_sources']
 return parent,spec,rows,[resolution],{},(root/resolution['actual']).read_bytes(),hashes,raw

def check(a):
 parent,spec,rows,resolutions,allowed,archive,hashes,raw=a
 return p.qualify_metadata(parent,spec,rows,rows,resolutions,allowed,archive,hashes,hashes)

def test_metadata_phase_is_exact_admitted251_plus173():
 spec=root_spec('P06');v=p.metadata(spec)
 assert p.phase(spec)==dict(rows=424,new_rows=251,retained_rows=173)
 assert v['raw_rows']==442 and v['historical_event_input_count']==10 and len(v['input_descriptors'])==12

def test_complete_actual424_metadata_and_literal442_file(actual):
 assert check(actual)==dict(passed=True,committed_rows=424,unadmitted_tail_rows_used=0,second_event_authorized=False,financial_authority=False)
 assert p.literal_prefix(actual[-1],actual[2],actual[1])

def test_whole_original_retained_seed_on_actual_readonly_parent(actual):
 parent,spec,rows,resolutions,allowed,archive,hashes,raw=actual
 D=Path('C:/GitHub/stocker/.codex-tmp/p06-fin356-DATA-20261107');sys.path.insert(0,str(D))
 import p06_FIN356_components_DATA as qualified
 root=Path('\\\\?\\C:\\Users\\mbron\\.codex\\visualizations\\2026\\11\\05\\01a1ac36-4c96-7aa1-82ca-4efb70a86ea8\\financial356-P06-source-snapshot\\capture-P06-13581395529-001\\verified-output')
 def member(n):return (root/n).read_bytes()
 parent11=qualified.strict_json(member(qualified.models.PARENT));seen=[]
 def visitor(r,current):
  assert r==root and current is parent
  qualified.full_history(r,parent11,current,member,qualified.strict_json);seen.append(current['sha256'])
 fn=p.bind_seed(contract=lambda current,target:hashes,visitor=visitor,reader=p.initial.seed_reader(inherited_root=C))
 result=fn(root,parent,spec)
 assert result[0]==hashes and result[1]==rows and seen==[parent['sha256']]
 assert len(result[1])==424 and json.loads(result[2])['passed'] is True

@pytest.mark.parametrize('change',['state','count','descriptors','proof','tail','resolution','authority','archive','controller'])
def test_corrupt_or_unadmitted_seed_material_is_refused(actual,change):
 a=list(deepcopy(actual))
 if change=='state':a[0]['run']['state']['last_processed_session']='2024-08-29'
 elif change=='count':a[0]['completed']+=1
 elif change=='descriptors':a[0]['repairs']=a[0]['repairs'][:-1]
 elif change=='proof':a[2][1]['chain_sha256']='f'*64
 elif change=='tail':a[2].append(json.loads(a[-1].splitlines()[424]))
 elif change=='resolution':a[3][0]['input_sha256']='f'*64
 elif change=='authority':a[4]['EXPLICIT_NONCANONICAL_PERMISSION_DTO']=True
 elif change=='archive':a[5]+=b'\n'
 else:a[6]['sentinel/controller/median5.py']='f'*64
 with pytest.raises(ValueError):check(a)

def test_literal_proof_guard_removal_falsifier(actual,monkeypatch):
 a=list(deepcopy(actual));a[2][1]['chain_sha256']='f'*64
 with pytest.raises(ValueError,match='LITERAL_ADMITTED'):check(a)
 original=p.need;monkeypatch.setattr(p,'need',lambda valid,label:None if label=='SEED_SUCCESSOR_LITERAL_ADMITTED_PROOFS_AND_FINAL_STATE' else original(valid,label))
 assert check(a)['passed'] is True

def test_whole_original_retained_seed_import_binding_undo():
 raw=(C/'system_campaign_financial_uncertainty.py').read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='retained_seed');after=p.seed_tree(raw)
 imp=next(n for n in after.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches')
 imp.names=[ast.alias(name='validate_input'),ast.alias(name='seed'),*imp.names]
 assert ast.dump(after)==ast.dump(before)
 with pytest.raises(ValueError):p.seed_tree(raw+b'\n')

@pytest.mark.parametrize('operation',['contract','seed','factory'])
def test_local_factory_and_seed_entrypoints_refuse_before_side_effects(tmp_path,monkeypatch,operation):
 monkeypatch.delenv('GITHUB_ACTIONS',raising=False);s=root_spec('P06')
 with pytest.raises(ValueError,match='REFUSED_FULL_SYSTEM_HOSTED_CORE_ONLY'):
  if operation=='contract':p.contract({},s)
  elif operation=='seed':p.original_seed(tmp_path/'absent',{},s,visitor=lambda *a:True)
  else:p.factory(None,None,None,None,inherited_root=tmp_path,retained_root=tmp_path,parent={},spec=s,visitor=lambda *a:True,boundary=lambda:True)
 assert not (tmp_path/'absent').exists()

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
