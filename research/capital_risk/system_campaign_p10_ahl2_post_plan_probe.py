"""Host metadata only; no Core/controller/account import is permitted."""
import argparse
import json
import os
from pathlib import Path
import sys

from system_campaign_parallel_discovery_probe import Fence
sys.meta_path.insert(0,Fence())


def main(args):
    from ephemeral_runner_capacity import validate_prepared_receipt
    from system_campaign_p10_ahl2_job import CAPACITY_SHA
    from system_campaign_p10_ahl2_contract import need,specification
    from system_campaign_p10_ahl2_post_plan import WORKFLOW,host_expected_request
    from system_campaign_p10_ahl2_wire import object_bytes
    expected = host_expected_request(Path(os.environ['GITHUB_WORKSPACE'])/'.github/workflows'/WORKFLOW)
    need(object_bytes(args.request.read_bytes()) == expected,'P10_POST_PLAN_METADATA_FULL_REQUEST_AND_HOST_WORKFLOW')
    validate_prepared_receipt(object_bytes(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],source_sha256=CAPACITY_SHA)
    specification()
    print(json.dumps(dict(status='P10_POST_PLAN_SOURCE_WORKFLOW_CAPACITY_AND_REUSE_SCOPE_READY',
        sources=len(expected['sources']),financial_authority=False,canonical_execution=False)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('request','capacity'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
