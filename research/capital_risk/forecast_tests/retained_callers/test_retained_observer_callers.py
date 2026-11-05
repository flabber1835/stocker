"""Exact original observer methods and synthetic canonical caller frames only."""
import ast,builtins
from contextlib import contextmanager,nullcontext
from copy import deepcopy
from dataclasses import asdict,make_dataclass
import hashlib,importlib.abc,inspect,json
from pathlib import Path
import sys
from types import CodeType,SimpleNamespace
import pytest

C=Path(__file__).resolve().parents[2]
if not(C/'system_campaign_financial_compound_dispatch.py').exists():C=C.parent
FIXTURE=Path(__file__).parent/'fixtures/P07-VCRA-caller-refusal.json'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def need(v,c):
    if not v:raise ValueError(c)
def tree(name):return ast.parse((C/name).read_bytes())
def execute(nodes,namespace):
    imports=ast.parse('import inspect').body if Path(namespace.get('__file__','')).name!='system_campaign_financial_ordinary_observer_v1.py' else []
    exec(compile(ast.fix_missing_locations(ast.Module(body=imports+nodes,type_ignores=[])),'<exact-source-observer-AST-synthetic-API>','exec'),namespace)
    return namespace
class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise AssertionError('NO_CANONICAL_FINANCE_IMPORT:'+fullname)
@pytest.fixture(autouse=True)
def fenced():
    guard=Fence();sys.meta_path.insert(0,guard);yield;sys.meta_path.remove(guard)

def setup(tmp_path):
    raw_fixture=FIXTURE.read_bytes();assert sha(raw_fixture)=='83e433c1394994bea22784e10e47220481bb2625abe25fec4fc989de22d9e993'
    f=json.loads(raw_fixture)
    assert sha((C/'system_campaign_financial_ordinary_observer_v1.py').read_bytes())==f['original_observer_sha256']=='a09361056879e891d831daec06686895a6cbb20dca0b1a0a9cded8dae1c650a3'
    assert sha(ast.dump(next(n for n in tree('system_campaign_financial_future.py').body if isinstance(n,ast.ClassDef)and n.name=='ActualEvents'),include_attributes=False).encode())==f['current_observer_class_AST_sha256']
    assert f['actual_refusal']['cash'][0]['actual_context_call']is False and f['actual_refusal']['cash'][0]['postcondition']['quantity']==41
    Term=make_dataclass('InputTerminal',[(k,object)for k in f['retained_term']])
    term=Term(**f['retained_term']);calls=[];output=[]
    class SyntheticData:
        def to_dict(self):return dict(test_only='unchanged primitive snapshot')
    state=SyntheticData();ledger=SyntheticData()
    def primitive(actual_state,actual_term,**kwargs):
        calls.append((actual_state,actual_term,kwargs));return dict(test_only_original_delegate=True)
    terminal=SimpleNamespace(apply_terminal=primitive)
    def step_session(state,ledger,session,terms,callback=None):
        pending=[]
        fn=terminal.apply_terminal if callback is None else callback
        fn(state,terms,ledger=ledger,phase='OPEN')
        return SimpleNamespace(state=SimpleNamespace(pending=[]))
    adapter=SimpleNamespace(step_session=step_session)
    def advance(run,published):return adapter.step_session(run.state,run.ledger,published.session,published.term,getattr(published,'callback',None))
    runtime=SimpleNamespace(advance=advance)
    shadow=tmp_path/'source-qualified-input';shadow.mkdir()
    for filename in('system_campaign_financial_future.py','system_campaign_financial_ordinary_observer_v1.py'):
        (shadow/filename).write_bytes((C/filename).read_bytes())
    (shadow/'system-campaign-factual-request.json').write_text(json.dumps(dict(sources={'system_campaign_financial_future.py':sha((shadow/'system_campaign_financial_future.py').read_bytes())})))
    future=SimpleNamespace(__file__=str(shadow/'system_campaign_financial_future.py'))
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='research.pooled_vacancy_funding':return SimpleNamespace(runtime=runtime)
        if name=='stock_strategy_shared.wealth_core':return SimpleNamespace(terminal=terminal,adapter=adapter)
        if name=='system_campaign_financial_future':return future
        return builtins.__import__(name,globals,locals,fromlist,level)
    base=dict(__builtins__=dict(vars(builtins),__import__=imports),contextmanager=contextmanager,
        Path=Path,json=json,ast=ast,inspect=inspect,CodeType=CodeType,need=need,sha=sha,digest=digest,
        deepcopy=deepcopy,asdict=asdict,hosted=lambda:None,save=lambda path,value:output.append((Path(path),deepcopy(value))))
    def observer(filename,selected):
        ns=dict(base,__file__=str(shadow/filename),__name__='source_bound_original_ordinary_observer')
        names={'actual_terminal_call','actual_cash_phase','actual_stock_phase','actual_source_phase'}
        nodes=[n for n in tree(filename).body if(isinstance(n,ast.FunctionDef)and n.name in names)or(isinstance(n,ast.ClassDef)and n.name=='ActualEvents')]
        ns['cash_postcondition']=lambda before,after,lb,la,terms,result:deepcopy(f['actual_refusal']['cash'][0]['postcondition'])
        execute(nodes,ns);obj=ns['ActualEvents'].__new__(ns['ActualEvents'])
        # Only the original constructor's inert fields; records start in advance().
        obj.out=tmp_path;obj.arm='P07';obj.terms={(t['session'],t['security_id']):deepcopy(t)for t in selected}
        obj.scopes=[];obj.saved=[];obj.current=None
        return obj,ns
    retained,oldns=observer('system_campaign_financial_ordinary_observer_v1.py',[f['retained_term']])
    newer,newns=observer('system_campaign_financial_future.py',f['new_terms']);future.ActualEvents=newns['ActualEvents']
    dispatch=dict(base,__file__=str(shadow/'system_campaign_financial_compound_dispatch.py'),_RETAINED_CALLER_BINDINGS={})
    names={'_caller_code_shape','_observer_terminal_code','_observer_predicate_code','_terminal_delegation_call','retained_terminal_callers'}
    execute([n for n in tree('system_campaign_financial_compound_dispatch.py').body if isinstance(n,ast.FunctionDef)and n.name in names],dispatch)
    return SimpleNamespace(f=f,term=term,state=state,ledger=ledger,calls=calls,output=output,terminal=terminal,runtime=runtime,
        retained=retained,newer=newer,oldns=oldns,newns=newns,dispatch=dispatch,advance=advance,primitive=primitive,step=step_session,
        run=SimpleNamespace(state=state,ledger=ledger),published=SimpleNamespace(session=term.session,term=term))

