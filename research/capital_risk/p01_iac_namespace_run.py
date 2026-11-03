"""Preserve complete generator globals in the source-bound runtime factory."""
import argparse
import ast
import builtins
import contextlib
import dis
import inspect
from pathlib import Path
from types import CodeType

import p01_iac_reference_run as published
from p01_iac_unit_contract import need,sha

HERE=Path(__file__).parent
REQUEST='p01_iac_namespace_request.json'
PUBLISHED_SHA='f8ee2ec26b10ac26dce5644e5a00c5436b8a5b8af8f9f239abf9ac1020c8b55c'
BASE_SHA='20f2d5bf1758d0574954b2e2e6700b6ad20c22d433a73c46112cd08d4d6735c0'
FUNCTIONS=('prepare','exact_prefixes','boundaries','report','refusal_rows','last_attempt','branch','economic','main')


def _raw():
    raw=Path(published.__file__).read_bytes()
    need(sha(raw)==PUBLISHED_SHA,'NAMESPACE_EXACT_PUBLISHED509_RUNTIME')
    return raw


def namespace_origin(function,name):
    """Exactly the one declared contextmanager, or an ordinary function."""
    need(name in FUNCTIONS and inspect.isfunction(function),'NAMESPACE_ONE_DECLARED_GENERATED_FUNCTION')
    import p01_iac_unit_run as base
    raw=Path(base.__file__).read_bytes();need(sha(raw)==BASE_SHA,'NAMESPACE_EXACT_BASE_DECORATED_FUNCTION_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    if name!='boundaries':
        need(node.decorator_list==[] and not hasattr(function,'__wrapped__') and not inspect.isgeneratorfunction(function),
             'NAMESPACE_ORDINARY_FUNCTION_HAS_NO_UNDECLARED_WRAPPER')
        return function
    need(len(node.decorator_list)==1 and ast.unparse(node.decorator_list[0])=='contextmanager',
         'NAMESPACE_EXACT_ONE_CONTEXTMANAGER_DECORATOR')
    generator=getattr(function,'__wrapped__',None)
    need(inspect.isfunction(generator) and inspect.isgeneratorfunction(generator)
         and generator.__name__==generator.__code__.co_name=='boundaries'
         and not hasattr(generator,'__wrapped__') and generator.__closure__ is None
         and tuple(inspect.signature(generator).parameters)==('old','out','binding','rows')
         and inspect.signature(generator)==inspect.signature(base.boundaries),
         'NAMESPACE_EXACT_UNWRAPPED_BOUNDARIES_GENERATOR_AND_SIGNATURE')
    closure=function.__closure__
    need(function.__code__ is contextlib.contextmanager(generator).__code__
         and closure is not None and len(closure)==1 and closure[0].cell_contents is generator,
         'NAMESPACE_STANDARD_CONTEXTLIB_WRAPPER_CLOSURE_IS_DECLARED_GENERATOR')
    return generator


def available_globals(function,name):
    origin=namespace_origin(function,name);namespace=origin.__globals__
    builtin=namespace.get('__builtins__',builtins)
    builtin=builtin if isinstance(builtin,dict) else vars(builtin)
    missing=set()
    def scan(code):
        for item in dis.get_instructions(code):
            if item.opname=='LOAD_GLOBAL' and item.argval not in namespace and item.argval not in builtin:
                missing.add(item.argval)
        for item in code.co_consts:
            if isinstance(item,CodeType):scan(item)
    scan(origin.__code__)
    need(not missing,'NAMESPACE_COMPLETE_RECURSIVE_LOAD_GLOBAL_BINDINGS')
    return dict(function=name,underlying_generator=name=='boundaries',missing_globals=[])


def _namespace():
    return dict(vars(published),**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)


def _body(name):
    raw=_raw();node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_body']
    node.name='_namespace_factory';changes=[]
    class Scope(ast.NodeTransformer):
        def visit_Attribute(self,item):
            if ast.unparse(item)=='frozen.__globals__':
                changes.append('underlying_namespace')
                return ast.copy_location(ast.parse('namespace_origin(frozen,name).__globals__',mode='eval').body,item)
            return self.generic_visit(item)
        def visit_Constant(self,item):
            if item.value=='p01_iac_reference_job':
                changes.append('new_host_gate');item.value='p01_iac_namespace_job'
            elif item.value=='p01_iac_reference_review':
                changes.append('new_review');item.value='p01_iac_namespace_review'
            return item
    node=Scope().visit(node)
    need(changes==['new_host_gate','new_review','underlying_namespace'],
         'NAMESPACE_ONLY_ONE_NAMESPACE_CHOICE_AND_TWO_METADATA_IMPORT_TARGETS')
    values=_namespace()
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-one-generator-namespace-factory>','exec'),values)
    result=values['_namespace_factory'](name);available_globals(result,name);return result


def _entry(name):
    need(name in ('qualify','branch'),'NAMESPACE_ONLY_TWO_UNCHANGED_ENTRY_WRAPPERS')
    node,=[n for n in ast.parse(_raw()).body if isinstance(n,ast.FunctionDef) and n.name==name]
    need(node.decorator_list==[],'NAMESPACE_UNCHANGED_ENTRY_HAS_NO_DECORATOR')
    values=_namespace()
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<source-bound-namespace-entry:'+name+'>','exec'),values)
    return values[name]


def prepare(*a,**k):return _body('prepare')(*a,**k)
def exact_prefixes(*a,**k):return _body('exact_prefixes')(*a,**k)
def boundaries(*a,**k):return _body('boundaries')(*a,**k)
def report(*a,**k):return _body('report')(*a,**k)
def refusal_rows(*a,**k):return _body('refusal_rows')(*a,**k)
def last_attempt(*a,**k):return _body('last_attempt')(*a,**k)
def branch(*a,**k):return _entry('branch')(*a,**k)
def qualify(*a,**k):return _entry('qualify')(*a,**k)
def economic(*a,**k):return _body('economic')(*a,**k)


def validate_worker_request(path,*,mode):
    from p01_iac_namespace_job import validate_worker_request as validate
    need(Path(path)==HERE/REQUEST,'NAMESPACE_FIXED_NEW_WHOLE_REQUEST_FIRST_IO')
    return validate(path,mode=mode)


def main(args):
    validate_worker_request(HERE/REQUEST,mode=args.mode)
    return _body('main')(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True);main(parser.parse_args())
