"""Hosted stopped-book review only; there is no financial execution mode."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_phase_timing import PhaseTiming
from system_campaign_q4_cash_context import CashRegistry
from system_campaign_close_review_materialization import review


def main(path):
    hosted()
    from research.pooled_vacancy_funding import journal
    driver=Path(__file__).parent;request=json.loads(path.read_bytes())
    target=json.loads((driver/request['review_target_file']).read_bytes())
    old_spec=json.loads((driver/request['original_predecessor_file']).read_bytes())
    old_request_raw=(driver/request['original_request_file']).read_bytes()
    need(sha(old_request_raw)==request['original_request_sha256']
         and (Path('/evidence')/'request.json').read_bytes()==old_request_raw
         and (Path('/evidence')/'spec.json').read_bytes()==(driver/request['original_predecessor_file']).read_bytes(),
         'CLOSE_REVIEW_RUN_EXACT_ORIGINAL_REQUEST_AND_PARENT_NO_GRAFT')
    checkpoint=journal.read_checkpoint(Path('/evidence/book/checkpoint.json.gz'))
    need(checkpoint['sha256']==target['outer_sha256'] and checkpoint['source_cursor']=='2024-04-30'
         and checkpoint['completed']==1592 and len(checkpoint['repairs'])==36
         and request['financial_replay_authorized'] is False,
         'CLOSE_REVIEW_RUN_ONLY_ACTUAL_STOPPED_CHECKPOINT')
    with PhaseTiming(Path('/out'),'review-only') as timing,CashRegistry():
        proof=review(Path('/out'),Path('/evidence'),Path('/old'),old_spec,
                     json.loads(old_request_raw),timing)
    need(proof['actual_nested_canonical_repair_loaded'] is True
         and proof['financial_sessions_advanced']==0,
         'CLOSE_REVIEW_RUN_ACTUAL_MATERIALIZATION_WITH_ZERO_ADVANCE')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True)
    main(p.parse_args().request)
