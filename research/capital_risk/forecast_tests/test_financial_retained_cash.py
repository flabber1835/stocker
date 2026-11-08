"""Qualified cash facts transfer only as data to an independently bound book."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_partial as authority
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard


def test_acc_reuses_exact_qualified_facts_without_foreign_book_authority():
    old,_,originals=f.own_cash_selection('P10','2022-07-29');original,=originals;before=deepcopy(original)
    codec,name,terms=f.selected('P11',cursor='2022-07-29');term,=terms
    assert original==before and name==f.OWN_CASH_CATALOG
    assert codec.catalog_sha==old.catalog_sha=='7b58c64413b5f513ce76b9c7382f34cf8df612969e0865604ba283eb8a464be9'
    assert codec.parent_outer_sha256==authority.root_spec('P11')['outer_sha256']
    assert codec.parent_outer_sha256!=old.parent_outer_sha256 and codec.parent_positions==[]
    assert term['added']==original['added'] and term['added']['cash_per_share']==65.47
    assert term['native_session']==term['last_trading_session']==term['actual_completion_date']=='2022-08-09'
    assert term['added']['session']=='2022-08-10' and term['preopen_completion_confirmed']is False
    assert term['identity_witness']==original['identity_witness'] and term['source_capture']==original['source_capture']
    assert not {'arm','parent_cursor','parent_outer_sha256','parent_root_admission_sha256','parent_positions'}&set(term)
    provenance=term['retained_qualified_source']
    assert provenance['source_term_sha256']==f.digest(original)
    assert provenance['source_parent_admission_sha256']==original['parent_root_admission_sha256']
    assert f.suppressions(dict(source_cursor='2022-07-29'),terms)==[dict(session='2022-08-09',security_id='209530306982231273',term_sha256=term['native_term_sha256'])]


def test_closed_generation_guard_removal_falsifier(monkeypatch):
    codec,name,terms=f.own_cash_selection('P10','2022-07-29')
    changed=SimpleNamespace(**vars(codec));changed.catalog_sha='0'*64
    monkeypatch.setattr(f,'own_cash_selection',lambda arm,cursor:(changed,name,deepcopy(terms)))
    code='RETAINED_CASH_EXACT_CLOSED_SOURCE_GENERATION'
    with pytest.raises(ValueError,match=code):f.retained_own_cash_selection('P11','2022-07-29')
    assert removed_guard('retained_own_cash_selection',code)('P11','2022-07-29')[2]


def test_neutral_document_binds_new_book_and_labels_retained_source_provenance():
    codec,_,terms=f.selected('P11',cursor='2022-07-29')
    cp=dict(source_cursor='2022-07-29',run=dict(checkpoint_sha256='b'*64))
    material=dict(terms=terms,catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,
                  selector_sha256='c'*64,original_validator_description=codec.validator_description)
    before=deepcopy((cp,material));document=f.document(cp,material,'d'*64)
    assert (cp,material)==before and document['predecessor_checkpoint_sha256']=='b'*64
    assert document['add']==[terms[0]['added']]
    captures=[e for e in document['source_evidence']if '/source-capture/'in e['reference']]
    assert len(captures)==2 and all('/P10/'in e['reference']and e['description'].startswith('Retained original factual source only;')for e in captures)
    proof,=[e for e in document['source_evidence']if e['reference'].endswith('/retained-qualified-source')]
    assert proof['sha256']==f.digest(terms[0]['retained_qualified_source'])


@pytest.mark.parametrize('change',['outer','bundle','archive'])
def test_own_parent_and_input_history_guard_removal_falsifiers(monkeypatch,change):
    actual=authority.root_spec;pin=f.RETAINED_OWN_CASH_PHASES['P11','2022-07-29']['parent_root_admission_sha256']
    def altered(arm,admission_sha256=None):
        result=deepcopy(actual(arm,admission_sha256))
        if admission_sha256==pin:
            if change=='outer':result['outer_sha256']='0'*64
            else:result['base'][change+'_sha256']='0'*64
        return result
    monkeypatch.setattr(authority,'root_spec',altered)
    code='RETAINED_CASH_EXACT_OWN_PARENT_AND_FROZEN_HISTORY'
    with pytest.raises(ValueError,match=code):f.retained_own_cash_selection('P11','2022-07-29')
    assert removed_guard('retained_own_cash_selection',code)('P11','2022-07-29')[2]


def test_declared_fact_scope_guard_removal_falsifier(monkeypatch):
    codec,name,terms=f.own_cash_selection('P10','2022-07-29');terms=deepcopy(terms)
    terms[0]['ticker']=terms[0]['identity_witness']['ticker']='OTHER'
    monkeypatch.setattr(f,'own_cash_selection',lambda arm,cursor:(codec,name,deepcopy(terms)))
    code='RETAINED_CASH_ORDINARY_MANDATORY_FUTURE_FACTS_ONLY'
    with pytest.raises(ValueError,match=code):f.retained_own_cash_selection('P11','2022-07-29')
    assert removed_guard('retained_own_cash_selection',code)('P11','2022-07-29')[2][0]['ticker']=='OTHER'
