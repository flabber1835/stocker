"""Metadata admission only; canonical financial imports remain fenced locally."""
import argparse
import json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence

if __name__ == '__main__':
    from full_system_benchmark import need
    from p01_action_clock_job import expected_request
    p = argparse.ArgumentParser(); p.add_argument('--request',type=Path,required=True)
    args = p.parse_args(); value = expected_request()
    need(json.loads(args.request.read_bytes()) == value, 'P01_CLOCK_METADATA_EXACT_REQUEST')
    print(json.dumps(dict(status='P01_CLOCK_METADATA_ONLY_VERIFIED',sources=len(value['sources']),
        maximum_component_transitions=2, financial_authority=False, local_financial_execution=False)))
