"""Whole frozen future APIs; finite18-term stock completion/provider bindings."""
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p05_remaining_batch_data as data
HERE=Path(__file__).parent
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')
QUALIFICATION='p05-retained18-input-qualification.json'
def qualification_save(path,value):
    path=Path(path)
    if path.name=='future-input-qualification.json':
        data.need(value['passed'] is True and type(value['financial_sessions_advanced']) is int and value['financial_sessions_advanced']==0,
            'P05_REMAINING18_ONLY_EXACT_ZERO_ADVANCE_QUALIFICATION_SAVE')
        path=path.with_name(QUALIFICATION)
    return original.save(path,value)
def api(parent,*,provider_root=Path('/out')):
    data.own.parent_contract(parent);codec=data.codec(parent);terms=data.terms()
    data.need(data.sha(Path(original.__file__).read_bytes())==data.own.FUTURE_SHA,'P05_REMAINING18_API_ENTIRE_FROZEN_FUTURE_SOURCE')
    def selected(arm,*,cursor=None):
        data.need((arm,cursor)==('P05','2022-08-31'),'P05_REMAINING18_API_ONE_EXACT_INITIAL_PARENT_CLOCK')
        return codec,data.CATALOG,deepcopy(terms)
    namespace=dict(vars(original),__file__=__file__,HERE=HERE,selected=selected,completion_session=data.completion_session)
    originals={}
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'P05_REMAINING18_API_NO_HIDDEN_ORIGINAL_CLOSURE')
        bound=FunctionType(fn.__code__,dict(namespace,save=qualification_save) if name=='qualify' else namespace,fn.__name__,fn.__defaults__)
        bound.__kwdefaults__=deepcopy(fn.__kwdefaults__);data.need(bound.__code__ is fn.__code__,'P05_REMAINING18_API_WHOLE_ORIGINAL_FUNCTION_CODE')
        originals[name]=namespace[name]=bound
    whole_hydrate=originals['hydrate']
    def hydrate(current,arm,*,source_root=None):
        original.hosted()
        data.own.parent_contract(current)
        candidates=[Path(source_root)/'provider-source/SHARADAR_ACTIONS.zip'] if source_root is not None else []
        candidates.append(Path(provider_root)/'provider-source/SHARADAR_ACTIONS.zip')
        found=[p for p in candidates if p.is_file()]
        data.need(found,'P05_REMAINING18_HOST_STAGED_OR_RETAINED_ORIGINAL_PROVIDER_OBJECT_REQUIRED')
        proofs=[data.validate_provider(p) for p in found]
        data.need(all(p==proofs[0] for p in proofs),'P05_REMAINING18_NO_CONFLICTING_OLD_AND_NEW_PROVIDER_SOURCE')
        return whole_hydrate(current,arm,source_root=source_root)
    namespace['hydrate']=hydrate
    whole_prepare=originals['prepare']
    def prepare(current,out,arm):
        original.hosted()
        data.need(arm=='P05','P05_REMAINING18_PREPARE_ONE_ARM')
        data.own.parent_contract(current)
        catalog=data.catalog(current)
        data.need(data.sha(data.encoded(catalog))==codec.catalog_sha,'P05_REMAINING18_PERSISTED_ACTUAL_CATALOG_EQUALS_SELECTOR_BYTES')
        original.save(Path(out)/data.CATALOG,catalog)
        return whole_prepare(current,out,arm)
    namespace['prepare']=prepare
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=selected,OVERLAY=original.OVERLAY,
        entire_original_functions=originals,whole_original_hydrate=whole_hydrate,whole_original_prepare=whole_prepare)
