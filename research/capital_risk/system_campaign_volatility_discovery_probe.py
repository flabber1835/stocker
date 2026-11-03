"""Metadata only; canonical strategy execution is hosted and offline."""
import argparse,json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence

if __name__=='__main__':
    from system_campaign_volatility_discovery_job import expected_request
    from full_system_benchmark import need
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'V_RETENTION_EXACT_METADATA')
    print(json.dumps(dict(status='V_RETENTION_METADATA_VERIFIED',sources=len(value['sources']),
        retained_sources=391,arms=value['arms'],financial_authority=False,production_contacted=False)))
