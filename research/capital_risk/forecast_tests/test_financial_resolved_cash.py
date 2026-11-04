"""Resolved read-only native evidence can qualify one ordinary future cash input."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_cash_calendar as calendar
from research.capital_risk.forecast_tests.test_financial_native_preimage import without_guard


def term():return f.selected('P04',cursor='2022-09-30')[2][0]


def test_actual_resolved_cash_right_keeps_both_scope_commitments_and_original_validator():
    codec,filename,terms=f.selected('P04',cursor='2022-09-30');t,=terms
    query=f.registered_scope(t['source_capture']['query_scope_sha256'])
    resolved=f.registered_scope(t['source_capture']['scope_sha256'])
    before=deepcopy((query,resolved))
    assert f.resolved_query_scope(query,[t['native']])==resolved
    assert (query,resolved)==before and query['terms'][0]['native_term_sha256'] is None
    assert t['native_term_sha256']==f.digest(t['native'])==resolved['terms'][0]['native_term_sha256']
    assert t['added']['cash_per_share']==68.5 and t['added']['session']==t['actual_completion_date']=='2022-10-05'
    assert t['native_session']==t['last_trading_session']=='2022-10-04'
    assert t['preopen_completion_confirmed'] is t['mandatory_common_share_completion_confirmed'] is True
    assert t['identity_witness']['issuer_id']=='SEC_CIK:1629137' and t['identity_witness']['security_type_eligible']=='1'
    assert t['parent_positions']==[] and len(codec.catalog['terms'])==6
    assert codec.compiler_sha==f.sha(Path(calendar.__file__).read_bytes())
    assert f.suppressions(dict(source_cursor='2022-09-30'),terms)==[dict(session='2022-10-04',
        security_id=t['security_id'],term_sha256=t['native_term_sha256'])]


def literal_fixture(tmp_path,monkeypatch,change):
    original=f.HERE;catalog=json.loads((original/f.OWN_CASH_CATALOG).read_bytes());t=catalog['terms'][-1]
    if change=='native':t['native']['reference']='substituted native preimage'
    elif change=='self':t['source_capture']['query_scope_sha256']=t['source_capture']['scope_sha256']
    elif change=='known':t['source_capture']['query_scope_sha256']=f.ACTIVE_WITNESS_SCOPES['P07']
    else:t['native']['cash_per_share']=68.5
    raw=(json.dumps(catalog,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    (tmp_path/f.OWN_CASH_CATALOG).write_bytes(raw)
    for row in catalog['terms']:
        primary=row.get('retained_primary_catalog')
        if primary:(tmp_path/primary['filename']).write_bytes((original/primary['filename']).read_bytes())
    monkeypatch.setattr(f,'HERE',tmp_path);monkeypatch.setattr(f,'OWN_CASH_SHA',f.sha(raw))
    return catalog


@pytest.mark.parametrize('change',['native','self','known','complete'])
def test_resolved_source_cannot_be_self_bound_or_swap_native_preimage(tmp_path,monkeypatch,change):
    literal_fixture(tmp_path,monkeypatch,change)
    with pytest.raises(ValueError):f.own_cash_selection('P04','2022-09-30')


def test_removing_query_resolution_guard_accepts_a_false_source_native(tmp_path,monkeypatch):
    literal_fixture(tmp_path,monkeypatch,'native')
    with pytest.raises(ValueError):f.own_cash_selection('P04','2022-09-30')
    broken=without_guard('own_cash_selection','OWN_CASH_EXACT_QUERY_RESOLUTION_NATIVE_PREIMAGE')
    assert broken('P04','2022-09-30')[2][0]['native']['reference']=='substituted native preimage'


def test_closed_five_term_catalog_generation_retains_its_exact_bytes():
    codec,_,terms=f.selected('P04',cursor='2022-08-31')
    assert len(codec.catalog['terms'])==5 and terms[0]['ticker']=='CTXS'
    assert codec.catalog_sha=='5a917388cfa61ed86d60792e263260fca876eaf3d8f3606ad95744d7a5ed7ed7'
