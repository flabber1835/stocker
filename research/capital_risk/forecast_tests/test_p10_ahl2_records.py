"""Pure wire predicates and stubbed hook lifecycle, no canonical execution."""
from copy import deepcopy
import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import system_campaign_p10_ahl2_contract as c
from system_campaign_p10_ahl2_observe import Observer
from system_campaign_p10_ahl2_review import carrier_valid
from system_campaign_p10_ahl2_gate import actual_v_guard_falsifier
from system_campaign_p10_ahl2_replay import replay_tree


def wire():
    spec = c.specification()
    state = dict(last_processed_session='2019-02-01', ledger={'events':[]})
    runtime = dict(state=state, state_sha256=c.digest(state), policy=c.POLICY, input_sha256='f'*64)
    runtime['checkpoint_sha256'] = c.digest(runtime)
    descriptors = spec['old_descriptors'] + [{'sha256':'f'*64}]
    binding = SimpleNamespace(spec=spec, descriptors=descriptors, run=SimpleNamespace(input_sha256='f'*64,policy=c.POLICY))
    cp = dict(schema=c.CHECKPOINT, authority=c.TAINT, financial_authority=False, account_performance_computed=False,
        discovery_transitions=1, input_descriptors=descriptors, original_diagnostic_checkpoint_sha256=spec['diagnostic_checkpoint_sha256'],
        strict_parent_outer_sha256=spec['strict_parent_outer_sha256'], source_binding_sha256=spec['source_binding_sha256'],
        runtime_checkpoint=runtime, source_cursor='2019-02-01')
    cp['sha256'] = c.digest(cp)
    return cp, binding


def test_versioned_carrier_requires_complete_runtime_and_own_source():
    cp, binding = wire()
    carrier_valid(cp,binding)


@pytest.mark.parametrize('mutate', [lambda x:x.update(schema='research.pooled-vacancy-backtest/1'),
    lambda x:x.update(discovery_transitions=True),
    lambda x:x.update(source_binding_sha256='0'*64),
    lambda x:x['input_descriptors'].pop(),
    lambda x:x['runtime_checkpoint'].update(input_sha256='0'*64),
    lambda x:x['runtime_checkpoint']['state'].update(last_processed_session='2019-02-14')])
def test_carrier_refuses_wrong_kind_count_source_input_or_cursor(mutate):
    cp,binding = wire()
    cp = deepcopy(cp)
    mutate(cp)
    cp['sha256'] = c.digest({k:v for k,v in cp.items() if k!='sha256'})
    with pytest.raises(ValueError): carrier_valid(cp,binding)


def stub_modules(monkeypatch, *, broken=False):
    import full_system_core
    monkeypatch.setattr(full_system_core, 'hosted', lambda:None)
    def f(*a,**kw): return ('delegated',a,kw)
    backtest = SimpleNamespace(apply_repair=f)
    risk = SimpleNamespace(volatility_stop=f)
    terminal = SimpleNamespace(apply_terminal=f)
    adapter = SimpleNamespace() if broken else SimpleNamespace(decide=f)
    values = SimpleNamespace(values=f)
    for name in ('research','stock_strategy_shared','sentinel'):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules,name,module)
    funding = ModuleType('research.pooled_vacancy_funding')
    funding.backtest = backtest
    wealth = ModuleType('stock_strategy_shared.wealth_core')
    wealth.capital_risk,wealth.terminal,wealth.adapter = risk,terminal,adapter
    controller = ModuleType('sentinel.controller')
    controller.terminal_returns = values
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',funding)
    monkeypatch.setitem(sys.modules,'stock_strategy_shared.wealth_core',wealth)
    monkeypatch.setitem(sys.modules,'sentinel.controller',controller)
    return f,backtest,risk,terminal,adapter,values


def test_all_real_observer_hooks_restore_after_body_exception(monkeypatch):
    f,backtest,risk,terminal,adapter,values = stub_modules(monkeypatch)
    binding = SimpleNamespace(spec=c.specification())
    observer = Observer(binding)
    with pytest.raises(RuntimeError,match='stub-body'):
        with observer:
            assert all(x is not f for x in (backtest.apply_repair,risk.volatility_stop,terminal.apply_terminal,adapter.decide,values.values))
            raise RuntimeError('stub-body')
    assert not observer.saved
    assert all(x is f for x in (backtest.apply_repair,risk.volatility_stop,terminal.apply_terminal,adapter.decide,values.values))


def test_observer_partial_install_failure_restores_every_installed_hook(monkeypatch):
    f,backtest,risk,terminal,adapter,values = stub_modules(monkeypatch,broken=True)
    observer = Observer(SimpleNamespace(spec=c.specification()))
    with pytest.raises(AttributeError): observer.__enter__()
    assert not observer.saved
    assert backtest.apply_repair is f and risk.volatility_stop is f and terminal.apply_terminal is f


