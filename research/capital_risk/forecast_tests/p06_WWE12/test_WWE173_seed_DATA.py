"""Actual173 saved proof, historical event epoch, whole ASTs; no engine."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('WWE173_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_WWE173_seed as seed
import system_campaign_p06_WWE_admission as authority
import system_campaign_p06_WWE173_preconditions as preconditions
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_financial_partial import root_spec
@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P06-source-snapshot/capture-P06-13525611349-001')
 root=Path('\\\\?\\'+str((F/'verified-output').resolve()));members=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  b=(root/n).read_bytes();assert dict(bytes=len(b),sha256=seed.data.sha(b))==members[n];return b
 current=strict_json(member('book/checkpoint.json.gz'));rows=[json.loads(b) for b in member('uncertainty-certificate.jsonl').splitlines()[:173]]
 allowed,resolutions=seed.prior_event(root,current,rows,current);assert len(resolutions)==1
 archive=member(resolutions[0]['actual']);hashes=json.loads((C/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
 return SimpleNamespace(root=root,current=current,rows=rows,spec=root_spec('P06',seed.data.ROOT),member=member,allowed=allowed,resolutions=resolutions,archive=archive,hashes=hashes)
def call(a,rows=None,archive=None):return seed.qualify_metadata(a.current,a.spec,a.rows if rows is None else rows,a.rows,a.resolutions,a.allowed,a.archive if archive is None else archive,a.hashes,a.hashes)
def test_actual_admitted_full11_and_independent_historical_event10(actual):
 authority.require(actual.spec);v=preconditions.actual_parent(actual.root,actual.current,member=actual.member)
 assert v['committed_rows']==173 and v['actual_held_WWE']==27
 assert seed.whole_prefix(actual.root,actual.current,actual.rows)
 result=call(actual);assert result['passed'] is True and result['committed_rows']==173
 assert actual.resolutions[0]['input_sha256']!=actual.current['run']['input_sha256']
 assert actual.resolutions[0]['input_sha256']==seed.data.digest(dict(base=actual.current['base'],repairs=actual.current['repairs'][:10]))
def test_no_unadmitted_tail_or_partial_prefix(actual):
 with pytest.raises(ValueError):call(actual,rows=actual.rows[:-1])
 with pytest.raises(ValueError):call(actual,rows=actual.rows+[actual.rows[-1]])
def test_wrong_actual_event_bytes_refused(actual):
 with pytest.raises(ValueError):call(actual,archive=actual.archive+b'NONCANONICAL-CORRUPTION')
def test_metadata_byte_guard_removal_is_meaningful(actual,monkeypatch):
 original=seed.point.need
 monkeypatch.setattr(seed.point,'need',lambda value,label:None if label=='P06_POINT_ACTUAL_ORIGINAL_EVENT_PRODUCER_AND_SOURCE_BYTES' else original(value,label))
 assert call(actual,archive=actual.archive+b'NONCANONICAL-CORRUPTION')['passed'] is True
def test_entire_original_metadata_AST_undo():
 raw=Path(seed.point.__file__).read_bytes();before=seed.point.function(raw,'qualify_seed_metadata');tree=seed.metadata_tree(raw)
 changes={13525611349:13478656632,1426:1259,'2023-08-31':'2022-12-30'}
 class Undo(ast.NodeTransformer):
  def visit_Compare(self,n):
   replacements={"proof['rows'] == 43":"proof['rows'] == 6","proof.get('retained_rows', 0) == 130":"proof.get('retained_rows', 0) == 0",'len(rows) == len(committed) == 173':'len(rows) == len(committed) == 6',"len(current['repairs']) == 11":"len(current['repairs']) == 10","resolution['input_sha256'] == event['input_sha256'] == digest(dict(base=current['base'], repairs=current['repairs'][:10]))":"resolution['input_sha256'] == event['input_sha256'] == current['run']['input_sha256']"}
   s=ast.unparse(n)
   if s in replacements:return ast.copy_location(ast.parse(replacements[s],mode='eval').body,n)
   return self.generic_visit(n)
  def visit_Constant(self,n):
   if type(n.value) in (str,int) and n.value in changes:n.value=changes[n.value]
   return n
 tree=Undo().visit(tree);tree.args.kw_defaults[-1]=deepcopy(before.args.kw_defaults[-1]);assert ast.dump(tree)==ast.dump(before)
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
