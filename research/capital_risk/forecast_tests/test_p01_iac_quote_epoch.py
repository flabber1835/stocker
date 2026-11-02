"""Source-selected loader and public-API stubs; no Core/serializer execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_quote_epoch as subject
import p01_epoch_resume as old


@pytest.fixture
def setup(tmp_path,monkeypatch):
    raw=b'{"synthetic_descriptor":true}\n';descriptor=tmp_path/'descriptor.json';descriptor.write_bytes(raw)
    (tmp_path/'p01_celg_bridge_quote_descriptor.json').write_bytes(raw)
    monkeypatch.setattr(old,'HERE',tmp_path)
    cache=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/research-capital-risk-20261027/system-optimization-002/p01-sequential-001/native-resume-001/source-semantics-516/shared__stock_strategy_shared__wealth_core__merger_rights.py.txt')
    if sys.platform=='win32':cache=Path('\\\\?\\'+str(cache.resolve()))
    market=ModuleType('stock_strategy_shared.wealth_core.merger_rights');market.__file__=str(cache)
    market.value=None;market.binds=0;market.reads=0;market.unrelated=None;events=[]
    def quote():
        market.reads+=1;events.append('quote_lookup')
        if market.unrelated is not None:raise ValueError(market.unrelated)
        if market.value is None:raise ValueError(subject.UNBOUND)
        return deepcopy(market.value)
    def bind(value,*,expected_sha256):
        events.append('canonical_bind');market.binds+=1
        if market.value is not None:raise ValueError('REFUSED_CELG_COMPONENT_ONE_EXACT_VERSIONED_MARKET_INPUT_REGISTRATION')
        assert subject.digest(value)==expected_sha256;market.value=deepcopy(value)
    market.quote=quote;market.bind_market_quote=bind
    package=ModuleType('stock_strategy_shared.wealth_core');package.merger_rights=market
    monkeypatch.setitem(sys.modules,'stock_strategy_shared.wealth_core',package)
    transport=ModuleType('p01_celg_input_transport');transport.calls=0;transport.failed=False
    transport.data=dict(identity={'synthetic_security':True},raw_open='1.25',raw_close='1.125',source='SYNTHETIC_ONLY')
    def load(root,desc):
        events.append('authenticate_full_capsule');transport.calls+=1
        if transport.failed:raise ValueError('SYNTHETIC_AUTHENTICATION_REFUSAL')
        return SimpleNamespace(quote=SimpleNamespace(model_dump=lambda **kw:deepcopy(transport.data)),
            capture_sha256='a'*64,manifest_sha256='b'*64,ciphertext_sha256='c'*64,input_identity_sha256='d'*64)
    transport.load_authenticated_input=load;monkeypatch.setitem(sys.modules,'p01_celg_input_transport',transport)
    return SimpleNamespace(root=tmp_path,descriptor=descriptor,market=market,transport=transport,events=events)


def test_actual_old_loader_second_context_reproduces_once_only_refusal(setup):
    x=setup;old._quote(x.root,x.descriptor)
    with pytest.raises(ValueError,match='ONE_EXACT_VERSIONED'):old._quote(x.root,x.descriptor)
    assert x.transport.calls==2 and x.market.binds==2


def test_new_actual_loader_authenticates_every_context_and_binds_only_once(setup):
    x=setup;first=subject.authenticated_quote(x.root,x.descriptor);x.events.clear()
    second=subject.authenticated_quote(x.root,x.descriptor)
    assert subject.encoded(first)==subject.encoded(second) and x.transport.calls==2 and x.market.binds==1
    assert x.events[0]=='authenticate_full_capsule' and 'canonical_bind' not in x.events


@pytest.mark.parametrize('kind',['identity','value','type','source'])
def test_different_existing_registration_refuses_without_rebinding(setup,kind):
    x=setup;subject.authenticated_quote(x.root,x.descriptor)
    if kind=='identity':x.market.value['identity']={'synthetic_security':False}
    if kind=='value':x.market.value['raw_close']='2.0'
    if kind=='type':x.market.value['observed_market_data']=1
    if kind=='source':x.market.value['capture_sha256']='e'*64
    before=deepcopy(x.market.value)
    with pytest.raises(ValueError,match='ENTIRE_TYPED_REGISTRATION'):subject.authenticated_quote(x.root,x.descriptor)
    assert x.market.binds==1 and x.market.value==before and x.transport.calls==2


def test_failed_authentication_and_wrong_descriptor_never_trust_existing_quote(setup):
    x=setup;subject.authenticated_quote(x.root,x.descriptor);reads=x.market.reads;x.transport.failed=True
    with pytest.raises(ValueError,match='AUTHENTICATION_REFUSAL'):subject.authenticated_quote(x.root,x.descriptor)
    assert x.market.reads==reads and x.market.binds==1
    x.transport.failed=False;x.descriptor.write_bytes(b'{"changed":true}')
    with pytest.raises(ValueError,match='EXACT_APPROVED_QUOTE_DESCRIPTOR'):subject.authenticated_quote(x.root,x.descriptor)
    assert x.market.reads==reads and x.transport.calls==2


def test_unrelated_registry_error_propagates_without_binding(setup):
    x=setup;x.market.unrelated='SYNTHETIC_UNRELATED_REGISTRY_FAILURE'
    with pytest.raises(ValueError,match='UNRELATED_REGISTRY_FAILURE'):subject.authenticated_quote(x.root,x.descriptor)
    assert x.transport.calls==1 and x.market.binds==0


def test_frozen_hydrator_actual_imported_alias_is_the_new_loader_without_entry():
    cm=subject.historical_epoch(Path('/old'),Path('/out'),{})
    namespace=cm.gen.gi_frame.f_globals
    assert namespace['_quote'] is subject.authenticated_quote
    import p01_iac_unit_epoch
    assert namespace['NativeEpochSourceGate'] is p01_iac_unit_epoch.IacEpochSourceGate
    cm.gen.close()


def test_original_authentication_source_changes_only_one_bind_expression():
    original=next(n for n in ast.parse(Path(old.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='_quote')
    actual=subject._quote_body();assert actual.__globals__['bind_or_require_exact'] is subject.bind_or_require_exact
    class Replace(ast.NodeTransformer):
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and ast.unparse(node.value.func)=='merger_rights.bind_market_quote':
                return ast.copy_location(ast.parse('bind_or_require_exact(merger_rights,value)').body[0],node)
            return self.generic_visit(node)
    expected=Replace().visit(deepcopy(original))
    assert actual.__code__.co_names.count('load_authenticated_input')==1
    assert 'bind_market_quote' not in actual.__code__.co_names and 'bind_or_require_exact' in actual.__code__.co_names


def test_canonical_registry_source_is_verified_before_public_lookup(setup,monkeypatch):
    x=setup;monkeypatch.setattr(subject,'MARKET_SOURCE_SHA','0'*64)
    with pytest.raises(ValueError,match='ACTUAL516_MARKET_MODULE_SOURCE'):subject.authenticated_quote(x.root,x.descriptor)
    assert x.transport.calls==1 and x.market.reads==0 and x.market.binds==0


def test_strict_typed_cache_guard_removal_exposes_old_numeric_coalescing(setup,monkeypatch):
    x=setup;subject.authenticated_quote(x.root,x.descriptor);x.market.value['observed_market_data']=1
    with pytest.raises(ValueError,match='ENTIRE_TYPED_REGISTRATION'):subject.authenticated_quote(x.root,x.descriptor)
    tree=ast.parse(Path(subject.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='bind_or_require_exact')
    removed=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,item):
            if any(isinstance(n,ast.Constant) and n.value=='QUOTE_LIFECYCLE_ENTIRE_TYPED_REGISTRATION_EQUALS_FRESH_AUTHENTICATED_INPUT' for n in ast.walk(item)):
                removed.append(item);return ast.copy_location(ast.Pass(),item)
            return self.generic_visit(item)
    fn=Remove().visit(fn);assert len(removed)==1;namespace=dict(vars(subject))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-strict-quote-cache-guard>','exec'),namespace)
    monkeypatch.setattr(subject,'bind_or_require_exact',namespace['bind_or_require_exact'])
    value,_=subject.authenticated_quote(x.root,x.descriptor)
    assert value['observed_market_data'] is True and type(x.market.value['observed_market_data']) is int
    assert x.market.binds==1


def test_actual_canonical_once_only_source_and_public_copy_api_are_unchanged(setup):
    raw=Path(setup.market.__file__).read_bytes();assert subject.sha(raw)==subject.MARKET_SOURCE_SHA
    tree=ast.parse(raw)
    bind=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='bind_market_quote')
    getter=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='quote')
    assert '_MARKET_QUOTE is None' in ast.unparse(bind)
    assert ast.unparse(getter.body[-1])=='return deepcopy(_MARKET_QUOTE)'
    newtree=ast.parse(Path(subject.__file__).read_bytes())
    assert not any(isinstance(n,(ast.Assign,ast.AugAssign,ast.AnnAssign)) and '_MARKET_QUOTE' in ast.unparse(n) for n in ast.walk(newtree))
