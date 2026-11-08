"""Stable component reuse never borrows clocks from volatile liveness."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from threading import Event
import time
import uuid

import pytest

from sentinel.panel import composition, model, projection_service as producer


@pytest.fixture
def component(monkeypatch,tmp_path):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','qualification-only-'+'x'*40)
    monkeypatch.setattr(composition.tempfile,'gettempdir',lambda:str(tmp_path))
    now=datetime.now(timezone.utc)
    panel=model.Panel(now=now,rows=[
        model.Row('book','book','VERIFIED',model.OK,as_of=now,valid_until=now+timedelta(seconds=300)),
        model.Row('automation_leader','leader','CURRENT',model.OK,as_of=now,valid_until=now+timedelta(seconds=9)),
        model.Row('alert_dispatcher','sender','CURRENT',model.OK,as_of=now,valid_until=now+timedelta(seconds=20))])
    coordinates=('a'*64,{'SHADOW':'b'*64,'PAPER':'c'*64})
    calls=[]
    monkeypatch.setattr(producer,'_coordinates',lambda *_:coordinates)
    from sentinel.panel import segment_disclosure,sources
    monkeypatch.setattr(segment_disclosure,'disclose',lambda panel,*_:panel)
    def collect(**_):calls.append(True);return panel
    monkeypatch.setattr(sources,'build_panel',collect)
    return now,panel,coordinates,calls,str(uuid.uuid4())


def test_twenty_unchanged_liveness_reads_do_not_recompose_or_renew_financial_clocks(component):
    now,panel,coordinates,calls,instance=component
    result=composition.collect('private-db','owner','/private',instance)
    for second in range(20):
        page,context,subjects,expiry=composition.read('owner',instance,now=now+timedelta(seconds=second))
        assert page==panel and (context,subjects)==coordinates
        assert expiry==now+timedelta(seconds=30)
        assert page.rows[0].valid_until==panel.rows[0].valid_until
    assert calls==[True] and result['valid_until']==(now+timedelta(seconds=30)).isoformat()


@pytest.mark.parametrize('fault',['expired','future','owner','tampered','negative','financial_expiry'])
def test_component_refuses_stale_cross_owner_or_failed_reuse(component,fault):
    now,panel,_,_,instance=component
    if fault=='financial_expiry':
        panel=replace(panel,rows=[replace(panel.rows[0],valid_until=now+timedelta(seconds=3)),*panel.rows[1:]])
        assert composition.stable_boundary(panel)==now+timedelta(seconds=3)
        return
    composition.collect('private-db','owner','/private',instance)
    if fault=='tampered':
        path=composition.path(instance);value=json.loads(path.read_text())
        value['value']['panel']['rows'][0]['value']='FORGED';path.write_text(json.dumps(value))
    elif fault=='negative':composition.failure('owner',instance,TimeoutError())
    instant=now+timedelta(seconds=30) if fault=='expired' else now-timedelta(seconds=1) if fault=='future' else now
    expected=composition.Pending if fault in {'expired','future'} else composition.Failed if fault=='negative' else ValueError
    with pytest.raises(expected):
        composition.read('other' if fault=='owner' else 'owner',instance,now=instant)


def test_component_authentication_guard_has_executed_falsifier(component,monkeypatch):
    monkeypatch.setattr(composition.hmac,'compare_digest',lambda *_:True)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_component_refuses_stale_cross_owner_or_failed_reuse(component,'tampered')


def test_fast_publication_keeps_running_while_next_full_collection_waits(monkeypatch,tmp_path):
    monkeypatch.setattr(producer,'HEARTBEAT',tmp_path/'heartbeat')
    full_started,release=Event(),Event()
    full_calls=[];fast_calls=[]
    class Full:
        def call(self,failed,*,timeout):
            assert timeout==20;full_calls.append(True)
            if len(full_calls)==2:
                full_started.set();assert release.wait(2)
            return dict(outcome='PUBLISHED',valid_until=(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat())
        def close(self):pass
    class Fast:
        def call(self,failed,*,timeout):
            assert timeout==5;fast_calls.append(True)
            return dict(outcome='PUBLISHED',valid_until=(datetime.now(timezone.utc)+timedelta(seconds=12)).isoformat())
        def close(self):pass
    publisher=producer.Publisher('private-db','owner')
    publisher.worker=Fast();publisher.composition_worker=Full()
    monkeypatch.setattr(producer,'refresh_delay',lambda *_,**__:0.005)
    publisher.start()
    try:
        deadline=time.monotonic()+1
        while not full_calls and time.monotonic()<deadline:time.sleep(.005)
        publisher.composition_wake.set()
        assert full_started.wait(1)
        before=len(fast_calls)
        deadline=time.monotonic()+1
        while len(fast_calls)<before+4 and time.monotonic()<deadline:time.sleep(.005)
        assert len(fast_calls)>=before+4 and full_calls==[True,True]
    finally:
        release.set();publisher.close()
    assert not publisher.thread.is_alive() and not publisher.composition_thread.is_alive()
