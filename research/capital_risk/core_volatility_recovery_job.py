"""One zero-transition qualification of the exact failed November prefix."""
import argparse
import json
from pathlib import Path

from core_volatility_job import HERE, DOC, launch
from core_volatility_source import need
from core_volatility_recovery import CURRENT, RUN, HEAD, ZIP
from seal import sha256_file

REQUEST = 'core-volatility-recovery-request.json'
PARENTS = 'core-volatility-recovery-evidence.json'
WORKFLOW = '.github/workflows/capital-core-volatility-recovery.yml'


def expected_request():
    parent = json.loads((HERE/PARENTS).read_bytes())
    need(parent['run_id'] == RUN and parent['head'] == HEAD and parent['zip_sha256'] == ZIP
         and parent['checkpoint_sha256'] == CURRENT, 'EXACT_READONLY_RECOVERY_EVIDENCE')
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-recovery-request/1', 'generation': 4,
            'stage': 'OWN_REVIEW_RECOVERY', 'arms': {'VOL075': .75}, 'parents': {'VOL075': parent},
            'maximum': 0, 'financial_sessions_advanced': 0,
            'financial_wait_seconds': 900, 'review_wait_seconds': 900,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_RECOVERY_SOURCE_CLOSURE')
    return {'status': 'CORE_VOLATILITY_RECOVERY_DATA_PROBE_PASSED', 'canonical_runtime_executed': False}


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
        need(not a.request.exists(), 'NEW_RECOVERY_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        probe(a.request)
        launch(a, contract=expected_request())
