"""Clearly noncanonical origin DTOs and actual immutable proof-file bytes only."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_ABMD_ORIGIN_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(1,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
sys.path.insert(2,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
import system_campaign_p07_abmd_origin as data
from system_campaign_abmd_bounded_catalog import document

@pytest.fixture(scope='module')
def actual_proof():
    p=data.models.plan();path=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial306-source-snapshot/capture-P07-13451345162-001/verified-output/uncertainty-certificate.jsonl')
    path=Path('\\\\?\\'+str(path.resolve()));raw=path.read_bytes()
    assert dict(bytes=len(raw),sha256=data.sha(raw))==p['full_certificate_file']
    return raw,raw[:p['committed_certificate_prefix']['bytes']]

@pytest.fixture
def dto(actual_proof,monkeypatch):
    p=data.models.plan();catalog=json.loads(Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/P07-own1238-ABMD-bounded-catalog-v2.json').read_bytes())
    # These have no checkpoint schema, financial state or journals. They cannot
    # be restored and are never passed to canonical runtime APIs.
    parent=dict(noncanonical_metadata_DTO=True,base={'synthetic_metadata':True},repairs=p['parent_descriptors'],
        source_cursor='2022-11-30',completed=1238,sha256=p['parent_outer_sha256'],run={'checkpoint_sha256':catalog['parent_inner_sha256']})
    raw=data.encoded(document(catalog));h=data.sha(raw);d=dict(filename=h+'.json',sha256=h,resume_session=parent['source_cursor'],
        predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
    adopted=dict(deepcopy(parent),sha256='f'*64,repairs=parent['repairs']+[d]);ih=lambda base,repairs:data.digest(dict(base=base,repairs=repairs))
    adopted['run']['input_sha256']=ih(adopted['base'],adopted['repairs'])
    current=dict(deepcopy(adopted),source_cursor='2022-12-30',completed=1259)
    seed=b'NONCANONICAL_OBSERVATION_DTO\n'
    monkeypatch.setattr(data,'INITIAL_OBSERVATION_PIN',dict(bytes=len(seed),sha256=data.sha(seed)))
    def zero(actual,prior,sha,earliest):
        assert actual['noncanonical_metadata_DTO'] is prior['noncanonical_metadata_DTO'] is True
        assert actual['completed']==prior['completed'] and actual['source_cursor']==prior['source_cursor']
        assert sha==h and earliest=='2022-12-21'
        return {'noncanonical_zero_callback':True,'input_sha256':h}
    parent_raw=gzip.compress(data.encoded(parent),mtime=0);adopted_raw=gzip.compress(data.encoded(adopted),mtime=0)
    files={data.DOCUMENT:raw,data.SOURCE:data.encoded(catalog['market_source']),
        data.DIRECTORY+'/parent-checkpoint.json.gz':parent_raw,data.DIRECTORY+'/adopted-checkpoint.json.gz':adopted_raw,
        data.DIRECTORY+'/proof.json':data.encoded(dict(event=zero(adopted,parent,h,'2022-12-21'),
            actual_checkpoint_gzip_sha256=data.sha(adopted_raw),original_outer_sha256=parent['sha256'],
            financial_state_unchanged=True,financial_sessions_advanced=0)),
        data.DIRECTORY+'/correlation-inputs.jsonl.gz':gzip.compress(seed,mtime=0),
        data.DIRECTORY+'/prior-committed-certificate.jsonl':actual_proof[1],
        data.DIRECTORY+'/entire-prior-certificate.jsonl':actual_proof[0]}
    meta=dict(root_admission_sha256=p['root_admission_sha256'],base=parent['base'],selected_file=dict(bytes=len(parent_raw),sha256=data.sha(parent_raw)))
    value=dict(schema=data.SCHEMA,arm='P07',passed=True,catalog_sha256=data.sha(data.encoded(catalog)),
        initial_root_admission_sha256=p['root_admission_sha256'],parent_outer_sha256=parent['sha256'],
        adopted_outer_sha256=adopted['sha256'],adopted_input_sha256=adopted['run']['input_sha256'],descriptor=d,
        parent_file=meta['selected_file'],adopted_file=dict(bytes=len(adopted_raw),sha256=data.sha(adopted_raw)),
        input_files={name:data.sha(raw) for name,raw in files.items()},committed_proof_rows=784,
        committed_proof_prefix=p['committed_certificate_prefix'],financial_state_unchanged=True,financial_sessions_advanced=0,
        canonical_financial_source_changed=False,financial_root_admitted=False)
    return dict(value=value,current=current,catalog=catalog,metadata=meta,files=files,input_hash=ih,zero=zero,seed=seed)

def check(a):
    return data.validate(a['value'],a['current'],a['catalog'],a['metadata'],lambda name:a['files'][name],
        input_hash=a['input_hash'],read_checkpoint=lambda name:json.loads(gzip.decompress(a['files'][name])),
        zero_adoption=a['zero'],observation_seed=a['seed'])

def test_actual_initial_observation_pin_from_complete_original_reader():
    # Read existing authenticated members only. No canonical runtime/replay or
    # serialization is invoked; correlation_seed checks its raw hash/state chain.
    import system_campaign_factual_run as factual
    root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial306-source-snapshot/capture-P07-13451345162-001')
    root=Path('\\\\?\\'+str(root.resolve()));pins=json.loads((root/'authenticated-manifest.json').read_bytes())['members']
    where=root/'verified-output'
    for name in ('book/checkpoint.json.gz','book/formation.jsonl','book/daily.jsonl','correlation-inputs.jsonl.gz'):
        raw=(where/name).read_bytes();assert dict(bytes=len(raw),sha256=data.sha(raw))==pins[name]
    cp=json.loads(gzip.decompress((where/'book/checkpoint.json.gz').read_bytes()))
    rows=factual.correlation_seed(where,cp);raw=b''.join(rows)
    assert len(rows)==1364 and dict(bytes=len(raw),sha256=data.sha(raw))==data.INITIAL_OBSERVATION_PIN

def test_full_resource_axis_and_original784_bytes_qualify_without_book_staging(dto):
    v=check(dto)
    assert v['passed'] is True and v['descriptor']==dto['current']['repairs'][23]
    assert v['prior_proof_rows_reexecuted']==v['financial_sessions_advanced']==0
    assert dto['current']['noncanonical_metadata_DTO'] is True

@pytest.mark.parametrize('change',['authority','bool_sessions','sessions','header','catalog','missing_file','raw_file','parent_pin',
    'current_hash','current_inputs','proof_bool','proof_event','correlation','prior_certificate','prior_count'])
def test_falsified_origin_authority_resources_or_neutral_proof_refuse(dto,change):
    a=deepcopy(dto)
    if change=='authority':a['value']['financial_root_admitted']=True
    elif change=='bool_sessions':a['value']['financial_sessions_advanced']=False
    elif change=='sessions':a['value']['financial_sessions_advanced']=1
    elif change=='header':a['value']['new_financial_book']=True
    elif change=='catalog':a['value']['catalog_sha256']='0'*64
    elif change=='missing_file':a['value']['input_files'].pop(data.SOURCE)
    elif change=='raw_file':a['files'][data.SOURCE]+=b' '
    elif change=='parent_pin':a['metadata']['selected_file']['sha256']='0'*64
    elif change=='current_hash':a['current']['run']['input_sha256']='0'*64
    elif change=='current_inputs':a['current']['repairs']=a['current']['repairs'][:-1]
    elif change in ('proof_bool','proof_event'):
        name=data.DIRECTORY+'/proof.json';v=json.loads(a['files'][name])
        if change=='proof_bool':v['financial_sessions_advanced']=False
        else:v['event']={'foreign':True}
        a['files'][name]=data.encoded(v);a['value']['input_files'][name]=data.sha(a['files'][name])
    elif change=='correlation':
        name=data.DIRECTORY+'/correlation-inputs.jsonl.gz';a['files'][name]=gzip.compress(b'WRONG_SYNTHETIC_ROWS',mtime=0);a['value']['input_files'][name]=data.sha(a['files'][name])
    elif change=='prior_certificate':
        name=data.DIRECTORY+'/prior-committed-certificate.jsonl';a['files'][name]+=b' ';a['value']['input_files'][name]=data.sha(a['files'][name])
    else:a['value']['committed_proof_rows']=783
    with pytest.raises(ValueError):check(a)

def test_meaningful_removal_of_authentication_guard_accepts_extra_whitespace(dto):
    a=deepcopy(dto);a['files'][data.SOURCE]+=b' '
    # Source JSON equality will still reject this particular file, so mutate
    # the whole prior-file bytes instead and preserve its independent file pin.
    a=deepcopy(dto);name=data.DIRECTORY+'/correlation-inputs.jsonl.gz'
    a['files'][name]=gzip.compress(a['seed'],mtime=1)
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(x,ast.Constant) and x.value=='P07_ABMD_AUTHENTICATE_EVERY_ORIGIN_BYTE_BEFORE_PARSE' for x in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-origin-byte-guard-DATA-only>','exec'),scope)
    with pytest.raises(ValueError):check(a)
    assert scope['validate'](a['value'],a['current'],a['catalog'],a['metadata'],lambda name:a['files'][name],
        input_hash=a['input_hash'],read_checkpoint=lambda name:json.loads(gzip.decompress(a['files'][name])),
        zero_adoption=a['zero'],observation_seed=a['seed'])['passed']

def test_entire_original_pause_gate_AST_undo():
    raw=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/system_campaign_financial_uncertainty.py').read_bytes()
    original=data.models.legacy.original.function(raw,'paused_own_adoption');after=data.pause_tree(raw)
    assignment=next(n for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
    assert ast.literal_eval(assignment.value.keys.pop())==data.ADOPTION
    assert ast.literal_eval(assignment.value.values.pop())==data.DOCUMENT
    assert ast.dump(after,include_attributes=False)==ast.dump(original,include_attributes=False)

@pytest.mark.parametrize('name',['adopt','verify'])
def test_runtime_staging_refuses_before_financial_imports(monkeypatch,name):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        if name=='adopt':data.adopt(None,None,None,None,None,None,None,None)
        else:data.verify(None,None,None)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
