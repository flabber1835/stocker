"""Pure frame/source/record/capsule predicates, never a local canonical run."""
import ast
from copy import deepcopy
from dataclasses import dataclass, replace, asdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import system_campaign_p10_ahl2_post_plan as context
import system_campaign_p10_ahl2_post_plan_observe as observe
import system_campaign_p10_ahl2_post_plan_replay as replay
import system_campaign_p10_ahl2_post_plan_parent as parent
import system_campaign_p10_ahl2_post_plan_gate as gate
import system_campaign_p10_ahl2_post_plan_review as review
from system_campaign_p10_ahl2_contract import digest,sha,need,specification


def mutant(module,name,label):
    fn, = [n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name == name]
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and ast.unparse(node.value.func) == 'need' and any(
                isinstance(a,ast.Constant) and a.value == label for a in node.value.args):
                self.count += 1;return None
            return self.generic_visit(node)
    remove = Remove();fn = remove.visit(fn);assert remove.count == 1
    scope = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<SYNTHETIC-predicate-removal-only>','exec'),scope)
    return scope[name]


@dataclass
class Packet:
    session: str
    terminal_events: tuple
    bars: object
    immutable_other_field: object


def frame_fixture():
    terms = ({'security_id':'toy1'},{'security_id':'toy2'},{'security_id':'toy3'})
    full = Packet('2019-02-15',terms,[{'toy':True}],object())
    prior = object();plan = object();code = frame_fixture.__code__
    globals_ = {'__name__':'sentinel.core.kernel'}
    frame = SimpleNamespace(f_code=code,f_globals=globals_,f_lineno=278,
        f_locals={'env':prior,'plan':plan,'published':full})
    source = dict(values_start=278,values_end=278)
    record = dict(session='2019-02-15',engines=[{'synthetic':True}],order=['ENGINE_BEGIN','ENGINE_RETURN'])
    args = dict(code=code,globals_=globals_,prior=prior,view=replace(full,terminal_events=(terms[0],)),record=record,source=source)
    return frame,args


def test_frame_positive_preserves_exact_whole_publication_and_declared_other_field():
    frame,args = frame_fixture()
    assert observe.frame_proof(frame,**args) is frame.f_locals['published']


@pytest.mark.parametrize('bad',['code','globals','module','line','prior','plan','copied_term','other_field','two_terms','engine','order'])
def test_frame_source_prior_term_and_post_plan_guards_refuse(bad):
    frame,args = frame_fixture()
    if bad == 'code':frame.f_code = (lambda:None).__code__
    elif bad == 'globals':frame.f_globals = dict(frame.f_globals)
    elif bad == 'module':frame.f_globals['__name__'] = 'wrong'
    elif bad == 'line':frame.f_lineno = 170
    elif bad == 'prior':frame.f_locals['env'] = object()
    elif bad == 'plan':frame.f_locals.pop('plan')
    elif bad == 'copied_term':args['view'] = replace(args['view'],terminal_events=(dict(args['view'].terminal_events[0]),))
    elif bad == 'other_field':args['view'] = replace(args['view'],immutable_other_field=object())
    elif bad == 'two_terms':args['view'] = replace(args['view'],terminal_events=frame.f_locals['published'].terminal_events[:2])
    elif bad == 'engine':args['record']['engines'] = []
    else:args['record']['order'] = ['ENGINE_BEGIN']
    with pytest.raises(ValueError):observe.frame_proof(frame,**args)


@pytest.mark.parametrize('label,bad',[
    ('P10_POST_PLAN_ACTUAL_CODE_OBJECT_GLOBALS_AND_CALLSITE','code'),
    ('P10_POST_PLAN_EXACT_PRIOR_AND_COMPLETED_PLAN_LOCAL','prior'),
    ('P10_POST_PLAN_EXACT_SINGLE_TERM_VIEW_ALL_OTHER_FIELDS_IDENTICAL','view'),
    ('P10_POST_PLAN_ACTUAL_ENGINE_RETURN_PRECEDES_SENSOR','order')])
