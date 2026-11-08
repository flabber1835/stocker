"""Finite original cash-calendar facts; actual1426 roles grant no future ownership."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_cash_calendar import validate_term,PREOPEN,NEXT
from system_campaign_full_history_successor import current_commitments
HERE=Path(__file__).parent
ROOT='b134772ff8128b4f97a16dabbc357f07e019351c529c03419cb778726fad5a59'
FACT='P07-ordinary28-retained-cash-source-fact.json'
FACT_SHA='aa662e8439e9f25b75d21d2334edf7da16e6430ff0abe30a542f470fcb226b74'
CATALOG='P07-ordinary28-retained-cash-catalog.json'
FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
CALENDAR_SHA='183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f'
encoded=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def retained(item,files):
 name=item['catalog_file']
 need(Path(name).name==name and name in files,'ORDINARY28_SAFE_ORIGINAL_SOURCE_CATALOG')
 raw=(HERE/name).read_bytes()
 need(dict(bytes=len(raw),sha256=sha(raw))==files[name] and sha(raw)==item['catalog_sha256'],'ORDINARY28_EXACT_ORIGINAL_SOURCE_FILE')
 source=json.loads(raw);index=item['index']
 need(type(index)is int and 0<=index<len(source['terms']),'ORDINARY28_EXACT_ORIGINAL_SOURCE_INDEX')
 term=item['term'];original=source['terms'][index]
 need(term==original and digest(term)==item['term_sha256'],'ORDINARY28_RETAINED_ORIGINAL_TERM_BYTES_AND_SCOPE')
 validate_term(term)
 need(term['recognition_rule']in (PREOPEN,NEXT) and term.get('portfolio_completion_authorized',True)is True
  and not term.get('require_unowned_and_unordered',False) and not term.get('require_never_held',False),
  'ORDINARY28_NO_UPGRADED_SOURCE_ONLY_OR_CONTINGENT_AUTHORITY')
 return deepcopy(term)

def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'ORDINARY28_AUTHENTIC_COMPLETE_SOURCE_FACT')
 v=json.loads(raw)
 need(v['schema']=='research.P07-ordinary28-retained-calendar-cash-fact/1' and v['root_admission_sha256']==ROOT
  and (v['parent_completed'],v['parent_through'],v['parent_inputs'],v['retained_proofs'])==(1426,'2023-08-31',27,972)
  and len(v['source_files'])==6 and len(v['selected'])==12 and len(v['already_inherited'])==3
  and len(v['nonterminal_descriptors'])==5 and v['current_role_is_not_future_ownership']is True
  and v['financial_authority']is v['input_adopted']is v['financial_profile_ready']is v['local_canonical_runtime_executed']is False,
  'ORDINARY28_FINITE_SOURCE_ONLY_FULL27_AND972_CONTRACT')
 need(v['canonical_calendar_loader_sha256']==CALENDAR_SHA==sha((HERE/'system_campaign_cash_calendar.py').read_bytes())
  and v['original_future_api_sha256']==FUTURE_SHA==sha((HERE/'system_campaign_financial_future.py').read_bytes()),
  'ORDINARY28_WHOLE_ORIGINAL_CALENDAR_AND_FUTURE_API')
 p=HERE/v['source_catalog'];need(p.name==v['source_catalog'] and sha(p.read_bytes())==v['source_catalog_sha256'],'ORDINARY28_AUTHENTIC_RETA_NATIVE_AND_QUOTES')
 all_terms=[retained(item,v['source_files']) for item in v['selected']+v['already_inherited']]
 need(len({t['security_id'] for t in all_terms})==15 and all(v['parent_through']<t['native_session']<=t['added']['session']<='2026-07-31' for t in all_terms),'ORDINARY28_ALL15_EXACT_FUTURE_IDENTITIES_AND_DATES')
 for item in v['already_inherited']:
  t=item['term'];a=item['existing_addition'];e=item['existing_descriptor']
  need(item['existing_suppression']==dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256'])
   and {k:x for k,x in a.items() if k!='reference'}=={k:x for k,x in t['added'].items() if k!='reference'}
   and e['filename']==e['sha256']+'.json','ORDINARY28_ONLY_EXACT_ALREADY_INHERITED_ECONOMICS_AND_DATES')
 reta=next(t for t in all_terms if t['ticker']=='RETA');payload=json.loads(p.read_bytes())['source_evidence']
 native=next(g for g in payload['native_groups'] if g['query']['arm']=='P07')['original_typed_terminals']
 quote=next(g for g in payload['observations'] if g['query']['name']=='p07-next-native')['rows'][0]['source_row']
 need(len(native)==1 and digest(native[0])==reta['native_term_sha256']
  and digest(quote)==reta['identity_witness']['source_observation_sha256']
  and reta['added']['cash_per_share']==172.5 and reta['native_session']=='2023-09-25'
  and reta['added']['session']==reta['actual_completion_date']=='2023-09-26',
  'ORDINARY28_ORIGINAL_RETA_COMPLETE_NATIVE_IDENTITY_CASH_AND_DISTINCT_CLOCKS')
 return v

def catalog():
 v=fact()
 return dict(schema='research.P07-ordinary28-retained-calendar-cash/1',root_admission_sha256=ROOT,parent_outer_sha256=v['parent_outer_sha256'],
  source_fact=FACT,source_fact_sha256=FACT_SHA,loader_sha256=sha(Path(__file__).read_bytes()),terms=[deepcopy(x['term']) for x in v['selected']],
  already_inherited=[dict(ticker=x['term']['ticker'],security_id=x['term']['security_id'],descriptor=x['existing_descriptor']) for x in v['already_inherited']],
  financial_authority=False,input_adopted=False,originating_financial_authority_reused=False,event_date_ownership='UNKNOWN_UNTIL_ACTUAL_GUARDED_TRANSITION')

def terms():return deepcopy(catalog()['terms'])

def roles(cp,items):
 s=cp['run']['state'];result={}
 for item in items:
  sid=item['term']['security_id'];result[sid]=dict(held=[v for v in s['wealth_core']['episodes'].values() if v['security_id']==sid],pending=[v for v in s['pending'] if v.get('security_id')==sid],leadership_selected=sid in s['median5']['selected'],signal_basis_anchor=s['feed']['series'].get(sid,{}).get('signal_basis_anchor'))
 return result

def parent_contract(cp,spec):
 from system_campaign_financial_partial import root_spec,validate_root_spec
 validate_root_spec(spec);v=fact();current_commitments(cp,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(spec==root_spec('P07',ROOT) and spec['root_admission_sha256']==ROOT
  and cp['sha256']==spec['outer_sha256']==v['parent_outer_sha256'] and cp['repairs']==spec['repairs']
  and cp['base']==spec['base'] and cp['journals']==spec['journals']
  and (cp['completed'],cp['source_cursor'],len(cp['repairs']))==(1426,'2023-08-31',27)
  and cp['run']['input_sha256']==v['parent_input_sha256']==spec['input_sha256'],
  'ORDINARY28_GENUINE_FULL27_PARENT_NOT_A_PROJECTED_BOOK')
 proof=spec['root_admission']['branch_uncertainty_proof']
 need(proof['passed']is True and proof['retained_rows']+proof['rows']==972
  and roles(cp,v['selected'])==v['actual_parent_roles'],'ORDINARY28_EXACT972_AND_ACTUAL_CURRENT_ROLES_NOT_FUTURE_ROLES')
 return v

def codec(parent,spec):
 parent_contract(parent,spec);value=catalog()
 need((HERE/CATALOG).read_bytes()==encoded(value),'ORDINARY28_EXACT_DECLARED_FINITE_CATALOG')
 return SimpleNamespace(catalog=value,catalog_sha=sha(encoded(value)),compiler_sha=sha(Path(__file__).read_bytes()),validator_description='Exact original mandatory cash-calendar terms; current own1426/full27 roles; unknown future roles; unchanged PREOPEN/NEXT conventions.')

def completion_session(term,dates):
 validate_term(term)
 need(dates==sorted(set(dates)) and term['last_trading_session']in dates
  and dates.index(term['last_trading_session'])+1<len(dates)
  and dates[dates.index(term['last_trading_session'])+1]==term['added']['session'],
  'ORDINARY28_ORIGINAL_NEXT_FROZEN_SESSION_AFTER_LAST_TRADE')

def source_names():
 v=fact();return (Path(__file__).name,FACT,CATALOG,v['source_catalog'],'system_campaign_cash_calendar.py','system_campaign_financial_future.py',*v['source_files'])
