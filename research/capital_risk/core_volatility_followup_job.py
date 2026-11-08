"""Known AAAP input-model reuse; retain the original measured segment bound."""
import argparse
import json
from pathlib import Path

from core_volatility_job import HERE, DOC, launch
from core_volatility_source import need
from seal import sha256_file

REQUEST = 'core-volatility-followup-request.json'
PARENTS = 'core-volatility-followup-parents.json'
WORKFLOW = '.github/workflows/capital-core-volatility-followup.yml'


def expected_request():
    parent = json.loads((HERE/PARENTS).read_bytes())
    need(parent['schema'] == 'research.core-volatility-reviewed-parents/1'
         and set(parent['arms']) == {'VOL075'}
         and parent['admissions']['VOL075']['whole_cipher_authenticated_before_parsing']
         and parent['arms']['VOL075']['completed'] == 21, 'EXACT_OWN_AAAP_REVIEWED_PARENT')
    original = json.loads((HERE/'core-volatility-continuation-request.json').read_bytes())
    target = original['parents']['VOL075']['completed']+original['maximum']
    need(target == 1642 and original['generation'] == 2, 'ORIGINAL_UNCHANGED_SEGMENT_TARGET')
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-followup-request/1', 'generation': 3,
            'stage': 'OWN_REVIEWED_FOLLOWUP', 'arms': {'VOL075': .75}, 'parents': parent['arms'],
            'input_model': 'ORIGINAL_AAAP_TENDER', 'maximum': target-21,
            'financial_wait_seconds': 12600, 'review_wait_seconds': 2700,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_AAAP_FOLLOWUP_SOURCE_CLOSURE')
    from core_volatility_aaap import prepare
    return {'status': 'CORE_VOLATILITY_AAAP_FOLLOWUP_DATA_PROBE_PASSED', 'canonical_runtime_executed': False}


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
        need(not a.request.exists(), 'NEW_FOLLOWUP_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        probe(a.request)
        launch(a, contract=expected_request())
