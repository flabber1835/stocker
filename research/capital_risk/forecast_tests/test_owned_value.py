"""Synthetic arithmetic/export checks; never execute the financial runtime."""
import ast,hashlib,json,sys,tarfile
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from owned_grid import metric
from owned_value import Metric,ceiling_guard,factor_dependency_guard,nav_step
from owned_value_review import ExactMetric
import owned_grid_job as job
from seal import decrypt


def test_exact_metric_matches_rational_equations_and_restores():
    anchor=('2017-12-29','50000');values=[('2018-01-02','51000'),('2018-01-03','48000'),('2018-01-04','52000'),('2018-01-05','47000')]
    value=Metric(anchor)
    for day,nav in values[:2]:value.add(day,nav)
    value=Metric(anchor,saved=json.loads(json.dumps(value.value)))
    for day,nav in values[2:]:value.add(day,nav)
    assert value.result()==metric(values,anchor)
    assert nav_step('51000','0.999')=='50949'
    independent=ExactMetric(anchor)
    for day,nav in values:independent.add(day,nav)
    assert independent.s==value.value and independent.result()==value.result()


def test_factor_dependency_rejects_nav_sensitive_multiplier():
    raw="""def _advance_strategy_economics():
    prior_nav = D(prior['strategy_nav'])
    pending = target
    strategy_nav = prior_nav * net_factor
    return {'previous_strategy_nav': prior_nav, 'pending': pending, 'nav': strategy_nav}
"""
    assert factor_dependency_guard(raw)['prior_nav_loads']==2
    with pytest.raises(ValueError):factor_dependency_guard(raw.replace('pending = target','pending = target\n    net_factor = prior_nav / 50'))
    tree=ast.parse(Path(job.__file__).with_name('owned_value.py').read_bytes());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='factor_dependency_guard')
    f.body=[n for n in f.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='need')]
    scope={};exec(compile(ast.Module(body=[f],type_ignores=[]),'<removed-factor-guard>','exec'),{'ast':ast},scope)
    assert scope[f.name](raw.replace('pending = target','pending = target\n    net_factor = prior_nav / 50'))['prior_nav_loads']==2


def test_ceiling_dependency_guard_rejects_state_predicate_read():
    raw="""def step():
    after = State()
    ceiling = RULE['active_ceiling'] if active else 1.
    return after, ceiling
"""
    assert ceiling_guard(raw)['reads']==1
    with pytest.raises(ValueError):ceiling_guard(raw.replace('after = State()',"after = State(RULE['active_ceiling'])"))
    tree=ast.parse(Path(job.__file__).with_name('owned_value.py').read_bytes());function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ceiling_guard')
    function.body=[n for n in function.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='need')]
    scope={};exec(compile(ast.Module(body=[function],type_ignores=[]),'<removed-ceiling-guard>','exec'),{'ast':ast},scope)
    assert scope['ceiling_guard'](raw.replace('after = State()',"after = State(RULE['active_ceiling'])"))['reads']==1


def test_partition_refuses_oversize_member():
    assert len(job.partition({'a':{'bytes':40},'b':{'bytes':40}},bound=64))==2
    with pytest.raises(ValueError):job.partition({'a':{'bytes':65}},bound=64)
    tree=ast.parse(Path(job.__file__).read_bytes());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='partition')
    for n in ast.walk(f):
        if hasattr(n,'body') and isinstance(n.body,list):n.body[:]=[x for x in n.body if not (isinstance(x,ast.Expr) and isinstance(x.value,ast.Call) and isinstance(x.value.func,ast.Name) and x.value.func.id=='need')]
    scope={};exec(compile(ast.Module(body=[f],type_ignores=[]),'<removed-member-bound>','exec'),{},scope)
    assert scope[f.name]({'a':{'bytes':65}},bound=64)[0]['a']['bytes']==65


def test_real_part_export_finalizes_gcm_and_durable_receipt(tmp_path,monkeypatch):
    root=tmp_path/'markers';root.mkdir();(root/'a').write_bytes(b'fixed marker A'*3);(root/'b').write_bytes(b'fixed marker B'*3)
    original=job.partition;monkeypatch.setattr(job,'partition',lambda m:original(m,bound=64))
    receipt={'status':'SYNTHETIC_COMPLETE','protocol_sha256':'1'*64,'request_sha256':'2'*64};path=tmp_path/'owned-grid.json';key=bytes(range(32))
    job.encrypt_parts(root,path,key,receipt);saved=json.loads(path.read_bytes())
    assert saved['status']=='SYNTHETIC_COMPLETE' and len(saved['encrypted_outputs'])==saved['output_parts_expected']==2
    for i,spec in enumerate(saved['encrypted_outputs']):
        plain=tmp_path/f'part-{i}.tar';decrypt(tmp_path/spec['name'],plain,key,spec['sha256'])
        with tarfile.open(plain,'r|gz') as archive:
            first=archive.next();raw=archive.extractfile(first).read();assert hashlib.sha256(raw).hexdigest()==spec['manifest_sha256'];manifest=json.loads(raw)
            seen=set()
            while item:=archive.next():
                payload=archive.extractfile(item).read();assert payload==(root/item.name).read_bytes();seen.add(item.name)
            assert seen==set(manifest['members'])
        assert manifest['part_index']==i and manifest['parts']==2 and len(manifest['members'])==1
        for name,v in manifest['members'].items():assert v['sha256']==hashlib.sha256((root/name).read_bytes()).hexdigest()
