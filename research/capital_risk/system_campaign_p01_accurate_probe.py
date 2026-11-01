"""P01 accurate-prefix request check; financial imports forbidden locally."""
import argparse,json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence
if __name__=='__main__':
    from system_campaign_p01_accurate_job import expected_request
    from full_system_benchmark import need
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'P01_ACCURATE_EXACT_METADATA')
    print(json.dumps(dict(status='P01_ACCURATE_METADATA_VERIFIED',sources=len(value['sources']),
        own_strict_parent='2019-08-30',maximum_transitions=19,financial_runtime_executed=False)))
