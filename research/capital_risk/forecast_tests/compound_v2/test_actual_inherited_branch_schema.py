"""Actual own838 inputs and unchanged B19/preflight DATA ASTs, no finance."""
import ast
from collections import defaultdict
from copy import deepcopy
import hashlib
import importlib.abc
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import system_campaign_financial_compound_ordinary_v2 as o
import system_campaign_financial_compound_input_v2 as model

F=Path(__file__).parent/'fixtures/actual-own838-inherited-repairs.json'
OLD='research.leadership-uncertainty-input/1';NEW='research.leadership-branch-uncertainty-input/1'

class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise AssertionError('NO_FINANCIAL_IMPORT:'+fullname)

@pytest.fixture(autouse=True)
def imported():
    fence=Fence();sys.meta_path.insert(0,fence);yield;sys.meta_path.remove(fence)

def data():
    raw=F.read_bytes();value=json.loads(raw)
    assert o.sha(raw)=='08a3d38514e5d1e2b21d3eff741be0aae2fb05f08c34f7f3345c392fff08de0c'
    assert value['schema']=='research.actual-retained-input-schema-regression-fixture/1'
    assert value['original_helper_sha256']=='1698a17299484a7ec3811838d1ac936f864ec74e1c063e37fef68daf261ce507'
    assert value['branch_sha256']=='b116e17c4cbfc7f7296fdff67e74a2c9d2368e37216233f24461a7e61edeeb01'
    assert value['actual_parent_outer_sha256']=='5d69ef0267188397137b2064f9a2225a6141bb966c5a218531ccc59671158391'
    assert value['no_financial_state_or_engine'] is True and len(value['descriptors'])==len(value['documents'])==18
    assert 'state' not in value['parent_metadata']['run']
    return value

def old_function():
    value=data();node,=ast.parse(value['original_inherited_proof']).body
    assert o.sha(ast.dump(node,include_attributes=False).encode())==value['original_inherited_proof_AST_sha256']
    namespace=dict(vars(o));exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<exact-failed-original-inherited-proof>','exec'),namespace)
    return namespace['inherited_proof']

def fixture(tmp_path):
    value=data();folder=tmp_path/'book/repairs';folder.mkdir(parents=True)
    for descriptor in value['descriptors']:
        raw=value['documents'][descriptor['filename']].encode();assert o.sha(raw)==descriptor['sha256']
        (folder/descriptor['filename']).write_bytes(raw)
    cp=deepcopy(value['parent_metadata'])
    raw=(Path(model.__file__).parent/'system_campaign_financial_branches.py').read_bytes()
    assert o.sha(raw)==value['exact_selected_B19_sha256']==o.BRANCH_SHA
    source=ast.parse(raw);statement=next(n for n in source.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='INPUT' for t in n.targets))
    assert ast.literal_eval(statement.value)==NEW
    node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='validate_input');calls=[]
    branch_doc=json.loads(value['documents'][value['branch_sha256']+'.json'])
    def parse(path,*,resume_session,predecessor_checkpoint_sha256,expected_evidence):
        raw=Path(path).read_bytes();doc=json.loads(raw)
        assert doc['schema']==NEW and doc['source_evidence']==expected_evidence
        assert doc['predecessor_checkpoint_sha256']==predecessor_checkpoint_sha256 and resume_session<doc['session']
        calls.append(dict(path=path,cursor=resume_session,predecessor=predecessor_checkpoint_sha256))
        return SimpleNamespace(sha256=o.sha(raw))
    namespace=dict(Path=Path,json=json,hashlib=hashlib,need=o.need,INPUT=NEW,parse=parse,evidence=lambda root:branch_doc['source_evidence'])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<unchanged-B19-input-validator-with-captured-pure-parser-metadata>','exec'),namespace)
    catalog=json.loads((Path(model.__file__).parent/'system-campaign-february-cash-calendar-terminal-facts.json').read_bytes())
    catalog['terms']=[t for t in catalog['terms'] if t['ticker']=='VCRA'];assert len(catalog['terms'])==1
    return cp,catalog,namespace['validate_input'],calls

def preflight():
    raw=(Path(model.__file__).parent/'system_campaign_action_preflight.py').read_bytes();assert o.sha(raw)==o.PREFLIGHT_SHA
    nodes=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)]
    namespace=dict(Path=Path,json=json,re=re,defaultdict=defaultdict,need=o.need,digest=o.digest,sha=o.sha)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<unchanged-original-collision-preflight>','exec'),namespace)
    return namespace

def test_actual242_failure_reproduces_and_exact_selected_B19_schema_is_accepted(tmp_path):
    cp,catalog,validate,calls=fixture(tmp_path)
    with pytest.raises(ValueError,match='ALL_INHERITED_ORDINARY_AND_BRANCH_BYTES'):
        old_function()(cp,tmp_path,catalog,branch_validator=validate)
    assert calls==[]
    proof=o.inherited_proof(cp,tmp_path,catalog,branch_validator=validate)
    assert len(calls)==1 and proof['original_branch_validated'] is True
    assert [r['descriptor'] for r in proof['retained_inputs']]==cp['repairs']

