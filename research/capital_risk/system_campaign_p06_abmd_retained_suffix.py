"""Whole original retained suffix review with one explicit proof-growth binding."""
import ast
from pathlib import Path
from system_campaign_bounded_sensor_input import need,sha
from system_campaign_p06_abmd_retained_data import LEGACY_SHA

def review_tree(raw):
    need(sha(raw)==LEGACY_SHA,'P06_SUFFIX_WHOLE_ORIGINAL_U_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review_new_rows']
    scope,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='scope']
    need(isinstance(scope,ast.Call) and ast.unparse(scope.func)=='dict' and len(scope.args)==1
         and ast.unparse(scope.args[0])=='vars(b)' and all(k.arg!='growth' for k in scope.keywords),
         'P06_SUFFIX_ONE_EXACT_ORIGINAL_B19_NAMESPACE_SITE')
    scope.keywords.append(ast.keyword(arg='growth',value=ast.Name(id='mixed_growth',ctx=ast.Load())))
    return ast.fix_missing_locations(fn)

def bind_review():
    import system_campaign_financial_uncertainty as legacy
    from system_campaign_p06_abmd_point_continuation import mixed_growth
    scope=dict(vars(legacy),mixed_growth=mixed_growth)
    exec(compile(ast.Module(body=[review_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-six-offset-B19-suffix-with-explicit-point-growth-namespace>','exec'),scope)
    return scope['review_new_rows']

def review(parent,current,retained,rows,financial,*,median5,champion_config):
    from full_system_core import hosted
    hosted()
    need(len(retained)==6 and not any(row['session']=='2022-12-22' for row in rows),
         'P06_SUFFIX_SIX_REAL_PRIOR_PROOFS_NO_REPLAYED_EVENT')
    return bind_review()(parent,current,retained,rows,financial,median5=median5,champion_config=champion_config)
