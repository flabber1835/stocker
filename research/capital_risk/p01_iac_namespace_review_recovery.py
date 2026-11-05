"""Review stopped515 evidence with the exact published restore-label order."""
import ast
from copy import deepcopy
from pathlib import Path

import p01_iac_namespace_review as previous
from p01_iac_unit_contract import need,sha

NAMESPACE_SHA='7273139c74f3bbb9d12cc7830a34868cdb1422607d84c6143754997d674a8505'
REFERENCE_SHA='9a047c86526c3b147d41490733c4d962c44250a4ebc15b5cd81e9075f8411cdd'
PRODUCER_CHECKER_SHA='3e2782792ad3baaefbe481dabd047269771cce89f9fe1e8fcc74f9c7d27f4a2a'
REQUEST_SHA='9068e16677950f58dcf3055bc5b7cbee39f898115bfab2587478bbad96e8b230'


def _raw():
    need(sha(Path(previous.__file__).read_bytes())==NAMESPACE_SHA
         and sha(Path(previous.published.__file__).read_bytes())==REFERENCE_SHA,
         'RESTORE_ORDER_EXACT_PUBLISHED515_AND_REFERENCE_REVIEW_BYTES')
    return Path(previous.published.__file__).read_bytes()


def producer_wires(component):
    """Mirror the source-pinned checker, including decoded dictionary order."""
    import p01_iac_unit_review as checker
    raw=Path(checker.__file__).read_bytes()
    need(sha(raw)==PRODUCER_CHECKER_SHA,'RESTORE_ORDER_EXACT_PRODUCER_CHECKER')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='synthetic_component']
    loop,=[n for n in node.body if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple)]
    need(ast.unparse(loop.target)=='(name, row)' and ast.unparse(loop.iter)=="value['target_cases'].items()"
         and [ast.unparse(n) for n in loop.body[:3]]==["sid, role = name.split('/')","before = row['before']","after = row['actual']"]
         and ast.unparse(loop.body[-1])=='wires.extend((before, after))',
         'RESTORE_ORDER_EXACT_PRODUCER_TARGET_ITERATION_AND_APPEND')
    wires=[]
    for name,row in component['target_cases'].items():
        wires.extend((row['before'],row['actual']))
    post=component['post_event_new_unit_case']
    wires.extend((post['before'],post['after']))
    return wires


def _metadata_node(name):
    need(name in ('validate_reuse','save_review'),'RESTORE_ORDER_ONLY_TWO_METADATA_FUNCTIONS')
    node,=[n for n in ast.parse(_raw()).body if isinstance(n,ast.FunctionDef) and n.name==name]
    changes=[]
    class Scope(ast.NodeTransformer):
        def visit_Constant(self,item):
            if item.value=='p01_iac_reference_request.json':
                need(name=='validate_reuse','RESTORE_ORDER_OLD_NAMESPACE_REQUEST_LITERAL')
                item.value=previous.REQUEST;changes.append('namespace_request')
            return item
        def visit_For(self,item):
            if name=='validate_reuse' and ast.unparse(item.target)=='case':
                expected=ast.parse("for case in component['fixture_aggregate']['expected_case_ids']:\n row=component['post_event_new_unit_case'] if case=='POST_EVENT_SOURCE_BUY' else component['target_cases'][case]\n wires.extend((row['before'],row['after'] if case=='POST_EVENT_SOURCE_BUY' else row['actual']))").body[0]
                need(ast.dump(item,include_attributes=False)==ast.dump(expected,include_attributes=False),
                     'RESTORE_ORDER_ONE_EXACT_AFFECTED_CONSUMER_COLLECTOR')
                changes.append('producer_order')
                return ast.parse('wires=producer_wires(component)').body[0]
            return self.generic_visit(item)
    node=Scope().visit(node)
    need(changes==(['namespace_request','producer_order'] if name=='validate_reuse' else []),
         'RESTORE_ORDER_ONLY_NAMESPACE_LITERAL_AND_AFFECTED_WIRE_COLLECTOR')
    return node


def _metadata(name):
    node=_metadata_node(name)
    values=previous._metadata(name).__globals__.copy()
    values.update(producer_wires=producer_wires,validate_reuse=validate_reuse,__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-ordered-restore-review-metadata:'+name+'>','exec'),values)
    return values[name]


def _node(name):
    _raw();node=previous._node(name);changes=[]
    class Save(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            if item.module=='p01_iac_namespace_review':
                need(name=='review_loaded' and [(n.name,n.asname) for n in item.names]==[('save_review','save')],
                     'RESTORE_ORDER_ONE_EXISTING_SINGLE_SAVE_IMPORT')
                item.module='p01_iac_namespace_review_recovery';changes.append('single_save')
            return item
    node=Save().visit(node)
    need(changes==(['single_save'] if name=='review_loaded' else []),'RESTORE_ORDER_ONLY_SINGLE_SAVE_METADATA_TARGET')
    return node


def _body(name):
    node=_node(name);values=previous._body(name).__globals__.copy()
    values.update(review=review,review_loaded=review_loaded,__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-ordered-restore-financial-review:'+name+'>','exec'),values)
    return values[name]


def validate_reuse(*a,**k):return _metadata('validate_reuse')(*a,**k)


def save_review(path,result):
    need(type(result) is dict and 'restore_label_order_review' not in result,
         'RESTORE_ORDER_NEW_BINDING_BEFORE_ONE_EXCLUSIVE_SAVE')
    result['restore_label_order_review']=dict(schema='research.p01-ordered-restore-review-recovery/1',
        adapter_source_sha256=sha(Path(__file__).read_bytes()),published_namespace_review_sha256=NAMESPACE_SHA,
        published_reference_review_sha256=REFERENCE_SHA,producer_checker_sha256=PRODUCER_CHECKER_SHA,
        original_request_sha256=REQUEST_SHA,wire_order='TARGET_CASES_ITEMS_BEFORE_ACTUAL_THEN_POST_BEFORE_AFTER',
        ordered_restore_records=25,financial_sessions_advanced=0,qualification_state_adopted=False,
        financial_predecessor_admitted=False)
    return _metadata('save_review')(path,result)


def review(*a,**k):return _body('review')(*a,**k)
def review_loaded(*a,**k):return _body('review_loaded')(*a,**k)
main=review
