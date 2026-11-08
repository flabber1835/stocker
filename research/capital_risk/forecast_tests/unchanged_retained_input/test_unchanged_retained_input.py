"""Pure metadata/source AST falsifiers; no canonical imports or execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

C=Path(__file__).resolve().parents[2]
SOURCE=C/'system_campaign_financial_uncertainty.py'
FIXTURE=Path(__file__).parent/'fixtures/P07-own1028-input-metadata.json'
F=json.loads(FIXTURE.read_bytes())
OLD='f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776'

def need(ok,label):
    if not ok:raise ValueError(label)

def functions(*,remove_pin=False,remove_guard=None):
    tree=ast.parse(SOURCE.read_bytes());nodes=[]
    names={'UNCHANGED_INPUT_SEEDS','UNCHANGED_INPUT','POINT_WITNESS_SHA','MODEL_ADOPTION'}
    functions_={'unchanged_input_phase','unchanged_input_receipt','review_unchanged_input'}
    for node in tree.body:
        if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id in names for t in node.targets):nodes.append(node)
        elif isinstance(node,ast.FunctionDef)and node.name in functions_:nodes.append(node)
    if remove_guard:
        calls=[n for root in nodes for n in ast.walk(root)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'
               and len(n.args)==2 and isinstance(n.args[1],ast.Constant)and n.args[1].value==remove_guard]
        assert len(calls)==1;calls[0].args[0]=ast.Constant(True)
    ns=dict(need=need,deepcopy=deepcopy,json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<pure-unchanged-input-metadata>','exec'),ns)
    if remove_pin:ns['UNCHANGED_INPUT_SEEDS']=ns['UNCHANGED_INPUT_SEEDS']-{F['pin']}
    return ns

def parent():return deepcopy(F['checkpoint_metadata'])
def spec(pin=None):return dict(root_admission_sha256=F['pin']if pin is None else pin)
def receipt_file(ns,root,cp):
    file=root/ns['UNCHANGED_INPUT'];file.parent.mkdir(parents=True)
    file.write_bytes((json.dumps(ns['unchanged_input_receipt'](cp,spec()),sort_keys=True,indent=2)+'\n').encode())

def test_exact_pin_and_old_unchanged_phase_registered_without_other_new_roots():
    ns=functions();assert ns['UNCHANGED_INPUT_SEEDS']==frozenset({F['pin'],OLD})
    assert ns['unchanged_input_phase'](spec()) and ns['unchanged_input_phase'](spec(OLD))
    assert not ns['unchanged_input_phase'](spec('0'*64))

def test_registration_removal_reproduces_prelaunch_phase_omission():
    assert functions()['unchanged_input_phase'](spec())
    assert not functions(remove_pin=True)['unchanged_input_phase'](spec())

def test_receipt_preserves_all20_descriptors_and_existing_input_without_overlay():
    ns=functions();cp=parent();got=ns['unchanged_input_receipt'](cp,spec())
    assert len(got['repairs'])==20 and got['repairs']==cp['repairs']
    assert got['input_sha256']==F['input_sha256'] and got['completed']==1028 and got['source_cursor']=='2022-01-31'
    assert got['new_factual_overlay'] is got['financial_source_changed'] is False
    got['repairs'].clear();assert len(cp['repairs'])==20

def test_unregistered_receipt_refuses_and_removing_registration_guard_is_detected():
    with pytest.raises(ValueError,match='EXACT_REGISTERED_PHASE'):functions()['unchanged_input_receipt'](parent(),spec('0'*64))
    altered=functions(remove_guard='FINANCIAL_NO_NEW_INPUT_EXACT_REGISTERED_PHASE')
    assert altered['unchanged_input_receipt'](parent(),spec('0'*64))['root_admission_sha256']=='0'*64

def test_exact_unchanged_receipt_review(tmp_path):
    ns=functions();cp=parent();receipt_file(ns,tmp_path,cp)
    ns['review_unchanged_input'](cp,deepcopy(cp),tmp_path,spec())

@pytest.mark.parametrize('changed',['repairs','input','base','overlay','adoption'])
def test_new_adoption_or_changed_input_refuses(tmp_path,changed):
    ns=functions();cp=parent();current=deepcopy(cp);receipt_file(ns,tmp_path,cp)
    if changed=='repairs':current['repairs']=current['repairs'][:-1]
    if changed=='input':current['run']['input_sha256']='0'*64
    if changed=='base':current['base']['capital']='changed'
    if changed=='overlay':(tmp_path/'future-financial-overlay.json').write_text('{}')
    if changed=='adoption':(tmp_path/ns['MODEL_ADOPTION']).mkdir()
    with pytest.raises(ValueError,match='EXACT_UNCHANGED_INPUT'):ns['review_unchanged_input'](cp,current,tmp_path,spec())

def test_review_guard_removal_is_detected(tmp_path):
    ns=functions();cp=parent();changed=deepcopy(cp);changed['repairs'].pop();receipt_file(ns,tmp_path,cp)
    with pytest.raises(ValueError,match='EXACT_UNCHANGED_INPUT'):ns['review_unchanged_input'](cp,changed,tmp_path,spec())
    altered=functions(remove_guard='FINANCIAL_RETAINED_PROOF_EXACT_UNCHANGED_INPUT')
    altered['review_unchanged_input'](cp,changed,tmp_path,spec())

def test_existing_run_retained_unchanged_branch_does_not_prepare_another_repair():
    fn=next(n for n in ast.parse(SOURCE.read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='run_retained')
    branch=next(n for n in fn.body if isinstance(n,ast.If)and ast.unparse(n.test)=='unchanged')
    yes=ast.unparse(ast.Module(body=branch.body,type_ignores=[]));no=ast.unparse(ast.Module(body=branch.orelse,type_ignores=[]))
    assert 'unchanged_input_receipt(cp, spec)'in yes and 'nullcontext()'in yes and 'prepare('not in yes
    assert 'prepare(cp, out, arm)'in no and 'ActualEvents('in no
    assert "extra = [] if unchanged else ['--repair-overlay', str(path)]"in ast.unparse(fn)
