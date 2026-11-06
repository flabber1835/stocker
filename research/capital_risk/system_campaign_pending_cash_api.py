"""Exact SRRA API binding with unchanged original future-input code objects."""
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_qualified_pending_cash as cash

HERE=Path(__file__).parent
ORIGINAL_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
CATALOG='system-campaign-p05-own1132-srra-pending-cash-input.json'
ROLE='SRRA-own1132-pending-role-DATA.json'
ROLE_SHA='c32076fb3cbc7b469864aa2d1815e83e79291770e7c34a0df8cc32c14a8c22cc'
FUNCTIONS=('selected','suppressions','hydrate','document','prepare','review_input','source_scopes')
need,sha,digest=original.need,original.sha,original.digest

def source_names():
    return ('system_campaign_pending_cash_api.py','system_campaign_qualified_pending_cash.py',CATALOG,ROLE,cash.PRIMARY)

def role():
    raw=(HERE/ROLE).read_bytes();need(sha(raw)==ROLE_SHA,'PENDING_API_EXACT_AUTHENTIC_PARENT_ROLE_METADATA');return json.loads(raw)

def validate_pending(cp,term):
    r=role();sid=cash.SID;run=cp['run'];state=run['state'];w=state['wealth_core']
    need(cp['sha256']==cash.OUTER==digest({k:v for k,v in cp.items() if k!='sha256'})
         and run['checkpoint_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==digest(state)
         and run['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))==r['input_sha256']
         and len(cp['repairs'])==15 and (cp['completed'],cp['source_cursor'])==(1132,'2022-06-30'),
         'PENDING_API_FULL_ACTUAL_PARENT_STATE_INPUT_COMMITMENTS')
    held=[dict(slot_id=e['slot_id'],ticker=e['ticker'],quantity=e['current_shares'],entry_date=e['entry_date'])
          for _,e in sorted(w['episodes'].items(),key=lambda item:int(item[0])) if e['security_id']==sid]
    p=w['terminal_pending_terms'][sid]
    context=dict(pending_sessions=w['terminal_pending_sessions'][sid],stale_at_event=p['stale_at_event'],
                 native_term_sha256=digest(p['terms']),unresolved=sid in w['unresolved_terminals'])
    need(held==r['positions']==term['parent_positions'] and w['slots']['8']==r['slot']
         and all(type(e['quantity']) is type(e['slot_id']) is int for e in held)
         and w['episodes']['8']['exit_pending'] is False
         and context==r['pending_context'] and type(context['pending_sessions']) is type(context['stale_at_event']) is int
         and context['unresolved'] is False and p['terms']==r['native']==term['native']
         and w['terminal_carry_audit'][sid]==r['carry_audit']
         and not any(x['security_id']==sid for x in state['pending'])
         and not any(x['security_id']==sid for x in state['ledger']['receivables']),
         'PENDING_API_WHOLE_ACTUAL_HELD_PENDING_CARRY_PREIMAGE')
    need(term['arm']=='P05' and term['ticker']=='SRRA' and term['security_id']==sid
         and term['parent_outer_sha256']==cash.OUTER and term['parent_root_admission_sha256']==cash.ROOT
         and term['parent_cursor']==term['native_session']==cp['source_cursor']
         and term['native_term_sha256']==cash.NATIVE and term['added']['session']=='2022-07-01'
         and term['added']['kind']=='CASH_MERGER' and term['added']['cash_per_share']==55.
         and term['source_capture']['run_id']==42148024783
         and term['source_capture']['head']=='1ee68c72572f8ac04d9e0474dd59ff0c30d4e545'
         and term['source_capture']['artifact_id']==13471725575,
         'PENDING_API_EXACT_SEPARATE_HELD_CASH_COMPLETION_CLOCK')

def pending_completion(cp,term):
    if term.get('arm')=='P05' and term.get('security_id')==cash.SID:return validate_pending(cp,term)
    return original.pending_completion(cp,term)

def private_api():
    need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'PENDING_API_ENTIRE_ORIGINAL_FUTURE_SOURCE')
    namespace=dict(vars(original),__file__=__file__,HERE=HERE,pending_completion=pending_completion)
    phases=deepcopy(original.FUTURE_LITERAL_PHASES)
    need(('P05','2022-06-30') not in phases,'PENDING_API_DISTINCT_NEW_PHASE_ONLY')
    phases['P05','2022-06-30']=('system_campaign_qualified_pending_cash','QualifiedPendingCash',CATALOG,('SRRA',))
    namespace['FUTURE_LITERAL_PHASES']=phases
    for name in FUNCTIONS:
        fn=getattr(original,name);need(fn.__closure__ is None,'PENDING_API_NO_HIDDEN_ORIGINAL_CLOSURE')
        bound=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__);bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
        need(bound.__code__ is fn.__code__,'PENDING_API_WHOLE_ORIGINAL_CODE_OBJECT')
        namespace[name]=bound
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},OVERLAY=original.OVERLAY)

def for_parent(cp,arm):
    if (arm,cp['source_cursor'])!=('P05','2022-06-30'):return original
    need(cp['sha256']==cash.OUTER and len(cp['repairs'])==15 and cp['completed']==1132,
         'PENDING_API_ONE_EXACT_NEW_OWN_PARENT_PHASE')
    return private_api()
