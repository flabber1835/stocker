"""Read-only successor metadata verification under a financial import fence."""
import argparse
import importlib.abc
import json
from pathlib import Path
import sys


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('SPINOFF_METADATA_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0, Fence())


def main(args):
    from system_campaign_discovery_spinoff_job import expected_request
    from full_system_benchmark import need
    request = expected_request()
    need(json.loads(args.request.read_bytes()) == request, 'SPINOFF_METADATA_EXACT_SUCCESSOR_REQUEST')
    print(json.dumps(dict(status='EXACT_SPINOFF_SUFFIX_METADATA_QUALIFIED_NO_FINANCIAL_EXECUTION',
        sources=len(request['sources']), retained_sources=426, arms=request['arms'],
        financial_authority=False, production_contacted=False)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    main(parser.parse_args())
