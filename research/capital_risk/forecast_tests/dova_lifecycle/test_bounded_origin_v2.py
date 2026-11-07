"""In-memory noncanonical origin DTOs; never a financial checkpoint or book."""
import gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_bounded_runtime_v2 import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_bounded_sensor_origin_v2 as data
import system_campaign_bounded_sensor_runtime_v2 as runtime

def finish(cp):
    cp['run']['state_sha256']=data.digest(cp['run']['state'])
    cp['run']['input_sha256']=data.digest(dict(base=cp['base'],repairs=cp['repairs']))
    cp['run']['checkpoint_sha256']=data.digest({k:v for k,v in cp['run'].items() if k!='checkpoint_sha256'})
    cp['sha256']=data.digest({k:v for k,v in cp.items() if k!='sha256'})
    return cp

@pytest.fixture
def dto():
    c=deepcopy(runtime.catalog());members={};repairs=[]
    for i in range(15):
        raw=data.encoded(dict(SYNTHETIC_SOURCE_INPUT_METADATA_ONLY=i));pin=data.sha(raw)
        repairs.append(dict(filename=pin+'.json',sha256=pin,resume_session='2019-01-02',predecessor_checkpoint_sha256='0'*64))
        members['book/repairs/'+pin+'.json']=raw
    parent=finish(dict(schema='NONCANONICAL_ORIGIN_METADATA_DTO',NONCANONICAL_NO_FINANCIAL_STATE=True,
        base={'SYNTHETIC_METADATA_ONLY':True},repairs=repairs,completed=462,source_cursor='2019-10-31',
        run=dict(state={'SYNTHETIC_METADATA_ONLY':True,'last_processed_session':'2019-10-31'}),journals={}))
    c.update(parent_descriptors=deepcopy(repairs),parent_outer_sha256=parent['sha256'],
        parent_inner_sha256=parent['run']['checkpoint_sha256'],parent_root_admission_sha256='SYNTHETIC_NOT_AN_ADMITTED_ROOT')
    raw=data.encoded(dict(SYNTHETIC_TYPED_INPUT_METADATA_ONLY=True));typed=SimpleNamespace(sha256=data.sha(raw))
    d=dict(filename=typed.sha256+'.json',sha256=typed.sha256,resume_session=c['parent_cursor'],predecessor_checkpoint_sha256=c['parent_inner_sha256'])
    adopted=deepcopy(parent);adopted['repairs'].append(d);finish(adopted)
    members['book/repairs/'+d['filename']]=members[data.original.DOCUMENT]=raw
    members[data.original.SOURCE]=data.encoded(c['market_source'])
    members[data.original.ORIGIN_DIRECTORY+'/catalog.json']=data.encoded(c)
    members[data.PARENT]=gzip.compress(data.encoded(parent));members[data.ADOPTED]=gzip.compress(data.encoded(adopted))
    originals={n:data.encoded(dict(SYNTHETIC_RESOURCE_METADATA_ONLY=n)) for n in
        ('hydrated-uncertainty-event.json','hydrated-alder-unresolved-date.json','branch-controller-qualification.json')}
    members.update(originals);members[data.PRIOR]=b'{"SYNTHETIC_PRIOR_PROOF_METADATA_ONLY":true}\n'
    pins={**{n:data.sha(raw) for n,raw in originals.items()},'uncertainty-certificate.jsonl':data.sha(members[data.PRIOR])}
    metadata=dict(outer_sha256=parent['sha256'],root_admission_sha256=c['parent_root_admission_sha256'],repairs=repairs,
        base=parent['base'],selected_file=dict(bytes=len(members[data.PARENT]),sha256=data.sha(members[data.PARENT])),bounded_input_resource_pins=pins)
    def neutral(after,before,pin,day):
        assert after['NONCANONICAL_NO_FINANCIAL_STATE'] is before['NONCANONICAL_NO_FINANCIAL_STATE'] is True
        assert after['run']['state']==before['run']['state'] and after['journals']==before['journals']
        assert after['repairs']==before['repairs']+[d] and pin==typed.sha256
        return dict(SYNTHETIC_ZERO_ADOPTION_METADATA_CALLBACK_ONLY=True)
    proof=dict(event=neutral(adopted,parent,typed.sha256,c['event']['native_session']),
        actual_checkpoint_gzip_sha256=data.sha(members[data.ADOPTED]),original_outer_sha256=parent['sha256'],
        financial_state_unchanged=True,financial_sessions_advanced=0)
    members[data.PROOF]=data.encoded(proof)
    origin=dict(schema=data.original.RECEIPT_SCHEMA,passed=True,arm=c['arm'],initial_root_admission_sha256=c['parent_root_admission_sha256'],
        parent_outer_sha256=parent['sha256'],parent_descriptors=repairs,catalog_sha256=data.sha(data.encoded(c)),
        event_contract_sha256=data.digest(c['event']),source_evidence=data.original.evidence(c),
        adopted_descriptors=adopted['repairs'],new_descriptor=d,initial_adopted_outer_sha256=adopted['sha256'],
        adopted_input_sha256=adopted['run']['input_sha256'],financial_state_unchanged=True,financial_sessions_advanced=0,
        canonical_financial_source_changed=False,portfolio_cash_or_settlement_created=False,input_files={n:data.sha(raw) for n,raw in members.items()})
    value=dict(schema=data.SCHEMA,passed=True,initial_root_admission_sha256=c['parent_root_admission_sha256'],
        catalog_sha256=data.sha(data.encoded(c)),financial_sessions_advanced=0,canonical_financial_source_changed=False,
        old_observer_origin_is_financial_seed=False,origin=origin,
        boundary_files={n:dict(bytes=len(members[n]),sha256=data.sha(members[n])) for n in (data.PARENT,data.ADOPTED,data.PROOF)})
    return dict(catalog=c,typed=typed,metadata=metadata,parent=parent,current=adopted,value=value,members=members,neutral=neutral)

