"""Fail closed on metadata closure before staging; never import financial code."""
import argparse
import importlib.abc
import json
from pathlib import Path
import sys


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('DISCOVERY_METADATA_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0,Fence())


def main(args):
    from system_campaign_p01_discovery_job import expected_request
    from full_system_benchmark import need
    from seal import sha256_file
    request=json.loads(args.request.read_bytes())
    need(request==expected_request(),'DISCOVERY_ACTUAL_EXACT_METADATA_REQUEST')
    root=Path(__file__).resolve().parent
    oldraw=(root/'system-campaign-p02-remainder-request.json').read_bytes()
    import hashlib
    need(hashlib.sha256(oldraw).hexdigest()=='1cf36abbe72d1796089883c2d357b7875a7ac7966a5c3ebe991c4bb0a30eb55e',
         'DISCOVERY_EXACT_PRIOR_REQUEST_BYTES')
    old=json.loads(oldraw)
    need(len(old['sources'])==354 and all(sha256_file(root/n)==h for n,h in old['sources'].items()),
         'DISCOVERY_ALL354_PRIOR_SOURCES_UNCHANGED')
    print(json.dumps(dict(status='DISCOVERY_METADATA_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(request['sources']),retained_sources=354,financial_authority=False,
        hosted_canonical_qualification_not_yet_observed=True,production_contacted=False)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args())
