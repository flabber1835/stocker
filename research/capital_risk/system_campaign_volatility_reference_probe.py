"""Metadata-only admission for the missing-reference qualification recovery."""
import argparse,json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence

if __name__=='__main__':
    from system_campaign_volatility_reference_job import expected_request,orchestration_tree
    from system_campaign_volatility_reference_gate import reference_tree
    from system_campaign_volatility_reference_parent import admission_tree
    from full_system_benchmark import need
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'V_REFERENCE_EXACT_REQUEST_METADATA')
    for fn in (orchestration_tree,reference_tree,admission_tree):fn()
    print(json.dumps(dict(status='V_REFERENCE_METADATA_VERIFIED',sources=len(value['sources']),
        retained_sources=408,arms=value['arms'],financial_runtime_executed=False)))
