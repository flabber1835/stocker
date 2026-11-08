"""Whole future APIs plus one full DOVA visitor dispatch and exclusive stage name."""
import ast,json
from copy import deepcopy
from functools import wraps
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p03_thor_data as data

FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
OVERLAY='p03-thor-ordinary17-overlay.json'
DIRECTORY='p03-thor-ordinary17-adoption'
QUALIFICATION='p03-thor-ordinary17-input-qualification.json'
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')
def remaining_tree(raw):
    data.need(data.sha(raw)==FUTURE_SHA,'THOR_API_WHOLE_ORIGINAL_FUTURE_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='remaining_ordinary_terms']
    blocks=[n for n in ast.walk(fn) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'"]
    data.need(len(blocks)==1,'THOR_API_ONE_ORIGINAL_NONTERMINAL_INPUT_BRANCH')
    block,=blocks;imp,guard,tail=block.body
    data.need(isinstance(imp,ast.ImportFrom) and imp.module=='system_campaign_financial_branches'
        and [(n.name,n.asname) for n in imp.names]==[('INPUT',None),('validate_input',None)]
        and isinstance(tail,ast.Continue),'THOR_API_WHOLE_ORIGINAL_B19_BRANCH_AND_CONTINUE')
    imp.names=imp.names[:1]
    added=ast.parse("if doc['schema']==DOVA_SCHEMA:\n    validate_dova_input(Path(root),cp,entry)\nelse:\n    pass").body[0]
    added.orelse=[guard];block.body=[imp,added,tail]
    return ast.fix_missing_locations(fn)
def full_branch_input(root,cp):
    from full_system_core import hosted
    hosted()
    import system_campaign_bounded_sensor_runtime_v2 as runtime
    runtime.full_models(root,cp)
    return runtime.catalog()['parent_descriptors'][-1]['sha256']
def validate_dova_input(root,cp,entry):
    from full_system_core import hosted
    hosted()
    import system_campaign_bounded_sensor_runtime_v2 as runtime
    value=runtime.full_models(root,cp)
    data.need(value==entry==cp['repairs'][15],'THOR_API_EXACT_TYPED16_IN_FULL_UNTRUNCATED_HISTORY')
def qualifier_save(path,value):
    path=Path(path)
    if path.name=='future-input-qualification.json':
        data.need(value['passed'] is True and type(value['financial_sessions_advanced']) is int
            and value['financial_sessions_advanced']==0,'THOR_API_ONLY_ORIGINAL_ZERO_FINANCIAL_QUALIFIER_SAVE')
        path=path.with_name(QUALIFICATION)
    return original.save(path,value)
def completion_session(term,dates):
    original.completion_session(term,dates)
    if term.get('security_id')!=data.SID:return
    data.need(dates==sorted(set(dates)) and term['last_trading_session'] in dates
        and dates.index(term['last_trading_session'])+1<len(dates)
        and dates[dates.index(term['last_trading_session'])+1]==term['added']['session']==term['native_session']=='2020-01-23',
        'THOR_API_EXISTING_CALENDAR_EXACT_NEXT_FROZEN_SESSION_AFTER_LAST_TRADE')
def api(cp,spec):
    raw=Path(original.__file__).read_bytes();data.need(data.sha(raw)==FUTURE_SHA,'THOR_API_ENTIRE_FROZEN_FUTURE_BYTES')
    data.parent_contract(cp,spec);catalog=data.catalog();codec=data.QualifiedThorCash(catalog)
    def selected(arm,*,cursor=None):
        data.need((arm,cursor)==('P03','2019-12-31'),'THOR_API_ONE_EXACT_ORIGINAL_PARENT_CLOCK')
        return codec,data.CATALOG,deepcopy(catalog['terms'])
    from system_campaign_bounded_sensor_input import SCHEMA
    namespace=dict(vars(original),__file__=__file__,selected=selected,OVERLAY=OVERLAY,completion_session=completion_session,
        validate_input=full_branch_input,validate_dova_input=validate_dova_input,DOVA_SCHEMA=SCHEMA)
    exec(compile(ast.Module(body=[remaining_tree(raw)],type_ignores=[]),
        '<whole-original-remaining-ordinary-inputs-one-full-DOVA-dispatch>','exec'),namespace)
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'THOR_API_ORIGINAL_FUNCTION_HAS_NO_HIDDEN_CLOSURE')
        bound=FunctionType(fn.__code__,dict(namespace,save=qualifier_save) if name=='qualify' else namespace,
            fn.__name__,fn.__defaults__);bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
        data.need(bound.__code__ is fn.__code__,'THOR_API_WHOLE_ORIGINAL_FUNCTION_CODE_OBJECT')
        if name=='hydrate':
            whole=bound
            @wraps(whole)
            def guarded(current,arm,*,source_root=None):
                from full_system_core import hosted
                hosted()
                from research.pooled_input_support.bundle import axis
                dates=axis()
                for term in catalog['terms']:completion_session(term,dates)
                return whole(current,arm,source_root=source_root)
            bound=guarded
        namespace[name]=bound
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=selected,OVERLAY=OVERLAY)
def source_names():return (Path(__file__).name,*data.source_names())
