"""Actual server projections retain independent facts across a partial scope."""
from copy import deepcopy
from dataclasses import replace
import importlib
import json
import re

from fastapi.testclient import TestClient
import pytest

from sentinel.panel import delivery, model, serialization
from sentinel.panel.presentation import dashboard_health
from sentinel.panel.render import render
from sentinel.panel.review_model import OperatorReview
from tests.sentinel.test_operational_dashboard_snapshot import panel as rich_panel


def partial(scope='PAPER'):
    page = rich_panel()
    return replace(page, observation_current=False, observation_changed_scopes=(scope,),
        rows=[*page.rows, model.Row('broker', 'Broker', 'CURRENT', model.OK, as_of=page.now),
            model.Row('automation', 'Automation', 'ENABLED', model.OK,
                operational_fact=model.OperationalFact(kind='AUTOMATION_POLICY', state='ENABLED_RELEASED'))],
        operator_review=OperatorReview(scope='a'*64, head=1, reviewed_head=0,
            status='REVIEW', observed_at=page.now, token='retained-token'))


def test_partial_paper_withdraws_affected_positives_and_executable_payloads_only():
    page = partial()
    before = deepcopy(page)
    payload = serialization.public_payload(page)
    rows = {row['key']:row for row in payload['rows']}
    assert rows['book']['current'] and rows['book']['color']=='green'
    assert rows['book']['shadow_book']['holdings'][0]['ticker']=='AAA'
    assert rows['exposure']['operational_fact']['state']=='ADOPTED'
    for key in ('paper_plan','trading_run','alpaca_account','broker','automation'):
        assert rows[key]['current'] is False and rows[key]['color']=='neutral'
        assert rows[key]['status']==model.PENDING and rows[key]['original_status']==model.OK
        assert rows[key]['operational_fact'] is None
    assert rows['paper_plan']['paper_plan'] is None and rows['trading_run']['trading_run'] is None
    assert rows['alpaca_account']['paper_account'] is None and rows['alpaca_account']['order_outcomes']==[]
    assert rows['alpaca_account']['as_of']==page.row('alpaca_account').as_of.isoformat()
    assert payload['operator_review'] is None and payload['operational']==model.UNKNOWN
    assert payload['dashboard_health']['color']=='neutral'
    html = render(page)
    assert 'data-observation-current="false"' in html and 'data-refresh-pending="false"' in html
    assert re.search(r'class="row ok" id="status-book"[^>]*data-current="true"',html)
    assert re.search(r'class="row neutral" id="status-broker"[^>]*data-current="false"',html)
    assert 'class="state neutral"' in html and 'id="review-acknowledge"' not in html
    assert 'class="overview-card core-slots"' in html and 'class="overview retained-overview"' not in html
    assert 'class="overview-card scope-not-current account-overview"' in html
    assert 'Last known account' in html and 'Account snapshot:' in html
    assert 'Last known saved plan · status refreshing.' in html
    assert 'Market-open time not current' in html
    assert page==before


@pytest.mark.parametrize('key,scope', [('book','SHADOW'),('paper_reconciliation','PAPER')])
def test_independently_revalidated_negative_wins_but_retained_negative_is_dated(key,scope):
    page=partial(scope)
    page=replace(page,rows=[replace(row,status=model.FAIL,detail='current financial refusal')
        if row.key==key else row for row in page.rows])
    # No matching current proof: retained failure is dated, not a current headline.
    assert dashboard_health(page)['color']=='neutral'
    assert serialization.public_payload(page)['dashboard_health']['active_conditions']==[]
    current=replace(page,observation_revalidated_keys=(key,))
    payload=serialization.public_payload(current)
    row=next(row for row in payload['rows'] if row['key']==key)
    assert row['current'] and row['color']=='red' and row['status']==model.FAIL
    assert payload['dashboard_health']['color']=='red'
    assert payload['dashboard_health']['active_conditions']==[key]
    html=render(current)
    assert 'class="state fail"' in html and f'href="#status-{key}"' in html
    assert 'id="review-acknowledge"' not in html


