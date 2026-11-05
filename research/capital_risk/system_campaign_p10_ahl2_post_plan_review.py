"""New raw-request identity; all frozen diagnostic carrier/prefix checks retained."""
import ast
from pathlib import Path

from system_campaign_p10_ahl2_contract import need
from system_campaign_p10_ahl2_context import frozen_namespace
from system_campaign_p10_ahl2_post_plan import REQUEST, retained_specification
from system_campaign_p10_ahl2_post_plan_gate import qualification_valid, compare_paths, records
from system_campaign_p10_ahl2_post_plan_parent import validate_retained
from system_campaign_p10_ahl2_post_plan_observe import source_shape, sensor_record_valid


def review_namespace():
    _,nodes,scope = frozen_namespace('system_campaign_p10_ahl2_review.py',('review',))
    fn, = nodes
    literals = {'system-campaign-p10-ahl2-request-001.json':REQUEST,
                'research.p10-own-ahl2-diagnostic-review/1':'research.p10-own-post-plan-diagnostic-review/1'}
    counts = dict.fromkeys(literals,0)
    for node in ast.walk(fn):
        if isinstance(node,ast.Constant) and type(node.value) is str and node.value in literals:
            counts[node.value] += 1;node.value = literals[node.value]
    need(all(n == 1 for n in counts.values()), 'P10_POST_PLAN_REVIEW_EXACT_RAW_REQUEST_AND_SCHEMA_SITES')
    scope['qualification_valid'] = qualification_valid
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<p10-post-plan-same-stopped-review-new-raw-request>','exec'),scope)
    return scope


def review(spec,out,evidence,*,root=Path('/old'),previous=Path('/previous/own1'),source_root=Path('/variant')):
    from full_system_core import hosted
    hosted()
    evidence = Path(evidence)
    retained = evidence/'retained-qualification'
    validate_retained(retained/'retained-parent-evidence',spec)
    fast,reference = records(retained/'fast'),records(retained/'reference')
    compare_paths(fast,reference)
    sensor_record_valid(fast[-1],source_shape((Path(source_root)/'sentinel/core/kernel.py').read_bytes()))
    # The original reader restores only current/new stopped suffix CPs, reuses
    # original OWN1 admission, compares the complete fresh changed path and
    # verifies all full prefixes and tails. No old control forward replay.
    return review_namespace()['review'](spec,out,evidence,root=root,previous=previous,source_root=source_root)
