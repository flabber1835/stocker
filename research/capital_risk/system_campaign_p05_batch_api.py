"""Whole original future API code objects with one exact bounded cash selection."""
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p05_batch_data as data

ORIGINAL_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')

def overlay(index):
    data.need(type(index) is int and 0<=index<3,'P05_BATCH_EXACT_CHUNK_INDEX')
    return 'p05-batch-'+str(index+1).zfill(2)+'-terminal-overlay.json'

def directory(index):return overlay(index).replace('-terminal-overlay.json','-adoption')
def catalog_name(index):return overlay(index).replace('-terminal-overlay.json','-qualified-catalog.json')
def qualification(index):return overlay(index).replace('-terminal-overlay.json','-input-qualification.json')

def qualification_save(index):
    name=qualification(index)
    def save(path,value):
        path=Path(path)
        if path.name=='future-input-qualification.json':
            data.need(value['passed'] is True and type(value['financial_sessions_advanced']) is int
                 and value['financial_sessions_advanced']==0,'P05_BATCH_ONLY_ORIGINAL_ZERO_FINANCIAL_QUALIFICATION_SAVE')
            path=path.with_name(name)
        return original.save(path,value)
    return save

def api(initial,current,catalog,index):
    data.need(data.sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'P05_BATCH_ENTIRE_ORIGINAL_FUTURE_API_SOURCE')
    data.parent_contract(initial);data.validate(catalog,initial)
    data.need(current['base']==initial['base'] and current['source_cursor']==initial['source_cursor']
         and current['completed']==initial['completed'] and current['run']['state']==initial['run']['state']
         and current['repairs'][:16]==initial['repairs'] and len(current['repairs'])==16+index
         and current['run']['input_sha256']==data.digest(dict(base=current['base'],repairs=current['repairs'])),
         'P05_BATCH_API_ACTUAL_CURRENT_NEUTRAL_PARENT_FULL_INPUTS')
    codec=data.QualifiedChunk(catalog,initial)
    def selected(arm,*,cursor=None):
        data.need(arm=='P05' and cursor==current['source_cursor'],'P05_BATCH_API_ONLY_EXACT_CURRENT_CHUNK_CLOCK')
        return codec,catalog_name(index),deepcopy(catalog['terms'])
    namespace=dict(vars(original),__file__=__file__,selected=selected,OVERLAY=overlay(index))
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'P05_BATCH_API_NO_HIDDEN_ORIGINAL_CLOSURE')
        bindings=dict(namespace,save=qualification_save(index)) if name=='qualify' else namespace
        bound=FunctionType(fn.__code__,bindings,fn.__name__,fn.__defaults__);bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
        data.need(bound.__code__ is fn.__code__,'P05_BATCH_API_COMPLETE_ORIGINAL_FUNCTION_CODE_OBJECT')
        namespace[name]=bound
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=selected,OVERLAY=overlay(index))
