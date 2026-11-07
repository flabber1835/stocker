"""Genuine saved P07 DATA; no invented financial book or local transition."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('P07_SAVED_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_saved_proofs as p
import system_campaign_postclose_distribution_history as history
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial343-P07-source-snapshot/capture-P07-13534905567-001')
 if not F.exists():pytest.skip('authenticated FIN343 DATA required')
 root=Path('\\\\?\\'+str((F/'verified-output').resolve()));mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 def member(name):
  raw=(root/name).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[name];return raw
 parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')));spec=root_spec('P07',p.ROOT)
 raw=member('uncertainty-certificate.jsonl');rows=[json.loads(v) for v in raw.splitlines()[:929]]
 return root,parent,spec,member,raw,rows

def test_entire_existing_parent_history_and_literal_prefix_are_verified(actual):
 root,parent,spec,member,raw,rows=actual;before=p.digest(parent)
 value=p.full_parent(root,parent,spec)
 assert value['full_input_count']==25 and value['bounded_descriptor']==parent['repairs'][23]
 assert p.literal_prefix(raw,rows,spec) and len(raw.splitlines())==930 and len(rows)==929
 assert p.metadata(spec)['excluded_tail_sessions']==['2023-07-03']
 assert p.digest(parent)==before

def test_whole_original_seed_reader_on_genuine_saved_parent(actual):
 root,parent,spec,member,raw,rows=actual;hashes=p.metadata(spec)['controller_sources'];seen=[]
 def contract(current,target):
  assert current is parent and target is spec;seen.append(current['sha256']);return hashes
 result=p.seed_reader(contract=contract)(root,parent,spec)
 assert result[0]==hashes and result[1]==rows and len(result[1])==929 and seen==[parent['sha256']]
 assert result[2]==member('branch-controller-qualification.json')
 assert p.phase(spec)==dict(rows=929,new_rows=124,retained_rows=805)

def test_entire_saved_factory_metadata_on_actual_historical_archive(actual):
 root,parent,spec,member,raw,rows=actual;catalog=p.original_lifecycle.catalog()
 allowed,resolutions=p.historical_permissions(root,rows,catalog,through=parent['source_cursor'],input_descriptors=parent['repairs'])
 ns=p.factory_namespace();result=ns.qualify_metadata(parent,spec,catalog,json.loads(member(spec['retained_abmd']['origin_file'])),
  rows,rows,resolutions,allowed,member(resolutions[0]['actual']),source_plan=p.models.original.plan())
 assert result['passed'] is True and result['committed_proof_rows']==929 and result['full_input_descriptors']==25
 assert result['prior_event_resolution']==p.metadata(spec)['historical_event_resolution']
 assert result['second_event_authorized'] is result['financial_authority'] is False
 assert result['prior_proof_rows_reexecuted']==0

def test_original_seed_function_AST_undo():
 raw=Path(p.uncertainty.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='retained_seed')
 after=p.retained.seed_tree(raw)
 imp=next(n for n in after.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches')
 imp.names.insert(0,ast.alias(name='validate_input'))
 assert ast.dump(after)==ast.dump(before)

def test_whole_original_factory_function_set_AST_undo():
 raw=p.certificate.source();before=ast.Module(body=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)],type_ignores=[])
 after=p.factory_nodes(raw)
 fn=next(n for n in after.body if n.name=='qualify_metadata')
 p.models.replace_count(fn,"len(current['repairs']) == 25","len(current['repairs']) == 24",1,'UNDO_ONE_COUNT')
 p.models.replace_count(fn,"resolution['input_sha256'] == row['input_sha256'] == historical_input_sha256(current)",
  "resolution['input_sha256'] == row['input_sha256'] == current['run']['input_sha256']",1,'UNDO_ONE_EVENT_EPOCH')
 site=next(kw for n in ast.walk(fn) if isinstance(n,ast.Call) for kw in n.keywords if kw.arg=='full_input_descriptors');site.value.value=24
 original=next(n for n in before.body if n.name=='certificate_class');changed=next(n for n in after.body if n.name=='certificate_class')
 imp=next(n for n in original.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_bounded_sensor_event_review')
 changed.body.insert(original.body.index(imp),deepcopy(imp))
 assert ast.dump(after)==ast.dump(before)

def test_whole_retained_declaration_validator_AST_undo():
 raw=Path(p.original_lifecycle.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='valid_retained');after=p.retained_tree(raw)
 p.models.replace_count(after,"len(spec['repairs']) == 25","len(spec['repairs']) == 24",1,'UNDO_ONE_RETAINED_COUNT')
 assert ast.dump(after)==ast.dump(before)

def test_unaccepted_tail_and_changed_proof_cannot_seed_restart(actual):
 _,_,spec,_,raw,rows=actual
 with pytest.raises(ValueError,match='LITERAL929'):p.literal_prefix(raw,rows+[json.loads(raw.splitlines()[929])],spec)
 changed=deepcopy(rows);changed[-1]['chain_sha256']='f'*64
 with pytest.raises(ValueError,match='LITERAL929'):p.literal_prefix(raw,changed,spec)

def test_literal_prefix_guard_removal_falsifier(actual,monkeypatch):
 _,_,spec,_,raw,rows=actual;changed=deepcopy(rows);changed[-1]['chain_sha256']='f'*64
 with pytest.raises(ValueError,match='LITERAL929'):p.literal_prefix(raw,changed,spec)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='P07_SAVED_LITERAL929_PREFIX_NO_UNADMITTED930TH_ROW' else original(ok,label))
 assert p.literal_prefix(raw,changed,spec)

def test_generic_next_input_reader_uses_genuine_complete_previous_parent(actual):
 root,parent,spec,member,raw,rows=actual;seen=[]
 def previous(where,current):
  assert where==root and current is parent
  result=p.full_parent(where,current,spec);seen.append(current['sha256']);return result
 def no_future_document(*args):pytest.fail('parent-only branch must not invent a future input')
 result=history.history(root,parent,spec,member=member,document=no_future_document,previous_history=previous)
 assert result['passed'] is True and result['full_inputs']==25 and result['new_input_adopted'] is False
 assert seen==[parent['sha256']]

def test_next_input_requires_actual_parent_archive_before_parsing(actual):
 _,_,spec,_,_,_=actual
 with pytest.raises(ValueError,match='GZIP_BEFORE_PARSE'):history.archived_parent(spec,lambda name:b'EXPLICIT_NONCANONICAL_UNAUTHENTICATED_DTO')

@pytest.mark.parametrize('operation',['factory','physical_contract'])
def test_financial_entrypoints_refuse_locally_before_canonical_imports(actual,monkeypatch,operation):
 _,parent,spec,_,_,_=actual;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if operation=='factory':p.certificate_class(None,current_checkpoint=parent,admitted_spec=spec)
  else:p.physical_contract(parent,spec)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
