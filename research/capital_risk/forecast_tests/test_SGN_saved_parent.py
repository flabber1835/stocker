"""Actual2050/14-input metadata and literal797-row seed, without canonical runtime."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('SGN_PARENT_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_retained_seed_successor as p
from system_campaign_financial_partial import root_spec
import system_campaign_source_exit_profiles as profiles
import system_campaign_source_exit_runtime as runtime

@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/P06-request228-source-snapshot/authenticated-artifact-13596566525')
 if not F.exists():pytest.skip('authenticated request228 DATA required')
 F=Path('\\\\?\\'+str(F.resolve()))
 mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  raw=(F/'verified-output'/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 spec=root_spec('P06');parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
 raw=member('uncertainty-certificate.jsonl');lines=raw.splitlines(keepends=True);rows=[json.loads(v) for v in lines[:797]]
 q=json.loads(member('branch-controller-qualification.json'))
 resolution=p.metadata(spec)['historical_event_resolution'];archive=member(resolution['actual'])
 return spec,parent,raw,rows,q,resolution,archive

def test_complete_actual797_seed_and_all10_diagnostic_rows_excluded(actual):
 spec,parent,raw,rows,q,resolution,archive=actual
 assert p.literal_prefix(raw,rows,spec) is True
 assert p.phase(spec)==dict(rows=797,new_rows=229,retained_rows=568)
 assert p.metadata(spec)['raw_rows']==807 and len(raw.splitlines())==807
 hashes=q['exact_controller_sources']
 result=p.qualify_metadata(parent,spec,rows,rows,[resolution],{},archive,hashes,hashes)
 assert result['passed'] is True and result['committed_rows']==797
 assert result['unadmitted_tail_rows_used']==0 and result['second_event_authorized'] is False
 assert (parent['completed'],len(parent['repairs']),parent['source_cursor'])==(2050,14,'2026-02-27')

def test_registered_provider_uses_exact_future_quote_and_complete_parent(actual):
 spec,*_=actual;value=profiles.profile(spec);provider=profiles.source(spec);catalog=provider.catalog()
 assert (value['source_version'],value['parent_inputs'],value['seed_rows'],value['retained_scope_count'])==(3,14,797,3)
 assert provider.validate_term is provider.module.original.research_source_exit_term
 assert catalog['term']['parent_cursor']<'2026-03-13'==catalog['term']['retained_quote']['session']<'2026-03-16'

@pytest.mark.parametrize('mutation',['tail','row','state','archive','permission'])
def test_actual_committed_state_and_original_unselected_event_cannot_be_changed(actual,mutation):
 spec,parent,raw,rows,q,resolution,archive=actual;rows=deepcopy(rows);parent=deepcopy(parent);allowed={}
 if mutation=='tail':rows.append(json.loads(raw.splitlines()[797]))
 elif mutation=='row':rows[-1]['decision']['reason']='EXPLICIT_NONCANONICAL_CHANGED_DECISION_DTO'
 elif mutation=='state':parent['run']['state_sha256']='f'*64
 elif mutation=='archive':archive=bytes([archive[0]^1])+archive[1:]
 else:allowed={'EXPLICIT_NONCANONICAL_PERMISSION_DTO':True}
 hashes=q['exact_controller_sources']
 with pytest.raises(ValueError):p.qualify_metadata(parent,spec,rows,rows,[resolution],allowed,archive,hashes,hashes)

def test_committed_tail_guard_removal_is_meaningful(actual,monkeypatch):
 spec,parent,raw,rows,*_=actual;rows=rows+[json.loads(raw.splitlines()[797])]
 with pytest.raises(ValueError,match='LITERAL_COMPLETE_PREFIX'):p.literal_prefix(raw,rows,spec)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='SEED_SUCCESSOR_LITERAL_COMPLETE_PREFIX_EXCLUDES_EVERY_RAW_TAIL' else original(ok,label))
 assert p.literal_prefix(raw,rows,spec) is True

@pytest.mark.parametrize('name',['run','review'])
def test_original_retained_worker_797_binding_AST_undo(name):
 raw=Path(runtime.retained.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
 after=runtime.retained_tree(raw,name,committed_rows=797)
 imp=next(n for n in ast.walk(after) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_source_exit_runtime')
 imp.module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
 if name=='review':imp.names[0].name='review'
 for n in ast.walk(after):
  if isinstance(n,ast.Constant) and type(n.value)is int and n.value==797:n.value=6
 if name=='run':
  after.body=[n for n in after.body if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='constructor_canary')]
 assert ast.dump(after)==ast.dump(before)
