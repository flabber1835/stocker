"""Verify the exact recorder successor without financial execution."""
import argparse,json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence
if __name__=='__main__':
    from system_campaign_volatility_discovery_job_v2 import expected_request
    from full_system_benchmark import need
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'V_RECORDER_EXACT_METADATA')
    print(json.dumps(dict(status='V_RECORDER_METADATA_VERIFIED',sources=len(value['sources']),
        retained_sources=402,arms=value['arms'],financial_runtime_executed=False)))
