"""Three immutable original observer generations, original constructors, exact order."""
import ast,builtins,copy,json,sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_additional_sensor import C,DEP,data,runtime,env,fixture,fence

def actual_selection(e,monkeypatch):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations
    monkeypatch.setattr(registry,'registrations',lambda driver=DEP:original(driver))
    api=runtime.ordinary_api(e.p)
    primary=api['selected']('P07',cursor=e.p['origin_cursor'])[2]
    extra,_=api['supplemental_selection']('P07',e.p['origin_cursor'])
    terms=api['merge_selected_terms'](primary,extra)
    assert [v['ticker'] for v in terms]==e.p['ordinary_expected_tickers']
    return api,terms

def source_root(e,monkeypatch):
    for name,raw in e.fixture['inherited_files'].items():(e.root/name).write_text(raw,encoding='utf8',newline='')
    for name,raw in e.fixture['original_projection_files'].items():(e.root/name).write_text(raw,encoding='utf8',newline='')
    (e.overlay/'system-campaign-own-future-projection.json').write_bytes((DEP/'system-campaign-own-future-projection.json').read_bytes())
    api,terms=actual_selection(e,monkeypatch)
    import system_campaign_financial_future as f
    cash=dict(f.CASH_PHASES);cash[e.p['arm'],e.p['origin_cursor']]=tuple(api['CASH_PHASES'][e.p['arm'],e.p['origin_cursor']])
    monkeypatch.setattr(f,'CASH_PHASES',cash)
    (e.root/api['hydration_name'](e.cp)).write_bytes(data.encoded(dict(arm='P07',terms=terms)))
    (e.root/api['OVERLAY']).write_bytes(data.encoded(dict(add=[v['added'] for v in terms])))
    import system_campaign_financial_projection as projection
    approved=SimpleNamespace(payload=dict(derived_projection=json.loads((e.root/'derived-own-future-projection.json').read_bytes())),
        projection_path=e.root/'derived-own-future-projection.json')
    monkeypatch.setattr(projection,'retained_activation',lambda root,cp:approved)
    monkeypatch.setattr(runtime,'read_cp',lambda path:e.cp)
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    return terms

def test_exact_original_cashcalendar_constructors_and_three_effective_observer_sources(env,monkeypatch):
    terms=source_root(env,monkeypatch)
    assert len(terms)==7
    bindings=runtime.observer_bindings(env.root,env.p)
    assert len(bindings)==3 and sum(v['stock_bearing'] for v in bindings)==1
    future={}
    for record in env.p['inherited_ordinary_observers']:
        doc=json.loads((env.root/record['effective_file']).read_bytes())
        future[record['descriptor']['sha256']]=[(v['session'],v['kind']) for v in doc['add'] if v['session']>env.p['origin_cursor']]
    assert sorted(len(v) for v in future.values())==[2,3,6]
    assert sum(kind=='CASH_PLUS_STOCK' for values in future.values() for day,kind in values)==1
    assert all(v['observation_directory'].endswith(v['descriptor_sha256']) for v in bindings)

@pytest.mark.parametrize('bad',['missing','extra','duplicate','kind','projection','material'])
def test_observer_inventory_and_original_projection_falsifiers(env,monkeypatch,bad):
    source_root(env,monkeypatch);p=copy.deepcopy(env.p)
    if bad=='missing':p['inherited_ordinary_observers'].pop()
    elif bad=='extra':p['inherited_ordinary_observers'].append(copy.deepcopy(p['inherited_ordinary_observers'][0]))
    elif bad=='duplicate':p['inherited_ordinary_observers'][1]=copy.deepcopy(p['inherited_ordinary_observers'][0])
    elif bad=='kind':p['inherited_ordinary_observers'][0]['stock_bearing']=True
    elif bad=='projection':
        r=next(v for v in p['inherited_ordinary_observers'] if v['projection'] is not None)
        r['projection']['binding_sha256']='0'*64
    else:
        r=p['inherited_ordinary_observers'][0];(env.root/r['material_file']).write_bytes(b'changed original input material')
    with pytest.raises((ValueError,json.JSONDecodeError)):runtime.observer_bindings(env.root,p)


