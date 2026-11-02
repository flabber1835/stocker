"""Minimal metadata closure; financial runtime imports are forbidden here."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys


class NoFinancialRuntime:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('WINTER2025_METADATA_OUTSIDE_LOCKED_BOUNDARY:'+fullname)
        return None


sys.meta_path.insert(0,NoFinancialRuntime())
from full_system_benchmark import need
from system_campaign_p02_winter2025_cash_job import expected_request
from system_campaign_close_import_probe import VERSIONS
from probe import check_context


def qualify(request):
    actual={name:version(name) for name in VERSIONS}
    need(actual==VERSIONS,'WINTER2025_EXACT_LOCKED_METADATA_DEPENDENCIES')
    need(request==expected_request(),'WINTER2025_COMPLETE_EXACT_REQUEST_AND_METADATA_CLOSURE')
    return dict(status='WINTER2025_METADATA_AND_EXACT_REQUEST_QUALIFIED',dependency_versions=actual,
        source_files=len(request['sources']),actual_financial_runtime_imports=False,
        financial_sessions_advanced=0,production_contacted=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args();check_context(os.environ)
    print(json.dumps(qualify(json.loads(args.request.read_bytes()))))
