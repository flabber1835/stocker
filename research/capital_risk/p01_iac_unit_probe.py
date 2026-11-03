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
    from p01_iac_unit_job import expected_request,HERE
    value=expected_request();need(json.loads(args.request.read_bytes())==value,'P01_IAC_EXACT_METADATA_REQUEST')
    need(sha256_file(HERE/'p01_celg_input_transport.py')==value['actual_quote_transport_sha256']
         and sha256_file(HERE/'ephemeral_runner_capacity.py')==value['capacity_source_sha256'],
         'P01_IAC_FROZEN_QUOTE_AND_CAPACITY_HELPERS')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],source_sha256=value['capacity_source_sha256'])
    need(value['source_epoch_physical_files']==516 and value['canonical_source_files']==224
         and value['original_inputs']==11 and value['successor_inputs']==12 and value['new_typed_factual_input']==1
         and value['maximum_financial_transitions']==251 and value['expected_completed']==879
         and value['financial_start']=='2020-07-01' and value['processing_endpoint']=='2021-06-29'
         and value['qualified_full_runtime_sessions']==2 and value['input_adoptions']==1
         and value['qualified_through']=='2020-07-02' and value['actual_fast_reference_full_components_required'] is True
         and value['source_epoch_boundary_reemitted'] is False
         and value['request_serialization']=='COPY_EXACT_SOURCE_BYTES'
         and value['quote_descriptor']['ciphertext_bytes']==10276,'P01_IAC_EXACT_UNCHANGED_EPOCH_AND_ENDPOINT')
    forbidden={'p01_celg_multileg_quote.json.gz','p01_celg_multileg_quote_capture.json',
        'p01_celg_multileg_facts.py','p01_celg_multileg_qualification_plan.json'}
    need(not set(value['sources'])&forbidden,'P01_IAC_NO_PRIVATE_MARKET_PAYLOAD_PUBLICATION')
    print(json.dumps(dict(status='P01_OWN628_IAC_UNIT_METADATA_AND_CAPACITY_VERIFIED',sources=len(value['sources']),
        original_inputs=11,successor_inputs=12,new_input=1,source_epoch_files=516,canonical_source_files=224,
        maximum_financial_transitions=251,capacity_prepared=True,local_financial_execution=False,
        financial_predecessor_admitted=False)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--capacity',type=Path,required=True);main(parser.parse_args())
