"""Hosted source reconstruction and original distribution financial checks."""
import ast,json,tempfile
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import FunctionType
import system_campaign_financial_compound_runtime_v2 as original
import system_campaign_postclose_distribution_input as source
import system_campaign_postclose_distribution_codec as typed
import system_campaign_postclose_distribution_history as history
import system_campaign_p07_saved_proofs as saved
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
from full_system_benchmark import need,save
HERE=Path(__file__).parent
ORIGINAL_SHA='0b4ade1d380b395098f057dd9a8b65cd73ae8697f364640f05118326da25bd74'
ACTUAL='actual-distribution-event.json'

def selected_spec():
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',saved.ROOT);saved.metadata(spec);return spec

def payload():
 value=source.catalog();spec=source.validate(value);witness,_=source.qualified_source(value);doc=typed.document(value)
 return dict(schema='research.postclose-distribution-payload/1',arm='P07',base=deepcopy(spec['base']),
  parent_root_admission_sha256=spec['root_admission_sha256'],parent_outer_sha256=spec['outer_sha256'],
  parent_input_sha256=spec['input_sha256'],parent_state_sha256=spec['state_sha256'],parent_cursor=spec['selected_session'],
  binding=source.build_terms(value),source_payload=witness,descriptor_sha256=sha(source.encoded(doc)),
  new_ordinary_cash_terms=[],financial_state_changed=False,production_contacted=False)

def reconstruct_source(parent,out):
 from full_system_core import hosted
 hosted();value=source.catalog();source.validate_parent(value,parent)
 from research.pooled_input_support import inputs
 from research.bounded_20y import run
 need(sha(Path(run.__file__).read_bytes())==source.source.PARSER_SHA,'POSTCLOSE_HOSTED_ORIGINAL_SOURCE_PARSER')
 expected=source.normalize(value);scope=expected['scope']
 with tempfile.TemporaryDirectory(prefix='postclose-source-reconstruction-',dir=out) as owned:
  actual=source.source.capture_distribution_only(parent,Path(owned),'P07',scope,sha(Path(source.__file__).read_bytes()))
  need(actual==expected,'POSTCLOSE_HOSTED_ENTIRE_FROZEN_SOURCE_RECONSTRUCTION')
 rows=[v['raw_source_row'] for v in actual['native_distributions']]
 return actual,inputs.load_actions(Path('/frozen/bundle')),run.distributions(rows)

def verify_payload(root):
 from full_system_core import hosted
 hosted();root=Path(root);spec=selected_spec();names=history.paths(spec)
 parent=history.archived_parent(spec,lambda n:(root/n).read_bytes())
 actual,_,_=reconstruct_source(parent,root);expected=payload();raw=(root/names['PAYLOAD']).read_bytes()
 need(json.loads(raw)==expected and actual==expected['source_payload']
  and (root/names['OVERLAY']).read_bytes()==source.encoded(typed.document()),'POSTCLOSE_HOSTED_EXACT_PAYLOAD_AND_TYPED_DESCRIPTOR')
 return expected,raw

class ProjectionContext:
 def __init__(self,root,*,payload=None):
  self.root=Path(root);self.payload,self.raw=verify_payload(root) if payload is None else payload
  need(self.payload==globals()['payload']() and self.raw==source.encoded(self.payload),'POSTCLOSE_EXACT_SOURCE_BOUND_CONTEXT_PAYLOAD')
  self.names=history.paths(selected_spec());self.codec=None
 @property
 def changed_packets(self):return self.codec.changed_packets
 def __enter__(self):
  from full_system_core import hosted
  hosted()
  from research.pooled_vacancy_funding import backtest,repair
  from research.bounded_20y.run import vendor
  from sentinel.core import spinoffs
  for owner,name in ((backtest,'research/pooled_vacancy_funding/backtest.py'),
   (repair,'research/pooled_vacancy_funding/repair.py'),(spinoffs,'sentinel/core/spinoffs.py')):
   need(sha(Path(owner.__file__).read_bytes())==self.payload['base']['sources'][name],'POSTCLOSE_EXACT_ACTUAL_PACKET_AND_PRIMITIVE_MODULES')
  binding=self.payload['binding'];value=source.catalog();rows=binding['original_rows']
  self.projection=source.projection_type(value)(binding,parent_bar=vendor(rows[binding['spin']['parent_security_id']]),
   child_bar=vendor(rows[binding['spin']['child_security_id']]),source_raw=Path(repair.__file__).read_bytes(),
   source_namespace=vars(repair),spin_factory=spinoffs.SpinoffDistribution)
  self.codec=typed.InputCodec(self.projection,value=value);self.codec.__enter__();return self
 def __exit__(self,*args):return self.codec.__exit__(*args)

