"""Frozen scope and source-bound adapters for eight diagnostic forks only."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_discovery_context import TAINT

HERE=Path(__file__).resolve().parent
ARMS=('P03','P04','P05','P06','P07','P09','P10','P11')
PARENTS='system-campaign-parallel-discovery-parents.json'
REQUEST='system-campaign-parallel-discovery-request-001.json'
PRIOR='system-campaign-p01-discovery-suffix-request-001.json'
PRIOR_SHA='c0ad97cf14eb505bf720b299124c4d15a6f2cbdd02e9609172852782d469b7f0'


def exact_raw(filename):
    old=(HERE/PRIOR).read_bytes()
    need(hashlib.sha256(old).hexdigest()==PRIOR_SHA,'PARALLEL_EXACT_PRIOR375_REQUEST')
    raw=(HERE/filename).read_bytes()
    need(hashlib.sha256(raw).hexdigest()==json.loads(old)['sources'][filename],
         'PARALLEL_ALL_ADOPTED_SOURCE_BYTES_UNCHANGED')
    return raw


def body(filename,name):
    fn,=[n for n in ast.parse(exact_raw(filename)).body if isinstance(n,ast.FunctionDef) and n.name==name]
    return deepcopy(fn)


def compile_body(fn,namespace):
    scope=dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<exact-source-bound-parallel-diagnostic-adapter>','exec'),scope)
    return scope[fn.name]


def literals(fn,replacements,counts=None):
    seen={k:0 for k in replacements}
    class Sites(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) in (str,int) and node.value in replacements:
                seen[node.value]+=1
                return ast.copy_location(ast.Constant(replacements[node.value]),node)
            return node
    fn=Sites().visit(fn)
    need(seen==(counts or {k:1 for k in replacements}),'PARALLEL_ONLY_DECLARED_LITERAL_SITES')
    return fn


def specification(arm):
    need(arm in ARMS,'PARALLEL_ONLY_OWNER_SELECTED_UNFINISHED_ARMS')
    raw=(HERE/PARENTS).read_bytes();index=json.loads(raw)
    need(index['schema']=='research.parallel-discovery-strict-parents/1'
         and set(index['arms'])==set(ARMS) and index['financial_authority'] is False
         and index['production_contacted'] is False,'PARALLEL_EXACT_DIAGNOSTIC_PARENT_INDEX')
    spec=index['arms'][arm]
    need(spec['arm']==arm and 0<spec['measured_closes']<2156
         and spec['expected_remaining_sessions']==2156-spec['measured_closes']
         and spec['financial_authority'] is False,'PARALLEL_OWN_UNFINISHED_MEASURED_PARENT')
    return spec


def check_parent(parent,spec):
    need(parent['sha256']==spec['outer_sha256'] and parent['source_cursor']==spec['selected_session']
         and parent['completed']==spec['measured_closes'] and parent['base']==spec['base']
         and parent['journals']==spec['journals'] and parent['repairs']==spec['repairs']
         and parent['run']['checkpoint_sha256']==spec['inner_sha256']
         and parent['run']['state_sha256']==spec['state_sha256']
         and parent['run']['input_sha256']==spec['input_sha256'],
         'PARALLEL_EXACT_OWN_STRICT_PARENT_NOT_TAIL_OR_OTHER_CANDIDATE')


def reference(spec):
    return dict(schema='research.parallel-discovery-parent-reference/1',authority=TAINT,
        arm=spec['arm'],run_id=spec['run_id'],head=spec['head'],artifact_id=spec['artifact_id'],
        selected_checkpoint=spec['selected_checkpoint'],selected_file=spec['selected_file'],
        outer_sha256=spec['outer_sha256'],inner_sha256=spec['inner_sha256'],
        input_sha256=spec['input_sha256'],state_sha256=spec['state_sha256'],
        original_source_binding_sha256=spec['source_binding_sha256'],prior_status=spec['prior_status'],
        prior_worker=spec['prior_worker'],prior_account_performance_certified=False,
        financial_authority=False,production_contacted=False)
