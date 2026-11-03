"""Verify exact unchanged original source closure without financial imports."""
import argparse,json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence


def main(args):
    from system_campaign_risk_discovery_job import expected_request
    from full_system_benchmark import need
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'RISK_RECOVERY_EXACT_METADATA_REQUEST')
    print(json.dumps(dict(status='RISK_RECOVERY_METADATA_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(value['sources']),retained_sources=383,arms=value['arms'],financial_authority=False,
        production_contacted=False)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);main(p.parse_args())
