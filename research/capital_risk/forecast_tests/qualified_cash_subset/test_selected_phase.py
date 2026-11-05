"""Selected cash composition and positive retained root are DATA only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('SELECTED_CASH_PHASE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_future as future
import system_campaign_financial_partial as partial
import system_campaign_financial_additional_sensor as sensor
import system_campaign_ordinary_augmentation_router as augmentation
import system_campaign_financial_uncertainty as uncertainty

def test_selected_cash_terms_are_exact_and_disjoint_with_supported_same_day_scope():
    codec,name,primary=future.selected('P05',cursor='2022-03-31')
    extra,sources=future.supplemental_selection('P05','2022-03-31')
    assert name=='system-campaign-p05-own1070-supported-cash-inputs.json'
    assert [t['ticker'] for t in primary]==['HMHC','ANAT']
    assert len(extra)==24 and len(sources)==1
    assert len(future.merge_selected_terms(primary,extra))==26
    assert all(t['native_session']>'2022-03-31' and t['added']['kind']=='CASH_MERGER' for t in primary+extra)
    assert [t['ticker'] for t in extra if t['native_session']==t['added']['session']]==['ONEM','PRVB']
    assert all(t['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION' and t['preopen_completion_confirmed'] is True
               for t in extra if t['native_session']==t['added']['session'])
    assert {t['security_id'] for t in primary}.isdisjoint(t['security_id'] for t in extra)
    assert codec.catalog['parent_root_admission_sha256']==partial.root_spec('P05','c3cb03f790d12d7d69b29da38727b3e24f7e7be411be70a22118470c3583b29f')['root_admission_sha256']

def test_positive_p07_root_retains_initial_provenance_full23_and784_proof_seed():
    spec=partial.root_spec('P07');partial.validate_root_spec(spec)
    assert (spec['measured_closes'],spec['selected_session'])==(1238,'2022-11-30')
    assert len(spec['repairs'])==23 and partial.reviewed_archive_limit(spec)==1024**3
    assert all(k not in spec for k in ('root_requalified_failed_review_parent','readonly_failed_review_requalification','qualified_review_transport_sha256'))
    phase=sensor.phase(spec);original=sensor.retained_origin(phase)
    assert phase['adoption_mode']=='RETAINED' and phase['ordinary_input_mode']=='UNCHANGED'
    assert (phase['proof_rows'],phase['proof_new_rows'],phase['proof_retained_rows'])==(784,42,742)
    assert augmentation.selected(spec) and augmentation.declaration(spec)['adoption_required'] is False
    assert augmentation.unchanged_phase(spec) is True
    generation=spec['retained_additional_sensor']['policy_catalog_sha256']
    assert spec['retained_additional_sensor']==sensor.declaration(original,generation)
    old=partial.root_spec('P07','75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719')
    assert old['measured_closes']==1196 and old['root_requalified_failed_review_parent'] is True
    assert sensor.retained_origin(sensor.phase(old))==original
    catalog=uncertainty.own_policy_catalog()
    closed=uncertainty.OWN_POLICY_CLOSED_GENERATIONS['54e98d2adf23bf9b51e8561e66375f991f9d5faeb138dfa439cc3d2f250f3158']
    assert set(closed)==set(catalog['phases'])-{spec['root_admission_sha256']}

def test_selected_batch_keeps_every_term_evidence_inside_original_repair_limit():
    codec,name,primary=future.selected('P05',cursor='2022-03-31')
    extra,sources=future.supplemental_selection('P05','2022-03-31')
    cp=dict(source_cursor='2022-03-31',run=dict(checkpoint_sha256=codec.catalog['parent_outer_sha256']))
    material=dict(catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,
                  selector_sha256=future.sha(Path(future.__file__).read_bytes()),terms=primary+extra,ordinary_components=sources)
    document=future.document(cp,material,'0'*64)
    assert len(document['source_evidence'])==110 and len(document['add'])==26
    # The canonical module is in the frozen image. Read its authenticated
    # at-use diagnostic commitment as DATA; never import or instantiate it.
    raw=(Path(__file__).parent/'fixtures/repair-evidence-capacity-fin309.json').read_bytes()
    assert future.sha(raw)=='ba22ea360a8da9d9e6686ec4ca7fe4fb2c7ad15a1e8a0595edee309ab60246ea'
    capacity=json.loads(raw)
    assert capacity['financial_authority'] is False
    assert partial.root_spec('P05')['base']['sources'][capacity['canonical_schema_source']]==capacity['canonical_schema_source_sha256']
    assert capacity['maximum_items']==128 and capacity['actual_refused_items']==370
    assert len(document['source_evidence'])<=capacity['maximum_items']
    all_terms=future.catalog_terms(codec,tuple(t['ticker'] for t in codec.catalog['terms']))
    expanded=future.document(cp,dict(material,terms=all_terms),'0'*64)
    assert len(expanded['source_evidence'])==370>128

def test_positive_p05_may_root_retains_march_history_and_exact_review_counts():
    spec=partial.root_spec('P05');partial.validate_root_spec(spec)
    old=partial.root_spec('P05','c3cb03f790d12d7d69b29da38727b3e24f7e7be411be70a22118470c3583b29f')
    assert spec['measured_closes']==1111 and spec['selected_session']=='2022-05-31'
    assert old['measured_closes']==1070 and old['selected_session']=='2022-03-31'
    assert spec['repairs'][:-1]==old['repairs'] and len(spec['repairs'])==14
    a=spec['root_admission'];proof=a['source_input_proof']
    assert a['parent_root_admission_sha256']==old['root_admission_sha256']
    assert a['new_daily_records']==41 and a['independent_accounting_snapshots']==82 and a['new_monthly_reports']==2
    assert proof['passed'] and proof['selected_input_terms']==26 and len(proof['actual_cash_events'])==4
    assert proof['June_uncommitted_tail_excluded'] and partial.reviewed_archive_limit(spec)==512*1024**2