def check(a,value=None,current=None,members=None):
    return data.validate_bundle(a['value'] if value is None else value,a['current'] if current is None else current,
        a['catalog'],a['typed'],a['metadata'],(a['members'] if members is None else members).__getitem__,
        input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),zero_adoption=a['neutral'])

def test_noncanonical_origin_metadata_guard_shape_preserves_actual_boundary_pins(dto):
    parent,adopted=check(dto)
    assert parent['NONCANONICAL_NO_FINANCIAL_STATE'] is adopted['NONCANONICAL_NO_FINANCIAL_STATE'] is True
    assert len(adopted['repairs'])==16 and parent['run']['state']==adopted['run']['state']

@pytest.mark.parametrize('change',['authority','bool_replay','replay','old_observer_seed','root','original_parent_pin','adopted_bytes','proof_bytes','input_hash','descriptor','resource'])
def test_wrong_origin_pins_state_or_financial_claim_refuses(dto,change):
    v=deepcopy(dto['value']);current=deepcopy(dto['current']);members=deepcopy(dto['members'])
    if change=='authority':v['canonical_financial_source_changed']=True
    elif change=='bool_replay':v['financial_sessions_advanced']=False
    elif change=='replay':v['financial_sessions_advanced']=1
    elif change=='old_observer_seed':v['old_observer_origin_is_financial_seed']=True
    elif change=='root':v['initial_root_admission_sha256']='FOREIGN'
    elif change=='original_parent_pin':v['boundary_files'][data.PARENT]['sha256']='0'*64
    elif change=='adopted_bytes':members[data.ADOPTED]+=b' '
    elif change=='proof_bytes':members[data.PROOF]+=b' '
    elif change=='input_hash':current['run']['input_sha256']='0'*64
    elif change=='descriptor':current['repairs'][15]['sha256']='0'*64
    else:members[data.PRIOR]+=b' '
    with pytest.raises(ValueError):check(dto,v,current,members)

def test_later_current_input_hash_is_checked_without_truncating_current(dto):
    current=deepcopy(dto['current']);current['repairs'].append(dict(SYNTHETIC_ORDINARY_METADATA_ONLY=True))
    finish(current);assert check(dto,current=current)[1]['repairs']==dto['current']['repairs']
    assert len(current['repairs'])==17
    current['run']['input_sha256']=dto['current']['run']['input_sha256']
    current['run']['checkpoint_sha256']=data.digest({k:v for k,v in current['run'].items() if k!='checkpoint_sha256'})
    current['sha256']=data.digest({k:v for k,v in current.items() if k!='sha256'})
    with pytest.raises(ValueError,match='FULL16_CONTINUATION_IDENTITY'):check(dto,current=current)

def test_unsafe_resource_name_refuses_before_any_member_access(dto):
    v=deepcopy(dto['value']);v['origin']['input_files']['../FOREIGN']='0'*64
    calls=[]
    def member(name):calls.append(name);return dto['members'][name]
    with pytest.raises(ValueError,match='SAFE_AUTHENTIC_RESOURCE_NAMES'):
        data.validate_bundle(v,dto['current'],dto['catalog'],dto['typed'],dto['metadata'],member,
            input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),zero_adoption=dto['neutral'])
    assert calls==[]

def test_removing_origin_authority_guard_accepts_false_advancement_claim(dto):
    import ast
    v=deepcopy(dto['value']);v['financial_sessions_advanced']=1
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_bundle')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(x,ast.Constant)
        and x.value=='BOUNDED_ORIGIN_EXACT_FAMILY_AND_NO_FALSE_AUTHORITY' for x in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-authority-guard-synthetic-metadata-only>','exec'),scope)
    with pytest.raises(ValueError):check(dto,value=v)
    assert scope['validate_bundle'](v,dto['current'],dto['catalog'],dto['typed'],dto['metadata'],dto['members'].__getitem__,
        input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),zero_adoption=dto['neutral'])[1]==dto['current']
