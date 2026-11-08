"""Actual PFNX source/annual DATA plus whole original hydration/packet ASTs."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PFNX_SOURCE_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PFNX_source as s
import system_campaign_p03_PFNX_hydration as h
import system_campaign_p03_PFNX_preparation as p
from system_campaign_financial_partial import root_spec

def value():return s.catalog()

def actual_parent():
 root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/P03-request244-source-snapshot/authenticated-artifact-13612090570')
 mf=json.loads((root/'authenticated-manifest.json').read_bytes())['members'];raw=Path('\\\\?\\'+str(root/'verified-output/book/checkpoint.json.gz')).read_bytes()
 assert dict(bytes=len(raw),sha256=s.sha(raw))==mf['book/checkpoint.json.gz']==root_spec('P03',s.ROOT)['selected_file']
 return json.loads(gzip.decompress(raw))

def test_entire_current_parent_contract_and_distinct_original_collection_context():
 v=value();assert s.parent_contract(actual_parent(),root_spec('P03',s.ROOT))
 assert v['parent_completed']==671 and len(v['parent_descriptors'])==21
 assert s.batch()['source_evidence']['admitted_context']['P03']['completed']==628
 assert v['parent_role']==dict(held=False,ordered=False,selected=False,signal_anchor=['2020-08-31',12.53,12.53])
 assert not v['event_date_ownership_verified'] and v['event']['historical_causality']=='UNVERIFIED'

def test_full_legal_range_separate_from_original_incomplete_native_and_quotes():
 v=value();assert v['event']['upfront_cash_per_share']=='12.00' and v['event']['right_upper_per_share']=='2.00'
 assert v['native']['cash_per_share']is None and v['native']['reference'].endswith('437.3')
 assert v['market_source']['raw_prior_row']['raw_open']=='12.74' and v['market_source']['raw_prior_row']['raw_close']=='12.75'
 assert v['event']['native_session']=='2020-09-30' and v['event']['effective_session']=='2020-10-01'
 assert v['market_source']['raw_event_row']is None

@pytest.mark.parametrize('change',['range','native','parent','descriptor','quote','absence','authority','annual','role','sourcepin'])
def test_source_substitution_or_authority_upgrade_refused(change):
 v=value()
 if change=='range':v['event']['right_upper_per_share']='1.00'
 elif change=='native':v['native']['cash_per_share']=12.
 elif change=='parent':v['parent_completed']=628
 elif change=='descriptor':v['parent_descriptors']=v['parent_descriptors'][:-1]
 elif change=='quote':v['market_source']['raw_prior_row']['raw_close']='12.00'
 elif change=='absence':v['market_source']['raw_event_row']=v['market_source']['raw_prior_row']
 elif change=='authority':v['financial_authority']=True
 elif change=='annual':v['full_annual_source_DATA']['security_rows']-=1
 elif change=='role':v['parent_role']['held']=True
 else:v['input_semantics_sources']['system_campaign_second_bounded_factory.py']='0'*64
 with pytest.raises(ValueError):s.validate(v,root_lookup=root_spec)

def test_source_range_guard_has_meaningful_removal_falsifier():
 v=value();v['event']['right_upper_per_share']='1.00';v['market_source']=s.market(v,s.source_rows(s.batch()));v['market_source_sha256']=s.sha(s.encoded(v['market_source']))
 with pytest.raises(ValueError,match='FULL_LEGAL12_TO14'):s.validate(v,root_lookup=root_spec)
 fn=next(n for n in ast.parse(Path(s.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
 site,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='PFNX_FULL_LEGAL12_TO14_RANGE_AND_DISTINCT_NATIVE_COMPLETION_DATES' for a in n.value.args)]
 fn.body.remove(site);scope=dict(vars(s));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-full-range-DATA-guard>','exec'),scope)
 assert scope['validate'](v,root_lookup=root_spec)==v

@pytest.mark.parametrize('name',['witness','hydrate'])
def test_entire_original_hydration_function_AST_undo(name):
 raw=Path(h.original.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name);new=h.tree(raw,name)
 dates={v:k for k,v in h.DATES.items()}
 for node in ast.walk(new):
  if isinstance(node,ast.Constant):
   if isinstance(node.value,str) and node.value in dates:node.value=dates[node.value]
   elif type(node.value)is int and node.value in (1541141,189):node.value={1541141:2080223,189:245}[node.value]
 assert ast.dump(new)==ast.dump(old)

def test_whole_original_witness_accepts_actual_full_annual_scan():
 v=value();audit=v['full_annual_source_DATA']
 assert h.witness(v,v['native'],audit['raw_source_rows'],scanned=audit['scanned'],security_rows=audit['security_rows'],last_source_session=audit['last_source_session'])==v['market_source']

@pytest.mark.parametrize('change',['scan','security_rows','last','missing','quote'])
def test_full_annual_witness_wrong_scan_or_quote_refused(change):
 v=value();a=v['full_annual_source_DATA'];rows=deepcopy(a['raw_source_rows']);kwargs=dict(scanned=a['scanned'],security_rows=a['security_rows'],last_source_session=a['last_source_session'])
 if change=='scan':kwargs['scanned']-=1
 elif change=='security_rows':kwargs['security_rows']-=1
 elif change=='last':kwargs['last_source_session']=s.DAY
 elif change=='missing':rows.pop()
 else:rows[0]['raw_close']='WRONG_QUOTE'
 with pytest.raises(ValueError):h.witness(v,v['native'],rows,**kwargs)

def test_whole_original_packet_qualifier_AST_undo():
 raw=Path(p.original.__file__).read_bytes();old=p.previous.packet_tree(raw);new=p.packet_tree(raw)
 for node in ast.walk(new):
  if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in (s.NATIVE,s.DAY):node.value={s.NATIVE:p.previous.NATIVE,s.DAY:p.previous.DAY}[node.value]
 limits,=[n for n in ast.walk(new) if isinstance(n,ast.List) and ast.unparse(n)=='[12.0, 14.0]'];limits.elts=[ast.Constant(40.),ast.Constant(44.)]
 assert ast.dump(new)==ast.dump(old)

def test_all_retained_inputs_apply_in_original_order_before_new_input(monkeypatch):
 seen=[]
 def apply(packet,obj):seen.append(obj);return packet+[obj]
 scope=p.packet_qualifier(['OPAQUE_OLD_'+str(n) for n in range(21)],apply).__globals__
 final='OPAQUE_NEW_INPUT';assert scope['apply_cumulative']([],final)==['OPAQUE_OLD_'+str(n) for n in range(21)]+[final]
 assert seen==['OPAQUE_OLD_'+str(n) for n in range(21)]+[final]

def test_exact_typed_source_document_and_wrong_cursor_or_parent_refused(tmp_path):
 from system_campaign_bounded_sensor_input import parse
 cp=actual_parent();v=value();path=tmp_path/'source-input.json';path.write_bytes(s.encoded(s.document(cp)));obj=s.parse_document(path,cp)
 assert obj.event.model_dump()==v['event'] and obj.earliest_affected_session==s.NATIVE
 for cursor,pin in ((s.NATIVE,cp['run']['checkpoint_sha256']),(cp['source_cursor'],'0'*64)):
  with pytest.raises(ValueError):parse(path,resume_session=cursor,predecessor_checkpoint_sha256=pin,expected_event=v['event'],expected_evidence=s.evidence(v))

def test_hosted_preparation_and_hydration_closed_locally():
 with pytest.raises(ValueError):p.qualify_packets(None,None,None,None,None,None)
 with pytest.raises(ValueError):h.hydrate(None,None)

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(name)
