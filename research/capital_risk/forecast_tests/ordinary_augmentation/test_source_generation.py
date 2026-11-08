"""Original catalog survives only an exactly reversible registry extension."""
import ast
from pathlib import Path
import shutil
import sys
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('SOURCE_GENERATION_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_ordinary_augmentation_data as data
NAME='system_campaign_financial_future.py'
PIN='8cd57c08782d33183c988c75bf3a945a9153316d4ed1479bf506830aa4dc6dec'

@pytest.fixture
def inputs(tmp_path,monkeypatch):
    for name in (NAME,'system_campaign_qualified_cash_subset.py','system-campaign-p05-own1070-supported-cash-inputs.json',
                 'system_campaign_qualified_explicit_cash.py','system-campaign-p05-own1111-msp-explicit-cash-input-v3.json'):
        shutil.copyfile(data.HERE/name,tmp_path/name)
    monkeypatch.setattr(data,'HERE',tmp_path)
    return tmp_path

def test_exact_registry_extension_recovers_entire_old_source(inputs):
    assert data.sha((inputs/NAME).read_bytes())!=PIN
    assert data.source_matches(NAME,PIN)

@pytest.mark.parametrize('change',['registry','function','extra_statement','catalog','loader','new_catalog','new_loader','new_registry','wrong_pin','foreign_name'])
def test_new_generation_rejects_any_other_source_or_binding_change(inputs,change):
    name=NAME;pin=PIN
    if change in ('registry','function','extra_statement'):
        p=inputs/NAME;raw=p.read_bytes()
        if change=='registry':raw=raw.replace(b"FUTURE_LITERAL_PHASES['P05', '2022-03-31']",b"FUTURE_LITERAL_PHASES['P05', '2022-04-29']",1)
        elif change=='function':raw=raw.replace(b'def selected(arm, *, cursor=None):',b'def selected(arm, *, cursor=False):',1)
        else:raw+=b'\nFOREIGN_SCOPE = True\n'
        p.write_bytes(raw)
    elif change=='catalog':
        p=inputs/'system-campaign-p05-own1070-supported-cash-inputs.json';p.write_bytes(p.read_bytes()+b' ')
    elif change=='loader':
        p=inputs/'system_campaign_qualified_cash_subset.py';p.write_bytes(p.read_bytes()+b'\n')
    elif change=='new_catalog':
        p=inputs/'system-campaign-p05-own1111-msp-explicit-cash-input-v3.json';p.write_bytes(p.read_bytes()+b' ')
    elif change=='new_loader':
        p=inputs/'system_campaign_qualified_explicit_cash.py';p.write_bytes(p.read_bytes()+b'\n')
    elif change=='new_registry':
        p=inputs/NAME;p.write_bytes(p.read_bytes().replace(b"FUTURE_LITERAL_PHASES['P05', '2022-05-31']",b"FUTURE_LITERAL_PHASES['P05', '2022-06-30']",1))
    elif change=='wrong_pin':pin='0'*64
    else:name='system_campaign_qualified_cash_subset.py'
    assert data.source_matches(name,pin) is False

def test_removing_entire_original_source_digest_guard_accepts_foreign_function(inputs):
    p=inputs/NAME;raw=p.read_bytes();amended=raw.replace(b'def selected(arm, *, cursor=None):',b'def selected(arm, *, cursor=False):',1)
    assert raw!=amended;p.write_bytes(amended)
    assert data.source_matches(NAME,PIN) is False
    fn,=[n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='source_matches']
    end=fn.body[-1];assert isinstance(end,ast.Return) and isinstance(end.value,ast.BoolOp) and len(end.value.values)==2
    end.value=end.value.values[0];scope=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-entire-source-digest-guard-DATA-only>','exec'),scope)
    assert scope['source_matches'](NAME,PIN) is True