def test_original_nested_observers_reproduce_exact_actual_false_and_count_refusal(tmp_path):
    s=setup(tmp_path)
    with s.retained,s.newer:
        with pytest.raises(ValueError,match='FUTURE_ONE_SELECTED_CASH_CALL_IN_ACTUAL_CANONICAL_STEP'):s.runtime.advance(s.run,s.published)
    inner=[v for _,v in s.output if v['cash']]
    assert len(s.calls)==1 and inner[-1]['cash']==s.f['actual_refusal']['cash']
    assert s.terminal.apply_terminal is s.primitive and s.runtime.advance is s.advance

def test_qualified_chain_passes_exact_original_caller_and_cash_count_guards(tmp_path):
    s=setup(tmp_path);original=s.oldns['actual_terminal_call']
    with s.retained:
        with s.dispatch['retained_terminal_callers']((object(),)):
            with s.newer:s.runtime.advance(s.run,s.published)
        assert s.oldns['actual_terminal_call']is original
    assert len(s.calls)==1
    assert any(v.get('cash')and v['cash'][0]['actual_context_call']is True and v['order']==['CASH:'+s.term.security_id]and v['passed']is True for _,v in s.output)
    assert s.terminal.apply_terminal is s.primitive and s.runtime.advance is s.advance

def test_selected_forwarding_frame_refused(tmp_path):
    s=setup(tmp_path);s.newer.terms[s.term.session,s.term.security_id]=asdict(s.term)
    with s.retained,s.dispatch['retained_terminal_callers']((object(),)),s.newer:
        with pytest.raises(ValueError,match='ONLY_FOREIGN_UNSELECTED'):s.runtime.advance(s.run,s.published)