def observer_type():
 need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'POSTCLOSE_WHOLE_ORIGINAL_FINANCIAL_OBSERVER_SOURCE')
 scope=dict(vars(original),ACTUAL=ACTUAL);attrs={}
 for name,fn in vars(original.Observer).items():
  if not isinstance(fn,FunctionType):continue
  need(fn.__closure__ is None,'POSTCLOSE_ORIGINAL_OBSERVER_METHOD_WITHOUT_HIDDEN_CLOSURE')
  bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=fn.__kwdefaults__
  need(bound.__code__ is fn.__code__,'POSTCLOSE_IDENTICAL_COMPLETE_ORIGINAL_FINANCIAL_OBSERVER_METHOD')
  attrs[name]=bound
 return type('PostCloseDistributionObserver',(object,),attrs)

def observer(root,value=None):
 from full_system_core import hosted
 hosted();value=payload() if value is None else value
 need(value==payload(),'POSTCLOSE_ONLY_EXACT_QUALIFIED_FINANCIAL_OBSERVER_PAYLOAD')
 folder=Path(root)/history.paths(selected_spec())['OBSERVATION'];folder.mkdir(parents=True,exist_ok=True)
 return observer_type()(folder,value)

def retained_stack(parent,out):
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 spec=selected_spec();saved.full_parent(Path('/old'),parent,spec);loaded=[]
 for entry in parent['repairs']:
  path=Path('/old')/'book/repairs'/entry['filename']
  obj=backtest.load_repair(path,resume_session=entry['resume_session'],predecessor_checkpoint_sha256=entry['predecessor_checkpoint_sha256'])
  need(obj.sha256==entry['sha256'],'POSTCLOSE_EVERY_RETAINED_DESCRIPTOR_USES_COMPLETE_PREVIOUS_LOADER')
  loaded.append(dict(descriptor=deepcopy(entry),loaded_sha256=obj.sha256))
 need(len(loaded)==25,'POSTCLOSE_ALL25_RETAINED_INPUTS_QUALIFIED')
 result=dict(passed=True,retained_inputs=loaded,new_ordinary_cash_terms=0,financial_sessions_advanced=0)
 exact(Path(out)/history.paths(spec)['RETAINED_QUALIFICATION'],source.encoded(result));return result

def qualifier_tree(raw):
 need(sha(raw)==ORIGINAL_SHA,'POSTCLOSE_WHOLE_ORIGINAL_PACKET_AND_PRIMITIVE_QUALIFIER')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualify']
 block,=[n for n in fn.body if isinstance(n,ast.With)]
 start,=[i for i,n in enumerate(block.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='record']
 need(ast.unparse(block.body[-1]).startswith('codec.qualify('),'POSTCLOSE_COMPLETE_ORIGINAL_NEW_CASH_QUALIFIER_BLOCK')
 block.body[start:]=ast.parse('retained_stack(cp,out)').body
 assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='ordinary_min']
 assignment.value=ast.Name(id='day',ctx=ast.Load())
 calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='repair.load_repair']
 need(len(calls)==1,'POSTCLOSE_ONE_PARSER_FALSIFIER_TARGET')
 calls[0].func=ast.parse('ctx.codec.load',mode='eval').body
 site,=[kw for n in ast.walk(fn) if isinstance(n,ast.Call) for kw in n.keywords if kw.arg=='original_ordinary_packet_notional_and_parser_falsifiers']
 site.arg='retained_stack_and_typed_parser_falsifiers'
 return ast.fix_missing_locations(fn)

