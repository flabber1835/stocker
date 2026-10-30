"""Typed archive scope and AST guards; no network, restore or financial replay."""
import ast,inspect,json
from copy import deepcopy
from pathlib import Path
import pytest
import system_campaign_large_factual_admit as a


def spec():
    return dict(zip_bytes=a.GIB+4096,arm='P02',stage='campaign-factual-suffix',
        receipt_schema='research.system-p02-uncertainty-suffix-receipt/1',receipt_name='p02-uncertainty.json',
        known_opaque_ancestor=dict(path=a.ANCESTOR,bytes=a.GIB,sha256='a'*64),review_sha256='b'*64,
        inspections={'economic-worker-inspect.json':dict(exit_code=1),
                     'independent-review-stop/worker-inspect.json':dict(exit_code=0)})


def inventory():return {a.ANCESTOR:dict(bytes=a.GIB,sha256='a'*64),'book/daily.jsonl':dict(bytes=128,sha256='b'*64)}


def test_original_strict_bound_remains_unchanged_and_new_scope_is_explicit():
    x=spec();a.archive_bound(x,2*a.GIB);assert a.inventory_bound(x,inventory())
    with pytest.raises(ValueError):a.original.archive_bound(x,2*a.GIB)
    with pytest.raises(ValueError):a.admit(x,None,b'0'*32)


@pytest.mark.parametrize('kind',('arm','unreviewed','failed_review','small','too_large','second_ancestor','review_refusal'))
def test_scope_mutations_refuse(kind):
    x=spec()
    if kind=='arm':x['arm']='P01'
    if kind=='unreviewed':x['inspections'].pop('independent-review-stop/worker-inspect.json')
    if kind=='failed_review':x['inspections']['independent-review-stop/worker-inspect.json']['exit_code']=1
    if kind=='small':x['zip_bytes']=a.GIB-1
    if kind=='too_large':x['zip_bytes']=2*a.GIB
    if kind=='second_ancestor':x['known_opaque_ancestor']['path']='other/ancestor.zip'
    if kind=='review_refusal':x['review_refusal']='CONVERSION_IDENTITY_REVIEW'
    with pytest.raises(ValueError):a.archive_bound(x,2*a.GIB)


@pytest.mark.parametrize('kind',('hash','length','total','unique','member'))
def test_one_exact_opaque_member_never_relaxes_ordinary_bounds(kind):
    x=spec();v=inventory()
    if kind=='hash':v[a.ANCESTOR]['sha256']='c'*64
    if kind=='length':v[a.ANCESTOR]['bytes']+=1
    if kind=='total':v['big']={'bytes':2*a.GIB,'sha256':'d'*64}
    if kind=='unique':
        for i in range(6):v[str(i)]={'bytes':200*1024**2,'sha256':'d'*64}
    if kind=='member':v['big']={'bytes':256*1024**2,'sha256':'d'*64}
    with pytest.raises(ValueError):a.inventory_bound(x,v)


def test_exact_original_function_is_compiled_without_process_monkeypatch():
    source=Path(a.original.__file__).read_bytes();old=a.original.archive_bound;code=a.original.admit.__code__
    fn=a.compiled_admit(source)
    assert fn.__globals__['_typed_archive_bound'] is a.archive_bound
    assert fn.__globals__['_typed_inventory_bound'] is a.inventory_bound
    assert a.original.archive_bound is old and a.original.admit.__code__ is code
    with pytest.raises(ValueError):a.compiled_admit(source+b'\n')


def test_actual_ancestor_guard_removal_falsifier():
    x=spec();v=inventory();v[a.ANCESTOR]['sha256']='c'*64
    with pytest.raises(ValueError):a.inventory_bound(x,v)
    tree=ast.parse(inspect.getsource(a.inventory_bound));node=tree.body[0]
    guard=next(n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call))
    node.body.remove(guard);scope=dict(vars(a));exec(compile(ast.fix_missing_locations(tree),'<ancestor-guard-removed>','exec'),scope)
    assert scope['inventory_bound'](x,v)


def test_large_adapter_is_explicitly_selected_only_in_the_new_large_request():
    root=Path(a.__file__).parent
    old=json.loads((root/'system-campaign-p02-december-request.json').read_bytes())
    assert Path(a.__file__).name not in old['sources'] and old['source_archive_limit_bytes']==a.GIB
    request=json.loads((root/'system-campaign-p02-february-request.json').read_bytes())
    assert Path(a.__file__).name in request['sources'] and request['source_archive_limit_bytes']==2*a.GIB
