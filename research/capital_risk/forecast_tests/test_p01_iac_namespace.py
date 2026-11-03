"""Metadata factories and synthetic reports only; no canonical execution."""
import ast
import contextlib
import inspect
from pathlib import Path
import subprocess
import sys
import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_namespace_run as runtime
import p01_iac_namespace_review as review


@pytest.mark.parametrize('name',runtime.FUNCTIONS)
def test_all_actual_factories_preserve_complete_underlying_global_scope(name):
    result=runtime._body(name)
    assert runtime.available_globals(result,name)['missing_globals']==[]
    if name=='boundaries':
        prior=runtime.published.previous._body(name)
        before=runtime.namespace_origin(prior,name).__globals__
        after=runtime.namespace_origin(result,name).__globals__
        seven=('EVENT','EpochPause','InputCodec','PauseAfterAdoption','adoption','arguments','document')
        assert all(after[n] is before[n] for n in seven)
        assert inspect.signature(result)==inspect.signature(prior)


def test_all_runtime_review_and_entry_factories_under_financial_import_fence():
    script=r'''
import sys,importlib.abc
class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='sentinel' or fullname.startswith(('sentinel.','stock_strategy_shared','research.pooled_','research.bounded_')):
            raise AssertionError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
sys.meta_path.insert(0,Fence())
import p01_iac_namespace_run as runtime
import p01_iac_namespace_review as review
for name in runtime.FUNCTIONS:assert runtime.available_globals(runtime._body(name),name)['missing_globals']==[]
for name in ('qualify','branch'):assert runtime._entry(name).__name__==name
for name in ('review','review_loaded'):assert review._body(name).__name__==name
for name in ('validate_reuse','save_review'):assert review._metadata(name).__name__==name
print('FENCED_REAL_FACTORIES_15_PASS')
'''
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=HERE,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='FENCED_REAL_FACTORIES_15_PASS'


@pytest.mark.parametrize('kind',['default','keyword_only','double_wrapper'])
def test_namespace_guard_refuses_other_generator_shapes(kind):
    code={'default':'def boundaries(old,out,binding,rows=None):\n yield None',
        'keyword_only':'def boundaries(old,out,binding,*,rows):\n yield None',
        'double_wrapper':'def boundaries(old,out,binding,rows):\n yield None'}[kind]
    namespace={};exec(code,namespace);generator=namespace['boundaries']
    if kind=='double_wrapper':generator.__wrapped__=lambda:None
    with pytest.raises(ValueError):runtime.namespace_origin(contextlib.contextmanager(generator),'boundaries')


def test_normal_functions_cannot_acquire_a_fallback_wrapper():
    function=runtime.published.previous._body('prepare');function.__wrapped__=lambda:None
    with pytest.raises(ValueError):runtime.namespace_origin(function,'prepare')


def test_actual_missing_global_is_refused_before_lazy_entry():
    function=runtime._body('boundaries');origin=runtime.namespace_origin(function,'boundaries')
    del origin.__globals__['arguments']
    with pytest.raises(ValueError,match='COMPLETE_RECURSIVE'):runtime.available_globals(function,'boundaries')


def test_review_financial_ast_reversal_only_two_metadata_imports():
    for name in ('review','review_loaded'):
        node=review._node(name)
        class Reverse(ast.NodeTransformer):
            def visit_ImportFrom(self,item):
                if item.module=='p01_iac_namespace_review':item.module='p01_iac_reference_review'
                if item.module=='p01_iac_namespace_export':item.module='p01_iac_reference_export'
                return item
        assert ast.dump(Reverse().visit(node),include_attributes=False)==ast.dump(review.published._node(name),include_attributes=False)
    actual=review._metadata('validate_reuse')
    assert review.REQUEST in actual.__code__.co_consts
    assert 'p01_iac_reference_request.json' not in actual.__code__.co_consts


def test_actual_current_request_save_metadata_then_one_exclusive_create(tmp_path):
    function=review._metadata('save_review')
    function.__globals__['validate_reuse']=lambda evidence:{'synthetic_only':True}
    result=dict(schema='research.p01-iac-unit-suffix-review/1',status='IAC_UNIT_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',
        financial_predecessor_admitted=False,qualification_state_adopted=False)
    path=tmp_path/'iac-unit-financial-review.json';function(path,result)
    assert path.is_file() and result['reference_reuse_review']=={'synthetic_only':True}
    assert result['review_recovery']['correction']=='METADATA_BEFORE_ORIGINAL_SINGLE_EXCLUSIVE_CREATE'
    with pytest.raises(ValueError):function(path,result)


def test_entry_wrapper_routes_to_actual_new_factory_without_mutating_published_module():
    original=runtime.published._body
    for name in ('qualify','branch'):
        function=runtime._entry(name)
        assert function.__globals__['_body'] is runtime._body
        assert function.__globals__['branch'] is (runtime.branch if name=='qualify' else function)
    assert runtime.published._body is original