def test_arbitrary_forwarding_function_refused(tmp_path):
    s=setup(tmp_path)
    with s.retained,s.dispatch['retained_terminal_callers']((object(),)):
        inner=s.terminal.apply_terminal
        def arbitrary(state,terms,**kwargs):return inner(state,terms,**kwargs)
        s.terminal.apply_terminal=arbitrary
        with pytest.raises(ValueError,match='EXACT_SOURCE_QUALIFIED'):s.runtime.advance(s.run,s.published)
        s.terminal.apply_terminal=inner

def test_cached_uninstalled_outer_observer_refused(tmp_path):
    s=setup(tmp_path)
    with s.retained,s.dispatch['retained_terminal_callers']((object(),)),s.newer:
        callback=s.terminal.apply_terminal;s.published.callback=callback;s.terminal.apply_terminal=s.primitive
        with pytest.raises(ValueError,match='OUTERMOST_OBSERVER_ACTUALLY_INSTALLED'):s.runtime.advance(s.run,s.published)
        s.terminal.apply_terminal=callback

def test_nested_contexts_and_exception_restore_original_namespace(tmp_path):
    s=setup(tmp_path);original=s.oldns['actual_terminal_call']
    with s.retained:
        with s.dispatch['retained_terminal_callers']((object(),)):
            first=s.oldns['actual_terminal_call']
            with pytest.raises(RuntimeError):
                with s.dispatch['retained_terminal_callers']((object(),)):raise RuntimeError('synthetic body')
            assert s.oldns['actual_terminal_call']is first
            with s.newer:s.runtime.advance(s.run,s.published)
        assert s.oldns['actual_terminal_call']is original
    assert s.dispatch['_RETAINED_CALLER_BINDINGS']=={}

def test_no_retained_context_changes_nothing(tmp_path):
    s=setup(tmp_path);original=s.oldns['actual_terminal_call']
    with s.dispatch['retained_terminal_callers'](()):assert s.oldns['actual_terminal_call']is original
    assert s.dispatch['_RETAINED_CALLER_BINDINGS']=={}

def test_changed_original_predicate_refused_before_install_and_guard_removal_detected(tmp_path):
    s=setup(tmp_path)
    exec('def actual_terminal_call(frame, step_code, state, ledger, session):\n    return True\n',s.oldns)
    with s.retained:
        with pytest.raises(ValueError,match='EXACT_UNCHANGED_ORIGINAL_GATE_CALLBACK'):
            with s.dispatch['retained_terminal_callers']((object(),)):pass
        fn=next(n for n in tree('system_campaign_financial_compound_dispatch.py').body if isinstance(n,ast.FunctionDef)and n.name=='retained_terminal_callers')
        call,=[n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'
            and len(n.args)==2 and isinstance(n.args[1],ast.Constant)and n.args[1].value=='RETAINED_CALLER_EXACT_UNCHANGED_ORIGINAL_GATE_CALLBACK']
        call.args[0]=ast.Constant(True);mutant=dict(s.dispatch);execute([fn],mutant)
        with mutant['retained_terminal_callers']((object(),)):assert s.oldns['actual_terminal_call'].__name__=='routed'

def chain_fixture(s):
    routed=s.oldns['actual_terminal_call']
    binding=dict(zip(routed.__code__.co_freevars,[v.cell_contents for v in routed.__closure__]))['binding']
    original=routed.__defaults__[-1]
    kwargs=dict(ledger=s.ledger,phase='OPEN')
    canonical=SimpleNamespace(f_code=s.step.__code__,f_locals=dict(state=s.state,ledger=s.ledger,session=s.term.session),f_back=None)
    outer=SimpleNamespace(f_code=s.newer.terminal.__func__.__code__,f_locals=dict(self=s.newer,state=s.state,terms=s.term,kwargs=dict(kwargs)),f_back=canonical)
    callee=SimpleNamespace(f_code=s.retained.terminal.__func__.__code__,f_locals=dict(self=s.retained,state=s.state,terms=s.term,kwargs=kwargs))
    return outer,callee,binding,original

