"""Actual method/source metadata and explicit acceptance-flag DTOs only."""
import ast,builtins,inspect,json,sys
from copy import deepcopy
from pathlib import Path
from types import CodeType,SimpleNamespace
import pytest
D=Path('C:\\GitHub\\stocker\\.codex-tmp\\p05-fin338-whole-module-gate-v3-20261106');C=Path(__file__).resolve().parents[2]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('GATE_V3_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(C)]
import system_campaign_p05_remaining_runtime_v3 as r
import system_campaign_financial_resume as m
from system_campaign_financial_partial import root_spec
def fn(raw,name):return next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
def dump(n):return ast.dump(n,include_attributes=False)
def req(spec):return dict(execution_mode=r.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,**{r.FIELD:{'P05':r.declaration(spec)}})
@pytest.fixture(scope='module')
def spec():return root_spec('P05',r.original.origin.data.own.ROOT)
def test_real_gate_exact_five_shapes_from_whole_module_context():
    tree=ast.parse(Path(m.__file__).read_bytes());actual=r.whole_module_gate(tree)
    assert all(r.original.code_shape(getattr(actual,n).__code__)==r.original.code_shape(getattr(m.AdoptionGate,n).__code__) for n in r.METHODS)
    assert r.original_gate(m.AdoptionGate,Path(m.__file__)) is m.AdoptionGate
def test_isolated_class_discrepancy_reproduced_only_write():
    cls=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate')
    ns={};exec(compile(ast.Module(body=[cls],type_ignores=[]),'<isolated-class-DATA-diagnostic>','exec',dont_inherit=True),ns)
    assert [n for n in r.METHODS if r.original.code_shape(getattr(ns['AdoptionGate'],n).__code__)!=r.original.code_shape(getattr(m.AdoptionGate,n).__code__)]==['write']
def test_original_validator_whole_AST_undo():
    raw=Path(r.original.__file__).read_bytes();tree=r.original_gate_tree(raw);old=fn(raw,'original_gate')
    i=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and ast.unparse(n)=="namespace['AdoptionGate'] = whole_module_gate(tree)")
    site=next(n for n in old.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='exec')
    tree.body[i]=deepcopy(site);assert dump(tree)==dump(old)
def test_whole_compiled_module_and_actual_writer_never_executed(monkeypatch):
    old_exec=builtins.exec;calls=[]
    def guarded(code,*a,**k):
        if isinstance(code,CodeType):assert code.co_filename!='<entire-original-module-compile-only-never-executed>'
        return old_exec(code,*a,**k)
    monkeypatch.setattr(builtins,'exec',guarded)
    original_gate=m.AdoptionGate;original_methods={n:getattr(original_gate,n) for n in r.METHODS}
    def profile(frame,event,arg):
        if event=='call':calls.append(frame.f_code)
    old_profile=sys.getprofile();sys.setprofile(profile)
    try:r.original_gate(m.AdoptionGate,Path(m.__file__))
    finally:sys.setprofile(old_profile)
    assert m.AdoptionGate is original_gate and all(getattr(m.AdoptionGate,n) is method for n,method in original_methods.items())
    assert all(method.__code__ not in calls for method in original_methods.values())
    assert any(c.co_name=='AdoptionGate' for c in calls)
@pytest.mark.parametrize('method',r.METHODS)
def test_every_substituted_live_method_refuses(method):
    substituted=type('ExplicitNoncanonicalMethodSubstitution',(m.AdoptionGate,),{method:lambda *a,**k:None})
    with pytest.raises(ValueError,match='ALL_FIVE_REAL_ORIGINAL_GATE_METHOD_CODE_SHAPES'):r.original_gate(substituted,Path(m.__file__))
