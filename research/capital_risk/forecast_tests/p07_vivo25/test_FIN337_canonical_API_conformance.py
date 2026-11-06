"""Pure AST ownership metadata; canonical modules are never imported or run."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from forecast_tests.p07_vivo25.test_VIVO25_data_models_api import actual,read,P
D=Path(__file__).parent
import system_campaign_p07_vivo_api as api
import system_campaign_p07_vivo_data as data

OLD=Path('C:/GitHub/stocker/.codex-tmp/p07-vivo25-continuation-20261106/system_campaign_p07_vivo_api.py')

def owner_metadata():
    audit=json.loads((D/'P07-FIN337-static-canonical-API-audit.json').read_bytes())
    source=audit['authenticated_sources']['research/pooled_vacancy_funding/backtest.py'];path=Path(source['path'])
    raw=read(path);assert data.sha(raw)==source['sha256']
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='input_hash']
    assert ast.unparse(fn)=="def input_hash(base, repairs):\n    return hash_value(dict(base=base, repairs=repairs))"
    # Defines one inert function object from its exact AST. Its body is never called.
    module=SimpleNamespace(__file__=str(path))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),vars(module))
    return module

def test_correct_canonical_input_hash_owner_metadata_without_function_execution(actual):
    _,cp,_=actual;module=owner_metadata()
    assert api.canonical_input_hash(module,cp) is module.input_hash

def test_meaningful_physical_source_guard_removal(actual,monkeypatch):
    _,cp,_=actual;bad=deepcopy(cp);bad['base']['sources']['research/pooled_vacancy_funding/backtest.py']='0'*64
    module=owner_metadata()
    with pytest.raises(ValueError,match='EXACT_IMMUTABLE_BACKTEST_SOURCE'):api.canonical_input_hash(module,bad)
    old=data.need
    def without(value,label):
        if label!='VIVO_CANONICAL_INPUT_HASH_EXACT_IMMUTABLE_BACKTEST_SOURCE':old(value,label)
    monkeypatch.setattr(data,'need',without)
    assert api.canonical_input_hash(module,bad) is module.input_hash

def test_meaningful_function_owner_guard_removal(actual,monkeypatch):
    _,cp,_=actual;module=owner_metadata();module.input_hash=lambda *a:'PRIVATE_METADATA_STUB_NEVER_EXECUTED'
    with pytest.raises(ValueError,match='ORIGINAL_FUNCTION_OWNER_AND_CODE_FILE'):api.canonical_input_hash(module,cp)
    old=data.need
    def without(value,label):
        if label!='VIVO_CANONICAL_INPUT_HASH_ORIGINAL_FUNCTION_OWNER_AND_CODE_FILE':old(value,label)
    monkeypatch.setattr(data,'need',without)
    assert api.canonical_input_hash(module,cp) is module.input_hash

def test_complete_original_API_AST_undo_only_import_and_guarded_callback():
    original=ast.parse(OLD.read_bytes());current=ast.parse(Path(api.__file__).read_bytes())
    current.body=[n for n in current.body if not(isinstance(n,ast.FunctionDef) and n.name=='canonical_input_hash')]
    fn,=[n for n in current.body if isinstance(n,ast.FunctionDef) and n.name=='full_models']
    imp,=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='research.pooled_vacancy_funding']
    assert [(n.name,n.asname) for n in imp.names]==[('backtest',None)]
    imp.module='research.pooled_input_support';imp.names=[ast.alias(name='inputs')]
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.keyword) and n.arg=='input_hash']
    assert len(sites)==1 and ast.unparse(sites[0].value)=='canonical_input_hash(backtest, cp)'
    sites[0].value=ast.parse('inputs.input_hash',mode='eval').body
    assert ast.dump(original)==ast.dump(current)

def test_every_new_direct_canonical_reference_static_and_authenticated():
    raw=(D/'P07-FIN337-static-canonical-API-audit.json').read_bytes();value=json.loads(raw)
    assert value['passed'] and len(value['active_references'])==9
    assert value['canonical_modules_imported'] is value['canonical_function_bodies_executed'] is False
    assert value['exact_missing_attribute']['present'] is False and value['qualified_owner']['present'] is True
    for name,source in value['authenticated_sources'].items():assert data.sha(read(Path(source['path'])))==source['sha256']
    assert value['qualification_write_seam']['P03_exclusive_xb_body_used'] is False
