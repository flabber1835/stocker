"""Hosted stopped-evidence review; metadata before one exclusive report save."""
import ast
from pathlib import Path

import p01_iac_unit_fixture_review as previous
from p01_iac_unit_contract import need,sha

FIXTURE_REVIEW_SHA='d7772c3592d24d07e2b419185265ec16709662a17c315523e27dc3fdd91dedaa'
ORIGINAL_REVIEW_SHA='3e2782792ad3baaefbe481dabd047269771cce89f9fe1e8fcc74f9c7d27f4a2a'
PUBLISHED_REQUEST_SHA='fd2ff79b00472f482e53df2b411cdeec5c999e27529be287bcfc6f9c914216a7'


def _node(name):
    need(name in ('review','review_loaded'),'STOPPED_REVIEW_ONLY_TWO_EXISTING_REVIEW_FUNCTIONS')
    need(sha(Path(previous.__file__).read_bytes())==FIXTURE_REVIEW_SHA
         and sha(Path(previous.previous.__file__).read_bytes())==ORIGINAL_REVIEW_SHA,
         'STOPPED_REVIEW_EXACT_PUBLISHED497_AND_ORIGINAL_VALIDATOR_BYTES')
    node=previous._node(name);changes=[]
    class Save(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            if item.module=='full_system_benchmark' and [(n.name,n.asname) for n in item.names]==[('save',None)]:
                need(name=='review_loaded','STOPPED_REVIEW_SAVE_IMPORT_ONLY_IN_LOADED_REVIEW')
                item.module='p01_iac_unit_review_recovery_adapter';item.names=[ast.alias(name='save_review',asname='save')]
                changes.append('single_save')
            return item
    node=Save().visit(node)
    need(changes==(['single_save'] if name=='review_loaded' else []),'STOPPED_REVIEW_ONE_EXACT_LOCAL_SAVE_IMPORT')
    return node


def _body(name):
    node=_node(name)
    values=dict(previous._body(name).__globals__)
    values.update(review=review,review_loaded=review_loaded,__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<source-bound-stopped-review-single-save:'+name+'>','exec'),values)
    return values[name]


def save_review(path,result):
    """The old callsite supplies its actual final result before first create."""
    path=Path(path)
    need(path.name=='iac-unit-financial-review.json' and type(result) is dict
         and result.get('schema')=='research.p01-iac-unit-suffix-review/1'
         and result.get('status')=='IAC_UNIT_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT'
         and result.get('financial_predecessor_admitted') is False
         and result.get('qualification_state_adopted') is False
         and 'fixture_review' not in result and 'review_recovery' not in result,
         'STOPPED_REVIEW_ACTUAL_EXISTING_RESULT_BEFORE_SINGLE_CREATE')
    result['fixture_review']=dict(schema='research.p01-iac-unit-fixture-review-binding/1',
        old_review_sha256=ORIGINAL_REVIEW_SHA,fixture_review_sha256=FIXTURE_REVIEW_SHA,cases=list(previous.CASE_IDS),
        full_feed_projection_checked=True,actual_reference_boundary_checked=True,old_financial_arithmetic_unchanged=True)
    result['review_recovery']=dict(schema='research.p01-iac-unit-single-save-review-binding/1',
        adapter_source_sha256=sha(Path(__file__).read_bytes()),published_request_sha256=PUBLISHED_REQUEST_SHA,
        published_fixture_reviewer_sha256=FIXTURE_REVIEW_SHA,original_reviewer_sha256=ORIGINAL_REVIEW_SHA,
        correction='METADATA_BEFORE_ORIGINAL_SINGLE_EXCLUSIVE_CREATE',financial_sessions_advanced=0,
        qualification_state_adopted=False,financial_predecessor_admitted=False)
    from full_system_benchmark import save
    return save(path,result)


def review(*a,**k):return _body('review')(*a,**k)
def review_loaded(*a,**k):return _body('review_loaded')(*a,**k)
main=review
