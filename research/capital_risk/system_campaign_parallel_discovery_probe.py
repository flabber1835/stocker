"""Metadata-only source closure admission before staging or worker creation."""
import argparse
import importlib.abc
import json
from pathlib import Path
import sys


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('PARALLEL_METADATA_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0,Fence())


def main(args):
    from system_campaign_parallel_discovery_job import expected_request
    from system_campaign_parallel_discovery import ARMS,HERE,PRIOR,PRIOR_SHA,specification
    from full_system_benchmark import need
    from seal import sha256_file
    need(json.loads(args.request.read_bytes())==expected_request(),'PARALLEL_ACTUAL_EXACT_METADATA_REQUEST')
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'PARALLEL_EXACT_ORIGINAL375_REQUEST')
    old=json.loads((HERE/PRIOR).read_bytes())
    need(len(old['sources'])==375 and all(sha256_file(HERE/n)==h for n,h in old['sources'].items()),
         'PARALLEL_ALL375_ORIGINAL_SOURCE_BYTES_UNCHANGED')
    for arm in ARMS:specification(arm)
    print(json.dumps(dict(status='PARALLEL_METADATA_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(expected_request()['sources']),retained_sources=375,arms=list(ARMS),
        financial_authority=False,production_contacted=False)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args())