def test_method_shape_guard_removal_is_meaningful():
    substituted=type('ExplicitNoncanonicalMethodSubstitution',(m.AdoptionGate,),{'write':lambda *a,**k:None})
    with pytest.raises(ValueError):r.original_gate(substituted,Path(m.__file__))
    tree=r.original_gate_tree(Path(r.original.__file__).read_bytes())
    stmt=next(n for n in tree.body if isinstance(n,ast.Expr) and 'P05_RUNTIME18_ALL_FIVE_REAL_ORIGINAL_GATE_METHOD_CODE_SHAPES' in ast.unparse(n))
    tree.body[tree.body.index(stmt)]=ast.Pass();ns=dict(vars(r.original),whole_module_gate=r.whole_module_gate)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[])),'<removed-method-shape-guard>','exec'),ns)
    assert ns['original_gate'](substituted,Path(m.__file__)) is substituted
def test_changed_original_gate_AST_refuses_before_class_body_build(tmp_path,monkeypatch):
    tree=ast.parse(Path(m.__file__).read_bytes());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='advance');method.body=[ast.Pass()]
    path=tmp_path/'NONCANONICAL-modified-source.py';path.write_text(ast.unparse(ast.fix_missing_locations(tree)))
    monkeypatch.setattr(r,'whole_module_gate',lambda tree:(_ for _ in ()).throw(AssertionError('CLASS_BODY_MUST_NOT_BUILD')))
    with pytest.raises(ValueError,match='WHOLE_ORIGINAL_ADOPTION_GATE_AST'):r.original_gate(m.AdoptionGate,path)
def test_both_whole_gate_wrappers_keep_real_original_methods(spec):
    gate=r.gate_class(m.AdoptionGate,Path('/out'),None,spec,module_path=Path(m.__file__))
    assert gate.__init__ is m.AdoptionGate.__init__ and gate.advance is m.AdoptionGate.advance
    assert gate.__enter__ is m.AdoptionGate.__enter__ and gate.__exit__ is m.AdoptionGate.__exit__
def test_origin_failure_recloses_advance_without_writer_or_checkpoint(spec,monkeypatch):
    Gate=r.gate_class(m.AdoptionGate,Path('/out'),None,spec,module_path=Path(m.__file__));Base=Gate.__mro__[1]
    def noncanonical_failure_flag_DTO(event,*a,**k):event.accepted=True;raise RuntimeError('NONCANONICAL-EXPECTED-ORIGIN-FAILURE')
    monkeypatch.setattr(Base,'write',noncanonical_failure_flag_DTO)
    event=object.__new__(Gate);event.accepted=False
    with pytest.raises(RuntimeError,match='NONCANONICAL-EXPECTED'):event.write()
    assert event.accepted is False
    with pytest.raises(ValueError,match='NEUTRAL_ADOPTION_REQUIRED_BEFORE_ADVANCE'):event.advance()
def test_frozen_v1_v2_sources_and_qualifications_retained():
    r.qualified_base()
    assert r.sha(Path(r.v2.__file__).read_bytes())=='31d8b6c1110cc2add682687eb0959d90cf3713d10e9421464bd855a04c04536d'
    assert r.sha((C/r.v2.QUALIFICATION).read_bytes())==r.V2_Q_SHA
def test_new_declaration_preserves_v2_packet_gate_and_adds_compiler_binding(spec):
    old=r.v2.declaration(spec);new=r.declaration(spec)
    assert {k:v for k,v in new.items() if k in old}==old
    assert new['whole_module_compiler_context_required_for_gate_identity'] is True
    assert new['actual_hosted36_packet_checks_required_before_financial_entry'] is True
    assert r.selected(spec,req(spec))
    with pytest.raises(ValueError):r.selected(spec,dict(req(spec),**{r.FIELD:{'P05':old}}))
def test_old_context_accepts_only_new_request_and_restores_on_abort(spec):
    target=SimpleNamespace(EXECUTION_MODE=r.MODE,financial_inputs=lambda *a:None,qualified_overlay=lambda *a:None,review_adoption=lambda *a:None)
    before=dict(vars(target));old_pending=r.original.pending.for_parent
    with pytest.raises(RuntimeError):
        with r.old_entry(target,spec,req(spec)):raise RuntimeError('EXPLICIT_DTO_ABORT')
    assert vars(target)==before and r.original.pending.for_parent is old_pending