def test_partial_shares_exact_http_html_and_json_delivery_contract(monkeypatch):
    app=importlib.import_module('sentinel.panel.app')
    page=partial()
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    response=app.panel()
    assert response.headers['X-Sentinel-Panel-Status']=='PARTIAL'
    assert 'data-refresh-pending="false"' in response.body.decode()
    assert json.loads(app.panel_json().body)==serialization.public_payload(page)


@pytest.mark.parametrize('path', ['/', '/?document=1', '/panel.json'])
def test_empty_dsn_exposes_current_negative_template_without_source_calls(monkeypatch,path):
    app=importlib.import_module('sentinel.panel.app')
    monkeypatch.setenv('SENTINEL_DATABASE_URL','')
    def forbidden(*_args,**_kwargs): raise AssertionError('unconfigured surface queried financial sources')
    monkeypatch.setattr(app.projection_service,'read',forbidden)
    monkeypatch.setattr(app.projection_service,'register_panel_incarnation',forbidden)
    with TestClient(app.app) as client:
        response=client.get(path)
    assert response.status_code==200
    required={'ownership','book','exposure','broker','paper_plan','authority','automation',
        'automation_leader','automation_cycle','automation_alerts','alert_dispatcher',
        'alpaca_account','backup_restore','runtime_identity','issuer_reference','feed',
        'ingest','trial_verification',*[row.key for row in model.automation_step_rows(installed=None) ]}
    if path=='/panel.json':
        value=response.json()
        assert required=={row['key'] for row in value['rows']}
        assert all(row['value']=='UNAVAILABLE' and row['status']==model.UNKNOWN for row in value['rows'])
        assert value['color']=='red' and value['operator_review'] is None
        assert value['source_errors']==['SENTINEL_DATABASE_URL is unset.']
        assert all(row['paper_plan'] is None and row['shadow_book'] is None for row in value['rows'])
    else:
        assert response.headers['X-Sentinel-Panel-Status']=='CURRENT'
        assert 'class="state fail"' in response.text and 'id="system-details"' in response.text
        assert 'SENTINEL_DATABASE_URL is unset.' in response.text
        assert all(f'data-key="{key}"' in response.text for key in required)
        assert 'data-key="shadow_verification"' not in response.text


def test_scoped_guard_removal_is_caught_by_the_public_projection_oracle(monkeypatch):
    monkeypatch.setattr(delivery,'row_current',lambda *_:True)
    with pytest.raises(AssertionError):
        test_partial_paper_withdraws_affected_positives_and_executable_payloads_only()


def test_unknown_positive_rows_fail_closed_and_only_named_independent_facts_remain_current():
    page=partial()
    keys=('new_unclassified_source','issuer_reference','backup_restore','shadow_worker',
          'automation_alerts','alert_dispatcher','trading_environment')
    page=replace(page,rows=[*page.rows,*[model.Row(key,key,'POSITIVE',as_of=page.now)
        for key in keys]])
    rows={row['key']:row for row in serialization.public_payload(page)['rows']}
    for key in keys[:2]:
        assert rows[key]['current'] is False and rows[key]['color']=='neutral'
        assert rows[key]['status']==model.PENDING and rows[key]['original_status']==model.OK
    for key in keys[2:]:
        assert rows[key]['current'] and rows[key]['color']=='green'
    # Full observations retain the ordinary model contract, including new keys.
    full=serialization.public_payload(replace(page,observation_current=True))
    assert next(row for row in full['rows'] if row['key']==keys[0])['current']


def test_admitting_unclassified_row_is_detected(monkeypatch):
    monkeypatch.setattr(delivery,'_KNOWN',delivery._KNOWN|{'new_unclassified_source'})
    with pytest.raises(AssertionError):
        test_unknown_positive_rows_fail_closed_and_only_named_independent_facts_remain_current()
