"""Source/target/workflow/capacity probe, never financial replay."""
import argparse
import sys
from system_campaign_parallel_discovery_probe import Fence
sys.meta_path.insert(0,Fence())
from pathlib import Path
from full_system_benchmark import need
from probe import check_context
from seal import sha256_file
from ephemeral_runner_capacity import validate_prepared_receipt
from p01_iac_stopped_review_target import plain,read,encoded

def main(args):
    import os
    from p01_iac_stopped_review_job import expected_request,HERE,WORKFLOW,WORKFLOW_SHA
    check_context(os.environ);value=expected_request()
    need(read(args.request)==encoded(value) and sha256_file(HERE.parents[1]/'.github/workflows'/WORKFLOW)==WORKFLOW_SHA,'STOPPED_REVIEW_ACTUAL_HOST_WORKFLOW_AND_REQUEST')
    validate_prepared_receipt(plain(read(args.capacity)),head=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],source_sha256=value['capacity_source_sha256'])
    print('STOPPED_REVIEW_METADATA_AND_CAPACITY_QUALIFIED')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True);parser.add_argument('--capacity',type=Path,required=True);main(parser.parse_args())