def test_original_preflight_still_refuses_full18_and_qualified_view_checks_all17(tmp_path):
    cp,catalog,validate,calls=fixture(tmp_path);original=deepcopy(cp);logic=preflight()
    proof=o.inherited_proof(cp,tmp_path,catalog,branch_validator=validate)
    with pytest.raises(ValueError,match='ACTION_PREFLIGHT_DECLARED_ORDINARY_SCHEMA'):
        logic['analyze_new_catalog'](cp,tmp_path,catalog)
    view,witness=o.qualified_collision_parent(cp,proof)
    report=logic['analyze_new_catalog'](view,tmp_path,catalog);logic['require_disjoint'](report)
    assert report['retained_ordinary_repairs']==17 and report['financial_sessions_advanced']==0
    assert cp==original and len(cp['repairs'])==18
    assert {k:v for k,v in view.items() if k!='repairs'}=={k:v for k,v in cp.items() if k!='repairs'}
    assert witness['omitted_validated_branch_sha256']==data()['branch_sha256'] and witness['retained_ordinary_count']==17
    assert witness['all_original_descriptors_sha256']==o.digest(cp['repairs'])
    assert witness['parent_outer_sha256']==cp['sha256'] and witness['parent_input_sha256']==cp['run']['input_sha256']
    assert witness['collision_analysis_only'] is True and witness['financial_authority'] is witness['input_adopted'] is False

@pytest.mark.parametrize('change',['legacy','raw','no_branch','two_branch','wrong_branch_result','target_addition'])
def test_actual_inherited_bytes_schema_branch_and_genuine_target_guards_remain(change,tmp_path):
    cp,catalog,validate,calls=fixture(tmp_path)
    branch=next(d for d in cp['repairs'] if d['sha256']==data()['branch_sha256']);path=tmp_path/'book/repairs'/branch['filename']
    if change=='legacy':
        doc=json.loads(path.read_bytes());doc['schema']=OLD;raw=o.encoded(doc);h=o.sha(raw)
        path.with_name(h+'.json').write_bytes(raw);branch.update(filename=h+'.json',sha256=h)
    elif change=='raw':path.write_bytes(path.read_bytes()+b' ')
    elif change=='no_branch':cp['repairs'].remove(branch)
    elif change=='two_branch':cp['repairs'].append(deepcopy(branch))
    elif change=='wrong_branch_result':validate=lambda *a:'f'*64
    else:
        descriptor=cp['repairs'][0];file=tmp_path/'book/repairs'/descriptor['filename'];doc=json.loads(file.read_bytes())
        doc['add'].append(deepcopy(catalog['terms'][0]['added']));raw=o.encoded(doc);h=o.sha(raw)
        file.with_name(h+'.json').write_bytes(raw);descriptor.update(filename=h+'.json',sha256=h)
    with pytest.raises((ValueError,AssertionError)):o.inherited_proof(cp,tmp_path,catalog,branch_validator=validate)

@pytest.mark.parametrize('change',['not_validated','bytes_not_checked','source','descriptor','unknown_schema','missing_branch'])
def test_collision_view_cannot_filter_an_unqualified_or_other_descriptor_set(change,tmp_path):
    cp,catalog,validate,calls=fixture(tmp_path);proof=o.inherited_proof(cp,tmp_path,catalog,branch_validator=validate)
    if change=='not_validated':proof['original_branch_validated']=False
    elif change=='bytes_not_checked':proof['all_original_input_bytes_verified']=False
    elif change=='source':proof['original_branch_source_sha256']='f'*64
    elif change=='descriptor':proof['retained_inputs'][0]['descriptor']['resume_session']='2021-04-30'
    elif change=='unknown_schema':proof['retained_inputs'][0]['schema']='unqualified/1'
    else:proof['retained_inputs']=[v for v in proof['retained_inputs'] if v['schema']!=NEW]
    with pytest.raises(ValueError):o.qualified_collision_parent(cp,proof)

def test_ordinary_collision_guards_remain_after_exact_branch_view(tmp_path):
    cp,catalog,validate,calls=fixture(tmp_path);proof=o.inherited_proof(cp,tmp_path,catalog,branch_validator=validate)
    view,_=o.qualified_collision_parent(cp,proof);logic=preflight()
    prior=next(t for d in view['repairs'] for t in json.loads((tmp_path/'book/repairs'/d['filename']).read_bytes())['add'])
    collision=dict(terms=[dict(ticker='existing',security_id=prior['security_id'],native_session=prior['session'],added=prior)])
    report=logic['analyze_new_catalog'](view,tmp_path,collision)
    assert any(v['reason']=='RETAINED_ADDITION_KEY_ALREADY_PRESENT' for v in report['conflicts'])
    with pytest.raises(ValueError,match='DISJOINT_UNCONSUMED'):logic['require_disjoint'](report)

def test_view_qualification_guard_removal_really_admits_missing_B19_validation(tmp_path):
    cp,catalog,validate,calls=fixture(tmp_path);proof=o.inherited_proof(cp,tmp_path,catalog,branch_validator=validate);proof['original_branch_validated']=False
    with pytest.raises(ValueError):o.qualified_collision_parent(cp,proof)
    node=next(n for n in ast.parse(Path(o.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='qualified_collision_parent')
    node.body=[n for n in node.body if not isinstance(n,ast.Expr) or not any(isinstance(v,ast.Constant) and v.value=='COMPOUND_V2_COLLISION_VIEW_ONLY_AFTER_COMPLETE_EXACT_B19_VALIDATION' for v in ast.walk(n))]
    namespace=dict(vars(o));exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-qualified-collision-view-guard>','exec'),namespace)
    view,_=namespace['qualified_collision_parent'](cp,proof);assert len(view['repairs'])==17

def test_hosted_hydrator_receives_only_the_scoped_view_material_retains_full_origin():
    function=next(n for n in ast.parse(Path(o.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='ordinary_input')
    source=ast.unparse(function)
    assert 'inherited_proof(origin, root, subset, branch_validator=branch.validate_input)' in source
    assert 'qualified_collision_parent(origin, inherited)' in source
    assert 'codec.hydrate(collision_parent, Path(root), Path(temp))' in source
    assert 'original_parent=origin' in source and 'ordinary_collision_view=collision_view' in source
