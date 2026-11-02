"""Metadata and AST closure only; prohibit local financial runtime imports."""
import argparse
import json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence


if __name__ == '__main__':
    from full_system_benchmark import need
    from system_campaign_volatility_native_job import expected_request, orchestration_tree
    from system_campaign_volatility_native_gate import native_tree
    from system_campaign_volatility_native_parent import admission_tree
    from system_campaign_volatility_native_run import worker_tree
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    value = expected_request()
    need(json.loads(args.request.read_bytes()) == value, 'V_NATIVE_EXACT_REQUEST_METADATA')
    for function in (orchestration_tree, native_tree, admission_tree, worker_tree):
        function()
    print(json.dumps(dict(status='V_NATIVE_METADATA_AND_AST_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(value['sources']),retained_sources=418,arms=value['arms'],
        financial_runtime_executed=False)),flush=True)
