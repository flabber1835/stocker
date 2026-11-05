"""P11 capacity receipt, immutable source closure and AST only; no financial replay."""
import argparse
import json
import os
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence


def main(args):
    from full_system_benchmark import need
    import system_campaign_volatility_capacity_job as job
    from system_campaign_volatility_native_gate import native_tree
    from system_campaign_volatility_native_parent import admission_tree
    from system_campaign_volatility_native_run import worker_tree
    value = job.expected_request()
    need(json.loads(args.request.read_bytes()) == value, 'V_CAPACITY_EXACT_REQUEST_METADATA')
    need(args.capacity_receipt is not None or os.environ.get('GITHUB_ACTIONS') != 'true',
         'V_CAPACITY_HOSTED_PREPARED_RECEIPT_REQUIRED')
    if args.capacity_receipt is not None:
        job.validate_capacity_receipt(args.capacity_receipt)
    for function in (job.native_main_tree, job.native.orchestration_tree, native_tree, admission_tree, worker_tree):
        function()
    print(json.dumps(dict(status='V_CAPACITY_METADATA_AND_AST_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(value['sources']),retained_sources=427,arms=value['arms'],
        capacity_receipt_checked=args.capacity_receipt is not None,
        financial_runtime_executed=False)),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--capacity-receipt', type=Path)
    main(parser.parse_args())