def qualify(parent,out,value,actions,spins):
 from full_system_core import hosted
 hosted();spec=selected_spec();saved.parent_contract(parent,spec);names=history.paths(spec)
 scope=dict(vars(original),ProjectionContext=ProjectionContext,retained_stack=retained_stack,
  OVERLAY=names['OVERLAY'],QUALIFICATION=names['QUALIFICATION'])
 exec(compile(ast.Module(body=[qualifier_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-distribution-qualifier-standalone-input-and-retained-chain>','exec'),scope)
 return scope['qualify'](parent,Path(out),value,actions,spins)

def prepare(parent,out,*,old=Path('/old')):
 from full_system_core import hosted
 hosted();out=Path(out);spec=selected_spec();saved.parent_contract(parent,spec);names=history.paths(spec)
 raw=(Path(old)/spec['selected_checkpoint']).read_bytes()
 need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'] and strict_json(raw)==parent,'POSTCLOSE_GENUINE_ORIGINAL_PARENT_ARCHIVE')
 exact(out/names['PARENT'],raw);actual,actions,spins=reconstruct_source(parent,out)
 value=payload();need(actual==value['source_payload'],'POSTCLOSE_ACTUAL_SOURCE_BEFORE_TYPED_PREPARATION')
 exact(out/names['PAYLOAD'],source.encoded(value));doc=typed.document();path=out/names['OVERLAY'];exact(path,source.encoded(doc))
 loaded=typed.parse(path,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],expected_document=doc)
 qualify(parent,out,value,actions,spins);return path,loaded

def packet_qualification(parent,spec,member):
 saved.parent_contract(parent,spec);names=history.paths(spec);value=json.loads(member(names['QUALIFICATION']));p=payload()
 quantity=sum((Fraction(str(v['quantity'])) for v in p['binding']['parent_positions']),Fraction(0))
 need(value['passed'] is True and type(value['financial_sessions_advanced'])is int and value['financial_sessions_advanced']==0
  and value['binding_sha256']==digest(p['binding']) and value['source_payload_sha256']==sha(source.encoded(p['source_payload']))
  and value['spin']==source.original.consideration(p['binding'],quantity,10)
  and value['canonical_primitives_delegated'] is value['original_native_quote_proxy_duplicate_role_falsifiers']
   is value['retained_stack_and_typed_parser_falsifiers'] is True
  and value['original_financial_source_changed'] is False and value['loaded_minimum_boundary']=='2023-07-05',
  'POSTCLOSE_COMPLETE_ORIGINAL_HOSTED_PACKET_PRIMITIVE_AND_PARSER_QUALIFICATION')
 retained=json.loads(member(names['RETAINED_QUALIFICATION']))
 need(retained['passed'] is True and retained['financial_sessions_advanced']==retained['new_ordinary_cash_terms']==0
  and retained['retained_inputs']==[dict(descriptor=d,loaded_sha256=d['sha256']) for d in parent['repairs']],
  'POSTCLOSE_ALL_RETAINED_INPUTS_QUALIFIED_WITHOUT_NEW_CASH')
 return True

def review_event(value,evidence,current):
 day=value['binding']['spin']['session'];folder=Path(evidence)/history.paths(selected_spec())['OBSERVATION'];actual=folder/ACTUAL
 if current['source_cursor']<day:
  return dict(passed=True,event_committed=False,financial_sessions_admitted=0)
 need(actual.is_file(),'POSTCLOSE_COMMITTED_EVENT_REQUIRES_ACTUAL_ORIGINAL_FINANCIAL_OBSERVER')
 record=json.loads(actual.read_bytes());quantity=sum((Fraction(str(v['quantity'])) for v in value['binding']['parent_positions']),Fraction(0))
 expected=dict(session=day,order=['SPINOFF'],spin=source.original.consideration(value['binding'],quantity,10),
  proxy_cash=dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False),passed=True,financial_source_changed=False)
 need(record==expected,'POSTCLOSE_COMPLETE_ACTUAL_CHILD_RECEIPT_SALE_REFERENCE_AND_NO_DUPLICATE_CASH')
 return dict(passed=True,event_committed=True,actual_record_sha256=sha(actual.read_bytes()),financial_sessions_admitted=0)
