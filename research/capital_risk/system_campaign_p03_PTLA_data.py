"""One mandatory ordinary-common cash term with unchanged source metadata."""
import json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
from system_campaign_facts import sha,digest
from full_system_benchmark import need
from system_campaign_cash_calendar import PREOPEN,validate_term
import system_campaign_qualified_cash_subset as subset
import system_campaign_p03_cash14_data as prior
import system_campaign_p03_PTLA_resources as resources
HERE=Path(__file__).parent
ROOT=resources.ROOT
SID='77684744013377591'
PRIMARY='P03-PTLA-mandatory-common-cash-primary.json'
BINDING='P03-PTLA-full20-factual-source-binding.json'
CATALOG='P03-PTLA-ordinary21-source-catalog.json'
PINS={PRIMARY:'423f16bec97e144f58361d46b862c9de8dd9d63bf58b7e9eee72f7c5dad95176',BINDING:'b3c15fbab54f6c40bd58674ac772836b757956f50ced1093786d0b228b98828c'}
encoded=resources.encoded


def facts():
 for name,pin in PINS.items():need(sha((HERE/name).read_bytes())==pin,'PTLA_CASH_EXACT_PRIMARY_AND_ACTUAL_SOURCE_BINDING:'+name)
 value=json.loads((HERE/BINDING).read_bytes());primary=json.loads((HERE/PRIMARY).read_bytes())
 need(value['primary_facts']==primary and value['primary_facts_sha256']==PINS[PRIMARY] and value['root_admission_sha256']==ROOT
  and primary['ordinary_remaining_common_entitlement'] is primary['preopen_completion_confirmed'] is True
  and primary['cash_per_common_share']=='18.00' and primary['native_session']=='2020-07-01'
  and primary['legal_completion_date']==primary['recognition_session']=='2020-07-02'
  and primary['future_ownership_verified'] is primary['financial_authority'] is primary['input_adopted'] is False,
  'PTLA_CASH_MANDATORY_ORDINARY_COMMON_AND_DISTINCT_NATIVE_RECOGNITION_CLOCKS')
 for filekey,hashkey in (('previous_complete_generation_file','previous_complete_generation_sha256'),('authenticated_batch_catalog_file','authenticated_batch_catalog_sha256')):
  need(Path(value[filekey]).name==value[filekey] and sha((HERE/value[filekey]).read_bytes())==value[hashkey],'PTLA_CASH_COMPLETE_ORIGINAL_AND_NEW_AUTHENTIC_SOURCE_GENERATIONS')
 need(value['last_source_quote']['session']=='2020-07-01'
  and value['last_source_quote']['raw_close']==value['last_source_quote']['signal_close']=='18.030000000000001'
  and value['last_source_quote_sha256']==digest(value['last_source_quote']) and value['completion_quote_present'] is False
  and value['provider_metadata_changed'] is False,'PTLA_CASH_ACTUAL_FINAL_MARKET_QUOTE_NOT_CASH_ENTITLEMENT')
 return value


def catalog():
 bound=facts();p=bound['primary_facts'];generation=prior.source('SOURCE327')
 index,row=next((i,v) for i,v in enumerate(generation['payload']['terms']) if v['native_term']['security_id']==SID)
 need(row==bound['original_term'] and row['native_term']==bound['native'] and digest(row['native_term'])==bound['native_sha256'],
  'PTLA_CASH_ORIGINAL_COMPLETE_NATIVE_AND_IDENTITY_ROW')
 value=prior.primary_catalog();term=deepcopy(value['terms'][0]);description='Mandatory remaining ordinary common18USD; merger completed before2020-07-02 open. Preserve the complete2020-07-01 market bar and suppress only its incomplete native terminal. No tender participation or payment timestamp assumed.'
 term.update(ticker='PTLA',security_id=SID,native_session='2020-07-01',native_term_sha256=bound['native_sha256'],native=deepcopy(bound['native']),
  identity_witness=deepcopy(row['identity_witness']),parent_positions=deepcopy(row['parent_positions']),last_trading_session='2020-07-01',actual_completion_date='2020-07-02',
  mandatory_common_share_completion_confirmed=True,preopen_completion_confirmed=True,recognition_rule=PREOPEN,
  primary_source=p['issuer_source'],timing_source=p['timing_corroboration'],description=description)
 term['added']=dict(term['added'],security_id=SID,session='2020-07-02',cash_per_share=18.0,reference=p['issuer_source']+' | '+description)
 term['primary_extraction']=dict(mandatory_common_cash=True,cash_currency='USD',cash_per_share='18.00',completion_date='2020-07-02',source=p['issuer_source'],
  preopen_completion_confirmed=True,qualified_primary_fact_sha256=PINS[PRIMARY],no_stock_or_contingent_rights_in_common_consideration=True)
 term['retained_qualified_source']=dict(schema='research.P03-retained-original-source-generation-only/1',source_arm='P03',source_label='SOURCE327',
  original_parent_root_admission_sha256=prior.old.ROOT,original_parent_outer_sha256=prior.old.OUTER,original_term_sha256=digest(term),
  originating_book_authority_retained=False,current_root_admission_sha256=ROOT,current_role_basis='SEPARATE_ACTUAL628_COMPLETE_STATE_CONTRACT',future_ownership_inferred=False)
 value.update(selected_source_indices=[index],retained_source_indices=[],terms=[term],loader_sha256=sha(Path(__file__).read_bytes()))
 return value


def validator():
 fn=subset.validator()
 return FunctionType(fn.__code__,dict(fn.__globals__,__file__=__file__,source_binding=prior.old.source_binding),fn.__name__,fn.__defaults__)


def validate(value):
 validator()(value);need(encoded(value)==encoded(catalog()),'PTLA_CASH_EXACT_SOURCE_PRIMARY_AMOUNT_AND_CLOCKS');return True


def terms():
 value=catalog();validate(value);return deepcopy(value['terms'])


def codec(parent,spec):
 resources.parent_contract(parent,spec);value=catalog();validate(value)
 state=parent['run']['state'];bound=facts()
 role=dict(held=any(v.get('security_id')==SID for v in state['wealth_core']['episodes'].values()),
  pending=any(v.get('security_id')==SID for v in state['pending']),leadership_selected=SID in state['median5']['selected'],
  raw_signal_anchor=state['feed']['series'][SID]['signal_basis_anchor'])
 need(role==bound['actual_parent_role'] and bound['actual_parent_role_is_not_future_ownership'] is True,
  'PTLA_CASH_ACTUAL628_ROLE_SEPARATE_FROM_OLD_SOURCE_AND_FUTURE_OWNERSHIP')
 return SimpleNamespace(catalog=value,catalog_sha=sha(encoded(value)),compiler_sha=sha(Path(__file__).read_bytes()),
  validator_description='Whole original selected cash predicates; complete original and new source rows; mandatory common cash on confirmed July2 preopen date.')


def completion_session(term,dates):
 validate_term(term)
 need(dates==sorted(set(dates)) and dates[dates.index('2020-07-01')+1]=='2020-07-02'==term['added']['session'],
  'PTLA_CASH_EXISTING_FROZEN_NEXT_SESSION_AND_DISTINCT_FINAL_TRADE')


def source_names():return (Path(__file__).name,PRIMARY,BINDING,CATALOG,*prior.source_names())
