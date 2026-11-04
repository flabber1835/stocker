"""Bounded raw identity discovery and capture reconstruction; DATA/synthetic only."""
import ast
from copy import deepcopy
from dataclasses import make_dataclass
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from research.capital_risk.forecast_tests.test_financial_native_preimage import fixture, without_guard
from research.capital_risk.forecast_tests.test_financial_source_witnesses import spec
import system_campaign_financial_future as f
import system_campaign_financial_partial as p


def row_fixture():
    cp, scope, natives, rows = fixture()
    scope['additional_row_queries'] = [dict(schema='research.frozen-observation-identity-query/1',
        session='2022-07-22', ticker='CHILD', maximum_rows=1,
        require_unheld_at_parent=True, financial_use_authorized=False)]
    extra = [dict(session='2022-07-22', security_id='child-id', ticker='CHILD', issuer_id='SEC_UNKNOWN:child-id',
                  listing_first_session='2022-07-22', security_type_eligible='0', raw_open='12.34', raw_close='12.50')]
    return cp, scope, natives, rows, extra


def test_query_resolves_full_identity_hash_and_native_without_upgrading_metadata():
    cp, scope, natives, rows, extra = row_fixture()
    before = deepcopy((cp, scope, natives, rows, extra))
    payload = f.witness_payload(cp,'P04',scope,natives,rows,extra)
    assert f.validate_witness_capture(payload,spec(cp),scope) == payload
    assert payload['schema'] == f.SOURCE_WITNESS_ROW_QUERY_SCHEMA
    assert payload['query_scope'] == scope and payload['query_scope_sha256'] == f.digest(scope)
    resolved = payload['scope']
    assert 'additional_row_queries' not in resolved and 'native_preimage_query' not in resolved
    assert resolved['terms'][0]['native_term_sha256'] == f.digest(natives[0])
    assert resolved['additional_rows'] == [dict(session='2022-07-22',security_id='child-id',ticker='CHILD',
        source_observation_sha256=f.digest(extra[0]),parent_positions=[])]
    assert payload['additional_rows'][0]['source_row'] == extra[0]
    assert payload['additional_rows'][0]['identity_witness']['security_type_eligible'] == '0'
    assert payload['financial_sessions_advanced'] == 0
    assert payload['financial_authority'] is payload['input_adopted'] is payload['provider_metadata_upgraded'] is False
    assert (cp, scope, natives, rows, extra) == before


@pytest.mark.parametrize('change',['missing','duplicate','multiple_queries','predeclared','date','ticker','empty_id',
                                  'eligible','issuer','listing','held','authority','count_bool','require_unheld','query_extra'])
def test_other_queries_rows_or_parent_roles_refuse(change):
    cp, scope, natives, rows, extra = row_fixture()
    query=scope['additional_row_queries'][0]
    if change=='missing':extra=[]
    elif change=='duplicate':extra.append(deepcopy(extra[0]))
    elif change=='multiple_queries':scope['additional_row_queries'].append(deepcopy(query))
    elif change=='predeclared':scope['additional_rows']=[dict(invalid=True)]
    elif change=='date':extra[0]['session']='2022-07-25'
    elif change=='ticker':extra[0]['ticker']='OTHER'
    elif change=='empty_id':extra[0]['security_id']=''
    elif change=='eligible':extra[0]['security_type_eligible']='2'
    elif change=='issuer':extra[0]['issuer_id']=None
    elif change=='listing':extra[0]['listing_first_session']='2023-01-01'
    elif change=='held':cp['run']['state']['wealth_core']['episodes']['8']=dict(slot_id=8,ticker='CHILD',security_id='child-id',current_shares=1,entry_date='2022-06-30')
    elif change=='authority':query['financial_use_authorized']=True
    elif change=='count_bool':query['maximum_rows']=True
    elif change=='require_unheld':query['require_unheld_at_parent']=False
    else:query['unsupported']='extra'
    with pytest.raises(ValueError):f.witness_payload(cp,'P04',scope,natives,rows,extra)


