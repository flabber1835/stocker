"""Original historical observer; WWE conversion stays in the canonical kernel."""
import json
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_financial_future as original
import system_campaign_p06_BBIG_observer as prior
import system_campaign_p06_BBIG_api as prior_api
import system_campaign_p06_BBIG_models as prior_models
import system_campaign_p06_BBIG_data as prior_data
import system_campaign_p06_WWE12_data as data
import system_campaign_p06_WWE12_resources as resources
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
DIRECTORY='p06-WWE-retained-historical-observation'
ORIGIN='observer-origin.json'

def historical_contract(parent,spec,member):
    from system_campaign_financial_partial import root_spec
    data.parent_contract(parent,spec)
    historical=strict_json(resources.checked(member,prior_models.PARENT))
    oldspec=root_spec('P06',prior_data.ROOT);prior_data.parent_contract(historical,oldspec)
    prefix=prior.DIRECTORY+'/'
    names=(prior_models.OVERLAY,original.hydration_name(historical),original.SOURCE_SCOPES)
    payloads={n:resources.checked(member,prefix+n) for n in names}
    material=json.loads(payloads[original.hydration_name(historical)])
    api=prior_api.api(historical,oldspec)
    scopes=api.source_scopes(historical,material,data.sha(payloads[prior_models.OVERLAY]),data.sha(payloads[original.hydration_name(historical)]))
    data.need(scopes==json.loads(payloads[original.SOURCE_SCOPES]) and len(scopes)==1
        and scopes[0]['security_id']==prior_data.SID and scopes[0]['require_never_held'] is True
        and scopes[0]['session']=='2023-07-27'<parent['source_cursor']
        and historical['repairs']==parent['repairs'][:10] and historical['sha256']!=parent['sha256'],
        'P06_WWE12_HISTORICAL1383_ONLY_OBSERVATION_NOT_ACTUAL1426_FINANCIAL_SEED')
    return historical,oldspec,payloads,scopes

def initializer(source_scopes):
    fn=original.ActualEvents.__init__
    data.need(data.sha(Path(original.__file__).read_bytes())==prior_data.FUTURE_SHA and fn.__closure__ is None,
        'P06_WWE12_WHOLE_UNCHANGED_ORIGINAL_OBSERVER_SOURCE')
    bound=FunctionType(fn.__code__,dict(fn.__globals__,OVERLAY=prior_models.OVERLAY,source_scopes=source_scopes),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
    data.need(bound.__code__ is fn.__code__,'P06_WWE12_IDENTICAL_ORIGINAL_OBSERVER_INITIALIZER_CODE')
    return bound

def origin(parent,historical,payloads,terms,scopes):
    data.need({t['ticker'] for t in terms}=={'TRQ','MYOV'} and len(terms)==2
        and all(t['added']['session']<parent['source_cursor'] for t in terms)
        and all(s['session']<parent['source_cursor'] for s in scopes),
        'P06_WWE12_ALL_HISTORICAL_CASH_AND_SOURCE_DATES_PRECEDE_REAL_FINANCIAL_SEED')
    return dict(schema='research.P06-WWE12-original-historical-observer/1',actual_financial_parent11=parent['sha256'],
        observation_parent10_only=historical['sha256'],historical_resources={n:dict(bytes=len(b),sha256=data.sha(b)) for n,b in payloads.items()},
        old_cash_terms=terms,original_BBIG_scopes=scopes,original_methods_unchanged=True,
        historical_financial_sessions_reexecuted=0,WWE_conversion_delegated_to_original_terminal=True)

def observer(root,out,current,parent,spec,request):
    from full_system_core import hosted
    hosted();root,out=Path(root),Path(out)
    historical,oldspec,payloads,scopes=historical_contract(parent,spec,lambda n:(root/n).read_bytes())
    folder=out/DIRECTORY
    for n,b in payloads.items():exact(folder/n,b)
    api=prior_api.api(historical,oldspec);event=original.ActualEvents.__new__(original.ActualEvents)
    initializer(api.source_scopes)(event,folder,'P06',cp=historical)
    terms=prior.cash_terms(root,current);prior.merge_cash(event,terms)
    data.need(event.advance.__func__ is original.ActualEvents.advance and event.terminal.__func__ is original.ActualEvents.terminal
        and event.source_values.__func__ is original.ActualEvents.source_values and event.scopes==scopes,
        'P06_WWE12_ENTIRE_ORIGINAL_OBSERVER_METHODS_AND_SOURCE_SCOPE')
    exact(folder/ORIGIN,data.encoded(origin(parent,historical,payloads,terms,scopes)))
    return event

def review(parent,current,evidence,out,*,spec,old):
    from full_system_core import hosted
    hosted();evidence,out,old=Path(evidence),Path(out),Path(old)
    resources.verify_preserved(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes())
    historical,_,payloads,scopes=historical_contract(parent,spec,lambda n:(evidence/n).read_bytes())
    terms=prior.cash_terms(evidence,current);folder=evidence/DIRECTORY
    data.need(json.loads((folder/ORIGIN).read_bytes())==origin(parent,historical,payloads,terms,scopes)
        and all((folder/n).read_bytes()==b for n,b in payloads.items())
        and not list(folder.glob('actual-future-event-20*.json'))
        and not (folder/'actual-future-event-refusal.json').exists(),
        'P06_WWE12_NO_REEXECUTED_OLD_CASH_SOURCE_OBSERVATIONS_OR_REFUSAL')
    result=dict(passed=True,all88_historical_resources_unchanged=True,original_TRQ_MYOV_BBIG_preserved=True,
        new_old_event_records=0,financial_sessions_reexecuted=0,original_observer_methods_unchanged=True)
    exact(out/'p06-WWE-historical-observation-review.json',data.encoded(result));return result

def source_names():return (Path(__file__).name,*resources.source_names(),*prior.source_names(),*prior_api.source_names())
