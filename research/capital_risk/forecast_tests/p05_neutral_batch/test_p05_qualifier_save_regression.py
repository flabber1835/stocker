"""The whole original qualifier body; only local imports bind DATA-only stubs."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_p05_neutral_batch import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_p05_batch_api as api

def whole_qualifier():
    raw=Path(api.original.__file__).read_bytes();assert api.data.sha(raw)==api.ORIGINAL_SHA
    before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualify')
    fn=deepcopy(before);imports=[(i,n) for i,n in enumerate(fn.body) if isinstance(n,ast.ImportFrom)]
    assert len(imports)==7
    assert [n.module for _,n in imports]==['research.pooled_input_support.adapter','research.pooled_vacancy_funding',
        'research.pooled_vacancy_funding.repair','research.bounded_20y.run','sentinel.controller',
        'system_campaign_sprint_facts','system_campaign_2021_completions_facts']
    fn.body=[n for n in fn.body if not isinstance(n,ast.ImportFrom)]
    restored=deepcopy(fn)
    for index,node in imports:restored.body.insert(index,deepcopy(node))
    assert ast.dump(restored,include_attributes=False)==ast.dump(before,include_attributes=False)
    return fn

def bindings(save):
    calls=[]
    class Packet:
        NONCANONICAL_EMPTY_PACKET_REGRESSION=True
    def qualify_schema(cls,pin):
        assert cls is Packet and pin=='NONCANONICAL_INPUT_SCHEMA_PIN';calls.append('SCHEMA')
    def reject(path,**kw):calls.append(('PARSER_FALSIFIER',kw));raise ValueError('NONCANONICAL_EXPECTED_REFUSAL')
    def forbidden(*a,**k):raise AssertionError('CANONICAL_PACKET_OR_CONTROLLER_MUST_NOT_RUN')
    ns=dict(vars(api.original),Packet=Packet,backtest=SimpleNamespace(apply_repair=forbidden),
        load_repair=reject,vendor=forbidden,terminal_returns=SimpleNamespace(values=forbidden),published_packet=forbidden,
        qualify_packet_schema=qualify_schema,notional=forbidden,require_witness=forbidden,save=save)
    fn=whole_qualifier();exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-qualifier-DATA-import-bindings-only>','exec'),ns)
    return ns['qualify'],calls

def arguments(out):
    # No financial state/journals/schema exists in this control DTO.
    cp=dict(NONCANONICAL_EMPTY_PACKET_REGRESSION=True,source_cursor='2099-01-01',
        base={'sources':{'research/pooled_input_support/adapter.py':'NONCANONICAL_INPUT_SCHEMA_PIN'}},run={'checkpoint_sha256':'f'*64})
    return cp,dict(NONCANONICAL_EMPTY_PACKET_REGRESSION=True,terms=[]),{},None,SimpleNamespace(earliest_affected_session='2099-01-02'),out/'NONCANONICAL_INPUT_DTO.json',out

def test_two_whole_original_qualifiers_save_exclusively_to_unique_phase_files(tmp_path):
    source_modules=set(sys.modules)
    for index in (0,1,2):
        fn,calls=bindings(api.qualification_save(index));fn(*arguments(tmp_path))
        value=json.loads((tmp_path/api.qualification(index)).read_bytes())
        assert value['passed'] is True and value['packet_checks']==0 and value['financial_sessions_advanced']==0
        assert calls[0]=='SCHEMA' and len(calls)==3
    assert not (tmp_path/'future-input-qualification.json').exists()
    assert not any(n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')) for n in set(sys.modules)-source_modules)
    fn,_=bindings(api.qualification_save(0))
    with pytest.raises(FileExistsError):fn(*arguments(tmp_path))

def test_removing_phase_binding_reproduces_original_second_save_failure(tmp_path):
    fn,_=bindings(api.original.save);fn(*arguments(tmp_path))
    assert (tmp_path/'future-input-qualification.json').exists()
    with pytest.raises(FileExistsError):fn(*arguments(tmp_path))

def test_other_original_saves_remain_exclusive_and_unmapped(tmp_path):
    save=api.qualification_save(1);path=tmp_path/'wrong-native-NONCANONICAL_INPUT_DTO.json'
    save(path,{'NONCANONICAL_INPUT_METADATA':True})
    assert json.loads(path.read_bytes())=={'NONCANONICAL_INPUT_METADATA':True}
    with pytest.raises(FileExistsError):save(path,{'NONCANONICAL_INPUT_METADATA':True})