def test_actual_frame_predicate_removal_falsifiers(label,bad):
    frame,args = frame_fixture()
    if bad == 'code':frame.f_code = (lambda:None).__code__
    elif bad == 'prior':frame.f_locals['env'] = object()
    elif bad == 'view':args['view'] = replace(args['view'],immutable_other_field=object())
    else:args['record']['order'] = []
    with pytest.raises(ValueError):observe.frame_proof(frame,**args)
    assert mutant(observe,'frame_proof',label)(frame,**args) is frame.f_locals['published']


def test_observer_values_reverse_AST_is_exact_outside_failed_block_and_new_proof():
    raw = observe.frozen_body('system_campaign_p10_ahl2_observe.py')
    cls, = [n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name == 'Observer']
    original, = [n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name == 'values']
    changed = observe.values_tree().body[0]
    block, = [n for n in original.body if isinstance(n,ast.If)]
    modified, = [n for n in changed.body if isinstance(n,ast.If)]
    start, = [i for i,n in enumerate(block.body) if isinstance(n,ast.Assign) and ast.unparse(n) == 'frames = []']
    at, = [i for i,n in enumerate(modified.body) if isinstance(n,ast.Assign) and ast.unparse(n).startswith('post_plan_context =')]
    modified.body[at:at+1] = deepcopy(block.body[start:start+4])
    call, = [n for n in ast.walk(changed) if isinstance(n,ast.Call) and ast.unparse(n.func) == "self.current['sensors'].append"]
    call.args[0].keywords = [k for k in call.args[0].keywords if k.arg != 'post_plan_context']
    assert ast.dump(changed,include_attributes=False) == ast.dump(original,include_attributes=False)


def test_actual_old_wrong_frame_predicate_refuses_completed_plan_stack():
    frames = [('advance_session','sentinel.core.kernel'),('values','system_campaign_discovery_context')]
    with pytest.raises(ValueError):need(('plan_session','sentinel.core.kernel') in frames,'P10_SENSOR_ACTUAL_CANONICAL_KERNEL_CALLSITE')
    assert ('advance_session','sentinel.core.kernel') in frames


def test_values_delegate_return_and_exception_are_unchanged():
    method = observe.Observer.values
    value = {'unrelated':12.5}
    prior = SimpleNamespace(median5={'selected':[]},feed={'series':{}})
    current = {'session':'2019-02-15','sensors':[],'order':['ENGINE_BEGIN','ENGINE_RETURN']}
    obj = SimpleNamespace(original_values=lambda **kwargs:value,current=current,
        context_proof=lambda *a:{'synthetic':True})
    assert method(obj,prior=prior,published=SimpleNamespace(session='2019-02-15')) is value
    assert current['order'][-1] == 'POST_PLAN_SENSOR'
    error = ValueError('synthetic canonical refusal unchanged')
    def refuse(**kwargs):raise error
    obj.original_values = refuse
    with pytest.raises(ValueError) as caught:method(obj,prior=prior,published=SimpleNamespace(session='2019-02-15'))
    assert caught.value is error


def test_unaffected_values_records_are_not_extended_or_changed():
    obj = SimpleNamespace(original_values=lambda **kwargs:{'toy':1.},current={'session':'2019-02-14','sensors':[],'order':[]})
    before = deepcopy(obj.current)
    assert observe.Observer.values(obj,prior=object(),published=SimpleNamespace(session='2019-02-14')) == {'toy':1.}
    assert obj.current == before


def test_source_shape_checks_complete_module_before_any_AST():
    with pytest.raises(ValueError,match='EXACT_OWN_KERNEL_BEFORE_AST'):observe.source_shape(b'def incomplete(')


def test_code_binding_compares_actual_content_not_only_function_name_and_filename():
    raw = b'def advance_session(env, published):\n    return env\n'
    code, = [c for c in compile(raw,'/variant/toy.py','exec',dont_inherit=True,optimize=0).co_consts if isinstance(c,type((lambda:None).__code__))]
    observe.code_source_valid(code,raw,'/variant/toy.py')
    with pytest.raises(ValueError):observe.code_source_valid(code,raw.replace(b'return env',b'return published'),'/variant/toy.py')
    with pytest.raises(ValueError):observe.code_source_valid(code,raw,'/variant/wrong.py')
    mutant(observe,'code_source_valid','P10_POST_PLAN_ACTUAL_CODE_CONTENT_EQUALS_EXACT_AUTHENTICATED_SOURCE')(
        code,raw.replace(b'return env',b'return published'),'/variant/toy.py')


