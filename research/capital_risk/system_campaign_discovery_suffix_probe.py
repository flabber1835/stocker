"""Source closure only; reject all financial imports before hosted staging."""
import argparse
import importlib.abc
import json
from pathlib import Path
import sys


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('SUFFIX_METADATA_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0,Fence())


def main(args):
    from system_campaign_discovery_suffix_job import expected_request
    from full_system_benchmark import need
    request=expected_request()
    need(json.loads(args.request.read_bytes())==request,'SUFFIX_METADATA_EXACT_REQUEST')
    print(json.dumps(dict(status='EXACT_SUFFIX_METADATA_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(request['sources']),retained_sources=418,arms=request['arms'],
        financial_authority=False,production_contacted=False)),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args())
