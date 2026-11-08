"""A shared-input replay of the existing control, on its own financial origin."""
import argparse
import json
from pathlib import Path

from core_volatility_job import HERE, DOC, launch
from core_volatility_source import need
from seal import sha256_file

REQUEST = 'core-volatility-control-replay-request.json'
PARENTS = 'core-volatility-control-replay-parents.json'
WORKFLOW = '.github/workflows/capital-core-volatility-control-replay.yml'


def expected_request():
    parent = json.loads((HERE/PARENTS).read_bytes())
    need(parent['schema'] == 'research.core-volatility-reviewed-parents/1'
         and set(parent['arms']) == {'CONTROL'} and parent['arms']['CONTROL']['completed'] == 1642
         and parent['arms']['CONTROL']['checkpoint_sha256'] == 'cf357b04513897586d869646cb0bdf850b5e051b4c847a75507a99e452ba847b'
         and parent['admissions']['CONTROL']['whole_cipher_authenticated_before_parsing']
         and parent['equivalence_admission']['diagnostic_only'] and parent['equivalence_admission']['exact_noop'] is False
         and parent['equivalence_admission']['whole_cipher_authenticated_before_parsing'], 'OWN_CONTROL_AND_NEGATIVE_CHECK_EVIDENCE')
    selected = parent['selected_history']
    need(selected['completed'] == 21 and selected['session'] == '2018-01-31'
         and selected['outer_sha256'] == '0f2dbfe6ee37ea47e6d0240b2cf0713a95474712e5648b1cab574198252be815', 'EXACT_OWN_21_REPLAY_START')
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-control-replay-request/1', 'generation': 9,
            'stage': 'OWN_CONTROL_INPUT_REPLAY', 'arms': {'CONTROL': 1.}, 'parents': parent['arms'],
            'selected_history': selected, 'equivalence_evidence': parent['equivalence_evidence'],
            'maximum': 1642-21, 'financial_wait_seconds': 12600, 'review_wait_seconds': 2700,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_CONTROL_REPLAY_SOURCE_CLOSURE')
    from core_volatility_control_replay import entrypoints, MODELS
    for model in MODELS:
        entrypoints(model)
    return {'status': 'CORE_VOLATILITY_CONTROL_REPLAY_DATA_PROBE_PASSED', 'canonical_runtime_executed': False}


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
        need(not a.request.exists(), 'NEW_CONTROL_REPLAY_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        probe(a.request)
        launch(a, contract=expected_request())
