"""Whole qualified THOR lifecycle bodies with finite actual524/70 safety bindings."""
import ast,gzip,json,shutil,stat,tempfile
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType
import system_campaign_p03_thor_runtime as original
import system_campaign_p03_HABT19_data as data
import system_campaign_p03_HABT19_api as api_module
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
from system_campaign_pxd_pause import adoption
uncertainty,typed=original.uncertainty,original.typed
HERE=Path(__file__).parent
U_SHA,TYPED_SHA=original.U_SHA,original.TYPED_SHA
RAW_PROOF='p03-HABT-ordinary19-origin/entire-prior-certificate.jsonl'
SELECTED='p03-HABT-ordinary19-origin/actual-selected-parent18.json.gz'
PRIOR_REVIEW='p03-HABT-ordinary19-origin/prior-hosted-branch-review.json'
VIEW_RECEIPT='p03-HABT-ordinary19-origin/temporary-seed-view-receipt.json'
VIEW_CLEANUP='p03-HABT-ordinary19-origin/temporary-seed-view-cleanup.json'
BOUNDARY_REVIEW='p03-HABT-ordinary19-neutral-boundary-review.json'
FUNCTIONS=('adoption_tree','adopter','boundary_relation','boundary','cleanup_observed','owned_view_permissions','seed_view','seed_resolver','bound_runtime','original_seed','run','review')
DATES={'2019-12-31':'2020-02-28','2020-01-23':'2020-03-18'}
INTS={16:18,17:19,49:89,63:101,14:12}
STRINGS={'p03-thor-owned-seed-view-':'p03-HABT-owned-seed-view-',
    'research.P03-actual-neutral17-temporary-seed-view/1':'research.P03-actual-neutral19-temporary-seed-view/1',
    'selected_parent16_file_sha256':'selected_parent18_file_sha256','actual_neutral17_file_sha256':'actual_neutral19_file_sha256'}
def source_tree(name):
    raw=Path(original.__file__).read_bytes();data.need(data.sha(raw)==data.facts()['frozen_sources'][Path(original.__file__).name],'P03_14_WHOLE_FROZEN_ORIGINAL_LIFECYCLE_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    return fn
def body_tree(name):
    data.need(name in FUNCTIONS,'P03_14_ONLY_EXPLICIT_ORIGINAL_LIFECYCLE_BODIES')
    fn=source_tree(name)
    class Finite(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is int and node.value in INTS:return ast.copy_location(ast.Constant(INTS[node.value]),node)
            if type(node.value) is str and node.value in DATES|STRINGS:return ast.copy_location(ast.Constant((DATES|STRINGS)[node.value]),node)
            return node
    fn=Finite().visit(fn)
    if name=='boundary_relation':
        replacements={"term, = value['terms']":"terms = value['terms']",
            "doc['add'] == [term['added']]":"doc['add'] == [t['added'] for t in terms]",
            "doc['suppress'] == [dict(session=term['native_session'], security_id=data.SID, term_sha256=term['native_term_sha256'])]":"doc['suppress'] == [dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in terms]",
            "adoption(neutral, parent, data.sha(raw), term['native_session'])":"adoption(neutral,parent,data.sha(raw),min(t['native_session'] for t in terms))"}
        class Batch(ast.NodeTransformer):
            hits=set()
            def visit(self,node):
                before=ast.unparse(node)
                if before in replacements:
                    self.hits.add(before);target=ast.parse(replacements[before]).body[0] if isinstance(node,ast.stmt) else ast.parse(replacements[before],mode='eval').body
                    return ast.copy_location(target,node)
                return super().visit(node)
        change=Batch();fn=change.visit(fn);data.need(change.hits==set(replacements),'P03_14_EXACT_FOUR_ONE_TO_FOURTEEN_ORDINARY_BOUNDARY_SITES')
    return ast.fix_missing_locations(fn)
def namespace():
    ns=dict(globals());ns.update({name:globals()[name] for name in ('RAW_PROOF','SELECTED','PRIOR_REVIEW','VIEW_RECEIPT','VIEW_CLEANUP','BOUNDARY_REVIEW')})
    tree=ast.Module(body=[body_tree(name) for name in FUNCTIONS],type_ignores=[])
    exec(compile(tree,'<whole-original-THOR-lifecycle-finite524-17to18-70seed>','exec'),ns)
    return ns
