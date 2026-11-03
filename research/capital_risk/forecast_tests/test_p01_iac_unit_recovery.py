"""Actual context functions and frozen-module-shaped stubs; no Core execution."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

HERE=Path(__file__).parents[1]
sys.path.insert(0,str(HERE))
import p01_iac_unit_recovery_guard as guard
import p01_iac_unit_guard as frozen
import p01_iac_unit_recovery_run as run
from p01_iac_unit_contract import need,sha

CASE=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/research-capital-risk-20261027/system-optimization-002/p01-sequential-001')


def exact_files():
    def ext(p):return Path('\\\\?\\'+str(p.resolve())) if sys.platform=='win32' else p
    back=ext(CASE/'final-delivery-preparation-001/source-contracts/backtest.py.txt')
    adapter=ext(CASE/'native-resume-001/source-semantics-516/research__pooled_input_support__adapter.py.txt')
    return back,adapter


@pytest.fixture
def context(monkeypatch):
    back_path,adapter_path=exact_files()
    adapter=ModuleType('research.pooled_input_support.adapter');adapter.__file__=str(adapter_path)
    class Buffer:
        def prepare(self,*args,**kwargs):return ('ORIGINAL_PREPARE',args,kwargs)
    Buffer.prepare.__module__=adapter.__name__;Buffer.prepare.__qualname__='Buffer.prepare'
    adapter.Buffer=Buffer
    back=ModuleType('research.pooled_vacancy_funding.backtest');back.__file__=str(back_path);back.adapter=adapter
    originals=dict(advance=object(),relevant=object(),archive_checkpoint=object())
    runtime=SimpleNamespace(advance=originals['advance'])
    back.relevant=originals['relevant'];back.archive_checkpoint=originals['archive_checkpoint']
    funding=ModuleType('research.pooled_vacancy_funding');funding.backtest=back
    inputs=ModuleType('research.pooled_input_support');inputs.adapter=adapter
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',funding)
    monkeypatch.setitem(sys.modules,'research.pooled_input_support',inputs)
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    events=[]
    def enter(subject):
        events.append('base_enter');subject.backtest=back;subject.runtime=runtime
        subject.original_advance=runtime.advance;subject.original_relevant=back.relevant
        subject.original_archive=back.archive_checkpoint
        runtime.advance=subject.advance;back.relevant=subject.relevant;back.archive_checkpoint=subject.archive
        return subject
    def exit(subject,*args):
        events.append('base_exit');runtime.advance=subject.original_advance
        back.relevant=subject.original_relevant;back.archive_checkpoint=subject.original_archive
    monkeypatch.setattr(guard.ActionGuard,'__enter__',enter)
    monkeypatch.setattr(guard.ActionGuard,'__exit__',exit)
    subject=guard.UnitGuard.__new__(guard.UnitGuard)
    subject.contract={'source_files':{guard.ADAPTER:guard.ADAPTER_SHA}}
    subject.prepare=lambda buffer,*a,**k:('GUARDED',subject.original_prepare(buffer,*a,**k))
    return SimpleNamespace(subject=subject,adapter=adapter,back=back,runtime=runtime,events=events,
        original_prepare=Buffer.prepare,originals=originals,base_enter=enter,base_exit=exit)


def assert_restored(c):
    assert c.adapter.Buffer.prepare is c.original_prepare
    assert c.runtime.advance is c.originals['advance']
    assert c.back.relevant is c.originals['relevant']
    assert c.back.archive_checkpoint is c.originals['archive_checkpoint']


def test_exact_old_enter_reproduces_original_missing_buffer(context):
    c=context
    assert c.back.adapter is c.adapter and not hasattr(c.back,'Buffer')
    with pytest.raises(AttributeError,match='Buffer'):
        frozen.UnitGuard.__enter__(c.subject)
    assert c.events==['base_enter']
    # Cleanup of this deliberately failed old function is test-owned, not a
    # claim that its failed __enter__ automatically invoked __exit__.
    c.base_exit(c.subject)
    assert_restored(c)


def test_actual_new_enter_hooks_same_class_used_by_frozen_backtest(context):
    c=context
    with c.subject as entered:
        assert entered is c.subject and c.subject.buffer_class is c.back.adapter.Buffer is c.adapter.Buffer
        assert c.back.adapter.Buffer().prepare('synthetic',formation=True)==('GUARDED',('ORIGINAL_PREPARE',('synthetic',),{'formation':True}))
        assert c.subject.recovery_interface_proof['source_files'][guard.BACKTEST]==guard.BACKTEST_SHA
        assert not hasattr(c.back,'Buffer')
    assert_restored(c);assert c.events==['base_enter','base_exit']


def test_body_exception_restores_buffer_and_all_base_hooks(context):
    c=context
    with pytest.raises(RuntimeError,match='SYNTHETIC_BODY_FAILURE'):
        with c.subject:
            raise RuntimeError('SYNTHETIC_BODY_FAILURE')
    assert_restored(c)


def test_recovery_setup_failure_after_base_enter_restores_all_hooks(context,monkeypatch):
    c=context
    def changed(subject):
        c.base_enter(subject)
        c.adapter.Buffer.prepare=lambda *a,**k:'unexpected'
        return subject
    monkeypatch.setattr(guard.ActionGuard,'__enter__',changed)
    with pytest.raises(ValueError,match='CLASS_UNCHANGED_DURING_BASE_CONTEXT_SETUP'):
        c.subject.__enter__()
    assert_restored(c);assert c.events==['base_enter','base_exit']


def test_nested_or_preexisting_prepare_hook_refuses_before_base_entry(context):
    c=context;c.adapter.Buffer.prepare=lambda *a,**k:None
    with pytest.raises(ValueError,match='NOT_ALREADY_HOOKED'):c.subject.__enter__()
    assert c.events==[]


def test_wrong_adapter_alias_refuses_and_guard_removal_falsifier_detects_it(context):
    c=context
    c.back.adapter=SimpleNamespace(Buffer=type('DifferentBuffer',(),{}))
    with pytest.raises(ValueError,match='MODULE_AND_CLASS_IDENTITY'):
        guard.resolve_buffer(c.back,c.adapter,c.subject.contract)
    tree=ast.parse(Path(guard.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='resolve_buffer')
    removed=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,node):
            if any(isinstance(n,ast.Constant) and n.value=='RECOVERY_ACTUAL_ADAPTER_MODULE_AND_CLASS_IDENTITY' for n in ast.walk(node)):
                removed.append(node);return ast.copy_location(ast.Pass(),node)
            return self.generic_visit(node)
    fn=Remove().visit(fn);assert len(removed)==1
    ns=dict(vars(guard));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-class-identity>','exec'),ns)
    # The falsifier demonstrates precisely why full source bytes alone do not
    # establish the active imported module/class identity.
    assert ns['resolve_buffer'](c.back,c.adapter,c.subject.contract)[0] is not c.back.adapter.Buffer


@pytest.mark.parametrize('which',['backtest','adapter'])
def test_source_preimage_mutation_refuses_before_context(which):
    bp,ap=exact_files();back=bp.read_bytes();adapter=ap.read_bytes()
    if which=='backtest':back+=b'\n# changed\n'
    else:adapter+=b'\n# changed\n'
    with pytest.raises(ValueError,match='EXACT516'):guard.interface(back,adapter)


def test_exact_source_alias_and_run_backtest_constructor_proof():
    bp,ap=exact_files();proof=guard.interface(bp.read_bytes(),ap.read_bytes())
    assert proof['run_backtest_uses_adapter_buffer'] is True and proof['financial_source_changed'] is False
    assert len(proof['run_backtest_function_sha256'])==64 and len(proof['buffer_prepare_function_sha256'])==64


def test_runtime_wrapper_first_io_gate_precedes_old_run(monkeypatch):
    events=[]
    monkeypatch.setattr(run,'validate_worker_request',lambda path,*,mode:events.append(('gate',path.name,mode)))
    monkeypatch.setattr(run,'_body',lambda name:lambda args:events.append(('old_run',name,args.mode)))
    run.main(SimpleNamespace(mode='qualify',spec=Path('/out/spec.json')))
    assert events==[('gate',run.REQUEST,'qualify'),('old_run','main','qualify')]
    def refused(*a,**k):raise ValueError('SYNTHETIC_REQUEST_REFUSAL')
    monkeypatch.setattr(run,'validate_worker_request',refused);events.clear()
    with pytest.raises(ValueError,match='REQUEST_REFUSAL'):run.main(SimpleNamespace(mode='economic'))
    assert events==[]


def test_corrected_guard_is_actual_global_in_source_bound_frozen_branch():
    branch=run._body('branch')
    assert branch.__globals__['UnitGuard'] is guard.UnitGuard
    old=Path(HERE/'p01_iac_unit_run.py').read_bytes();assert sha(old)==run.SOURCE_SHA
    tree=ast.parse(old);original=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='branch')
    assert branch.__code__.co_names.count('UnitGuard')==1
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='UnitGuard' for n in ast.walk(original))


def test_economic_rewrites_only_exact_host_gate_import():
    economic=run._body('economic')
    assert 'p01_iac_unit_recovery_job' in economic.__code__.co_names
    assert 'p01_iac_unit_job' not in economic.__code__.co_names
    branch=run._body('branch')
    assert 'p01_iac_unit_recovery_job' not in branch.__code__.co_names


def test_runtime_static_public_entrypoint_never_imports_old_run_before_gate():
    tree=ast.parse(Path(run.__file__).read_bytes())
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and any(a.name=='p01_iac_unit_run' for a in n.names) for n in tree.body)
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    assert ast.unparse(main.body[0])=='validate_worker_request(HERE / REQUEST, mode=args.mode)'
