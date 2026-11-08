"""Source-bound, own-control input equivalence; no new CAGR candidate."""
import argparse
import json
from pathlib import Path

from core_volatility_job import HERE, DOC, launch
from core_volatility_source import need
from seal import sha256_file

REQUEST = 'core-volatility-equivalence-request.json'
PARENTS = 'core-volatility-equivalence-parents.json'
WORKFLOW = '.github/workflows/capital-core-volatility-equivalence.yml'


def expected_request():
    parent = json.loads((HERE/PARENTS).read_bytes())
    need(parent['schema'] == 'research.core-volatility-reviewed-parents/1'
         and set(parent['arms']) == {'CONTROL'} and parent['arms']['CONTROL']['completed'] >= 312
         and parent['admissions']['CONTROL']['whole_cipher_authenticated_before_parsing']
         and set(parent['historical_checkpoints']) == {'AAAP', 'DECEMBER', 'BEL'}, 'OWN_AUTHENTICATED_CONTROL_DIAGNOSTIC_INPUT')
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-equivalence-request/1', 'generation': 7,
            'stage': 'OWN_CONTROL_INPUT_EQUIVALENCE', 'arms': {'CONTROL': 1.}, 'parents': parent['arms'],
            'historical_checkpoints': parent['historical_checkpoints'], 'maximum': 54,
            'financial_wait_seconds': 2700, 'review_wait_seconds': 2700,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'diagnostic_only': True, 'performance_admitted': False,
            'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_EQUIVALENCE_SOURCE_CLOSURE')
    from core_volatility_control_equivalence import compiler
    for model, window in (('AAAP', 'AAAP'), ('SODA', 'DECEMBER'), ('SONC', 'DECEMBER'), ('BEL', 'BEL')):
        compiler(model, '0'*64, window)
    return {'status': 'CORE_VOLATILITY_EQUIVALENCE_DATA_PROBE_PASSED', 'canonical_runtime_executed': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--request', type=Path, default=HERE/REQUEST)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--arm', choices=('CONTROL',))
    for field in ('staging', 'capacity', 'output'):
        p.add_argument('--'+field, type=Path)
    a = p.parse_args()
    if a.prepare:
        need(not a.request.exists(), 'NEW_EQUIVALENCE_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        probe(a.request)
        launch(a, contract=expected_request())