def test_source_shape_exact_callable_order_on_explicit_synthetic_module(monkeypatch):
    raw = b'def advance_session(env, published):\n    plan = plan_session()\n    return median5_controller.witness(terminal_values=terminal_returns.values(prior=env, published=published))\n'
    monkeypatch.setattr(observe,'KERNEL_SHA',sha(raw))
    value = observe.source_shape(raw)
    assert value['plan_end'] < value['values_start']
    assert value['function_ast_sha256']


def test_cached_prefix_axis_requires_exact_prior10_and_first_new_feb15():
    days = ['2019-02-01','2019-02-04','2019-02-05','2019-02-06','2019-02-07','2019-02-08',
            '2019-02-11','2019-02-12','2019-02-13','2019-02-14']
    replay.prefix_axis_valid(days,days+['2019-02-15'],resume=True)
    replay.prefix_axis_valid(days[:1],days,resume=False)
    with pytest.raises(ValueError):replay.prefix_axis_valid(days,days+['2019-02-18'],resume=True)
    mutant(replay,'prefix_axis_valid','P10_POST_PLAN_EXACT_COMMITTED_AXIS_AND_FIRST_NEW_ADJACENCY')(
        days,days+['2019-02-18'],resume=True)


@pytest.mark.parametrize('resume',[False,True])
def test_actual_replay_namespace_has_only_declared_single_site_changes(resume):
    namespace = replay.replay_namespace(resume)
    assert namespace['Observer'] is observe.Observer
    assert namespace['NEXT'] == ('2019-02-15' if resume else '2019-02-04')
    assert namespace['replay'].__globals__ is namespace
    assert namespace['seed_bound_book'] is replay.seed_bound_book


@pytest.mark.parametrize('bad',['reference','unbounded','wrong_cursor','wrong_count'])
def test_cached_resume_is_never_reference_suffix_or_new_origin(bad):
    binding = SimpleNamespace(active={'source_cursor':'2019-02-14','discovery_transitions':10})
    kwargs = dict(mode='FAST',processing_end='2019-02-15',resume=True)
    if bad == 'reference':kwargs['mode'] = 'REFERENCE'
    elif bad == 'unbounded':kwargs['processing_end'] = '2026-07-31'
    elif bad == 'wrong_cursor':binding.active['source_cursor'] = '2019-02-15'
    else:binding.active['discovery_transitions'] = 11
    with pytest.raises(ValueError,match='Q_FAST_ONE_DAY_ONLY'):replay.replay(binding,**kwargs)


def test_fresh_suffix_refuses_qualifier_state_before_any_canonical_import():
    binding = SimpleNamespace(active={'source_cursor':'2019-02-14','discovery_transitions':10})
    with pytest.raises(ValueError,match='ALWAYS_ORIGINAL_OWN1'):replay.replay(binding,resume=False)


def test_inventory_validation_preserves_full_tail_bytes_and_refuses_changed_extra_missing(tmp_path):
    (tmp_path/'tail.jsonl').write_bytes(b'committed\nunadopted-tail\n')
    inventory = {'tail.jsonl':dict(bytes=25,sha256=sha(b'committed\nunadopted-tail\n'))}
    inventory['tail.jsonl']['bytes'] = (tmp_path/'tail.jsonl').stat().st_size
    parent.inventory_valid(tmp_path,inventory)
    (tmp_path/'extra').write_bytes(b'x')
    with pytest.raises(ValueError):parent.inventory_valid(tmp_path,inventory)
    (tmp_path/'extra').unlink();(tmp_path/'tail.jsonl').write_bytes(b'committed\n')
    with pytest.raises(ValueError):parent.inventory_valid(tmp_path,inventory)


