"""Whole original future APIs; finite full24 model visitor and PREOPEN batch."""
import ast
from copy import deepcopy
from functools import wraps
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_ordinary_augmentation_data as ordinary
import system_campaign_p07_abmd_lifecycle as lifecycle
import system_campaign_p07_vivo_data as data
import system_campaign_p07_vivo_models as models
from system_campaign_p07_vivo_boundary import OVERLAY,DIRECTORY,QUALIFICATION

FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')

def remaining_tree(raw):
    data.need(data.sha(raw)==FUTURE_SHA,'VIVO_WHOLE_ORIGINAL_REMAINING_ORDINARY_SOURCE')
    return ordinary.remaining_tree(raw)

def canonical_input_hash(module,cp):
    name='research/pooled_vacancy_funding/backtest.py'
    path=Path(module.__file__)
    data.need(path.as_posix().endswith('/'+name) and data.sha(path.read_bytes())==cp['base']['sources'][name],
         'VIVO_CANONICAL_INPUT_HASH_EXACT_IMMUTABLE_BACKTEST_SOURCE')
    fn=getattr(module,'input_hash',None)
    data.need(isinstance(fn,FunctionType) and fn.__globals__ is vars(module)
         and Path(fn.__code__.co_filename).resolve()==path.resolve(),
         'VIVO_CANONICAL_INPUT_HASH_ORIGINAL_FUNCTION_OWNER_AND_CODE_FILE')
    return fn


def full_models(root,cp):
    from full_system_core import hosted
    hosted()
    from system_campaign_abmd_bounded_catalog import evidence
    from research.pooled_vacancy_funding import backtest
    value=lifecycle.catalog()
    return models.models().validate_full(root,cp,value,evidence(value),input_hash=canonical_input_hash(backtest,cp),root_metadata=lifecycle.initial_spec())

def typed_input_valid(root,cp,entry):
    result=full_models(root,cp)
    data.need(result['bounded_descriptor']==cp['repairs'][23] and result['full_input_count']==len(cp['repairs'])
         and entry in (cp['repairs'][11],cp['repairs'][21],cp['repairs'][23]),
         'VIVO_FULL_TYPED_VISITOR_ALL_B19_ZOG_ABMD_EXACT_POSITIONS_NO_CODEC_SUBSTITUTION')
    return True

def qualifier_save(path,value):
    path=Path(path)
    if path.name=='future-input-qualification.json':
        data.need(value['passed'] is True and type(value['financial_sessions_advanced']) is int
             and value['financial_sessions_advanced']==0,'VIVO_ORIGINAL_EXCLUSIVE_ZERO_FINANCIAL_QUALIFICATION_SAVE')
        path=path.with_name(QUALIFICATION)
    return original.save(path,value)

def completion_session(term,dates):
    original.completion_session(term,dates)
    from system_campaign_cash_calendar import validate_term,PREOPEN
    data.need(term['recognition_rule']==PREOPEN,'VIVO_BATCH_ONLY_EXISTING_PREOPEN_POLICY')
    validate_term(term)
    data.need(dates==sorted(set(dates)) and term['last_trading_session'] in dates
         and dates.index(term['last_trading_session'])+1<len(dates)
         and dates[dates.index(term['last_trading_session'])+1]==term['added']['session'],
         'VIVO_EXISTING_CALENDAR_ALL23_EXACT_NEXT_FROZEN_SESSION_AFTER_LAST_TRADE')

def api(cp,spec):
    raw=Path(original.__file__).read_bytes();data.need(data.sha(raw)==FUTURE_SHA,'VIVO_ENTIRE_ORIGINAL_FUTURE_API_BYTES')
    data.parent_contract(cp,spec);catalog=data.catalog();codec=data.QualifiedVivoCash(catalog)
    def selected(arm,*,cursor=None):
        data.need((arm,cursor)==('P07','2022-12-30'),'VIVO_ONE_EXACT_REAL1259_PARENT_CLOCK')
        return codec,data.CATALOG,deepcopy(catalog['terms'])
    namespace=dict(vars(original),__file__=__file__,selected=selected,OVERLAY=OVERLAY,
        completion_session=completion_session,typed_input_valid=typed_input_valid)
    exec(compile(ast.Module(body=[remaining_tree(raw)],type_ignores=[]),'<whole-remaining-ordinary-full-B19-ZOG-ABMD-visitor>','exec'),namespace)
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'VIVO_API_NO_HIDDEN_ORIGINAL_CLOSURE')
        bound=FunctionType(fn.__code__,dict(namespace,save=qualifier_save) if name=='qualify' else namespace,
            fn.__name__,fn.__defaults__);bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
        data.need(bound.__code__ is fn.__code__,'VIVO_API_COMPLETE_ORIGINAL_FUNCTION_CODE_OBJECT')
        if name=='hydrate':
            whole=bound
            @wraps(whole)
            def guarded(current,arm,*,source_root=None):
                from full_system_core import hosted
                hosted()
                from research.pooled_input_support.bundle import axis
                data.need(source_root is not None,'VIVO_ACTUAL_FULL24_SOURCE_ROOT_REQUIRED')
                full_models(source_root,current)
                dates=axis()
                for term in catalog['terms']:completion_session(term,dates)
                return whole(current,arm,source_root=source_root)
            bound=guarded
        namespace[name]=bound
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=selected,OVERLAY=OVERLAY)

def source_names():return (Path(__file__).name,*models.source_names(),*data.source_names())
