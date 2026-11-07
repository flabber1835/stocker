"""One source-bound HABT cash term; original calendar and source predicates."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_p03_cash14_data as prior
import system_campaign_qualified_cash_subset as subset
import system_campaign_cash_calendar as calendar
from system_campaign_bounded_sensor_input import need,sha,digest
HERE=Path(__file__).parent
ROOT='f297ca81235193b7403b80a5badc5be199035d3550c5a893c2e0c3dc0a3e0eb8'
OUTER='50529edab057a7f1a835f3ebb6e947efc5b4f10b64ca941d12f212cd709d1f8a'
SID='594373256712467281'
FACT='P03-own543-HABT19-finite-facts.json'
FACT_SHA='2f88bf1c1281cf0016926877206573fe740a847e4c2ad47da0fc1fd69eca4f4d'
PRIMARY='P03-HABT-mandatory-common-cash-primary.json'
CATALOG='P03-own543-HABT-ordinary19-catalog.json'
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def facts():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'HABT_EXACT_ACTUAL543_FINITE_FACTS');v=json.loads(raw)
 for n,p in v['source_files'].items():
  b=(HERE/n).read_bytes();need(dict(bytes=len(b),sha256=sha(b))==p,'HABT_SOURCE_ASSET:'+n)
 for n,p in v['frozen_sources'].items():need(sha((Path(prior.__file__).parent/n).read_bytes())==p,'HABT_WHOLE_ORIGINAL_SOURCE:'+n)
 return v
def parent_contract(cp,spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);v=facts();run=cp['run']
 need({k:x for k,x in spec.items() if k!='root_admission'}==v['parent_transport'] and spec['root_admission_sha256']==ROOT
  and spec['root_admission']['branch_uncertainty_proof']==v['branch_proof'] and (cp['sha256'],cp['completed'],cp['source_cursor'],len(cp['repairs']))==(OUTER,543,'2020-02-28',18)
  and cp['sha256']==spec['outer_sha256']==digest({k:x for k,x in cp.items() if k!='sha256'}) and cp['repairs']==spec['repairs'] and cp['base']==spec['base']
  and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:x for k,x in run.items() if k!='checkpoint_sha256'})
  and run['state_sha256']==spec['state_sha256']==digest(run['state']) and run['input_sha256']==spec['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))
  and run['state']['last_processed_session']==cp['source_cursor'],'HABT_ONLY_ACTUAL_ADMITTED543_FULL18_ALL_COMMITMENTS')
 need([x for x in run['state']['wealth_core']['episodes'].values() if x['security_id']==SID]==v['actual_current_HABT_episodes'],'HABT_ACTUAL_CURRENT_ROLES_NEVER_OLD503_OR_FUTURE_INFERENCE')
 p=v['branch_proof'];need(p['passed'] is p['all_comparisons_and_state_sets_verified'] is p['all_math_watch_financial_chains_verified'] is True
  and (p['rows'],p['retained_rows'])==(19,70),'HABT_EXACT89_ADMITTED_PROOFS')
 return v
def primary_fact():
 facts();v=json.loads((HERE/PRIMARY).read_bytes())
 need(v['security_id']==SID and v['mandatory_common_cash']=='14.00' and v['currency']=='USD' and v['completion_date']=='2020-03-18'
  and v['preopen_completion_confirmed'] is False and v['exchange_last_trading_date']=='2020-03-18' and v['exchange_suspension_date']=='2020-03-19'
  and v['input_qualified'] is v['financial_authority'] is v['canonical_runtime_executed'] is False,'HABT_MANDATORY_COMMON_CASH_LEGAL_AND_RECOGNITION_DATES_DISTINCT')
 return v
def catalog():
 p=primary_fact();generation=prior.source('SOURCE327');index=25;row=generation['payload']['terms'][index];native=row['native_term']
 need(native['security_id']==SID and native['session']=='2020-03-18' and digest(native)==p['native_term_sha256'],'HABT_EXACT_RETAINED_NATIVE25')
 value=prior.primary_catalog();term=deepcopy(value['terms'][0]);description='Mandatory HABT Class A common cash14USD; legal merger March18. Retained next-session recognition March19 after Nasdaq last trading March18; no preopen completion or payment timestamp asserted.'
 term.update(ticker='HABT',security_id=SID,native_session='2020-03-18',native_term_sha256=digest(native),native=native,identity_witness=deepcopy(row['identity_witness']),parent_positions=deepcopy(row['parent_positions']),last_trading_session='2020-03-18',actual_completion_date='2020-03-18',mandatory_common_share_completion_confirmed=True,preopen_completion_confirmed=False,recognition_rule=calendar.NEXT,primary_source=p['primary_sources'][0],timing_source=p['primary_sources'][1],description=description)
 term['added']=dict(term['added'],security_id=SID,session='2020-03-19',cash_per_share=14.0,reference=term['primary_source']+' | '+description)
 term['primary_extraction']=dict(mandatory_common_cash=True,cash_currency='USD',cash_per_share='14.00',completion_date='2020-03-18',source=term['primary_source'],preopen_completion_confirmed=False,qualified_primary_fact_sha256=sha((HERE/PRIMARY).read_bytes()),no_stock_or_contingent_rights_in_common_consideration=True)
 term['retained_qualified_source']=dict(schema='research.P03-retained-original-source-generation-only/1',source_arm='P03',source_label='SOURCE327',original_parent_root_admission_sha256=prior.old.ROOT,original_parent_outer_sha256=prior.old.OUTER,original_term_sha256=digest(term),originating_book_authority_retained=False,current_root_admission_sha256=ROOT,current_role_basis='SEPARATE_ACTUAL543_COMPLETE_STATE_CONTRACT',future_ownership_inferred=False)
 value.update(selected_source_indices=[index],retained_source_indices=[],terms=[term],loader_sha256=sha(Path(__file__).read_bytes()))
 return value
def validator_tree():
 fn=subset.validator();raw=Path(subset.original.__file__).read_bytes()
 # Obtain the entire already-qualified subset function, with its exact three
 # original member-selection bindings, then lift only the existing calendar route.
 source=ast.parse(raw);node,=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='validate']
 site,=[i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='(terms, captured, declared)']
 node.body.insert(site+1,ast.parse('captured, declared, checked_members = selected_members(catalog,payload,review)').body[0])
 class Adapt(ast.NodeTransformer):
  selected=calendar=0
  def visit_Subscript(self,n):
   if ast.unparse(n)=="review['terms']":self.selected+=1;return ast.copy_location(ast.Name(id='checked_members',ctx=ast.Load()),n)
   return self.generic_visit(n)
  def visit_Compare(self,n):
   if ast.unparse(n)=="term['recognition_rule'] == PREOPEN":
    self.calendar+=1;n.ops=[ast.In()];n.comparators=[ast.Tuple(elts=[ast.Name(id='PREOPEN',ctx=ast.Load()),ast.Constant(calendar.NEXT)],ctx=ast.Load())]
   return self.generic_visit(n)
 change=Adapt();node=change.visit(node);need(change.selected==2 and change.calendar==1,'HABT_EXACT_WHOLE_SUBSET_AND_SINGLE_EXISTING_NEXT_ROUTE')
 return ast.fix_missing_locations(node)
def validate(value):
 scope=dict(vars(subset.original),__file__=__file__,CashInputBatch=subset.CashInputSubset,selected_members=subset.selected_members,source_binding=prior.old.source_binding)
 exec(compile(ast.Module(body=[validator_tree()],type_ignores=[]),'<whole-original-cash-subset-plus-existing-NEXT-calendar-route>','exec'),scope);scope['validate'](value)
 need(encoded(value)==encoded(catalog()),'HABT_EXACT_PRIMARY_NATIVE_CASH_AND_BOTH_CLOCKS');return True
def terms():
 value=catalog();validate(value);return deepcopy(value['terms'])
def codec(parent,spec):
 parent_contract(parent,spec);v=catalog();validate(v)
 return SimpleNamespace(catalog=v,catalog_sha=sha(encoded(v)),compiler_sha=sha(Path(__file__).read_bytes()),validator_description='Whole source-subset predicates and original retained NEXT cash-calendar convention; legal and recognition dates distinct.')
def completion_session(term,dates):
 calendar.validate_term(term)
 need(dates==sorted(set(dates)) and dates[dates.index('2020-03-18')+1]=='2020-03-19'==term['added']['session'],'HABT_EXACT_NEXT_FROZEN_SESSION_NO_PREOPEN_ASSERTION')
def source_names():return (Path(__file__).name,FACT,PRIMARY,CATALOG,*facts()['source_files'],*prior.source_names())
