"""Source/capacity metadata only; financial imports are fenced."""
import argparse
import json
import os
from pathlib import Path
import sys
from system_campaign_parallel_discovery_probe import Fence

sys.meta_path.insert(0, Fence())


def main(args):
    from ephemeral_runner_capacity import validate_prepared_receipt
    from system_campaign_p10_ahl2_contract import specification, need
    from system_campaign_p10_ahl2_job import expected_request, CAPACITY_SHA
    value = expected_request()
    need(json.loads(args.request.read_bytes()) == value, 'P10_METADATA_EXACT_REQUEST_AND_SOURCE_CLOSURE')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()), head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'], source_sha256=CAPACITY_SHA)
    specification()
    print(json.dumps(dict(status='P10_OWN_DIAGNOSTIC_METADATA_AND_CAPACITY_READY',
        sources=len(value['sources']), financial_authority=False, local_canonical_execution=False)))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('request','capacity'):
        p.add_argument('--' + name, type=Path, required=True)
    main(p.parse_args())
