"""Fresh own628 recovery; exact frozen unit run with corrected Buffer context."""
import argparse
import ast
from pathlib import Path

from p01_iac_unit_contract import need, sha
from p01_iac_unit_recovery_guard import UnitGuard

HERE = Path(__file__).parent
REQUEST = 'p01_iac_unit_recovery_request.json'
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
                item.module = 'p01_iac_unit_recovery_job'; changes.append('economic_host_gate')
            return item
    node = Scope().visit(node)
    need(changes == (['economic_host_gate'] if name == 'economic' else []),
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
def qualify(*a,**k): return _body('qualify')(*a,**k)
def economic(*a,**k): return _body('economic')(*a,**k)


def validate_worker_request(path, *, mode):
    """Metadata-only, first-I/O gate for the flattened read-only driver mount."""
    from p01_iac_unit_recovery_job import validate_worker_request as validate
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