def test_local_financial_entry_refuses_before_output(spec,tmp_path):
    with pytest.raises(ValueError):
        with r.entry_context(None,spec,request=req(spec),mode='economic',out=tmp_path):pass
    assert list(tmp_path.iterdir())==[]
def test_actual_FIN338_packet_positive_DATA():
    value=json.loads((D/'P05-FIN338-actual-packet-and-whole-module-gate-DATA.json').read_bytes())
    assert value['passed'] is True and value['actual_preflight_packet_checks']==value['actual_economic_packet_checks']==36
    assert value['actual_preflight_gate']['passed'] is True and value['actual_neutral20_created'] is False
    assert value['new_financial_closes']==0 and value['full_inputs']==19 and all(v['whole_module_shape_equal'] for v in value['method_metadata'])
def test_request_binds_complete_sources_and_new_declaration_without_replacement(spec,tmp_path,monkeypatch):
    for name in r.source_names():
        if name==r.QUALIFICATION:
            # Opaque noncanonical source-pin fixture only; never a qualification.
            raw=b'EXPLICIT-NONCANONICAL-REQUEST-SOURCE-PIN-FIXTURE\n'
        else:
            p=D/name if (D/name).is_file() else C/name;raw=p.read_bytes()
        (tmp_path/name).write_bytes(raw)
    monkeypatch.setattr(r,'HERE',tmp_path)
    original=dict(execution_mode=r.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
        sources={'unchanged-original.py':'a'*64},arm_inputs={'P05':dict(new_factual_overlay=False),'P03':dict(new_factual_overlay=True)})
    actual=r.expected_request(lambda:deepcopy(original),execution_mode=r.MODE,selected_arms=['P05','P03'],root_lookup=lambda arm:spec)
    assert r.selected(spec,actual) and actual['arm_inputs']['P05']['new_factual_overlay'] is True
    assert actual['arm_inputs']['P03']==original['arm_inputs']['P03'] and actual['sources']['unchanged-original.py']=='a'*64
    assert set(r.source_names())<=set(actual['sources'])
    bad=deepcopy(original);bad['sources'][r.QUALIFICATION]='0'*64
    with pytest.raises(ValueError,match='NO_OLD_SOURCE_PIN_REPLACEMENT'):r.expected_request(lambda:bad,execution_mode=r.MODE,selected_arms=['P05'],root_lookup=lambda arm:spec)
def test_whole_entry_binding_routes_to_v3_gate_without_financial_entry(spec,monkeypatch):
    old=r.v2.bind_function;calls=[]
    def spy(function,**changes):calls.append((function,changes));return old(function,**changes)
    monkeypatch.setattr(r.v2,'bind_function',spy)
    with pytest.raises(ValueError):
        with r.entry_context(None,spec,request=req(spec),mode='economic',out=Path('/NONCANONICAL-NO-OUTPUT')):pass
    assert any(f is r.original.entry_context.__wrapped__ and changes['gate_class'] is r.gate_class and changes['selected'] is r.selected for f,changes in calls)
def test_lost_compiler_context_still_refuses_at_original_method_guard(monkeypatch):
    def isolated(tree):
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate');ns={}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'<deliberately-isolated-class-negative>','exec',dont_inherit=True),ns);return ns['AdoptionGate']
    monkeypatch.setattr(r,'whole_module_gate',isolated)
    with pytest.raises(ValueError,match='ALL_FIVE_REAL_ORIGINAL_GATE_METHOD_CODE_SHAPES'):r.original_gate(m.AdoptionGate,Path(m.__file__))
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    assert not any(n==prefix or n.startswith(prefix+'.') for n in sys.modules)
    with pytest.raises(ImportError):Fence().find_spec(prefix)