def test_capsule_routes_exact_nested_original59_and_retained217_without_flat_fallback(tmp_path,monkeypatch):
    calls = []
    (tmp_path/'own1').mkdir();(tmp_path/'retained-qualification').mkdir()
    (tmp_path/'capsule.json').write_bytes(b'{"synthetic":true}')
    monkeypatch.setattr(parent,'capsule_manifest',lambda:{'synthetic':True})
    monkeypatch.setattr(parent,'validate_contents',lambda p,s:calls.append(('own',p.name)))
    monkeypatch.setattr(parent,'validate_retained',lambda p,s:calls.append(('q',p.name)))
    own,q = parent.validate_capsule(tmp_path,{})
    assert own == tmp_path/'own1' and q == tmp_path/'retained-qualification'
    assert calls == [('own','own1'),('q','retained-qualification')]
    (tmp_path/'source-bindings.json').write_bytes(b'{}')
    with pytest.raises(ValueError,match='NO_FLAT_FALLBACK'):parent.validate_capsule(tmp_path,{})


def synthetic_summary():
    from test_p10_ahl2_host import summary
    value = summary(specification())
    retained = context.retained_specification()
    value.update(schema=gate.SCHEMA,status=gate.STATUS,retained_execution_counts=deepcopy(gate.COUNTS),
        root_q_only_admission_sha256=retained['root_q_only_admission_sha256'],
        retained_artifact_id=retained['artifact_id'],retained_request_sha256=retained['request_sha256'],
        cached_failed_tenth_adopted=False,source_own1_suffix_origin_preserved=True,
        correct_actual_post_plan_context_qualified=True)
    return value


def test_qualification_keeps_all_original20_restore_and_actual_gates_with_new_provenance():
    value = synthetic_summary()
    assert gate.qualification_valid(value,specification()) is value
    assert len(value['actual_new_canonical_roundtrips']) == 20


@pytest.mark.parametrize('bad',['cached_forward','control_forward','restores','bool_count','admission','failed_adopted','postplan','old_schema','missing_gate'])
def test_qualification_reuse_counts_and_missing_actual_gates_refuse(bad):
    value = synthetic_summary()
    if bad == 'cached_forward':value['retained_execution_counts']['cached_fast_forward_transitions'] = 9
    elif bad == 'control_forward':value['retained_execution_counts']['old_control_forward_transitions'] = 10
    elif bad == 'restores':value['actual_new_canonical_roundtrips'].pop()
    elif bad == 'bool_count':value['retained_execution_counts']['new_fast_transitions'] = True
    elif bad == 'admission':value['root_q_only_admission_sha256'] = '0'*64
    elif bad == 'failed_adopted':value['cached_failed_tenth_adopted'] = True
    elif bad == 'postplan':value['correct_actual_post_plan_context_qualified'] = False
    elif bad == 'old_schema':value['schema'] = 'research.p10-ahl2-changed-qualification/1'
    else:value['all21_guard_preserved'] = False
    with pytest.raises(ValueError):gate.qualification_valid(value,specification())


def test_reuse_gate_predicate_removal_admits_bad_forward_count_and_is_detected():
    value = synthetic_summary();value['retained_execution_counts']['old_control_forward_transitions'] = 10
    with pytest.raises(ValueError):gate.qualification_valid(value,specification())
    assert mutant(gate,'qualification_valid','P10_POST_PLAN_EXPLICIT_REUSE_COUNTS_ROOT_ADMISSION_AND_REMAINING_ACTUAL_GATES')(
        value,specification()) is value


def test_new_review_request_hardpin_and_schema_do_not_modify_old_reader():
    scope = review.review_namespace()
    assert scope['qualification_valid'] is gate.qualification_valid
    assert scope['review'].__globals__ is scope
    old = (HERE/'system_campaign_p10_ahl2_review.py').read_text()
    assert "(HERE / 'system-campaign-p10-ahl2-request-001.json').read_bytes()" in old
    constants = scope['review'].__code__.co_consts
    assert context.REQUEST in constants and 'system-campaign-p10-ahl2-request-001.json' not in constants