def test_host_guard_rich_stub(tmp_path,monkeypatch):
    """Exercise exporter mechanics on a toy stub, never the canonical risk code."""
    from dataclasses import dataclass,asdict,is_dataclass
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    raw=b"""def volatility_stop(ep,*,bars,session,cfg):
    bar=next((b for b in bars if b.security_id==ep.security_id),None)
    axis=['D']*21
    if bar is None or list(bar.signal_sessions or ()) != axis or len(bar.closes) < 21:
        raise ValueError('REFUSED_VOLATILITY_CAUSAL_AXIS')
    ep.research_stop_cursor=session
    return False
"""
    module=ModuleType('toy_risk_stub');exec(compile(raw,'<toy-not-canonical-risk>','exec'),vars(module))
    for name in ('stock_strategy_shared','stock_strategy_shared.wealth_core'):
        m=ModuleType(name);m.__path__=[];monkeypatch.setitem(sys.modules,name,m)
    sys.modules['stock_strategy_shared.wealth_core'].capital_risk=module
    @dataclass(frozen=True)
    class Bar:
        security_id:str
        signal_sessions:tuple
        closes:tuple
    bar=Bar('SYNTHETIC',tuple('D' for _ in range(21)),tuple(range(1,22)))
    ep=SimpleNamespace(security_id='SYNTHETIC',slot_id=0,research_stop_cursor=None)
    def material(x):return asdict(x) if is_dataclass(x) else vars(x).copy()
    observer=SimpleNamespace(risk_sample=(ep,bar,'D',SimpleNamespace()),original_risk=module.volatility_stop,material=material)
    name='shared/stock_strategy_shared/wealth_core/capital_risk.py';p=tmp_path/name;p.parent.mkdir(parents=True);p.write_bytes(raw)
    binding=SimpleNamespace(source_binding={'all_sources':{name:c.sha(raw)}})
    proof=actual_v_guard_falsifier(observer,tmp_path,binding)
    assert proof['source_sha256']==c.sha(raw) and proof['original_prior_episode']==proof['original_after_refusal_episode']
    assert proof['mutant_installed_on_real_module'] is False and proof['mutant_result'] is False
    assert proof['original_function_ast_sha256']!=proof['mutant_function_ast_sha256']


def test_full_record_serialized_type_guard_removal():
    """Python considers1==1.0; the actual gate must preserve serialized types."""
    fn=c.function((HERE/'system_campaign_p10_ahl2_gate.py').read_bytes(),'qualify')
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='need'
           and len(n.args)==2 and isinstance(n.args[1],ast.Constant)
           and n.args[1].value=='P10_ALL_CHANGED_FULL_PUBLICATIONS_PRIORS_RUNTIME_COMPONENTS_EXACT']
    ns=dict(need=c.need,encoded=c.encoded,fast=[{'synthetic_price':1}],reference=[{'synthetic_price':1.0}])
    assert ns['fast']==ns['reference']
    with pytest.raises(ValueError):eval(compile(ast.Expression(call),'<actual-full-record-type-guard>','eval'),ns)
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            if ast.unparse(node)=='encoded(fast) == encoded(reference)':
                self.count+=1
                return ast.copy_location(ast.Constant(True),node)
            return self.generic_visit(node)
    remove=Remove();mutant=remove.visit(deepcopy(call));assert remove.count==1
    eval(compile(ast.fix_missing_locations(ast.Expression(mutant)),'<removed-serialized-type-guard>','eval'),ns)


def test_actual_pre_event_checkpoint_precedes_prepare_and_affected_success_commits():
    tree=replay_tree('FAST')
    loop,=[n for n in ast.walk(tree) if isinstance(n,ast.For) and ast.unparse(n.iter)=='wanted']
    pre,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.If) and ast.unparse(n.test)=='packet.terminal or packet.spins']
    prepared,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='published']
    assert pre<prepared
    text=ast.unparse(loop.body[pre])
    assert text.index('checkpoint()')<text.index('write_new(') and "book / 'pre-event'" in text
    assert isinstance(loop.body[-1],ast.If) and ast.unparse(loop.body[-1].test)=='packet.day == AFFECTED'
    assert ast.unparse(loop.body[-1].body[0])=='checkpoint()'


def test_all20_new_roundtrips_gate_missing_or_mutated_refuses():
    from system_campaign_p10_ahl2_gate import qualification_valid
    spec=c.specification()
    value=dict(schema='research.p10-ahl2-changed-qualification/1',status='P10_OWN_FOURTH_INPUT_CHANGED_PATH_QUALIFIED',
        financial_authority=False,qualifier_state_adopted=False,original_diagnostic_file_sha256=spec['diagnostic_checkpoint_sha256'],
        candidate_transitions=10,qualified_through='2019-02-15',first_session='2019-02-04',
        full_FAST_REFERENCE_publication_runtime_event_proof_equal=True,actual_old_refusal_reproduced=True,all21_guard_preserved=True,
        actual_new_canonical_roundtrips=[dict(mode=m,session=d,checkpoint_sha256='c'*64,state_sha256='d'*64,full_state_equal=True)
            for m in ('FAST','REFERENCE') for d in ('2019-02-04','2019-02-05','2019-02-06','2019-02-07','2019-02-08',
                '2019-02-11','2019-02-12','2019-02-13','2019-02-14','2019-02-15')])
    qualification_valid(value,spec)
    for mode in ('missing','false','wrong_transport','duplicate_day'):
        bad=deepcopy(value)
        if mode=='missing':bad.pop('actual_new_canonical_roundtrips')
        elif mode=='false':bad['actual_new_canonical_roundtrips'][0]['full_state_equal']=False
        elif mode=='wrong_transport':bad['actual_new_canonical_roundtrips'][0]['mode']='NOT_QUALIFIED'
        else:bad['actual_new_canonical_roundtrips'][0]['session']='2019-02-05'
        with pytest.raises(ValueError):qualification_valid(bad,spec)
