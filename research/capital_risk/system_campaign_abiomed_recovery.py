"""Authenticate unchanged own parent bytes after the pre-financial refusal."""
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha

HERE = Path(__file__).resolve().parent
EQUIVALENCE = 'system-campaign-p02-abiomed-unadvanced-equivalence.json'


def verify(root, spec, request):
    raw = (HERE / EQUIVALENCE).read_bytes()
    need(sha(raw) == request['abiomed_unadvanced_equivalence_sha256'],
         'ABIOMED_RECOVERY_EXACT_AUTHENTICATED_FAILURE_RECORD')
    proof = json.loads(raw)
    need(proof['status'] == 'EXACT_SAME_FINANCIAL_PARENT_NO_REPLAY_ENTRY'
         and proof['failed_run_id'] == 41171548427
         and proof['failed_head'] == '65dc046a7a802ed6f52150742b528a106cf528bc'
         and proof['actual_worker_exit_code'] == 1 and proof['actual_reviewer_exit_code'] == 0
         and proof['all_inventory_members_authenticated'] == 123
         and proof['all_driver_git_blobs_verified'] == 177
         and proof['actual_stopped_fences_verified'] is True
         and proof['financial_entry_not_reached'] is True and proof['new_model_not_adopted'] is True
         and proof['financial_parent_run_id'] == spec['run_id'] == 41166283025
         and proof['financial_parent_outer_sha256'] == spec['outer_sha256']
         and proof['financial_parent_session'] == spec['selected_session'] == '2022-11-30'
         and proof['measured_closes'] == 1238 and proof['retained_input_descriptors'] == 28
         and proof['no_checkpoint_rollback_or_new_origin'] is True
         and proof['production_contacted'] is False,
         'ABIOMED_RECOVERY_EXACT_UNADVANCED_FINANCIAL_AUTHORITY')
    expected = proof['exact_unchanged_members']
    need(set(expected) == {'book/checkpoint.json.gz', 'book/identity.json', 'source-bindings.json',
                          *(f'book/{name}.jsonl' for name in ('formation', 'daily', 'monthly', 'watch'))}
         and expected['book/checkpoint.json.gz'] == spec['selected_file'],
         'ABIOMED_RECOVERY_ALL_SEVEN_COMPLETE_PHYSICAL_FILES_REQUIRED')
    for name, wanted in expected.items():
        count = 0; digest = hashlib.sha256()
        with (root / name).open('rb') as stream:
            while block := stream.read(1024**2):
                count += len(block); digest.update(block)
        need(dict(bytes=count, sha256=digest.hexdigest()) == wanted,
             'ABIOMED_RECOVERY_ACTUAL_COMPLETE_PARENT_AND_UNSENT_TAIL_BYTES')
    return proof
