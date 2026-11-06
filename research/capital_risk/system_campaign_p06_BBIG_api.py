"""Whole future input lifecycle; source-only selector retains its original policy."""
import ast
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models

FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')
def remaining_tree(raw):
    data.need(data.sha(raw)==data.FUTURE_SHA,'P06_BBIG_WHOLE_REMAINING_TERMS_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='remaining_ordinary_terms']
    block,=[n for n in ast.walk(fn) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'"]
    imp,guard,tail=block.body
    data.need(isinstance(imp,ast.ImportFrom) and imp.module=='system_campaign_financial_branches'
        and [(n.name,n.asname) for n in imp.names]==[('INPUT',None),('validate_input',None)] and isinstance(tail,ast.Continue),
        'P06_BBIG_ONE_EXACT_NONTERMINAL_B19_DISPATCH')
    imp.names=imp.names[:1]
    added=ast.parse('if doc["schema"]==TYPED_SCHEMA:\n validate_typed_input(Path(root),cp,entry)\nelse:\n pass').body[0]
    added.orelse=[guard];block.body=[imp,added,tail]
    return ast.fix_missing_locations(fn)
def full_input(root,cp):
    models.full(root,cp);return cp['repairs'][9]['sha256']
def validate_typed_input(root,cp,entry):
    result=models.full(root,cp)
    data.need(result['bounded_descriptor']==entry==cp['repairs'][9],
        'P06_BBIG_EXACT_TYPED10_IN_FULL_ACTUAL_HISTORY')
def qualifier_save(path,value):
    path=Path(path)
    if path.name=='future-input-qualification.json':
        data.need(value['passed'] is True and type(value['financial_sessions_advanced']) is int
            and value['financial_sessions_advanced']==0,'P06_BBIG_ZERO_FINANCIAL_ORIGINAL_QUALIFICATION')
        path=path.with_name(models.QUALIFICATION)
    return original.save(path,value)
def api(cp,spec):
    data.parent_contract(cp,spec);data.catalog()
    raw=Path(original.__file__).read_bytes();data.need(data.sha(raw)==data.FUTURE_SHA,'P06_BBIG_WHOLE_FUTURE_API_SOURCE')
    from system_campaign_bounded_sensor_input import SCHEMA
    namespace=dict(vars(original),selected=data.selected,OVERLAY=models.OVERLAY,validate_input=full_input,
        validate_typed_input=validate_typed_input,TYPED_SCHEMA=SCHEMA)
    exec(compile(ast.Module(body=[remaining_tree(raw)],type_ignores=[]),'<whole-original-remaining-terms-ABMD-full-history-dispatch>','exec'),namespace)
    for name in FUNCTIONS:
        fn=getattr(original,name);data.need(fn.__closure__ is None,'P06_BBIG_CLOSED_ORIGINAL_API_FUNCTION')
        bound=FunctionType(fn.__code__,dict(namespace,save=qualifier_save) if name=='qualify' else namespace,fn.__name__,fn.__defaults__)
        bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
        data.need(bound.__code__ is fn.__code__,'P06_BBIG_WHOLE_ORIGINAL_API_CODE_OBJECT')
        namespace[name]=bound
    return SimpleNamespace(**{name:namespace[name] for name in FUNCTIONS},selected=data.selected,OVERLAY=models.OVERLAY)
def source_names():return (Path(__file__).name,*models.source_names())
