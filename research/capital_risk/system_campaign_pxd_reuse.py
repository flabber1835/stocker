"""Explicit source-bound observation/gate adaptation; never canonical rewriting."""
import ast
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_pxd_facts import contract


def rewritten(fn,*,bindings,fraction_terms=False,preopen=False,replacements=None):
    path=Path(fn.__code__.co_filename);raw=path.read_bytes()
    value=contract()
    need(path.name in ('system_campaign_close_gate.py','system_campaign_close_review.py')
         and sha(raw)==value['inherited_sources'][path.name] and fn.__closure__ is None,
         'PXD_REUSE_EXACT_ADOPTED_GATE_OR_OBSERVER_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==fn.__name__]
    mapping=dict(replacements or {})
    if fraction_terms:mapping.update({'30':'0','0.03002':'2.3234'})
    counts={k:0 for k in mapping};clocks=[]
    class Change(ast.NodeTransformer):
        def visit_Constant(self,item):
            if type(item.value) is str and item.value in mapping:
                counts[item.value]+=1
                return ast.copy_location(ast.Constant(value=mapping[item.value]),item)
            return item
        def visit_keyword(self,item):
            if item.arg=='preopen_completion_claimed':
                need(preopen and isinstance(item.value,ast.Constant) and item.value.value is False,
                     'PXD_REUSE_ONE_ORIGINAL_FALSE_FACTUAL_CLOCK_FIELD')
                clocks.append(item);item.value=ast.Constant(value=True)
                return item
            return self.generic_visit(item)
    node=Change().visit(node)
    need(all(v==1 for v in counts.values()) and len(clocks)==int(preopen),
         'PXD_REUSE_EXACT_DECLARED_LITERAL_AND_CLOCK_SITES')
    namespace=dict(fn.__globals__,**bindings)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-PXD-gate-or-observer-only>','exec'),namespace)
    return namespace[fn.__name__]
