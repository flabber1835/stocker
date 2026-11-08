"""Continue the reviewed VOL075 prefix using the original qualified GBT fact."""
import argparse
import json
from pathlib import Path

from core_volatility_job import HERE, DOC, launch
from core_volatility_source import need
from seal import sha256_file

REQUEST = 'core-volatility-gbt-retry-request.json'
PARENTS = 'core-volatility-gbt-retry-parents.json'
WORKFLOW = '.github/workflows/capital-core-volatility-gbt-retry.yml'


def expected_request():
    parent = json.loads((HERE/PARENTS).read_bytes())
    need(parent['schema'] == 'research.core-volatility-reviewed-parents/1'
         and set(parent['arms']) == {'VOL075'} and parent['arms']['VOL075']['completed'] == 1196
         and parent['arms']['VOL075']['checkpoint_sha256'] == '376b422e09e8cf01c682b674dfee80d5ff483c0b4a7fab6ddbf78472642b84af'
         and parent['admissions']['VOL075']['whole_cipher_authenticated_before_parsing'], 'REVIEWED_OWN_1196_GBT_PARENT')
    failed = parent['failed_attempt']
    need(failed['arm']['run_id'] == 42534267876 and failed['arm']['artifact_id'] == 13638878300
         and failed['arm']['worker_exit_code'] == 1 and failed['arm']['completed'] == 1196
         and failed['arm']['checkpoint_sha256'] == parent['arms']['VOL075']['checkpoint_sha256']
         and failed['admission']['whole_cipher_authenticated_before_parsing'], 'PRESERVED_AUTHENTICATED_ZERO_ADVANCE_FAILURE')
    original = json.loads((HERE/'core-volatility-request.json').read_bytes())
    need(original['schema'] == 'research.core-volatility-request/1', 'ORIGINAL_FIXED_EXPERIMENT')
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-gbt-retry-request/1', 'generation': 11,
            'stage': 'OWN_REVIEWED_FOLLOWUP', 'arms': {'VOL075': .75}, 'parents': parent['arms'],
            'input_model': 'ORIGINAL_CASH_CATALOG', 'cash_case': 'GBT', 'maximum': 2156-1196,
            'financial_wait_seconds': 12600, 'review_wait_seconds': 2700,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'failed_attempt': failed, 'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_GBT_SOURCE_CLOSURE')
    from core_volatility_gbt_facts import selected_term, selected_generation, source_scope, CATALOG, SCOPE
    term = selected_term((HERE/CATALOG).read_bytes())
    selected_generation((HERE/CATALOG).read_bytes())
    source_scope((HERE/SCOPE).read_bytes(), term)
    return {'status': 'CORE_VOLATILITY_GBT_DATA_PROBE_PASSED', 'canonical_runtime_executed': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--request', type=Path, default=HERE/REQUEST)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--arm', choices=('VOL075',))
    for field in ('staging', 'capacity', 'output'):
        p.add_argument('--'+field, type=Path)
    a = p.parse_args()
    if a.prepare:
        need(not a.request.exists(), 'NEW_GBT_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        probe(a.request)
        launch(a, contract=expected_request())
