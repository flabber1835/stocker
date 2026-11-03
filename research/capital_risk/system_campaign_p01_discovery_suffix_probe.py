"""Verify every prior source byte and suffix AST without financial execution."""
import argparse
import hashlib
import importlib.abc
import json
from pathlib import Path
import sys


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('P01_SUFFIX_METADATA_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0,Fence())


def main(args):
    from full_system_benchmark import need
    from seal import sha256_file
    from system_campaign_p01_discovery_suffix_job import expected_request
    from system_campaign_p01_discovery_suffix_replay import iterator_tree,suffix_tree,exact_raw,original
    root=Path(__file__).resolve().parent
    request=json.loads(args.request.read_bytes())
    need(request==expected_request(),'P01_SUFFIX_METADATA_EXACT_REQUEST')
    oldraw=(root/'system-campaign-p01-discovery-request-003.json').read_bytes()
    need(hashlib.sha256(oldraw).hexdigest()=='82174d3116e9aa8617de2041f3ba69df5bc447fa7c2e7cb00ced450e5a5bc3b7',
         'P01_SUFFIX_EXACT_ADMITTED_PRIOR_REQUEST_BYTES')
    old=json.loads(oldraw)
    need(len(old['sources'])==367 and all(sha256_file(root/n)==h for n,h in old['sources'].items()),
         'P01_SUFFIX_ALL367_PRIOR_DRIVER_BYTES_UNCHANGED')
    compile(iterator_tree(exact_raw(original)),'<suffix-iterator-metadata>','exec')
    compile(suffix_tree(exact_raw(original)),'<suffix-replay-metadata>','exec')
    print(json.dumps(dict(status='P01_SUFFIX_METADATA_QUALIFIED_NO_FINANCIAL_EXECUTION',sources=len(request['sources']),
        retained_sources=367,financial_authority=False,production_contacted=False)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args())
