"""Closed234 input bindings, independent child arithmetic and retention falsifiers."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parent/'fixtures'
sys.path.insert(0,str(Path(__file__).parent))
import test_distribution_v2 as t
m,s=t.m,t.s

def proposal():return t.data('P07-closed-source-input-v2-PROPOSAL.json')['records'][0]
def actual_binding():
    r=proposal();w=t.data('P07-closed-source234-payload.json')
    return m.build_terms(r['research_assumption'],w,child_security_id=r['child_security_id'],reference=r['reference'],source_proof=r['source_proof'])

def test_actual_closed_source_input_and_original_generation_are_exact(monkeypatch,tmp_path):
    name='P07-closed-source-input-v2-PROPOSAL.json'
    (tmp_path/name).write_bytes(t.raw(name));(tmp_path/s.SOURCE_V2).write_bytes(t.raw(s.SOURCE_V2))
    monkeypatch.setattr(s,'HERE',tmp_path)
    monkeypatch.setattr(s,'CATALOG_FILE',name);monkeypatch.setattr(s,'CATALOG_SHA',m.sha(t.raw(name)))
    r=s.qualified_record();b=actual_binding()
    assert r==proposal() and b['parent_positions']==[dict(slot_id=7,ticker='PPLI',quantity=13,entry_date='2021-04-13')]
    assert b['source_DATA_sha256']=='03262b38e00587f40bd0a5eb3f1f6a49a5f85d0a1d4d89da8d632b4da9d1ec99'
    assert b['suppressed_parent_cash_proxy']=='84.55' and len(b['original_native_distributions'])==2
    assert b['terminal'] is b['original_terminal'] is None
    assert b['original_rows']['517224929580411308']['issuer_id']=='SEC_UNKNOWN:517224929580411308'
    assert m.sha(t.raw(s.SOURCE_V2))=='820be270c8c84aa40e81c18cc92aed4e24f1f45d414f04f6f4b514464ab6de17'

@pytest.mark.parametrize('change',['outer','cursor','consumed','data','source_file','scope','qualification'])
def test_selected_record_has_same_own_parent_and_closed_source(change,tmp_path,monkeypatch):
    catalog=t.data('P07-closed-source-input-v2-PROPOSAL.json');r=catalog['records'][0]
    if change=='outer':r['parent_outer_sha256']='c'*64
    elif change=='cursor':r['parent_cursor']='2021-04-29'
    elif change=='consumed':r['parent_cursor']=r['source_scope']['parent_cursor']='2021-05-25';r['source_proof']['scope_sha256']=m.digest(r['source_scope'])
    elif change=='data':r['source_proof']['independent_DATA_passed']=False
    elif change=='source_file':r['source_module_file']='mutable_current_source.py'
    elif change=='scope':r['source_proof']['scope_sha256']='f'*64
    else:r['source_proof']['independent_qualification_passed']=False
    raw=m.encoded(catalog);(tmp_path/s.CATALOG_FILE).write_bytes(raw)
    (tmp_path/s.SOURCE_V2).write_bytes(t.raw(s.SOURCE_V2))
    monkeypatch.setattr(s,'HERE',tmp_path);monkeypatch.setattr(s,'CATALOG_SHA',m.sha(raw))
    with pytest.raises(ValueError):s.qualified_record()

@pytest.mark.parametrize('change',['ratio','cash','continuity','single','cash_semantics','session','url','identity'])
def test_explicit_primary_economic_interpretation_is_required(change):
    r=proposal();p=r['primary_extraction']
    if change=='ratio':p['child_shares_per_original_parent']='1.7'
    elif change=='cash':p['additional_cash_per_original_parent']='84.55'
    elif change=='continuity':p['continuing_parent_ratio']='0'
    elif change=='single':p['single_in_kind_distribution']=False
    elif change=='cash_semantics':p['equivalent_native_economic_representation']='TWO_SEPARATE_DISTRIBUTIONS'
    elif change=='session':p['distribution_session']='2021-05-26'
    elif change=='url':p['primary_source']='http://example.invalid/other'
    else:p['frozen_parent_identity_upgraded']=True
    with pytest.raises(ValueError):s.primary_binding(r)

def test_primary_guard_removal_falsifier():
    r=proposal();r['primary_extraction']['additional_cash_per_original_parent']='84.55'
    with pytest.raises(ValueError):s.primary_binding(r)
    assert t.drop(s,'primary_binding','COMPOUND_V2_PRIMARY_SINGLE_CHILD_CONTINUING_PARENT_NO_ADDITIONAL_CASH')(r) is True

def child_fixture():
    b=actual_binding();p=m.consideration(b,Fraction(13),10);spin=b['spin'];sid=spin['parent_security_id'];child=spin['child_security_id'];day=spin['session']
    before=dict(cash=100.,slots={'7':dict(reserved_for=None)},episodes={
        '7':dict(security_id=sid,current_shares=13,entry_split_adjusted_price=170.,episode_peak_split_adjusted_close=180.,source_lots=[]),
        '3':dict(security_id='UNRELATED',current_shares=8)})
    after=deepcopy(before);after['cash']+=p['child_cash']
    scale=173.77/(173.77+float(Fraction('1.6235')*Fraction('47.15')))
    parent=after['episodes']['7'];parent['entry_split_adjusted_price']*=scale;parent['episode_peak_split_adjusted_close']*=scale
    parent['source_lots'].append(dict(kind='SPINOFF_CHILD_LIQUIDATION',session=day,source_row_id=spin['source_row_id'],
        parent_security_id=sid,child_security_id=child,child_ticker='VMEO',child_shares_per_parent=str(Fraction('1.6235')),child_open=47.15,reference_scale=scale))
    lb=dict(events=[dict(prior='preserved')],receivables=[dict(unrelated='preserved')]);la=deepcopy(lb)
    la['events'] += [dict(event_type='SPINOFF_RECEIPT',security_id=child,session=day,shares_delta=21,detail=dict(fractional_entitlement='211/2000'),cash_before=100.,cash_after=100.),
        dict(event_type='SPINOFF_LIQUIDATION',security_id=child,session=day,shares_delta=-21,cash_before=100.,cash_after=after['cash'],cash_delta=p['child_cash'],price=47.15,fees=21*47.15-p['child_whole_proceeds'])]
    result=[dict(parent_security_id=sid,child_security_id=child,whole_child_shares=21,fractional_child_shares='211/2000',cash_proceeds=p['child_cash'])]
    return b,before,after,lb,la,result,10

def test_source_closed_child_oracle_matches_exact_cash_and_original_postconditions():
    args=child_fixture();before=deepcopy(args);p=s.spin_postcondition(*args)
    assert args==before and Fraction(p['exact_total_inflow'])==Fraction('994.134175')
    assert p['child_entitlement']=='42211/2000' and p['parent_units_unchanged']=='13'
    assert p['suppressed_cash_proxy_is_additional_cash'] is False

@pytest.mark.parametrize('change',['double_cash','receipt','sale','fraction','fee','parent_units','other_episode','rebase','lot','receivable','slots','audit'])
def test_child_receipt_sale_cash_and_original_parent_state_falsifiers(change):
    b,before,after,lb,la,result,cost=args=child_fixture()
    if change=='double_cash':after['cash']+=13*84.55
    elif change=='receipt':la['events'][-2]['shares_delta']=22
    elif change=='sale':la['events'][-1]['cash_delta']+=1
    elif change=='fraction':la['events'][-2]['detail']['fractional_entitlement']='0'
    elif change=='fee':la['events'][-1]['fees']=0.
    elif change=='parent_units':after['episodes']['7']['current_shares']=0
    elif change=='other_episode':after['episodes']['3']['current_shares']=9
    elif change=='rebase':after['episodes']['7']['entry_split_adjusted_price']+=1
    elif change=='lot':after['episodes']['7']['source_lots']=[]
    elif change=='receivable':la['receivables']=[]
    elif change=='slots':after['slots']['7']['reserved_for']='NEW'
    else:result[0]['cash_proceeds']+=1
    with pytest.raises(ValueError):s.spin_postcondition(*args)

def test_original_child_cash_guard_removal_falsifier():
    import system_campaign_financial_compound_runtime as original
    args=child_fixture();args[4]['events'][-1]['fees']=0.
    with pytest.raises(ValueError):s.spin_postcondition(*args)
    mutant=t.drop(original,'spin_postcondition','COMPOUND_EXACT_CANONICAL_CHILD_RECEIPT_SALE_FRACTION_CASH')
    mutant.__globals__.update(consideration=m.consideration,original_role=s.original_role)
    assert mutant(*args)['child_whole']==21

def retained_fixture():
    original=dict(base={'sources':'immutable original383'},sha256='a'*64,source_cursor='2021-04-30')
    current=deepcopy(original);current['source_cursor']='2021-06-30';payload=b'qualified immutable payload bytes'
    prior=b''.join((json.dumps(dict(certificate=i),sort_keys=True)+'\n').encode() for i in range(384))
    desc=dict(parent_outer_sha256=original['sha256'],parent_cursor=original['source_cursor'],payload_sha256=m.sha(payload),
        APHA_projection_source_sha256='2165e64a961bf0ee44c8f19ac2d6ec65059cc92a2b4154ad735685d29e120777',
        branch_source_sha256='b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef',retained_certificate_rows=384)
    return original,current,dict(payload_raw=payload,descriptor=desc,prior_certificate_raw=prior,current_certificate_raw=prior+b'{"new":1}\n')

def test_retention_preserves_payload_and_all384_certificate_prefix_bytes():
    o,c,kw=retained_fixture();before=deepcopy((o,c,kw));assert s.retained_payload_proof(o,c,**kw) is True
    assert (o,c,kw)==before

@pytest.mark.parametrize('change',['base','parent','payload','APHA','B19','count','prefix'])
def test_retention_generation_and_certificate_falsifiers(change):
    o,c,kw=retained_fixture();d=kw['descriptor']
    if change=='base':c['base']={}
    elif change=='parent':d['parent_outer_sha256']='b'*64
    elif change=='payload':kw['payload_raw']+=b'changed'
    elif change=='APHA':d['APHA_projection_source_sha256']='b'*64
    elif change=='B19':d['branch_source_sha256']='b'*64
    elif change=='count':d['retained_certificate_rows']=383
    else:kw['current_certificate_raw']=b'X'+kw['current_certificate_raw'][1:]
    with pytest.raises(ValueError):s.retained_payload_proof(o,c,**kw)

def test_retention_guard_removal_falsifier():
    o,c,kw=retained_fixture();kw['current_certificate_raw']=b'X'+kw['current_certificate_raw'][1:]
    with pytest.raises(ValueError):s.retained_payload_proof(o,c,**kw)
    assert t.drop(s,'retained_payload_proof','COMPOUND_V2_SAME_OWN_GENERATION_PAYLOAD_AND_ALL384_BRANCH_CERTIFICATE_BYTES')(o,c,**kw) is True
