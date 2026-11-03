"""Prospective source/term guards only; no canonical or financial execution."""
import ast,inspect,json
from copy import deepcopy
from pathlib import Path
import pytest
import system_campaign_stock_calendar as s
from system_campaign_facts import digest

ROOT=Path(s.__file__).parent


def catalog():return json.loads((ROOT/'system-campaign-stock-calendar-terminal-facts.json').read_bytes())


def test_five_incomplete_cases_exclude_retained_complete_xilinx_input():
    x=catalog();assert [t['ticker'] for t in x['terms']]==['GNOG','CCMP','DRE','LSI','MTTR']
    for t in x['terms']:s.validate_term(t)
    c=next(t for t in x['terms'] if t['ticker']=='CCMP');assert c['added']['cash_per_share']==133.
    m=next(t for t in x['terms'] if t['ticker']=='MTTR');assert m['added']['exchange_ratio']==.03552
    assert all(t['added']['cash_in_lieu_price_per_delivered_share'] is None for t in x['terms'])
    gn=x['terms'][0];assert gn['frozen_provider_issuer_limitation']['actual_new_issuer']=='SEC_CIK:1883685'


@pytest.mark.parametrize('kind',('ratio','nan','zero_cash','wrong_kind','invented_CIL','issuer','delivery_date',
    'mandatory','preopen','consumed','same_security','reference'))
def test_refuses_economic_or_identity_mutation(kind):
    t=deepcopy(catalog()['terms'][1])
    if kind=='ratio':t['added']['exchange_ratio']=0.
    if kind=='nan':t['added']['exchange_ratio']=float('nan')
    if kind=='zero_cash':t['added']['cash_per_share']=0.
    if kind=='wrong_kind':t['added']['kind']='CASH_MERGER'
    if kind=='invented_CIL':t['added']['cash_in_lieu_price_per_delivered_share']=1.
    if kind=='issuer':t['added']['delivered_issuer_id']='wrong'
    if kind=='delivery_date':t['delivered_identity_witness']['session']='2022-07-05'
    if kind=='mandatory':t['mandatory_common_share_completion_confirmed']=False
    if kind=='preopen':t['preopen_completion_confirmed']=False
    if kind=='consumed':t['last_trading_session']=t['added']['session']
    if kind=='same_security':t['delivered_identity_witness']['security_id']=t['security_id']
    if kind=='reference':t['added']['reference']='unbound'
    with pytest.raises(ValueError):s.validate_term(t)


def test_cash_guard_removal_falsifier():
    t=deepcopy(catalog()['terms'][1]);t['added']['cash_per_share']=0.
    with pytest.raises(ValueError):s.validate_term(t)
    tree=ast.parse(inspect.getsource(s.validate_term));node=tree.body[0]
    guard=next(n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call))
    node.body.remove(guard);scope=dict(vars(s));exec(compile(ast.fix_missing_locations(tree),'<removed-guard>','exec'),scope)
    scope['validate_term'](t)


def test_every_provider_row_hash_and_date_is_required():
    rows=[dict(date='2022-05-04',ticker='GNOG',contraticker='DKNG',action='acquisitionby')]
    t=dict(ticker='GNOG',native_session='2022-05-04',provider_rows_proof=dict(rows_sha256=digest(rows),selected_row_sha256=[digest(r) for r in rows]))
    s.require_provider_rows(rows,t);wrong=deepcopy(rows);wrong[0]['contraticker']='OTHER'
    with pytest.raises(ValueError):s.require_provider_rows(wrong,t)


def test_actual_loader_hash_model_scope_and_hosted_hydration_only():
    obj=s.StockCalendar(catalog())
    with pytest.raises(ValueError,match='HOSTED_STOCK_CALENDAR_HYDRATION_ONLY'):obj.hydrate({},None,None)
    with pytest.raises(ValueError,match='HYDRATION_REQUIRED'):obj.patch()
    for field,value in (('loader_sha256','0'*64),('cil_convention','ACTUAL_SETTLEMENT'),('provider_metadata_upgraded',True)):
        bad=catalog();bad[field]=value
        with pytest.raises(ValueError):s.StockCalendar(bad)


def test_only_explicit_group_selected_in_the_combined_request():
    request=json.loads((ROOT/'system-campaign-p02-february-request.json').read_bytes())
    assert Path(s.__file__).name in request['sources']
    registry=json.loads((ROOT/'system-campaign-ordinary-catalog-registry.json').read_bytes())
    assert catalog()['commitment_group'] in registry['groups']
    text=Path(s.__file__).read_text();ast.parse(text)
    assert 'not native.completeness(0)[0]' in text and 'for obj in [*old_objects,loaded]' in text
    assert "financial_sessions_advanced=0" in text


def test_provider_archive_claim_cannot_be_relabelled():
    t=deepcopy(catalog()['terms'][0]);t['provider_rows_proof']['archive_sha256']='0'*64
    with pytest.raises(ValueError):s.validate_term(t)
