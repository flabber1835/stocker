"""Input-only resources and noncanonical DTOs; no actual book is staged."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_bounded_runtime_v2 import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_bounded_sensor_runtime_v2 as runtime
import system_campaign_bounded_sensor_full_models_v2 as data
from system_campaign_bounded_sensor_lifecycle_data import document,evidence
from system_campaign_bounded_sensor_catalog import encoded

@pytest.fixture
def dto(tmp_path):
    c=runtime.catalog();meta=runtime.metadata();root=tmp_path/'source-inputs-only'
    raw=encoded(document(c,root_lookup=lambda *a:meta));assert data.sha(raw)==data.TYPED_SHA
    p=root/'book/repairs'/(data.TYPED_SHA+'.json');p.parent.mkdir(parents=True);p.write_bytes(raw)
    d=dict(filename=data.TYPED_SHA+'.json',sha256=data.TYPED_SHA,resume_session=c['parent_cursor'],predecessor_checkpoint_sha256=c['parent_inner_sha256'])
    cp=dict(schema='NONCANONICAL_INPUT_METADATA_DTO',noncanonical=True,base=meta['base'],repairs=deepcopy(c['parent_descriptors'])+[d],run={})
    tail=encoded(dict(schema='terminal-repair/1',synthetic_input_metadata_only=True,add=[]));pin=data.sha(tail)
    (p.parent/(pin+'.json')).write_bytes(tail)
    cp['repairs'].append(dict(filename=pin+'.json',sha256=pin,resume_session='2019-11-29',predecessor_checkpoint_sha256='f'*64))
    cp['run']['input_sha256']=data.digest(dict(base=cp['base'],repairs=cp['repairs']))
    return root,cp,c,meta

def check(a,cp=None,fn=None):
    root,current,c,meta=a
    return (data.descriptor if fn is None else fn)(root,current if cp is None else cp,c,evidence(c),
        input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),root_metadata=meta)

def test_full17_metadata_list_preserves_exact16th_typed_and_full_hash(dto):
    assert check(dto)['sha256']==data.TYPED_SHA
    assert not (dto[0]/'book/checkpoint.json.gz').exists()

@pytest.mark.parametrize('change',['input_hash','base','prefix','typed_hash','typed_predecessor','tail_name','tail_bytes','tail_schema'])
def test_wrong_full_input_identity_and_every_tail_refuse(dto,change):
    root,cp,c,meta=dto;cp=deepcopy(cp)
    if change=='input_hash':cp['run']['input_sha256']='0'*64
    elif change=='base':cp['base']={'FOREIGN':True}
    elif change=='prefix':cp['repairs'][0]['sha256']='0'*64
    elif change=='typed_hash':cp['repairs'][15]['sha256']='0'*64
    elif change=='typed_predecessor':cp['repairs'][15]['predecessor_checkpoint_sha256']='0'*64
    elif change=='tail_name':cp['repairs'][-1]['filename']='../foreign.json'
    elif change=='tail_bytes':
        p=root/'book/repairs'/cp['repairs'][-1]['filename'];p.write_bytes(p.read_bytes()+b' ')
    else:
        raw=encoded(dict(schema='UNQUALIFIED_MODEL',synthetic_input_metadata_only=True));pin=data.sha(raw)
        (root/'book/repairs'/(pin+'.json')).write_bytes(raw);cp['repairs'][-1].update(filename=pin+'.json',sha256=pin)
    if change!='input_hash':cp['run']['input_sha256']=data.digest(dict(base=cp['base'],repairs=cp['repairs']))
    with pytest.raises(ValueError):check(dto,cp)

def test_removing_full_input_guard_accepts_wrong_epoch_and_is_detected(dto):
    cp=deepcopy(dto[1]);cp['run']['input_sha256']='0'*64
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='descriptor')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(x,ast.Constant)
        and x.value=='BOUNDED_FULL_CURRENT_UNTRUNCATED_HISTORY_AND_INPUT_HASH' for x in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-guard-input-metadata-only>','exec'),scope)
    with pytest.raises(ValueError):check(dto,cp)
    assert check(dto,cp,scope['descriptor'])['sha256']==data.TYPED_SHA
