"""Synthetic gateway and pause wiring; no local canonical execution."""
from dataclasses import asdict, dataclass, replace
import signal
import sys
from types import ModuleType, SimpleNamespace

import pytest

from system_campaign_uncertainty_context import SensorCertificate, SID, DAY
from system_campaign_uncertainty_integration import AdmissionPause


@dataclass(frozen=True)
class Term:
    session: str
    security_id: str = SID
    cash_per_share: float | None = None
    def completeness(self, value): return False, 'synthetic incomplete'


@dataclass(frozen=True)
class Publication:
    session: str
    terminal_events: tuple
    bars: tuple = ()


def gateway(tmp_path):
    native = Term('2019-10-21')
    source = dict(session=DAY,security_id=SID,source_quote_present=False,split_ratio='1')
    obj = SensorCertificate(tmp_path,SimpleNamespace(objects=[object()]),native,{},event_source=source)
    obj.original_values = lambda **kwargs: {}
    prior = SimpleNamespace(median5={'selected':[SID]},wealth_core={'episodes':{}},pending=[],
        last_processed_session='2019-10-21',feed={'series':{SID:{'signal_basis_anchor':['2019-10-21',20.,20.]}}})
    return obj,prior,Publication(DAY,(replace(native,session=DAY),))


def test_actual_gateway_preserves_unresolved_term_and_whole_price_range(tmp_path):
    obj, prior, publication = gateway(tmp_path)
    before = asdict(publication)
    assert obj.values(prior=prior,published=publication) == {SID:18.}
    assert obj.event_bounds.pair() == [18.,20.] and obj.event_basis['signal_consideration_interval'] == [18.,20.]
    assert before == asdict(publication) and publication.terminal_events[0].cash_per_share is None


@pytest.mark.parametrize('mutation', ['split','quote_presence','term','missing_commitment'])
def test_actual_gateway_refuses_wrong_source_or_uncommitted_treatment(tmp_path,mutation):
    obj, prior, publication = gateway(tmp_path)
    if mutation=='split':obj.event_source['split_ratio']='2'
    if mutation=='quote_presence':obj.event_source['source_quote_present']=True
    if mutation=='term':publication=replace(publication,terminal_events=(replace(publication.terminal_events[0],cash_per_share=18.),))
    if mutation=='missing_commitment':obj.codec.objects=[]
    with pytest.raises(ValueError):obj.values(prior=prior,published=publication)


def fake_packages(monkeypatch):
    root = ModuleType('research');root.__path__=[]
    package = ModuleType('research.pooled_vacancy_funding');package.__path__=[]
    records = [];advances = []
    def write(path,value):records.append((path,value))
    def advance(*args,**kwargs):advances.append(True)
    package.backtest=SimpleNamespace(write_json=write)
    package.runtime=SimpleNamespace(advance=advance)
    monkeypatch.setitem(sys.modules,'research',root)
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',package)
    return package,records,advances,write,advance


def test_actual_pause_hook_invokes_installed_handler_and_restores_every_hook(monkeypatch,tmp_path):
    p,records,advances,write,advance = fake_packages(monkeypatch)
    original=signal.getsignal(signal.SIGTERM);stops=[]
    with AdmissionPause() as pause:
        signal.signal(signal.SIGTERM,lambda number,frame:stops.append(number))
        p.backtest.write_json(tmp_path/'status.json',dict(status='RESUMED'))
        assert pause.paused and stops==[signal.SIGTERM] and pause.calls==0
    assert signal.getsignal(signal.SIGTERM)==original
    assert p.backtest.write_json is write and p.runtime.advance is advance
    assert len(records)==1 and not advances


def test_actual_zero_transition_guard_blocks_original_advance(monkeypatch):
    p,_,advances,_,_ = fake_packages(monkeypatch)
    with AdmissionPause() as pause:
        with pytest.raises(ValueError,match='MUST_NOT_ADVANCE'):
            p.runtime.advance('synthetic','synthetic')
        assert pause.calls==1 and not advances


def test_unchanged_old_handler_cannot_be_used_as_pause_proof(monkeypatch,tmp_path):
    p,_,_,_,_=fake_packages(monkeypatch)
    with AdmissionPause() as pause:
        with pytest.raises(ValueError,match='CANONICAL_PAUSE_HANDLER'):
            p.backtest.write_json(tmp_path/'status.json',dict(status='RESUMED'))
        assert not pause.paused
