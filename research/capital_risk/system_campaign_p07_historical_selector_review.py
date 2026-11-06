"""Private exact historical source identity for whole original readonly review."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType
from system_campaign_facts import sha
from full_system_benchmark import need

HERE=Path(__file__).parent
HISTORICAL='P07-ordinary-selector-8cd57-DATA-SOURCE.txt'
OLD_SHA='8cd57c08782d33183c988c75bf3a945a9153316d4ed1479bf506830aa4dc6dec'
CURRENT_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
LEGACY_SHA='d41fccdc9ecb3dbaa4165329812ea3037b15ea316e073e9c6af50a71a9f4ab7c'

def source_contract():
    import system_campaign_financial_future as future
    import system_campaign_ordinary_augmentation_data as ordinary
    current=Path(future.__file__).read_bytes();historical=(HERE/HISTORICAL).read_bytes()
    need(sha(current)==CURRENT_SHA and sha(historical)==OLD_SHA,
         'P07_READONLY_EXACT_CURRENT_AND_PHYSICAL_HISTORICAL_SELECTOR_SOURCES')
    definitions=lambda raw:[n for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
    need(ast.dump(ast.Module(body=definitions(current),type_ignores=[]),include_attributes=False)
         ==ast.dump(ast.Module(body=definitions(historical),type_ignores=[]),include_attributes=False),
         'P07_READONLY_EVERY_WHOLE_FUNCTION_AND_CLASS_AST_IDENTICAL')
    need(ordinary.source_matches(Path(future.__file__).name,OLD_SHA),
         'P07_READONLY_ORIGINAL_ADDITIVE_REGISTRY_QUALIFICATION_STILL_REQUIRED')
    return HERE/HISTORICAL

def historical_factory(original):
    def factory(*args,**kwargs):
        path=source_contract();namespace=original(*args,**kwargs)
        import system_campaign_financial_future as future
        need(type(namespace) is dict and namespace is not vars(future)
             and all(isinstance(namespace[name],FunctionType) and namespace[name].__globals__ is namespace
                     for name in ('hydrate','document','prepare','review_input')),
             'P07_READONLY_FRESH_COMPLETE_COMPILER_NAMESPACE_NOT_GLOBAL_MODULE')
        namespace['__file__']=str(path)
        return namespace
    return factory

def bind_review_lambda(original):
    need(isinstance(original,FunctionType) and original.__closure__ is not None,
         'P07_READONLY_ORIGINAL_PLAN_PHASE_VALIDATOR_CLOSURE_REQUIRED')
    ordinary=original.__globals__['review_ordinary'];factory=ordinary.__globals__['future_api']
    need(isinstance(ordinary,FunctionType) and ordinary.__closure__ is None and isinstance(factory,FunctionType),
         'P07_READONLY_COMPLETE_ORIGINAL_ORDINARY_REVIEW_AND_FACTORY')
    scope=dict(ordinary.__globals__,future_api=historical_factory(factory))
    reviewed=FunctionType(ordinary.__code__,scope,ordinary.__name__,ordinary.__defaults__)
    reviewed.__kwdefaults__=deepcopy(ordinary.__kwdefaults__)
    result=FunctionType(original.__code__,dict(original.__globals__,review_ordinary=reviewed),
        original.__name__,original.__defaults__,original.__closure__)
    result.__kwdefaults__=deepcopy(original.__kwdefaults__)
    need(result.__code__ is original.__code__ and result.__closure__ is original.__closure__
         and reviewed.__code__ is ordinary.__code__,'P07_READONLY_WHOLE_REVIEW_BODIES_AND_CLOSURE_UNCHANGED')
    return result

@contextmanager
def context():
    from full_system_core import hosted
    hosted()
    import system_campaign_p07_abmd_legacy as legacy
    need(sha(Path(legacy.__file__).read_bytes())==LEGACY_SHA,'P07_READONLY_EXACT_UNCHANGED_GEN2_ABMD_LEGACY_SOURCE')
    source_contract();original=legacy.build
    def build(*args,**kwargs):
        hosted();result=original(*args,**kwargs);namespace=result.run.__globals__
        need(result.review.__globals__ is namespace and namespace.get('review_ordinary') is result.review_ordinary,
             'P07_READONLY_ONE_PRIVATE_ACTUAL_REVIEW_NAMESPACE')
        rebound=bind_review_lambda(result.review_ordinary)
        namespace['review_ordinary']=rebound;result.review_ordinary=rebound
        return result
    legacy.build=build
    try:yield
    finally:legacy.build=original
