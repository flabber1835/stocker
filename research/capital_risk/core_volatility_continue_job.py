"""Resume each own reviewed arm; source-bound request, never pilot reruns."""
import argparse
import json
import math
from pathlib import Path

from core_volatility_job import HERE, DOC, launch
from core_volatility_source import ARMS, need
from seal import sha256_file

REQUEST = 'core-volatility-continuation-request.json'
PARENTS = 'core-volatility-parents.json'
WORKFLOW = '.github/workflows/capital-core-volatility-continuation.yml'


def bounds(timings):
    need(set(timings) == set(ARMS), 'PAIRED_TIMING_SCOPE')
    rate = max(v['financial_seconds']/v['new_financial_transitions'] for v in timings.values())
    warmup = max(v['warmup_seconds'] for v in timings.values())
    need(math.isfinite(rate) and rate > 0 and math.isfinite(warmup) and warmup >= 0, 'ACTUAL_TIMING_VALUES')
    remaining = max(2156-v['completed'] for v in timings.values())
    reserve = 2*warmup+600
    projection = remaining*rate*1.35+reserve
    maximum = 0 if projection <= 12000 else int((12000-reserve)/(rate*1.35))
    need(maximum == 0 or 21 <= maximum <= 2156, 'USEFUL_BOUNDED_SEGMENT')
    return {'maximum': maximum, 'financial_wait_seconds': 12600, 'review_wait_seconds': 2700,
            'conservative_transition_seconds': rate, 'projection_seconds_with_margin': projection,
            'full_remaining_axis_budgeted': maximum == 0}


def expected_request():
    parents = json.loads((HERE/PARENTS).read_bytes())
    need(parents['schema'] == 'research.core-volatility-reviewed-parents/1'
         and set(parents['arms']) == set(ARMS)
         and all(v['whole_cipher_authenticated_before_parsing'] for v in parents['admissions'].values()),
         'INDEPENDENT_PAIRED_PILOT_ADMISSION')
    plan = bounds(parents['timings'])
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-continuation-request/1', 'generation': 2,
            'stage': 'OWN_PILOT_CONTINUATION', 'arms': ARMS, 'parents': parents['arms'], **plan,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_CONTINUATION_SOURCE_CLOSURE')
    from core_volatility_admit import hosted
    return {'status': 'CORE_VOLATILITY_CONTINUATION_DATA_PROBE_PASSED', 'canonical_runtime_executed': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--request', type=Path, default=HERE/REQUEST)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--arm', choices=ARMS)
    for field in ('staging', 'capacity', 'output'):
        p.add_argument('--'+field, type=Path)
    a = p.parse_args()
    if a.prepare:
        need(not a.request.exists(), 'NEW_CONTINUATION_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        probe(a.request)
        launch(a, contract=expected_request())
