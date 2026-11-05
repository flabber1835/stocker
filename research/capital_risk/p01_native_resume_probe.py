"""Metadata/capacity preflight; no financial runtime imports or execution."""
import argparse
import json
import os
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence


def main(args):
    from full_system_benchmark import need
    from seal import sha256_file
    from ephemeral_runner_capacity import validate_prepared_receipt
    from p01_native_resume_job import expected_request,HERE
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'P01_NATIVE_EXACT_METADATA_REQUEST')
    need(sha256_file(HERE/'p01_celg_input_transport.py')==value['actual_quote_transport_sha256']
         and sha256_file(HERE/'ephemeral_runner_capacity.py')==value['capacity_source_sha256'],
         'P01_NATIVE_FROZEN_QUOTE_AND_CAPACITY_HELPERS')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],source_sha256=value['capacity_source_sha256'])
    need(value['source_epoch_physical_files']==516 and value['canonical_source_files']==224
         and value['original_inputs']==11 and value['new_typed_factual_input']==0
         and value['maximum_financial_transitions']==1 and value['expected_completed']==628
         and value['financial_start']==value['processing_endpoint']=='2020-06-30'
         and value['qualified_full_runtime_sessions']==1 and value['input_boundary_reemitted'] is False
         and value['request_serialization']=='COPY_EXACT_SOURCE_BYTES'
         and value['quote_descriptor']['ciphertext_bytes']==10276,'P01_NATIVE_EXACT_UNCHANGED_EPOCH_AND_ENDPOINT')
    forbidden={'p01_celg_multileg_quote.json.gz','p01_celg_multileg_quote_capture.json',
        'p01_celg_multileg_facts.py','p01_celg_multileg_qualification_plan.json'}
    need(not set(value['sources'])&forbidden,'P01_NATIVE_NO_PRIVATE_MARKET_PAYLOAD_PUBLICATION')
    print(json.dumps(dict(status='P01_OWN627_NATIVE_METADATA_AND_CAPACITY_VERIFIED',sources=len(value['sources']),
        original_inputs=11,new_input=0,source_epoch_files=516,canonical_source_files=224,
        maximum_financial_transitions=1,capacity_prepared=True,local_financial_execution=False,
        financial_predecessor_admitted=False)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--capacity',type=Path,required=True);main(parser.parse_args())
