"""Metadata-only source/input/OWN475 request check; no canonical runtime imports."""
import argparse
import json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence


def main(args):
    from full_system_benchmark import need
    from p01_celg_bridge_job import expected_request,HERE,SOURCE_MAP,DESCRIPTOR
    from seal import sha256_file
    from p01_celg_bridge_codec import NATIVE,NATIVE_SHA
    from p01_celg_bridge_gate import digest
    value=expected_request()
    need(json.loads(args.request.read_bytes())==value,'P01_CELG_BRIDGE_EXACT_METADATA_REQUEST')
    need(sha256_file(HERE/'p01_celg_input_transport.py')==value['actual_quote_transport_sha256']
         and sha256_file(HERE/'ephemeral_runner_capacity.py')==value['capacity_source_sha256'],
         'P01_CELG_BRIDGE_EXACT_QUALIFIED_TRANSPORT_AND_CAPACITY_HELPERS')
    need(digest(NATIVE)==NATIVE_SHA and len(value['source_map_changed_paths'])==6
         and value['quote_descriptor']['ciphertext_bytes']==10276
         and value['quote_descriptor']['ciphertext_sha256']==
             '91892ed9db39a6d0f208cb809b89138806746f07299109b077fc69232c982aa9',
         'P01_CELG_BRIDGE_FIXED_NATIVE_PREIMAGE_SOURCE_DELTA_AND_ACTUAL_QUOTE_CIPHER')
    forbidden={'p01_celg_multileg_quote.json.gz','p01_celg_multileg_quote_capture.json',
               'p01_celg_multileg_facts.py','p01_celg_multileg_qualification_plan.json'}
    need(not set(value['sources'])&forbidden,'P01_CELG_BRIDGE_NO_PRIVATE_MARKET_PAYLOAD_PUBLICATION')
    print(json.dumps(dict(status='P01_CELG_OWN475_METADATA_SOURCE_INPUT_BRIDGE_VERIFIED',
        sources=len(value['sources']),original_inputs=9,new_input=1,maximum_financial_transitions=51,
        source_paths_changed=6,local_financial_execution=False,financial_predecessor_admitted=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);main(p.parse_args())
