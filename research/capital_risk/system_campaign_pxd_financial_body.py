"""Explicit metadata-only adaptation of authenticated orchestration bodies."""
import ast
from copy import deepcopy
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha

HERE=Path(__file__).resolve().parent


def tree(filename,name,replacements,*,insert_after=None,expected_counts=None,keywords=None,receipt_fields=None):
    import json
    qualified=json.loads((HERE/'system-campaign-pxd-qualification-request.json').read_bytes())
    raw=(HERE/filename).read_bytes()
    need(sha(raw)==qualified['sources'][filename],'PXD_BODY_EXACT_UNCHANGED_ADOPTED_ORCHESTRATOR')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    changes={key:0 for key in replacements}
    class Sites(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) in (str,int) and node.value in replacements:
                changes[node.value]+=1
                return ast.copy_location(ast.Constant(value=replacements[node.value]),node)
            return node
    fn=Sites().visit(deepcopy(fn))
    wanted={key:1 for key in replacements}
    if expected_counts is not None:
        need(set(expected_counts)<=set(wanted),'PXD_BODY_ONLY_DECLARED_MULTIPLE_SITES')
        wanted.update(expected_counts)
    need(changes==wanted,'PXD_BODY_EVERY_DECLARED_LITERAL_SITE_EXACTLY_ONCE')
    if keywords:
        seen={key:0 for key in keywords}
        for node in ast.walk(fn):
            if isinstance(node,ast.keyword) and node.arg in keywords:
                seen[node.arg]+=1;node.arg=keywords[node.arg]
        need(all(v==1 for v in seen.values()),'PXD_BODY_EXACT_LINEAGE_METADATA_KEY_SITES')
    if receipt_fields:
        receipt,=[node.value for node in ast.walk(fn) if isinstance(node,ast.Assign)
            and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            and node.targets[0].id=='receipt' and isinstance(node.value,ast.Call)]
        need(ast.unparse(receipt.func)=='dict' and not set(receipt_fields)&{k.arg for k in receipt.keywords},
             'PXD_BODY_NEW_RECEIPT_FIELDS_NEVER_OVERRIDE_ORIGINAL_OUTCOMES')
        receipt.keywords.extend(ast.keyword(arg=k,value=ast.parse(v,mode='eval').body)
                               for k,v in receipt_fields.items())
    if insert_after is not None:
        matches=[]
        for node in ast.walk(fn):
            for field,value in ast.iter_fields(node):
                if isinstance(value,list):
                    for index,statement in enumerate(value):
                        if (isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call)
                            and statement.value.args and isinstance(statement.value.args[0],ast.Constant)
                            and statement.value.args[0].value==insert_after):matches.append((value,index))
        need(len(matches)==1,'PXD_BODY_ONE_POST_GATE_ARCHIVE_PRESERVATION_SITE')
        statements,index=matches[0]
        statements[index+1:index+1]=ast.parse('preserve_all_checkpoints(old,out)').body
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))


def function(filename,name,replacements,namespace,**kwargs):
    body=tree(filename,name,replacements,**kwargs)
    scope=dict(namespace)
    exec(compile(body,'<source-bound-original-orchestration-metadata-sites>','exec'),scope)
    return scope[name]


ECONOMIC={41208142260:41214327942,'2023-10-31':'2024-04-30','2023-11-06':'2024-05-02',
          1468:1592,35:36,1014:1138,
          'RETAINED_SIX_MODELS_GUARDED_TWNK_CLOSE_SUFFIX':'RETAINED_SEVEN_MODELS_UNOWNED_PXD_SUFFIX',
          'close-constructor-admission.json':'pxd-constructor-admission.json',
          'close-position-refusal.json':'pxd-position-refusal.json',
          'close-economic-outcome.json':'pxd-economic-outcome.json'}
REVIEW={'close-lineage-review.json':'pxd-lineage-review.json',
        'close-position-and-event-review.json':'pxd-position-and-event-review.json',
        'close-constructor-admission.json':'pxd-constructor-admission.json'}
REVIEW_KEYWORDS={'all35_old_descriptors_preserved':'all36_old_descriptors_preserved',
                'all_six_original_model_semantics_unchanged':'all_seven_original_model_semantics_unchanged',
                'exactly_one_guarded_closing_fact_input':'exactly_one_guarded_pxd_fact_input'}
