"""Synthetic full descriptor DTOs and original B19 visitor AST falsifiers."""
import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import pytest

sys.path[:0]=[str(Path(__file__).parent),str(Path.cwd().parents[1])]


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_MODELS_DATA_ONLY:'+fullname)


sys.meta_path.insert(0,Fence())
import system_campaign_bounded_sensor_models as data
from system_campaign_bounded_sensor_catalog import encoded


def fixture(tmp_path):
    catalog=json.loads((Path(data.__file__).parent/'P03-own462-DOVA-source-bound-input-catalog-v1.json').read_bytes())
    evidence=[dict(reference='research:synthetic-input-evidence/'+str(i),description='Source input DTO, no checkpoint',sha256=pin)
              for i,pin in enumerate([data.sha(encoded(catalog)),catalog['source_data']['qualification_sha256'],
                                     catalog['market_source_sha256'],data.BRANCH_SHA])]
    doc=dict(schema=data.SCHEMA,predecessor_checkpoint_sha256=catalog['parent_inner_sha256'],event=deepcopy(catalog['event']),source_evidence=deepcopy(evidence))
    root_meta=dict(base=dict(synthetic_descriptor_DTO=True))
    cp=dict(base=root_meta['base'],repairs=deepcopy(catalog['parent_descriptors']),sha256='f'*64,
        completed=catalog['parent_completed'],source_cursor=catalog['parent_cursor'],run=dict(input_sha256=''))
    def hash_input(base,descriptors):return data.digest([base,descriptors])
    def save(doc):
        raw=encoded(doc);pin=data.sha(raw);p=tmp_path/'book/repairs'/(pin+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        cp['repairs']=deepcopy(catalog['parent_descriptors'])+[dict(filename=pin+'.json',sha256=pin,
            resume_session=catalog['parent_cursor'],predecessor_checkpoint_sha256=catalog['parent_inner_sha256'])]
        cp['run']['input_sha256']=hash_input(cp['base'],cp['repairs'])
    save(doc)
    return catalog,evidence,doc,root_meta,cp,hash_input,save


def test_only_new_descriptor_is_parsed_but_the_entire16_input_hash_is_checked(tmp_path):
    catalog,evidence,doc,meta,cp,hash_input,save=fixture(tmp_path);before=deepcopy(cp);calls=[]
    def full(base,descriptors):calls.append(descriptors);return hash_input(base,descriptors)
    result=data.typed_descriptor(tmp_path,cp,catalog,evidence,input_hash=full,root_metadata=meta)
    assert result==cp['repairs'][-1] and cp==before
    assert len(calls)==1 and calls[0] is cp['repairs'] and len(calls[0])==16


@pytest.mark.parametrize('mutation',['prefix','extra17','missing','hash','schema','cash_settlement','wrong_event',
    'clock','predecessor','filename','bytes','evidence'])
def test_new_schema_scope_and_complete_input_mutations_fail(tmp_path,mutation):
    catalog,evidence,doc,meta,cp,hash_input,save=fixture(tmp_path)
    if mutation=='prefix':cp['repairs'][0]['resume_session']='2018-01-03'
    elif mutation=='extra17':cp['repairs'].append(deepcopy(cp['repairs'][-1]))
    elif mutation=='missing':cp['repairs'].pop(0)
    elif mutation=='hash':cp['run']['input_sha256']='0'*64
    elif mutation in ('schema','cash_settlement','wrong_event','evidence'):
        if mutation=='schema':doc['schema']='terminal-repair/1'
        elif mutation=='cash_settlement':doc['event']['cash_settlement_authorized']=True
        elif mutation=='wrong_event':doc['event']['right_upper_per_share']='100.00'
        else:doc['source_evidence'][0]['sha256']='0'*64
        save(doc)
    elif mutation=='clock':cp['repairs'][-1]['resume_session']='2019-11-12'
    elif mutation=='predecessor':cp['repairs'][-1]['predecessor_checkpoint_sha256']='0'*64
    elif mutation=='filename':cp['repairs'][-1]['filename']='../../other.json'
    else:(tmp_path/'book/repairs'/cp['repairs'][-1]['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError):data.typed_descriptor(tmp_path,cp,catalog,evidence,input_hash=hash_input,root_metadata=meta)


def test_unadopted15_requires_exact_current_root_axis(tmp_path):
    catalog,evidence,doc,meta,cp,hash_input,save=fixture(tmp_path)
    cp['repairs']=deepcopy(catalog['parent_descriptors']);cp['run']['input_sha256']=hash_input(cp['base'],cp['repairs'])
    with pytest.raises(ValueError,match='UNADOPTED_EXACT_CURRENT_PARENT'):
        data.typed_descriptor(tmp_path,cp,catalog,evidence,input_hash=hash_input,root_metadata=meta)
    cp['sha256']=catalog['parent_outer_sha256']
    assert data.typed_descriptor(tmp_path,cp,catalog,evidence,input_hash=hash_input,root_metadata=meta) is None


def test_entire_original_b19_visitor_restored_by_undo_of_one_skip_site():
    p=Path.cwd()/'system_campaign_financial_branches.py';raw=p.read_bytes();fn=data.visitor_tree(raw)
    loop,=[n for n in fn.body if isinstance(n,ast.For)]
    skip,=[n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=='schema == BOUNDED_SCHEMA']
    assert ast.unparse(skip.body[0].value.args[0])=='descriptor == validated_descriptor and validated_descriptor is not None'
    loop.body.remove(skip)
    original,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_input']
    assert ast.dump(fn,include_attributes=False)==ast.dump(original,include_attributes=False)
    with pytest.raises(ValueError,match='UNCHANGED_ORIGINAL_B19_SOURCE'):data.visitor_tree(raw+b'\n')


def test_full_input_hash_guard_removal_is_meaningful(tmp_path):
    catalog,evidence,doc,meta,cp,hash_input,save=fixture(tmp_path);cp['run']['input_sha256']='0'*64
    with pytest.raises(ValueError,match='FULL_CANONICAL_INPUT_HASH'):
        data.typed_descriptor(tmp_path,cp,catalog,evidence,input_hash=hash_input,root_metadata=meta)
    fn,=[n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='typed_descriptor']
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(a,ast.Constant) and a.value=='MODELS_FULL_CANONICAL_INPUT_HASH' for a in n.value.args)]
    assert len(guards)==1;fn.body.remove(guards[0]);namespace=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<full-hash-guard-removal-data-only>','exec'),namespace)
    assert namespace['typed_descriptor'](tmp_path,cp,catalog,evidence,input_hash=hash_input,root_metadata=meta)==cp['repairs'][-1]


@pytest.mark.parametrize('name',['research.pooled_vacancy_funding','stock_strategy_shared.wealth_core','sentinel.controller','numpy','pandas'])
def test_financial_runtime_import_fences(name):
    with pytest.raises(ImportError,match='DATA_ONLY'):importlib.import_module(name)
