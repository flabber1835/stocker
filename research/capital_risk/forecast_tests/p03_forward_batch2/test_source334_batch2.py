"""Finite source-only batch2; original module bodies and first batch stay exact."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[2];sys.path.insert(0,str(C))
import system_campaign_p03_forward_source_queries as old
import system_campaign_p03_forward_source_queries_batch2 as new
from system_campaign_financial_partial import root_spec
def test_entire_query_module_AST_undo_only_catalog_name_and_hash():
    before=(C/old.__name__).with_suffix('.py').read_text()
    after=(C/new.__name__).with_suffix('.py').read_text()
    assert after.count(new.CATALOG)==after.count(new.CATALOG_SHA)==1
    after=after.replace(new.CATALOG,old.CATALOG,1).replace(new.CATALOG_SHA,old.CATALOG_SHA,1)
    assert ast.dump(ast.parse(before))==ast.dump(ast.parse(after))
def test_new128_source_identities_extend_first128_without_replacing_them():
    previous=old.registry().queries[0];query=new.registry().queries[0]
    assert query.root_admission_sha256==previous.root_admission_sha256
    assert (query.parent_completed,query.parent_input_count)==(503,16)
    assert len(query.scope.terms)==len(previous.scope.terms)==128
    assert not {t.native_term_sha256 for t in previous.scope.terms}&{t.native_term_sha256 for t in query.scope.terms}
    assert query.scope.terms[0].native_session=='2021-01-28' and query.scope.terms[-1].native_session=='2021-09-09'
    assert all(not t.parent_positions for t in query.scope.terms)
    assert query.scope.additional_rows==[]
def test_exact_current_root_readonly_source_selection_and_disabled_identity():
    current=root_spec('P03');original={'P03':{'explicitly_noncanonical_test_scope':True}}
    assert new.selected_scopes(original,['P03'],enabled=False,root_lookup=lambda _:None)==original
    assert new.selected_scopes(original,['P05'],enabled=True,root_lookup=lambda _:None)==original
    selected=new.selected_scopes(original,['P03'],enabled=True,root_lookup=lambda _:current)
    assert selected['P03']==new.registry().queries[0].scope.model_dump() and original['P03']!={}
@pytest.mark.parametrize('field,value',[('outer_sha256','0'*64),('selected_session','2020-01-02'),('measured_closes',504),('repairs',[]),('financial_authority',True)])
def test_full_original_root_guard_rejects_wrong_axis_or_authority(field,value):
    current=deepcopy(root_spec('P03'));current[field]=value
    with pytest.raises(ValueError):new.selected_scopes({},['P03'],enabled=True,root_lookup=lambda _:current)
def test_new_catalog_hash_guard_refuses_changed_source(tmp_path,monkeypatch):
    (tmp_path/new.CATALOG).write_bytes((C/new.CATALOG).read_bytes()+b'\n')
    monkeypatch.setattr(new,'HERE',tmp_path)
    with pytest.raises(ValueError,match='EXACT_DECLARED_CATALOG_BYTES'):new.registry()
def test_source_only_flags_and_128_bound_remain_strict():
    v=json.loads((C/new.CATALOG).read_bytes());v['financial_authority']=True
    with pytest.raises(ValueError):new.Registry.model_validate(v)
    v=json.loads((C/new.CATALOG).read_bytes());v['queries'][0]['scope']['terms'].append(deepcopy(v['queries'][0]['scope']['terms'][-1]))
    with pytest.raises(ValueError):new.Registry.model_validate(v)
def test_current_P06_admission_is_full130_and_retains_closed_seed():
    current=root_spec('P06');proof=current['root_admission']['branch_uncertainty_proof']
    assert (current['measured_closes'],current['selected_session'],len(current['repairs']))==(1383,'2023-06-30',10)
    assert (proof['retained_rows'],proof['rows'])==(6,124) and proof['passed']
    assert current['root_admission']['parent_root_admission_sha256']=='41520825b51f125272ed44bb01ca58905fe7b170005fc1a1c4a72856bf01263f'
    previous=root_spec('P06',current['root_admission']['parent_root_admission_sha256'])
    assert previous['repairs']==current['repairs'] and previous['input_sha256']==current['input_sha256']
    assert previous['measured_closes']==1259
