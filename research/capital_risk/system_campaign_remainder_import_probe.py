"""Metadata closure only; canonical execution is restricted to hosted workers."""
import argparse
import importlib.abc
import json
from pathlib import Path
import sys


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_', 'numpy', 'pandas')):
            raise ImportError('REMAINDER_LOCAL_FINANCIAL_IMPORT_FORBIDDEN:' + fullname)
        return None


sys.meta_path.insert(0, Fence())


def main(args):
    from full_system_benchmark import need
    from seal import sha256_file
    from system_campaign_p02_remainder_job import expected_request
    from system_campaign_remainder_facts import validate
    root = Path(__file__).resolve().parent
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(), 'REMAINDER_EXACT_METADATA_REQUEST')
    old = json.loads((root / 'system-campaign-p02-discovery-request.json').read_bytes())
    need(len(old['sources']) == 343 and all(sha256_file(root / n) == h for n, h in old['sources'].items()),
         'REMAINDER_ALL343_PREVIOUS_DRIVER_BYTES_UNCHANGED')
    validate(json.loads((root / 'system-campaign-remainder-terminal-facts.json').read_bytes()))
    print(json.dumps(dict(status='REMAINDER_METADATA_PASSED', sources=len(request['sources']),
        retained_sources=343, local_financial_execution=False,
        hosted_canonical_qualification_not_yet_observed=True, production_contacted=False)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--request', type=Path, required=True)
    main(parser.parse_args())
