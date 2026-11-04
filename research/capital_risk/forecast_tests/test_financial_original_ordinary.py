"""Shared original ordinary inputs: immutable data and unconsumed boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard

def selection(cursor='2018-01-31'):
    return f.original_ordinary_selection('P05',cursor)

def scmp():return next(t for t in selection()[2] if t['ticker']=='SCMP')

def test_existing_catalog_and_validator_supply_all_five_exact_cash_terms():
    codec,name,terms=selection()
    assert [(t['ticker'],t['added']['cash_per_share']) for t in terms]==[
        ('CUDA',27.55),('JUNO',87.),('BIVV',105.),('SCMP',18.),('CSRA',41.25)]
    assert name=='system-campaign-corrected-winter-facts.json'
    assert codec.catalog_sha=='9784f96a4037fda8f4494d4d080b2a99e56bb4d4cd7640a52dd9cd9b99e23f4c'
    assert codec.compiler_sha=='5330c91601f6ee9e37f50f3ec62e7e36ba3fa46f4cb857fbec02634f12d0f487'
    assert len(codec.catalog['terms'])==5
    assert [t['ticker'] for t in selection('2018-02-28')[2]]==['JUNO','BIVV','CSRA']
    assert f.original_ordinary_selection('P04','2025-10-31') is None
    assert selection('2018-04-30') is None

def test_catalog_bytes_guard_removal_accepts_changed_source_metadata(tmp_path,monkeypatch):
    name=selection()[1];j=json.loads((f.HERE/name).read_bytes());j['terms'][0]['description']='not the qualified original description'
    (tmp_path/name).write_text(json.dumps(j));monkeypatch.setattr(f,'HERE',tmp_path)
    with pytest.raises(ValueError,match='ORIGINAL_ORDINARY_CATALOG_BYTES'):selection()
    assert removed_guard('original_ordinary_selection','FUTURE_ORIGINAL_ORDINARY_CATALOG_BYTES')('P05','2018-01-31')[2]

def test_consumed_pending_native_guard_removal_discards_an_unsettled_boundary():
    with pytest.raises(ValueError,match='NO_CONSUMED_PENDING_NATIVE'):selection('2018-04-03')
    assert removed_guard('original_ordinary_selection','FUTURE_ORIGINAL_ORDINARY_NO_CONSUMED_PENDING_NATIVE')('P05','2018-04-03') is None

def test_selected_events_guard_removal_accepts_duplicate_native_and_effective_keys():
    t=scmp()
    with pytest.raises(ValueError,match='DISJOINT_SELECTED_TERMS'):f.merge_selected_terms([t],[t])
    assert len(removed_guard('merge_selected_terms','FUTURE_ORIGINAL_ORDINARY_DISJOINT_SELECTED_TERMS')([t],[t]))==2

def test_date_guard_removal_uses_a_future_identity_without_a_prior_frozen_day():
    t=scmp();dates=['2018-02-13','2018-02-14']
    with pytest.raises(ValueError,match='EXACT_FROZEN_DATES'):f.ordinary_term_dates(t,dates)
    bad=removed_guard('ordinary_term_dates','FUTURE_ORIGINAL_ORDINARY_EXACT_FROZEN_DATES')(t,dates)
    assert bad['ordinary_identity_session']=='2018-02-14'

def test_identity_guard_removal_accepts_a_different_frozen_ticker():
    t=f.ordinary_term_dates(scmp(),['2018-02-12','2018-02-13'])
    row=dict(security_id=t['security_id'],ticker='WRONG',session='2018-02-12',listing_first_session='2010-01-04',security_type_eligible='0',issuer_id='SOURCE_UNCHANGED',raw_close='17.99')
    with pytest.raises(ValueError,match='UNMODIFIED_FROZEN_IDENTITY'):f.ordinary_identity(t,row)
    assert removed_guard('ordinary_identity','FUTURE_ORIGINAL_ORDINARY_UNMODIFIED_FROZEN_IDENTITY')(t,row)['ticker']=='WRONG'
    row['ticker']='SCMP';w=f.ordinary_identity(t,row)
    assert w['security_type_eligible']=='0' and w['source_observation_sha256']==f.digest(row)

def test_tender_and_ordinary_material_form_one_disjoint_future_document():
    from system_campaign_financial_partial import root_spec
    cp=dict(source_cursor='2018-01-31',run=dict(checkpoint_sha256='a'*64))
    own,_,primary=f.selected('P05',cursor='2018-01-31');codec,name,extra=selection()
    terms=f.merge_selected_terms(primary,extra);assert len(terms)==6
    material=dict(terms=terms,catalog_sha256=own.catalog_sha,original_validator_sha256=own.compiler_sha,
        selector_sha256=f.sha(Path(f.__file__).read_bytes()),ordinary_components=[codec.ordinary_source])
    doc=f.document(cp,material,'b'*64)
    assert len(doc['add'])==len(doc['suppress'])==6
    assert {x['reference'] for x in doc['source_evidence']} >= {
        f.REFERENCE+'/'+name,f.REFERENCE+'/system_campaign_winter_facts.py'}
    assert next(t for t in doc['add'] if t['security_id']=='950273523314609853')['cash_per_share']==18.
