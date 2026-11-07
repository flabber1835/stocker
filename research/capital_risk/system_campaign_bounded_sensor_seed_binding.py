"""Whole retained proof seed with one explicit full-input visitor binding."""
import ast
from pathlib import Path
import system_campaign_financial_uncertainty as original
from system_campaign_bounded_sensor_input import need,sha

ORIGINAL_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'

def seed_tree(raw):
    need(sha(raw)==ORIGINAL_SHA,'BOUNDED_SEED_ENTIRE_ORIGINAL_GUARDED_SOURCE')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='retained_seed')
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches']
    need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==
         [('validate_input',None),('seed',None),('discrete',None),('digest',None)],
         'BOUNDED_SEED_ONE_EXACT_ORIGINAL_VISITOR_IMPORT')
    imports[0].names=imports[0].names[1:]
    return ast.fix_missing_locations(fn)

def bind_seed(*,validate_input,retained_contract,retained_phase):
    need(all(callable(fn) for fn in (validate_input,retained_contract,retained_phase)),
         'BOUNDED_SEED_ALL_EXPLICIT_QUALIFIED_VISITORS_REQUIRED')
    namespace=dict(vars(original),validate_input=validate_input,retained_contract=retained_contract,retained_phase=retained_phase)
    exec(compile(ast.Module(body=[seed_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
                 '<entire-original-retained-seed-explicit-full-input-visitor>','exec'),namespace)
    return namespace['retained_seed']