def test_actual_original_constructor_bindings_require_stock_owner_outermost_after_consumption(env,monkeypatch,tmp_path):
    source_root(env,monkeypatch)
    import system_campaign_financial_future as f
    import system_campaign_financial_compound_dispatch as dispatch
    events=[];calls=[]
    # Exact __init__ code; inert synthetic enter/exit only. No financial API is imported.
    class Observer(f.ActualEvents):
        def __enter__(self):events.append(self);calls.append(('enter',self));return self
        def __exit__(self,*args):calls.append(('exit',self))
    monkeypatch.setattr(f,'ActualEvents',Observer)
    # Class AST qualification is separately proved against original source; substitute only this inert API boundary.
    original_api=runtime.ordinary_api(env.p);original_api['ActualEvents']=Observer
    monkeypatch.setattr(runtime,'ordinary_api',lambda p:original_api)
    original_class=f.ActualEvents
    monkeypatch.setattr(dispatch,'retained_versions',lambda root,cp:('qualified-original-v2',))
    @contextmanager
    def routed(modules):
        assert len(events)==4 and modules==('qualified-original-v2',);calls.append(('caller',None));yield
    monkeypatch.setattr(dispatch,'retained_terminal_callers',routed)
    # original observer_bindings calls ordinary_api only for the deterministic material filename.
    actual=runtime.observer_bindings
    monkeypatch.setattr(runtime,'observer_bindings',lambda root,p:[dict(descriptor_sha256=r['descriptor']['sha256'],stock_bearing=r['stock_bearing'],
        observation_directory='additional-inherited-ordinary-observation/'+r['descriptor']['sha256']) for r in p['inherited_ordinary_observers']])
    with runtime.ordinary_observers(env.root,tmp_path/'observations',env.p,env.cp):pass
    assert len(events)==4
    assert all(v['kind']=='CASH_MERGER' or v['session']<=env.p['origin_cursor'] for event in events[:-1] for v in event.terms.values())
    assert any(v['kind']=='CASH_PLUS_STOCK' and v['session']=='2022-05-17' for v in events[-1].terms.values())
    assert calls[-1][0]=='exit' and all(e.scopes==[] for e in events)
    assert events[2].out.name=='observations'
    assert all(e.out.parent.name=='additional-inherited-ordinary-observation' for e in (events[0],events[1],events[3]))

@pytest.mark.parametrize('bad',['current_nonempty','current_mutates','frozen_mutates'])
def test_dual_original_and_current_scope_results_must_be_empty_and_readonly(bad):
    material=dict(synthetic_material=True)
    def frozen(cp,value,*args):
        if bad=='frozen_mutates':value['changed']=True
        return []
    def current(cp,value,*args):
        if bad=='current_mutates':value['changed']=True
        return [dict(unqualified_scope=True)] if bad=='current_nonempty' else []
    with pytest.raises(ValueError):runtime.empty_scope_results(dict(source_scopes=frozen),SimpleNamespace(source_scopes=current),{},material,'a','b')
    assert material==dict(synthetic_material=True)

def test_current_scope_readonly_guard_removal_admits_mutation():
    material=dict(synthetic=True)
    def mutating(cp,value,*args):value['bad_mutation']=True;return []
    args=(dict(source_scopes=lambda *a:[]),SimpleNamespace(source_scopes=mutating),{},material,'a','b')
    with pytest.raises(ValueError):runtime.empty_scope_results(*args)
    fn=data.function(Path(runtime.__file__).read_bytes(),'empty_scope_results')
    guard,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='need'
        and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='ADDITIONAL_CURRENT_EMPTY_SCOPE_READONLY']
    guard.args[0]=ast.Constant(True);scope=dict(vars(runtime))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<scope-readonly-guard-removal>','exec'),scope)
    assert scope['empty_scope_results'](*args)==[]

def test_frozen_original_routing_ignores_later_current_registry_mutation(env,monkeypatch):
    import system_campaign_financial_future as f
    original_api,terms=actual_selection(env,monkeypatch)
    expected=data.encoded(terms)
    later=dict(f.CASH_PHASES);later['P07','2022-02-28']=('missing-later-source.json',('WRONG',))
    monkeypatch.setattr(f,'CASH_PHASES',later)
    later_own=dict(f.OWN_CASH_PHASES);later_own['P07','2022-02-28']='WRONG'
    monkeypatch.setattr(f,'OWN_CASH_PHASES',later_own)
    api=runtime.ordinary_api(env.p)
    selected=api['selected']('P07',cursor='2022-02-28')[2]
    supplement,_=api['supplemental_selection']('P07','2022-02-28')
    assert data.encoded(api['merge_selected_terms'](selected,supplement))==expected

@pytest.mark.parametrize('bad',['call','update','missing'])
def test_frozen_metadata_rejects_unknown_nondeclarative_or_missing_sites(env,bad):
    raw=(env.overlay/runtime.FROZEN_FUTURE).read_bytes()
    if bad=='call':raw+=b'\nCASH_PHASES = unqualified_external_read()\n'
    elif bad=='update':raw+=b'\nCASH_PHASES.update(unqualified_external_read())\n'
    else:
        tree=ast.parse(raw);node=next(n for n in tree.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='PLANS')
        lines=raw.decode().splitlines(keepends=True);raw=''.join(lines[:node.lineno-1]+lines[node.end_lineno:]).encode()
    with pytest.raises(ValueError):runtime.frozen_metadata(raw,{})

def test_unknown_selected_future_namespace_cannot_hide_as_baseline_fact(env,monkeypatch):
    source_root(env,monkeypatch)
    baseline=next(d for d in env.cp['repairs'] if d['sha256'].startswith('1787c452'))
    doc=json.loads((env.root/'book/repairs'/baseline['filename']).read_bytes())
    doc['source_evidence'].append(dict(reference='research:system-optimization-002/selected-future-ordinary-input/2/selector',
        description='Synthetic unknown selected generation',sha256='0'*64))
    raw=data.encoded(doc);h=data.sha(raw);new=dict(baseline,filename=h+'.json',sha256=h)
    (env.root/'book/repairs'/new['filename']).write_bytes(raw)
    env.cp['repairs']=[new if d is baseline else d for d in env.cp['repairs']]
    with pytest.raises(ValueError,match='UNKNOWN_SELECTED_FUTURE_NAMESPACE'):runtime.observer_bindings(env.root,env.p)
