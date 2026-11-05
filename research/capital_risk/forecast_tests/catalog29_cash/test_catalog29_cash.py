"""Closed EXAS source binding and unchanged cash path; no canonical finance."""
from copy import deepcopy
import hashlib,json,sys
from pathlib import Path

import pytest

BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE))


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise ImportError('CATALOG29_INPUT_ONLY:'+fullname)


_fence=Fence();sys.meta_path.insert(0,_fence)
import system_campaign_financial_future as f


@pytest.fixture(scope='module',autouse=True)
def fence():
    assert not any(n.startswith(('stock_strategy_shared','sentinel','research.pooled_'))for n in sys.modules)
    try:yield
    finally:sys.meta_path.remove(_fence)


sha=lambda b:hashlib.sha256(b).hexdigest()
enc=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def facts():
    raw=(Path(__file__).parent/'fixtures/source274-P11-input-fixture.json').read_bytes()
    assert sha(raw)=='2bb51b47bf3c12a5d51a845226272fb8825f6b23e27a63be6b48ecbc8943d9ed'
    return json.loads(raw)


def selected():return f.own_cash_selection('P11','2026-02-27')


def test_exact_closed_own_root_source_and_ordinary_cash_consideration():
    x=facts();r=x['source_review'];q=x['source_validation'];b=x['bindings']
    codec,name,terms=selected();t,=terms;n,=r['terms']
    assert name==f.OWN_CASH_CATALOG and len(codec.catalog['terms'])==29
    assert codec.catalog_sha==b['catalog_after_sha256']=='51674fc83cb9240168b27c2566edff62f44089cb4e00e57ce2e8f06b8a50277e'
    assert t['source_capture']==b['source_capture']
    assert t['identity_witness']==n['identity_witness'] and t['native']==n['native_term']
    assert f.digest(t['native'])==t['native_term_sha256']=='689adccb69cd2f499298678e43c60d83e73de51f1af1ba8f4de739aabc85ccbd'
    assert t['parent_positions']==n['parent_positions']==[dict(entry_date='2026-02-10',quantity=79,slot_id=13,ticker='EXAS')]
    assert t['parent_outer_sha256']==r['parent_outer_sha256'] and t['parent_root_admission_sha256']==r['parent_root_admission_sha256']
    assert r['parent_pending_context'][t['security_id']]==[] and r['parent_selected'][t['security_id']]is False
    assert q['all_original_input_documents_byte_exact']==12 and q['raw_source']['all_parent_date_action_rows']==2
    assert t['added']['cash_per_share']==105. and t['added']['session']=='2026-03-23'
    assert t['native_session']==t['last_trading_session']=='2026-03-20'
    assert t['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION' and t['preopen_completion_confirmed']is True
    p=x['primary'];assert p['ordinary_common_cash_per_share']=='105.00'
    assert p['official_exchange_preopen_legal_completion_explicitly_confirmed']is True
    assert t['timing_source']==p['supplementary_official_exchange_source']['url']
    for field in ('exact_legal_effective_minute_observed','actual_cash_payment_or_settlement_observed','actual_opening_cash_availability_proved'):
        assert t['primary_extraction'][field]is False
    assert t['primary_extraction']['updated_alert_publication_time_observed']is False


def test_catalog28_and_each_historical_generation_are_retained_exactly():
    x=facts();catalog=json.loads((BASE/f.OWN_CASH_CATALOG).read_bytes())
    prior=dict(deepcopy(catalog),terms=catalog['terms'][:28])
    assert sha(enc(prior))==x['bindings']['catalog_before_sha256']=='b199b6df1b4e34e1b98336795dc3eeb62caa9981f3f9a96b2b1edb1704aa6581'
    assert f.CLOSED_CASH_GENERATIONS[sha(enc(prior))]==28
    iphi,_,_=f.own_cash_selection('P06','2021-03-31')
    assert enc(iphi.catalog)==enc(prior) and iphi.catalog_sha==sha(enc(prior))


@pytest.mark.parametrize('change',['cash','preopen','completion','native','identity','entitlement','stock'])
def test_original_cash_validator_rejects_invalid_new_term(change):
    from system_campaign_cash_calendar import validate_term
    _,_,terms=selected();t=deepcopy(terms[0])
    if change=='cash':t['added']['cash_per_share']=0.
    elif change=='preopen':t['preopen_completion_confirmed']=False
    elif change=='completion':t['actual_completion_date']='2026-03-24'
    elif change=='native':t['native_session']='2026-03-19'
    elif change=='identity':t['identity_witness']['security_id']='wrong'
    elif change=='entitlement':t['added']['entitlement_aggregation']='EPISODE'
    else:t['added']['exchange_ratio']=1.
    with pytest.raises(ValueError):validate_term(t)


@pytest.mark.parametrize('change',['source_clock','source_scope','parent_position','root','native'])
def test_current_generic_selector_refuses_foreign_bindings(tmp_path,monkeypatch,change):
    catalog=json.loads((BASE/f.OWN_CASH_CATALOG).read_bytes())
    t,=[v for v in catalog['terms']if(v['arm'],v['parent_cursor'],v['ticker'])==('P11','2026-02-27','EXAS')]
    if change=='source_clock':t['source_capture']['artifact_id']+=1
    elif change=='source_scope':t['source_capture']['scope_sha256']='0'*64
    elif change=='parent_position':t['parent_positions'][0]['quantity']+=1
    elif change=='root':t['parent_outer_sha256']='0'*64
    else:t['native_term_sha256']='0'*64
    names={v[field][key]for v in catalog['terms']
           for field,key in (('retained_primary_catalog','filename'),('retained_original_legal_record','catalog_file'))
           if field in v}
    for name in names:
        (tmp_path/name).write_bytes((BASE/name).read_bytes())
    raw=enc(catalog);(tmp_path/f.OWN_CASH_CATALOG).write_bytes(raw)
    monkeypatch.setattr(f,'HERE',tmp_path);monkeypatch.setattr(f,'OWN_CASH_SHA',sha(raw))
    with pytest.raises(ValueError):selected()


def test_document_carries_exact_native_suppression_and_source_evidence():
    codec,name,terms=selected();t,=terms
    cp=dict(source_cursor='2026-02-27',run=dict(checkpoint_sha256='a'*64))
    material=dict(terms=terms,catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,
        selector_sha256='b'*64,original_validator_description=codec.validator_description)
    doc=f.document(cp,material,'c'*64)
    assert doc['suppress']==[dict(session='2026-03-20',security_id=t['security_id'],term_sha256=t['native_term_sha256'])]
    assert doc['add']==[t['added']]
    hashes={v['sha256']for v in doc['source_evidence']}
    assert t['source_capture']['payload_sha256']in hashes
    assert t['source_capture']['independent_data_review_sha256']in hashes
