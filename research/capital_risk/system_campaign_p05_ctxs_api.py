"""Whole frozen future API bodies bound to one separate CTXS source-only phase."""
import json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p05_ctxs_data as data
HERE=Path(__file__).parent
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')
QUALIFICATION='p05-ctxs-source-only-input-qualification.json'
def qualification_save(path,value):
    path=Path(path)
    if path.name=='future-input-qualification.json':
        data.need(value['passed'] is True and type(value['financial_sessions_advanced']) is int and value['financial_sessions_advanced']==0,
            'P05_CTXS_ONLY_EXACT_ZERO_ADVANCE_QUALIFICATION_SAVE')
        path=path.with_name(QUALIFICATION)
    return original.save(path,value)
def api(parent):
    data.parent_contract(parent);codec=data.codec(parent);term=data.term()
    data.need(data.sha(Path(original.__file__).read_bytes())==data.FUTURE_SHA,'P05_CTXS_API_WHOLE_FROZEN_FUTURE_SOURCE')
    def selected(arm,*,cursor=None):
        data.need((arm,cursor)==('P05','2022-08-31'),'P05_CTXS_API_ONLY_EXACT_INITIAL_OWN_PARENT_CLOCK')
        return codec,data.CATALOG,[deepcopy(term)]
    namespace=dict(vars(original),__file__=__file__,HERE=HERE,selected=selected)
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'P05_CTXS_API_NO_HIDDEN_ORIGINAL_CLOSURE')
        bound=FunctionType(fn.__code__,dict(namespace,save=qualification_save) if name=='qualify' else namespace,fn.__name__,fn.__defaults__)
        bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
        data.need(bound.__code__ is fn.__code__,'P05_CTXS_API_ENTIRE_ORIGINAL_FUNCTION_CODE_OBJECT')
        namespace[name]=bound
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=selected,OVERLAY=original.OVERLAY)
def for_parent(parent,arm):
    if arm!='P05' or parent['sha256']!=data.OUTER:return original
    return api(parent)
