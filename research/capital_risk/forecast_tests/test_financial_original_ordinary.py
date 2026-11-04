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
    assert [t['ticker'] for t in selection('2018-04-30')[2]]==['AVXS','KS']
    assert selection('2018-11-05') is None

def test_catalog_bytes_guard_removal_accepts_changed_source_metadata(tmp_path,monkeypatch):
    for plan in f.ORIGINAL_ORDINARY_SOURCES['P05']:
        (tmp_path/plan[2]).write_bytes((f.HERE/plan[2]).read_bytes())
    name=selection()[1];j=json.loads((f.HERE/name).read_bytes());j['terms'][0]['description']='not the qualified original description'
    (tmp_path/name).write_text(json.dumps(j));monkeypatch.setattr(f,'HERE',tmp_path)
    with pytest.raises(ValueError,match='ORIGINAL_ORDINARY_CATALOG_BYTES'):selection()
    assert removed_guard('original_ordinary_selection','FUTURE_ORIGINAL_ORDINARY_CATALOG_BYTES')('P05','2018-01-31')[2]

def test_consumed_pending_native_guard_removal_discards_an_unsettled_boundary():
    with pytest.raises(ValueError,match='NO_CONSUMED_PENDING_NATIVE'):selection('2018-04-03')
    assert [t['ticker'] for t in removed_guard('original_ordinary_selection','FUTURE_ORIGINAL_ORDINARY_NO_CONSUMED_PENDING_NATIVE')('P05','2018-04-03')[2]]==['AVXS','KS']


def test_original_followup_cash_is_selected_without_pnk_stock_or_past_avxs():
    codec,name,terms=selection('2018-10-31');t,=terms
    assert name=='system-campaign-followup-terminal-facts.json' and len(codec.catalog['terms'])==3
    assert t['ticker']=='KS' and t['added']['cash_per_share']==35. and t['added']['session']=='2018-11-05'
    assert t['native_session']=='2018-11-02'
    assert codec.catalog_sha=='046cac14b87a620ac922e6f10a96682943952f9ba7ce3cd2f99a3decffa13222'
    assert codec.compiler_sha=='33e23f906c69ad6437d9173060b23cb03bf4a616ef816a1b48a588fa7d28a9a9'
    with pytest.raises(ValueError,match='NO_CONSUMED_PENDING_NATIVE'):selection('2018-11-02')


def test_catalog_order_guard_removal_accepts_a_later_catalog_before_earlier_facts(monkeypatch):
    monkeypatch.setitem(f.ORIGINAL_ORDINARY_SOURCES,'P05',tuple(reversed(f.ORIGINAL_ORDINARY_SOURCES['P05'])))
    with pytest.raises(ValueError,match='ORDERED_DISJOINT_CASH_CATALOGS'):selection()
    assert [t['ticker'] for t in removed_guard('original_ordinary_selection','FUTURE_ORIGINAL_ORDINARY_ORDERED_DISJOINT_CASH_CATALOGS')('P05','2018-01-31')[2]]==['AVXS','KS']

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


def inherited_fixture(tmp_path):
    terms=selection()[2];selected=[deepcopy(t) for t in terms[:3]]
    selected[1]['added'].update(session='2018-03-07',reference='Retained original daily convention')
    doc=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='c'*64,source_evidence=[],
        suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in selected],
        add=[t['added'] for t in selected])
    raw=(json.dumps(doc,sort_keys=True,indent=2)+'\n').encode();h=f.sha(raw)
    folder=tmp_path/'book/repairs';folder.mkdir(parents=True);(folder/(h+'.json')).write_bytes(raw)
    cp=dict(source_cursor='2018-01-31',repairs=[dict(filename=h+'.json',sha256=h,
        predecessor_checkpoint_sha256='c'*64,resume_session='2018-01-31')])
    return cp,terms,doc


def replace_inherited(tmp_path,cp,doc):
    raw=(json.dumps(doc,sort_keys=True,indent=2)+'\n').encode();h=f.sha(raw)
    cp['repairs'][0].update(filename=h+'.json',sha256=h);(tmp_path/'book/repairs'/(h+'.json')).write_bytes(raw)


def test_inherited_three_events_remain_unchanged_and_only_missing_two_are_selected(tmp_path):
    cp,terms,doc=inherited_fixture(tmp_path);before=deepcopy((cp,terms,doc))
    new,old=f.remaining_ordinary_terms(cp,terms,tmp_path)
    assert [t['ticker'] for t in new]==['SCMP','CSRA']
    assert [t['ticker'] for t in old]==['CUDA','JUNO','BIVV']
    assert old[1]['inherited_addition']['session']=='2018-03-07'
    assert old[1]['selected_catalog_addition']['session']=='2018-03-06'
    assert old[1]['inherited_date_and_reference_preserved'] is True
    assert (cp,terms,doc)==before


def test_inherited_repair_bytes_guard_removal_accepts_unbound_json(tmp_path):
    cp,terms,doc=inherited_fixture(tmp_path);p=tmp_path/'book/repairs'/cp['repairs'][0]['filename']
    p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError,match='EXACT_REPAIR_BYTES'):f.remaining_ordinary_terms(cp,terms,tmp_path)
    assert len(removed_guard('remaining_ordinary_terms','FUTURE_INHERITED_ORDINARY_EXACT_REPAIR_BYTES')(cp,terms,tmp_path)[0])==2


@pytest.mark.parametrize('change',['cash','duplicate','preimage','past_date'])
def test_inherited_event_guard_removal_accepts_conflicting_or_incomplete_repair(tmp_path,change):
    cp,terms,doc=inherited_fixture(tmp_path)
    if change=='cash':doc['add'][0]['cash_per_share']=1.
    elif change=='duplicate':doc['add'].append(deepcopy(doc['add'][0]))
    elif change=='preimage':doc['suppress'][0]['term_sha256']='0'*64
    else:doc['add'][0]['session']='2018-01-30'
    replace_inherited(tmp_path,cp,doc)
    with pytest.raises(ValueError,match='ONE_EQUIVALENT_FORWARD_EVENT'):f.remaining_ordinary_terms(cp,terms,tmp_path)
    assert len(removed_guard('remaining_ordinary_terms','FUTURE_INHERITED_ORDINARY_ONE_EQUIVALENT_FORWARD_EVENT')(cp,terms,tmp_path)[0])==2


def test_inherited_addition_without_native_half_refuses(tmp_path):
    cp,terms,doc=inherited_fixture(tmp_path);doc['suppress'].pop(0);replace_inherited(tmp_path,cp,doc)
    with pytest.raises(ValueError,match='ONE_EQUIVALENT_FORWARD_EVENT'):f.remaining_ordinary_terms(cp,terms,tmp_path)