def test_review_reverse_AST_proves_no_economic_or_source_predicate_changes(monkeypatch):
    import builtins
    compiler = builtins.compile;captured = []
    def capture(source,filename,*a,**kw):
        if filename == '<p10-post-plan-same-stopped-review-new-raw-request>':captured.extend(source.body)
        return compiler(source,filename,*a,**kw)
    monkeypatch.setattr(builtins,'compile',capture)
    review.review_namespace()
    fn, = captured
    mapping = {context.REQUEST:'system-campaign-p10-ahl2-request-001.json',
               'research.p10-own-post-plan-diagnostic-review/1':'research.p10-own-ahl2-diagnostic-review/1'}
    for n in ast.walk(fn):
        if isinstance(n,ast.Constant) and type(n.value) is str and n.value in mapping:n.value = mapping[n.value]
    old, = [n for n in ast.parse((HERE/'system_campaign_p10_ahl2_review.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name == 'review']
    assert ast.dump(fn,include_attributes=False) == ast.dump(old,include_attributes=False)


def test_admission_reverse_AST_preserves_every_original_crypto_predicate():
    import system_campaign_factual_admit as crypto
    raw = parent.retained_source(crypto)
    old, = [n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name == 'admit']
    boundary, = [i for i,n in enumerate(old.body) if isinstance(n,ast.For) and ast.unparse(n.iter) == "spec['inspections'].items()"]
    old.body = old.body[:boundary]
    new = parent.admission_tree();new.body = new.body[:-2]
    for n in ast.walk(new):
        if isinstance(n,ast.Subscript) and ast.unparse(n) == "r['qualification_encrypted_output']":n.slice = ast.Constant('encrypted_output')
    class Reverse(ast.NodeTransformer):
        def visit_BinOp(self,n):
            if ast.unparse(n) == "set(spec['public_members']) | {asset['name']}":
                return ast.parse("{spec['receipt_name'],'full-core-staging.json',asset['name']}",mode='eval').body
            return self.generic_visit(n)
    new = Reverse().visit(new)
    container, = [n for n in new.body if isinstance(n,ast.With) and ast.unparse(n.items[0].context_expr) == 'zipfile.ZipFile(archive)']
    at, = [i for i,n in enumerate(container.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) == '(header, tag)']
    del container.body[at-2:at]
    assert ast.dump(new,include_attributes=False) == ast.dump(old,include_attributes=False)


def full_toy_paths():
    result = [dict(session=d,publication={'all_fields':1},prior={'all_fields':1}) for d in
        ('2019-02-04','2019-02-05','2019-02-06','2019-02-07','2019-02-08','2019-02-11','2019-02-12','2019-02-13','2019-02-14','2019-02-15')]
    result[-1]['sensors'] = [dict(post_plan_context=dict(actual_code_object_identity=True,engine_return_before_sensor=True)) for _ in range(3)]
    return result


@pytest.mark.parametrize('bad',['numeric_type','unexcluded_field','prior','count'])
def test_full_changed_path_comparison_refuses_every_material_difference(bad):
    fast = full_toy_paths();reference = deepcopy(fast);gate.compare_paths(fast,reference)
    if bad == 'numeric_type':reference[0]['publication']['all_fields'] = 1.0
    elif bad == 'unexcluded_field':reference[0]['publication']['new_field'] = 'different'
    elif bad == 'prior':reference[0]['prior']['all_fields'] = 2
    else:reference.pop(0)
    with pytest.raises(ValueError):gate.compare_paths(fast,reference)


def test_full_equality_predicate_removal_falsifier_detects_new_source_field_difference():
    fast = full_toy_paths();reference = deepcopy(fast);reference[0]['publication']['source_identity'] = 'wrong'
    with pytest.raises(ValueError):gate.compare_paths(fast,reference)
    mutant(gate,'compare_paths','P10_POST_PLAN_ALL10_FULL_RECORD_AND_NUMERIC_TYPE_EQUALITY')(fast,reference)


def test_new_admission_preserves_GCM_and_selects_only_old_qualification_asset():
    fn = parent.admission_tree()
    calls = [n for n in ast.walk(fn) if isinstance(n,ast.Call)]
    assert len([n for n in calls if ast.unparse(n.func) == 'authenticate']) == 1
    assert len([n for n in calls if ast.unparse(n.func) == 'AuthenticatedStream']) == 1
    assert any(ast.unparse(n) == "r['qualification_encrypted_output']" for n in ast.walk(fn))
    assert not any(ast.unparse(n) == "r['encrypted_output']" for n in ast.walk(fn))
    assert ast.unparse(fn.body[-2]) == 'validate_retained(dest, specification())'
    assert ast.unparse(fn.body[-1]) == 'return dest'
