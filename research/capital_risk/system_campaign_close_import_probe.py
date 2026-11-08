"""Metadata-only transfer import qualification before staging or worker launch."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys


class NoFinancialRuntime:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_')):
            raise ImportError('HOST_METADATA_MUST_NOT_IMPORT_FINANCIAL_RUNTIME:' + fullname)
        return None


sys.meta_path.insert(0, NoFinancialRuntime())
from full_system_benchmark import need
from system_campaign_p02_close_job import expected_request
from probe import check_context

VERSIONS = {'pydantic': '2.11.7', 'pydantic-core': '2.33.2',
            'annotated-types': '0.8.0', 'typing-extensions': '4.16.0',
            'typing-inspection': '0.4.4'}


def qualify(request):
    actual = {name: version(name) for name in VERSIONS}
    need(actual == VERSIONS, 'CLOSE_EXACT_HASH_LOCKED_METADATA_DEPENDENCIES')
    expected = expected_request()
    need(request == expected, 'CLOSE_ACTUAL_IMPORT_CLOSURE_AND_EXACT_REQUEST')
    return dict(status='METADATA_IMPORT_AND_SCHEMA_REQUEST_QUALIFIED',
        dependency_versions=actual, source_files=len(request['sources']),
        actual_financial_runtime_imports=False, financial_sessions_advanced=0,
        production_contacted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    check_context(os.environ)
    print(json.dumps(qualify(json.loads(args.request.read_bytes()))))
