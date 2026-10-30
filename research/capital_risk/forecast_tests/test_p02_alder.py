"""Synthetic input packets only; actual canonical packet proof is hosted."""
import ast,json,sys
from dataclasses import dataclass,replace
from pathlib import Path
from types import ModuleType,SimpleNamespace
import pytest
from system_campaign_alder_facts import AlderFacts
from system_campaign_facts import digest

ROOT=Path(__file__).parents[1];CATALOG=ROOT/'system-campaign-alder-unresolved-date.json'


@dataclass(frozen=True)
class Term:
    session:str='2019-10-21'
    security_id:str='941065113449292610'
    cash_per_share:float|None=None
    def completeness(self,shares):return (self.cash_per_share is not None,'MISSING_CONSIDERATION')


@dataclass(frozen=True)
class Packet:
    session:str
    terminal:tuple


def fixture(monkeypatch,tmp_path,cls=AlderFacts):
    v=json.loads(CATALOG.read_bytes());native=Term();v['native_term_sha256']=digest(native.__dict__)
    p=tmp_path/'catalog';p.write_text(json.dumps(v));f=cls(p);f.native=native;f.hydrated_sha='a'*64
    module=ModuleType('research.pooled_vacancy_funding')
    def original(packet,loaded):
        return replace(packet,terminal=tuple(t for t in packet.terminal if not(t.security_id==native.security_id and packet.session=='2019-10-21')))
    module.backtest=SimpleNamespace(apply_repair=original);monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',module)
    return f,module.backtest,original


@pytest.mark.parametrize('key,value',[('effective_session','2019-10-21'),('known_cash_leg','20.00'),
    ('preserve_unresolved_consideration',False),('maximum_conditional_later_cash','0.00')])
def test_wrong_date_or_completed_consideration_refused(tmp_path,key,value):
    v=json.loads(CATALOG.read_bytes());v[key]=value;p=tmp_path/'bad';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='ALDER_EXACT_DATE_UNRESOLVED_RIGHT'):AlderFacts(p)


def test_actual_wrapper_reschedules_only_unknown_term(monkeypatch,tmp_path):
    f,backtest,original=fixture(monkeypatch,tmp_path)
    first=Packet('2019-10-21',(f.native,));second=Packet('2019-10-22',())
    with f:
        assert backtest.apply_repair(first,None).terminal==()
        term,=backtest.apply_repair(second,None).terminal
        assert term==replace(f.native,session='2019-10-22') and not term.completeness(0)[0] and term.cash_per_share is None
        assert first.terminal==(f.native,) and second.terminal==()
    assert backtest.apply_repair is original


def test_actual_unresolved_guard_removal_falsifier(monkeypatch,tmp_path):
    f,backtest,_=fixture(monkeypatch,tmp_path);f.native=replace(f.native,cash_per_share=18.)
    with f:
        with pytest.raises(ValueError,match='ALDER_UNRESOLVED_TERM_NOT_COMPLETED'):backtest.apply_repair(Packet('2019-10-22',()),None)
    node=next(n for n in ast.parse(Path(AlderFacts.__init__.__code__.co_filename).read_bytes()).body if isinstance(n,ast.ClassDef))
    entry=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__enter__')
    corrected=next(n for n in entry.body if isinstance(n,ast.FunctionDef))
    corrected.body=[n for n in corrected.body if not any(isinstance(v,ast.Constant) and v.value=='ALDER_UNRESOLVED_TERM_NOT_COMPLETED' for v in ast.walk(n))]
    scope=dict(AlderFacts.__init__.__globals__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-unresolved-guard-removed>','exec'),scope)
    mutant,backtest,_=fixture(monkeypatch,tmp_path,scope['AlderFacts']);mutant.native=replace(mutant.native,cash_per_share=18.)
    with mutant:assert backtest.apply_repair(Packet('2019-10-22',()),None).terminal[0].cash_per_share==18.


def test_duplicate_or_unhydrated_wrapper_refuses(monkeypatch,tmp_path):
    f,backtest,_=fixture(monkeypatch,tmp_path)
    with f:
        with pytest.raises(ValueError,match='NO_DUPLICATE'):backtest.apply_repair(Packet('2019-10-22',(f.native,)),None)
    f.native=None
    with pytest.raises(ValueError,match='HYDRATED_BEFORE_WRAPPER'):f.__enter__()


def test_local_hydration_and_consumed_event_refuse(monkeypatch,tmp_path):
    f=AlderFacts(CATALOG);monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED_ALDER'):f.hydrate(tmp_path/'out')
    f.hydrated_sha='a'*64;f.hydrated_digest=digest(f.catalog)
    with pytest.raises(ValueError,match='UNCONSUMED_EVENT'):f.overlay({'source_cursor':'2019-10-21'},tmp_path/'out')
    assert not (tmp_path/'out').exists()
