"""Whole original history/factory bindings and authentic consumed archives."""
import ast,gzip,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PFNX_MODEL_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PFNX_history as h
import system_campaign_p03_PFNX_certificate as c
r=h.resources;s=h.source
F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/P03-request244-source-snapshot/authenticated-artifact-13612090570')
O=Path('\\\\?\\'+str(F/'verified-output'))

def member(name):
 raw=(O/name).read_bytes();assert r.pin(raw)==r.fact()['actual_manifest'][name];return raw

def parent():return json.loads(gzip.decompress(member('book/checkpoint.json.gz')))

def test_complete_original_history_function_code_defaults_and_earliest_native():
 fn=h.history_function();assert fn.__code__ is h.templates.history.__code__ and fn.__closure__ is None
 assert fn.__kwdefaults__==dict(previous_history=h.full_parent)
 assert fn.__globals__['source'].DAY==s.NATIVE and fn.__globals__['spec'] is h.spec and fn.__globals__['document'] is h.document
 assert fn.__globals__['PARENT']==h.PARENT and fn.__globals__['NEUTRAL']==h.NEUTRAL

def test_entire_canonical_boundary_AST_undo():
 raw=Path(h.templates.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='boundary');new=h.boundary_tree(raw)
 for node in ast.walk(new):
  if isinstance(node,ast.Constant) and type(node.value) is int and node.value in (21,22):node.value={21:19,22:20}[node.value]
 assert ast.dump(old)==ast.dump(new)

def test_entire_consumed_two_event_factory_AST_undo():
 raw=Path(c.previous.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='certificate_class');new=c.consumed_tree(raw)
 for node in ast.walk(new):
  if isinstance(node,ast.Compare) and ast.unparse(node.left)=="history.full(root, current)['full_inputs']" and node.comparators[0].value==22:node.comparators[0].value=21
 assert ast.dump(old)==ast.dump(new)
 fn=c.consumed_function();assert fn.__globals__['resources'] is r and fn.__globals__['history'] is h and fn.__globals__['archived_bases'] is c.archived_bases
 assert c.bind_consumed is c.previous.bind_consumed

def test_original_consumed_resolver_accepts_actual217_and_both_original_archives():
 rows=[json.loads(v) for v in member('uncertainty-certificate.jsonl').splitlines()[:217]]
 actual=c.archived_bases(O,parent(),rows,member('branch-controller-qualification.json'))
 assert c.archived_bases_function().__code__ is c.previous.archived_bases.__code__
 assert [v[0]['event']['ticker'] for v in actual]==['DOVA','STML'] and len({v[1]['actual'] for v in actual})==2
 for catalog,resolution,raw in actual:
  assert resolution in r.fact()['historical_archive_resolutions'] and s.sha(raw)==resolution['gzip_sha256']
  assert catalog['event']['effective_session']<'2020-08-31'

def packet_qualification_DTO():
 cp=parent();v=s.catalog();q=dict(passed=True,catalog_sha256=s.sha(s.encoded(v)),typed_document_sha256=s.sha(s.encoded(s.document(cp))),
  market_source_sha256=v['market_source_sha256'],financial_sessions_advanced=0,packet=dict(actual_packet_checks=2,actual_selected_signal_range=[12.,14.],**{k:True for k in h.PACKET_FLAGS}))
 return cp,q

def test_complete_two_packet_qualification_DTO_preserves_full_range():
 cp,q=packet_qualification_DTO();assert h.packet_qualification(q,cp)

@pytest.mark.parametrize('change',['count','range','source','document','transition',*h.PACKET_FLAGS])
def test_incomplete_packet_proof_DTO_cannot_be_accepted(change):
 cp,q=packet_qualification_DTO()
 if change=='count':q['packet']['actual_packet_checks']=1
 elif change=='range':q['packet']['actual_selected_signal_range']=[12.,12.]
 elif change=='source':q['market_source_sha256']='0'*64
 elif change=='document':q['typed_document_sha256']='0'*64
 elif change=='transition':q['financial_sessions_advanced']=1
 else:q['packet'][change]=False
 with pytest.raises(ValueError,match='COMPLETE_ORIGINAL_TWO_PACKET'):h.packet_qualification(q,cp)

def test_third_layer_reuses_original_parent_metadata_protocol_on_opaque_class():
 oldcodec=object();codec=SimpleNamespace(previous_owner=lambda:oldcodec)
 class EXPLICIT_NONCANONICAL_MARKED_PARENT_DTO:
  def __init__(self):pass
  def values(self):pass
  def recover(self):pass
  def advance(self):pass
  def witness(self):pass
 old=dict(effective_session='2020-06-10',security_id='235472954303009097')
 marked=c.factory.mark(EXPLICIT_NONCANONICAL_MARKED_PARENT_DTO,old,oldcodec)
 assert c.factory.parent_metadata(marked,s.catalog()['event'],codec)==old
 with pytest.raises(ValueError):c.factory.parent_metadata(marked,s.catalog()['event'],SimpleNamespace(previous_owner=lambda:object()))

def test_new_PFNX_layer_keeps_original_pre_event_constructor_predicate():
 fn=next(n for n in ast.parse(Path(c.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='certificate_class')
 names=[ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)]
 assert 'factory.second_factory'in names and not any('bind_consumed'in n for n in names)
 assert 'consumed_function()'in names

def test_local_canonical_history_and_constructor_stay_closed():
 with pytest.raises(ValueError):h.full_parent(None,None)
 with pytest.raises(ValueError):c.certificate_class(None,None,None,None,None,None)

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
