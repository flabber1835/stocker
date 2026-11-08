"""Exact saved-session admission, separate positive review and no new writer."""
import sys
from pathlib import Path
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
import system_campaign_financial_partial as p


def test_new_P06_root_preserves_all13_inputs_and_genuine_admitted_parent():
 current=p.root_spec('P06');parent=p.root_spec('P06','ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845')
 assert current['root_admission_sha256']=='27c4e51a5fc479b418668a7950a4146129380eb73dc029840b0a62a9a0163da0'
 assert (current['measured_closes'],current['selected_session'],len(current['repairs']))==(1821,'2025-03-31',13)
 assert (parent['measured_closes'],parent['selected_session'],len(parent['repairs']))==(1677,'2024-08-30',12)
 assert current['repairs'][:-1]==parent['repairs'] and current['base']==parent['base']
 a=current['root_admission'];assert a['parent_root_admission_sha256']==parent['root_admission_sha256']
 assert (a['new_daily_records'],a['independent_accounting_snapshots'],a['new_monthly_reports'])==(144,288,7)
 assert (a['branch_uncertainty_proof']['rows'],a['branch_uncertainty_proof']['retained_rows'])==(144,424)
 assert a['source_input_proof']['full_inputs']==13 and a['source_input_proof']['all104_resources_verified'] is True
 assert a['source_input_proof']['ordinary_observation_proof']['ticker']=='TBIO'


def test_original_failed_financial_run_and_separate_positive_review_remain_distinct():
 current=p.root_spec('P06');a=current['root_admission'];proof=a['fresh_readonly_financial_review_requalification']
 assert current['receipt_status']==a['original_failed_financial_receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED'
 assert [current['prior_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,1]
 assert a['original_failed_financial_receipt_preserved'] is True and current['artifact_id']==13587599730
 assert proof['passed'] is proof['original_failed_stops_preserved'] is True and proof['financial_sessions_advanced']==0
 assert proof['original_financial_artifact_id']==13587599730 and proof['readonly_artifact_id']==a['readonly_artifact_id']==13589492472
 assert proof['readonly_run_id']==a['readonly_run_id']==42410678202
 assert a['local_canonical_runtime_executed'] is a['production_contacted'] is a['performance_scoring_authorized'] is a['full_financial_validation_completed'] is False


def test_unqualified_full13_financial_continuation_is_not_selected():
 import system_campaign_financial_resume as resume
 import system_campaign_source_exit_runtime as old_profile
 assert resume.SELECTED_ARMS==() and old_profile.candidate(p.root_spec('P06')) is False
 assert p.root_spec('P06')['root_admission']['next_session']=='2025-04-01'
