"""Metadata-only source and synthetic-fixture check before capacity/staging."""
import argparse
import json
from pathlib import Path
from system_campaign_parallel_discovery_probe import Fence

def main(args):
    from full_system_benchmark import need
    from seal import sha256_file
    from p01_celg_job import expected_request,HERE
    from p01_celg_multileg_facts import PRIMARY_SHA
    from p01_celg_component import quote,QUOTE_AUTHORITY
    value=expected_request()
    need(json.loads(args.request.read_bytes())==value,'CELG_EXACT_METADATA_ONLY_REQUEST')
    need(sha256_file(HERE/'p01_celg_multileg_primary.json')==PRIMARY_SHA,'CELG_EXACT_PUBLIC_PRIMARY_LEGAL_EXTRACTION')
    need(value['capacity_source_sha256']=='c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379',
         'CELG_EXACT_QUALIFIED_CAPACITY_HELPER')
    need(not set(value['sources'])&{'p01_celg_multileg_quote.json.gz','p01_celg_multileg_quote_capture.json',
                                  'p01_celg_multileg_qualification_plan.json'}
         and quote()['authority']==QUOTE_AUTHORITY and quote()['observed_market_data'] is False,
         'CELG_NO_PRIVATE_PROVIDER_CAPTURE_PUBLICATION_OR_AUTHENTICATION_CLAIM')
    print(json.dumps(dict(status='CELG_METADATA_ONLY_SYNTHETIC_COMPONENT_VERIFIED',sources=len(value['sources']),
        retained_p01_driver_sources=418,required_positive_cases=1,required_negative_cases=10,
        financial_authority=False,local_financial_execution=False,production_contacted=False)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);main(p.parse_args())
