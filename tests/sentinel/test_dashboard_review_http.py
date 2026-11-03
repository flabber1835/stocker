"""Review action is explicit, bounded and same-origin; no financial authority."""
from datetime import datetime,timezone
import importlib

from fastapi.testclient import TestClient
import pytest

from sentinel.panel import model
from sentinel.panel.review_model import OperatorReview

app=importlib.import_module('sentinel.panel.app')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLIC_ORIGIN','https://private.invalid')
    with TestClient(app.app) as client:
        yield client


@pytest.mark.parametrize('method,origin,status',[
    ('get','https://private.invalid',405),('post',None,403),
    ('post','https://foreign.invalid',403),('post','null',403),
])
def test_no_get_or_cross_origin_ack(client,method,origin,status):
    response=getattr(client,method)('/review/acknowledge',headers={'Origin':origin} if origin else {})
    assert response.status_code==status
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-frame-options']=='DENY'


@pytest.mark.parametrize('body,status',[('x'*10001,413),('[]',409),('{',409),('{}',409)])
def test_malformed_or_oversized_ack_refuses(client,body,status):
    response=client.post('/review/acknowledge',content=body,
        headers={'Origin':'https://private.invalid','Content-Type':'application/json'})
    assert response.status_code==status


def test_ack_is_never_triggered_by_a_normal_page_read(client,monkeypatch):
    page=model.Panel(rows=[],now=datetime.now(timezone.utc))
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    def forbidden(*args,**kwargs):
        raise AssertionError('GET cannot acknowledge')
    monkeypatch.setattr(app.recorder,'acknowledge',forbidden)
    assert client.get('/').status_code==200
    assert client.get('/panel.json').json()['operator_review'] is None


def test_successful_post_returns_only_new_review_metadata(client,monkeypatch):
    now=datetime.now(timezone.utc)
    result=OperatorReview(scope='a'*64,head=2,reviewed_head=2,status='CLEAN',observed_at=now,reviewed_at=now)
    monkeypatch.setattr(app,'_acknowledge_review',lambda token:result if token=='private-view' else None)
    response=client.post('/review/acknowledge',json={'token':'private-view'},headers={'Origin':'https://private.invalid'})
    assert response.status_code==200 and response.json()['status']=='CLEAN'
    assert response.headers['cache-control']=='no-store'


def test_uncaught_render_failure_is_latched_but_queued_refresh_is_neutral(monkeypatch):
    events=[]
    monkeypatch.setattr(app.recorder,'read_failed',lambda:events.append('server-failure'))
    page=model.Panel(rows=[],now=datetime.now(timezone.utc))
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    original=app.render
    def broken(*_args,**_kwargs):
        raise ValueError('private render failure')
    monkeypatch.setattr(app,'render',broken)
    with TestClient(app.app,raise_server_exceptions=False) as client:
        assert client.get('/').status_code==500
        assert events==['server-failure']
        monkeypatch.setattr(app,'render',original)
        assert client.get('/').status_code==200
        def pending():
            raise app.singleflight.BuildUnavailable('already running')
        monkeypatch.setattr(app,'_read_panel',pending)
        assert client.get('/').status_code in {200,503}
        assert events==['server-failure']
