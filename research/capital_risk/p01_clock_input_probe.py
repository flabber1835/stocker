"""Metadata-only clock input/source/request check before any hosted staging."""
import argparse
import json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence

if __name__=='__main__':
    from full_system_benchmark import need
    from p01_clock_input_job import expected_request
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'P01_CLOCK_INPUT_EXACT_METADATA')
    print(json.dumps(dict(status='P01_CLOCK_INPUT_METADATA_ONLY_VERIFIED',sources=len(value['sources']),
        original_inputs=8,new_clock_inputs=1,maximum_financial_transitions=37,
        source515_unchanged=True,local_financial_execution=False)))