@pytest.mark.parametrize('bad',['state','terms','kwargs','chain','step_code'])
def test_complete_foreign_chain_rejects_changed_arguments_or_link(tmp_path,bad):
    s=setup(tmp_path)
    with s.retained,s.dispatch['retained_terminal_callers']((object(),)),s.newer:
        s.newer.current=object();outer,callee,binding,original=chain_fixture(s)
        call=lambda function:s.dispatch[function](outer,callee,s.step.__code__,s.state,s.ledger,s.term.session,original=original,terminal=s.terminal,binding=binding)
        assert call('_terminal_delegation_call')is True
        if bad=='state':outer.f_locals['state']=object()
        elif bad=='terms':outer.f_locals['terms']=deepcopy(s.term)
        elif bad=='kwargs':outer.f_locals['kwargs']['phase']='CASH'
        elif bad=='chain':s.newer.terminal_original=s.primitive
        else:s.newer.step_code=(lambda:None).__code__
        with pytest.raises(ValueError):call('_terminal_delegation_call')

@pytest.mark.parametrize('label,bad',[
    ('RETAINED_CALLER_FOREIGN_FRAME_ARGUMENTS_IDENTICAL','terms'),
    ('RETAINED_CALLER_COMPLETE_EXACT_OBSERVER_DELEGATION_CHAIN','chain')])
def test_argument_and_chain_guard_removal_falsifiers(tmp_path,label,bad):
    s=setup(tmp_path)
    with s.retained,s.dispatch['retained_terminal_callers']((object(),)),s.newer:
        s.newer.current=object();outer,callee,binding,original=chain_fixture(s)
        if bad=='terms':outer.f_locals['terms']=deepcopy(s.term)
        else:s.newer.terminal_original=s.primitive
        args=(outer,callee,s.step.__code__,s.state,s.ledger,s.term.session)
        kw=dict(original=original,terminal=s.terminal,binding=binding)
        with pytest.raises(ValueError):s.dispatch['_terminal_delegation_call'](*args,**kw)
        fn=next(n for n in tree('system_campaign_financial_compound_dispatch.py').body if isinstance(n,ast.FunctionDef)and n.name=='_terminal_delegation_call')
        call,=[n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'
            and len(n.args)==2 and isinstance(n.args[1],ast.Constant)and n.args[1].value==label]
        call.args[0]=ast.Constant(True);mutant=dict(s.dispatch);execute([fn],mutant)
        assert mutant['_terminal_delegation_call'](*args,**kw)is True

@pytest.mark.parametrize('name',['stock_strategy_shared','sentinel','research.pooled_vacancy_funding','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(AssertionError):__import__(name)


def test_real_current_import_and_original_frozen_factory_keep_distinct_exact_code_contexts():
    import system_campaign_financial_future as future
    import system_campaign_financial_compound_dispatch as dispatch
    from system_campaign_financial_compound_ordinary_v2 import original_observer
    raw=Path(future.__file__).read_bytes()
    actual=dispatch._caller_code_shape(future.ActualEvents.terminal.__code__)
    assert dispatch._observer_terminal_code(raw)==actual
    assert dispatch._observer_predicate_code(raw)==dispatch._caller_code_shape(future.actual_terminal_call.__code__)
    # Reinstating the old standalone-current compiler reproduces the real refusal.
    assert dispatch._observer_terminal_code(raw,module_context=False)!=actual
    frozen=original_observer();old=Path(frozen.__file__).read_bytes()
    assert dispatch._observer_terminal_code(old,module_context=False)==dispatch._caller_code_shape(frozen.ActualEvents.terminal.__code__)
    assert dispatch._observer_predicate_code(old,module_context=False)==dispatch._caller_code_shape(frozen.actual_terminal_call.__code__)


def test_current_module_code_qualification_compiles_without_executing_module_statements():
    import system_campaign_financial_future as future
    import system_campaign_financial_compound_dispatch as dispatch
    raw=Path(future.__file__).read_bytes()
    dangerous=raw+b'\nraise AssertionError("MODULE_MUST_NOT_EXECUTE")\n'
    assert dispatch._observer_terminal_code(dangerous)==dispatch._observer_terminal_code(raw)
