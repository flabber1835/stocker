"""Exact unchanged financial parent admission after the constructor refusal."""
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha

HERE = Path(__file__).resolve().parent
EQUIVALENCE = 'system-campaign-p02-spring2023-unadvanced-equivalence.json'


def verify(root, spec, request):
    raw = (HERE / EQUIVALENCE).read_bytes()
    need(sha(raw) == request['spring2023_unadvanced_equivalence_sha256'],
         'SPRING2023_RECOVERY_EXACT_AUTHENTICATED_FAILURE_RECORD')
    proof = json.loads(raw)
    need(proof['status'] == 'EXACT_SAME_FINANCIAL_PARENT_NO_REPLAY_ENTRY'
         and proof['failed_run_id'] == 41178393607
         and proof['failed_head'] == 'b1e51f2e78c272e510f38e9f605f78a91fb546fe'
         and proof['failed_artifact_id'] == 13034330753
         and proof['actual_worker_exit_code'] == 1 and proof['actual_reviewer_exit_code'] == 0
         and proof['all_inventory_members_authenticated'] > 0
         and proof['all_driver_git_blobs_verified'] == 189
         and proof['actual_stopped_fences_verified'] is True
         and proof['financial_entry_not_reached'] is True
         and proof['new_ordinary_overlay_not_created'] is True and proof['new_input_not_adopted'] is True
         and proof['financial_parent_run_id'] == spec['run_id'] == 41174261514
         and proof['financial_parent_outer_sha256'] == spec['outer_sha256']
         and proof['financial_parent_session'] == spec['selected_session'] == '2023-03-31'
         and proof['measured_closes'] == 1321 and proof['retained_input_descriptors'] == 29
         and proof['no_checkpoint_rollback_or_new_origin'] is True
         and proof['production_contacted'] is False,
         'SPRING2023_RECOVERY_EXACT_UNADVANCED_OWN_FINANCIAL_AUTHORITY')
    expected = proof['exact_unchanged_members']
    need(set(expected) == {'book/checkpoint.json.gz', 'book/identity.json', 'source-bindings.json',
                          *(f'book/{n}.jsonl' for n in ('formation', 'daily', 'monthly', 'watch'))}
         and expected['book/checkpoint.json.gz'] == spec['selected_file'],
         'SPRING2023_RECOVERY_ALL_SEVEN_COMPLETE_PHYSICAL_FILES')
    for name, wanted in expected.items():
        count = 0; digest = hashlib.sha256()
        with (root / name).open('rb') as stream:
            while block := stream.read(1024**2):
                count += len(block); digest.update(block)
        need(dict(bytes=count, sha256=digest.hexdigest()) == wanted,
             'SPRING2023_RECOVERY_ACTUAL_COMPLETE_PARENT_AND_ALL_UNSENT_TAIL_BYTES')
    return proof