@pytest.mark.parametrize('change',['query','resolved','row','role','schema','native','producer'])
def test_capture_commitments_and_complete_rows_cannot_change(change):
    cp,scope,natives,rows,extra=row_fixture();payload=f.witness_payload(cp,'P04',scope,natives,rows,extra)
    if change=='query':payload['query_scope']['additional_row_queries'][0]['ticker']='OTHER'
    elif change=='resolved':payload['scope']['additional_rows'][0]['security_id']='other'
    elif change=='row':payload['additional_rows'][0]['source_row']['raw_open']='99.0'
    elif change=='role':payload['additional_rows'][0]['parent_positions']=[dict(slot_id=1)]
    elif change=='schema':payload['schema']=f.SOURCE_WITNESS_DISCOVERY_SCHEMA
    elif change=='native':payload['terms'][0]['native_term']['reference']='changed'
    else:payload['producer_sha256']='0'*64
    with pytest.raises(ValueError):f.validate_witness_capture(payload,spec(cp),scope)


def test_future_identity_guard_removal_falsifier():
    _,scope,_,_,extra=row_fixture();extra[0]['ticker']='OTHER'
    with pytest.raises(ValueError):f.resolved_row_query_scope(scope,extra)
    result=without_guard('resolved_row_query_scope','SOURCE_OBSERVATION_QUERY_EXACT_FUTURE_IDENTITY')(scope,extra)
    assert result['additional_rows'][0]['ticker']=='OTHER'


def test_single_query_guard_removal_falsifier():
    _,scope,_,_,extra=row_fixture();scope['additional_row_queries'].append(deepcopy(scope['additional_row_queries'][0]))
    with pytest.raises(ValueError):f.resolved_row_query_scope(scope,extra)
    assert without_guard('resolved_row_query_scope','SOURCE_OBSERVATION_QUERY_SINGLE_EXPLICIT_ROW')(scope,extra)['additional_rows']


def test_hosted_capture_scans_only_declared_year_and_rejects_duplicate_matches(tmp_path,monkeypatch):
    cp,scope,natives,rows,extra=row_fixture()
    Native=make_dataclass('Native',[(key,type(value)) for key,value in natives[0].items()])
    native=Native(**natives[0]);calls=[];observations=rows+extra+[dict(extra[0],session='2023-07-22')]
    inputs=SimpleNamespace(load_actions=lambda path:SimpleNamespace(terminal={native.session:[native]}),
        _archive_rows=lambda archive,name:(calls.append(name) or iter(observations)))
    module=ModuleType('research.pooled_input_support');module.inputs=inputs
    monkeypatch.setitem(sys.modules,module.__name__,module)
    class Archive:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(f.zipfile,'ZipFile',lambda path:Archive())
    monkeypatch.setattr(f,'hosted',lambda:None)
    written=[];monkeypatch.setattr(f,'save',lambda path,value:written.append((path,value)))
    payload=f.capture_source_witnesses(cp,tmp_path,'P04',scope)
    assert calls==['observations-2022.csv.gz'] and payload['additional_rows'][0]['source_row']==extra[0]
    assert len(written)==1 and written[0][0]==tmp_path/f.SOURCE_WITNESS_FILE
    observations.append(deepcopy(extra[0]));written.clear()
    with pytest.raises(ValueError,match='SINGLE_EXPLICIT_ROW'):
        f.capture_source_witnesses(cp,tmp_path,'P04',scope)
    assert written==[]


def test_actual_p03_query_uses_only_admitted_own82_and_explicit_cvia_session():
    root=p.root_spec('P03');scope=f.WITNESS_SCOPES['P03']
    assert root['measured_closes']==82 and root['outer_sha256']==scope['parent_outer_sha256']
    assert root['selected_session']==scope['parent_cursor']=='2018-04-30'
    assert scope['terms'][0]['ticker']=='FMSA' and scope['terms'][0]['native_session']=='2018-05-31'
    assert scope['terms'][0]['parent_positions']==[]
    query,=scope['additional_row_queries']
    assert query['ticker']=='CVIA' and query['session']=='2018-06-01'
