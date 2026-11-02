"""Exact P11-only metadata; no local market or strategy processing."""
import argparse,json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence

if __name__=='__main__':
    from system_campaign_volatility_admission_recovery import expected_request,tree
    from full_system_benchmark import need
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'V_ADMISSION_EXACT_METADATA')
    tree()
    print(json.dumps(dict(status='P11_ADMISSION_RECOVERY_METADATA_VERIFIED',sources=len(value['sources']),
        retained_sources=415,arms=value['arms'],financial_runtime_executed=False)))
