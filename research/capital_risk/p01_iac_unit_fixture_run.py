"""Own628 complete-fixture qualification; original financial runtime preserved."""
import argparse
import ast
from pathlib import Path

from p01_iac_unit_contract import need, sha
from p01_iac_unit_recovery_guard import UnitGuard
from p01_iac_unit_fixture_component import qualify_components,CASE_IDS

HERE = Path(__file__).parent
REQUEST = 'p01_iac_unit_fixture_request.json'
SOURCE_SHA = '20f2d5bf1758d0574954b2e2e6700b6ad20c22d433a73c46112cd08d4d6735c0'
FUNCTIONS = ('prepare','exact_prefixes','boundaries','report','refusal_rows','last_attempt',
             'branch','qualify','economic','main')


def _body(name):
    need(name in FUNCTIONS, 'RECOVERY_EXPLICIT_FROZEN_RUNTIME_FUNCTION')
    import p01_iac_unit_run as previous
    raw = Path(previous.__file__).read_bytes()
    need(sha(raw) == SOURCE_SHA, 'RECOVERY_EXACT_FROZEN_UNIT_RUNTIME')
    node, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == name]
    changes = []
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self, item):
            if item.module == 'p01_iac_unit_job':
                need(name == 'economic' and [(n.name,n.asname) for n in item.names]
                     == [('check_qualification',None),('expected_request',None)],
                     'RECOVERY_ONE_EXACT_ECONOMIC_HOST_GATE_IMPORT')
                item.module = 'p01_iac_unit_fixture_job'; changes.append('economic_host_gate')
            if item.module == 'p01_iac_unit_review':
                need(name=='main' and [(n.name,n.asname) for n in item.names]==[('review',None)],
                     'FIXTURE_ONE_EXACT_HOSTED_REVIEW_IMPORT')
                item.module='p01_iac_unit_fixture_review';changes.append('fixture_review')
            return item
        def visit_Call(self,item):
            item=self.generic_visit(item)
            if isinstance(item.func,ast.Name) and item.func.id=='qualify_components':
                need(name=='branch' and [k.arg for k in item.keywords]==['post_event_state'],
                     'FIXTURE_ONE_EXACT_REFERENCE_COMPONENT_CALLSITE')
                item.keywords.extend(ast.parse('f(reference_components=guard.components,qualifier_checkpoint=final,input_zero_checkpoint=zero["input_checkpoint"])').body[0].value.keywords)
                changes.append('durable_reference_path')
            return item
    node = Scope().visit(node)
    need(changes == ({'economic':['economic_host_gate'],'main':['fixture_review'],'branch':['durable_reference_path']}.get(name,[])),
         'RECOVERY_ONLY_DECLARED_RUNTIME_IMPORT_SITE')
    namespace = dict(vars(previous), **{k:v for k,v in globals().items() if not k.startswith('__')}, __file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<source-bound-recovery-runtime:'+name+'>','exec'), namespace)
    return namespace[name]


def prepare(*a,**k): return _body('prepare')(*a,**k)
def exact_prefixes(*a,**k): return _body('exact_prefixes')(*a,**k)
def boundaries(*a,**k): return _body('boundaries')(*a,**k)
def report(*a,**k): return _body('report')(*a,**k)
def refusal_rows(*a,**k): return _body('refusal_rows')(*a,**k)
def last_attempt(*a,**k): return _body('last_attempt')(*a,**k)
def branch(*a,**k): return _body('branch')(*a,**k)
def save(path,value):
    from full_system_benchmark import save as original
    path=Path(path)
    if path.name!='qualification-summary.json':return original(path,value)
    import gzip,json
    raw=(path.parent/'unit-normalization-component.json.gz').read_bytes()
    component=json.loads(gzip.decompress(raw));aggregate=component['fixture_aggregate']
    need(component['schema']=='research.p01-iac-unit-synthetic-canonical-component/2'
         and aggregate['expected_case_ids']==aggregate['attempted_case_ids']==aggregate['passed_case_ids']==list(CASE_IDS)
         and aggregate['complete'] is True and aggregate['all_passed'] is True and aggregate['failed_cases']==[],
         'FIXTURE_ALL_NINE_ACTUAL_CANONICAL_CASES_BEFORE_SUCCESS_SUMMARY')
    summary=dict(value)
    summary.update(fixture_aggregate_complete=True,fixture_aggregate_all_passed=True,fixture_expected_case_count=len(CASE_IDS),
        fixture_attempted_case_count=len(aggregate['attempted_case_ids']),fixture_passed_case_count=len(aggregate['passed_case_ids']),
        fixture_failed_case_count=len(aggregate['failed_cases']),fixture_expected_case_ids=list(CASE_IDS),fixture_component_sha256=sha(raw))
    return original(path,summary)


def qualify(*a,**k):return _body('qualify')(*a,**k)
def economic(*a,**k): return _body('economic')(*a,**k)


def validate_worker_request(path, *, mode):
    """Metadata-only, first-I/O gate for the flattened read-only driver mount."""
    from p01_iac_unit_fixture_job import validate_worker_request as validate
    path = Path(path)
    need(path == HERE / REQUEST, 'RECOVERY_EXACT_MOUNTED_REQUEST_PATH')
    return validate(path, mode=mode)


def main(args):
    validate_worker_request(HERE / REQUEST, mode=args.mode)
    return _body('main')(args)


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--mode', choices=('qualify','economic','review'), required=True)
    p.add_argument('--spec', type=Path, required=True)
    main(p.parse_args())
