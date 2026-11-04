"""Own admitted reporting seeds and exact retained codecs; DATA/synthetic only."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import pytest

CAP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CAP))
import system_campaign_financial_partial as p
import system_campaign_financial_resume as m
import system_campaign_financial_branches as b
import system_campaign_parallel_discovery_run as frozen


def test_all_current_reporting_seeds_are_closest_admitted_own_checkpoints():
    specs=json.loads((CAP/m.PARTIALS).read_bytes())['arms']
    assert {a:p.reporting_seed(specs[a])['measured_closes'] for a in ('P04','P07','P10')}==dict(P04=1132,P07=565,P10=1592)
    assert {a:specs[a]['measured_closes'] for a in ('P04','P07','P10')}==dict(P04=1175,P07=628,P10=2156)
    assert all(specs[a]['financial_authority'] is specs[a]['financial_predecessor_admitted'] is False for a in specs)


@pytest.mark.parametrize('change',['already_admitted','older_seed'])
def test_request_refuses_repeating_closed_reporting_or_substituting_older_seed(monkeypatch,change):
    monkeypatch.setattr(m,'COMPLETED_ADMISSIONS',{})
    monkeypatch.setattr(m,'SELECTED_ARMS',('P10',))
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    original=m.root_spec
    def altered(arm,*args):
        root=deepcopy(original(arm,*args))
        if change=='already_admitted':root['measured_closes']=json.loads((CAP/m.PARTIALS).read_bytes())['arms'][arm]['measured_closes']
        else:root['root_admission_sha256']='0'*64
        return root
    monkeypatch.setattr(m,'root_spec',altered)
    with pytest.raises(ValueError,match='ONLY_NEW_SUFFIX_FROM_CURRENT_ADMITTED_REPORTING_SEED'):m.expected_request()


def test_new_reporting_scope_guard_removal_falsifier(monkeypatch):
    monkeypatch.setattr(m,'COMPLETED_ADMISSIONS',{})
    monkeypatch.setattr(m,'SELECTED_ARMS',('P10',))
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    original=m.root_spec
    monkeypatch.setattr(m,'root_spec',lambda arm:dict(original(arm),measured_closes=json.loads((CAP/m.PARTIALS).read_bytes())['arms'][arm]['measured_closes']))
    with pytest.raises(ValueError):m.expected_request()
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='expected_request')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and
                a.value=='RESUME_ONLY_NEW_SUFFIX_FROM_CURRENT_ADMITTED_REPORTING_SEED' for a in node.value.args):
                self.count+=1;return ast.Pass()
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1
    ns=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-new-reporting-scope-guard>','exec'),ns)
    assert ns['expected_request']()['readonly_partial_review'] is True


@pytest.mark.parametrize('change',['admission','source','count','cursor','arm'])
def test_wrong_admission_source_axis_or_arm_cannot_seed_reporting(change):
    spec=deepcopy(json.loads((CAP/m.PARTIALS).read_bytes())['arms']['P04'])
    if change=='admission':spec['monthly_seed_root_admission_sha256']='0'*64
    elif change=='source':spec['base']['sources'][next(iter(spec['base']['sources']))]='0'*64
    elif change=='count':spec['measured_closes']=800
    elif change=='cursor':spec['selected_session']='2021-03-30'
    else:spec['arm']='P10'
    with pytest.raises(ValueError):p.reporting_seed(spec)


def test_admitted_seed_guard_removal_falsifier(monkeypatch):
    spec=deepcopy(json.loads((CAP/m.PARTIALS).read_bytes())['arms']['P04'])
    seed=p.root_spec('P04',p.PRIOR_ADMISSIONS['P04']);seed['root_admission_sha256']='0'*64
    monkeypatch.setattr(p,'root_spec',lambda *args:seed)
    with pytest.raises(ValueError):p.reporting_seed(spec)
    fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='reporting_seed')
    branch=next(n for n in fn.body if isinstance(n,ast.If) and any(isinstance(v,ast.Constant) and v.value=='monthly_seed_root_admission_sha256' for v in ast.walk(n.test)));branch.body.pop(1);ns=dict(vars(p))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-admitted-seed-guard>','exec'),ns)
    with pytest.raises(AssertionError):
        try:ns['reporting_seed'](spec)
        except ValueError:refused=True
        else:refused=False
        assert refused


def test_retainer_adapter_undo_recovers_the_entire_frozen_function():
    original=next(n for n in ast.parse(Path(frozen.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='retained_inputs')
    predicate=next(n.value.args[0] for n in ast.walk(original) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='PARALLEL_NO_UNSELECTED_CONDITIONAL_INPUT_MODELS' for a in n.value.args))
    class Undo(ast.NodeTransformer):
        guard=codec=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='PARALLEL_NO_UNSELECTED_CONDITIONAL_INPUT_MODELS' for a in node.value.args):
                assert ast.unparse(node.value.args[0])=='retained_models(root, parent, selected_spec)'
                node.value.args[0]=deepcopy(predicate);self.guard+=1;return node
            if ast.unparse(node)=='stack.enter_context(model_context(root, parent, selected_spec))':
                self.codec+=1;return None
            return self.generic_visit(node)
    undo=Undo();restored=undo.visit(p.retention_tree())
    assert undo.guard==undo.codec==1 and ast.dump(restored,include_attributes=False)==ast.dump(original,include_attributes=False)


def typed_book(tmp_path):
    root=tmp_path/'old';root.mkdir();(root/'book/repairs').mkdir(parents=True)
    (root/'hydrated-uncertainty-event.json').write_bytes(b'{"synthetic_event":true}\n')
    original=dict(source_cursor='2019-09-30',run=dict(checkpoint_sha256='a'*64))
    path=b.overlay(original,root);raw=path.read_bytes();h=p.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw)
    cp=dict(repairs=[dict(filename=h+'.json',sha256=h,resume_session=original['source_cursor'],predecessor_checkpoint_sha256='a'*64)])
    return root,cp,dict(arm='P07',retained_uncertainty_model=b.INPUT)


def test_model_retainer_validates_entire_original_book_without_mutation(tmp_path):
    root,cp,spec=typed_book(tmp_path);saved=deepcopy(cp)
    assert p.retained_models(root,cp,spec) is True and cp==saved
    assert p.retained_models(root,cp,dict(arm='P07')) is False


@pytest.mark.parametrize('change',['scope','unknown','duplicate','evidence','missing'])
def test_unselected_or_misbound_model_refuses(tmp_path,change):
    root,cp,spec=typed_book(tmp_path)
    if change=='scope':spec['arm']='P04'
    elif change=='unknown':spec['retained_uncertainty_model']='unknown/1'
    elif change=='duplicate':cp['repairs'].append(deepcopy(cp['repairs'][0]))
    elif change=='missing':cp['repairs'].clear()
    else:(root/'hydrated-uncertainty-event.json').write_bytes(b'changed')
    with pytest.raises(ValueError):p.retained_models(root,cp,spec)


def test_source_bound_retainer_preserves_actual_checkpoint_documents_and_hydration_guard(tmp_path,monkeypatch):
    root,cp,spec=typed_book(tmp_path);out=tmp_path/'out';out.mkdir();calls=[]
    (root/'hydrated-factual-catalog.json').write_bytes(b'exact synthetic hydration')
    class FakeCodec:
        changed=False
        def __init__(self,*a):pass
        def hydrate(self,path):path.write_bytes(b'changed' if self.changed else b'exact synthetic hydration')
        def __enter__(self):calls.append('factual-enter');return self
        def __exit__(self,*a):calls.append('factual-exit')
    @contextmanager
    def model(root_arg,parent_arg,spec_arg):
        assert root_arg is root and parent_arg is cp and spec_arg is spec
        calls.append('model-enter');yield;calls.append('model-exit')
    monkeypatch.setattr(frozen,'hosted',lambda:None)
    monkeypatch.setattr(frozen,'FactualInputs',FakeCodec)
    monkeypatch.setattr(p,'model_context',model)
    with p.financial_inputs(root,cp,out,spec):calls.append('body')
    assert calls==['factual-enter','model-enter','body','model-exit','factual-exit']
    name=cp['repairs'][0]['filename'];assert (out/'book/repairs'/name).read_bytes()==(root/'book/repairs'/name).read_bytes()
    calls.clear();FakeCodec.changed=True;other=tmp_path/'other';other.mkdir()
    with pytest.raises(ValueError,match='HYDRATION_BYTES'):
        with p.financial_inputs(root,cp,other,spec):raise AssertionError('must refuse before body')
    assert calls==[]


def test_retained_model_scope_guard_removal_falsifier(tmp_path):
    root,cp,spec=typed_book(tmp_path);spec['arm']='P04'
    with pytest.raises(ValueError):p.retained_models(root,cp,spec)
    fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='retained_models')
    site=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='PARTIAL_ONLY_EXACT_SELECTED_RETAINED_MODEL' for a in n.value.args))
    fn.body.remove(site);ns=dict(vars(p));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-model-scope-guard>','exec'),ns)
    with pytest.raises(AssertionError):
        try:ns['retained_models'](root,cp,spec)
        except ValueError:refused=True
        else:refused=False
        assert refused


def preflight_fixture(tmp_path,monkeypatch):
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(readonly_source_witnesses=False)))
    monkeypatch.setattr(m,'REQUEST',request)
    old,out=tmp_path/'old',tmp_path/'out';(old/'book').mkdir(parents=True);(old/'stopped-review').mkdir();out.mkdir()
    cp=dict(sha256='a'*64,completed=1090)
    (old/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    review=dict(all_prefixes_verified=True,all_daily_factors_and_chains_verified=True,checkpoint_sha256=cp['sha256'],counts=dict(formation=126,daily=1090))
    path=old/'stopped-review/core-review.json';path.write_bytes(json.dumps(review).encode())
    spec=dict(arm='P04',selected_checkpoint='book/checkpoint.json.gz',outer_sha256=cp['sha256'],selected_file={},
        archive_format='FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1',review_sha256=p.sha(path.read_bytes()),reuse_closed_hosted_prefix_review=True)
    @contextmanager
    def retained(root,parent,output,selected):
        assert root is old and output is out and parent==cp and selected is spec
        yield
    monkeypatch.setattr(m,'hosted',lambda:None);monkeypatch.setattr(m,'financial_inputs',retained)
    monkeypatch.setattr(m,'strict_parent',lambda value,spec:value)
    monkeypatch.setattr(m,'actual_parent',lambda *a:(cp,'2022-05-02'))
    monkeypatch.setattr(m,'seed_rows',lambda *a:None)
    monkeypatch.setattr(m,'readonly_review',lambda *a:(_ for _ in ()).throw(AssertionError('closed audit repeated')))
    calls=[];monkeypatch.setattr(m,'monthly_reproduction',lambda *a:calls.append('new reporting only'))
    return old,out,spec,calls


def test_reused_exact_closed_review_supplies_no_new_financial_authority(tmp_path,monkeypatch):
    old,out,spec,calls=preflight_fixture(tmp_path,monkeypatch);m.preflight(old,out,spec)
    assert calls==['new reporting only']
    proof=json.loads((out/'strict-parent-preflight.json').read_bytes())
    assert proof['financial_sessions_advanced']==0 and proof['root_admission_sha256'] is None
    assert (out/'old-prefix-canonical-review.json').read_bytes()==(old/'stopped-review/core-review.json').read_bytes()


@pytest.mark.parametrize('change',['flag','hash','counts'])
def test_closed_review_reuse_requires_exact_boolean_bytes_and_current_count(tmp_path,monkeypatch,change):
    old,out,spec,calls=preflight_fixture(tmp_path,monkeypatch)
    if change=='flag':spec['reuse_closed_hosted_prefix_review']=1
    elif change=='hash':spec['review_sha256']='0'*64
    else:
        path=old/'stopped-review/core-review.json';v=json.loads(path.read_bytes());v['counts']['daily']=1091;path.write_bytes(json.dumps(v).encode());spec['review_sha256']=p.sha(path.read_bytes())
    with pytest.raises(ValueError):m.preflight(old,out,spec)
    assert calls==[]
