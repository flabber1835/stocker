"""Qualify the exact request and complete metadata import closure before staging."""
import argparse
import json
import os
from pathlib import Path
from types import FunctionType

import system_campaign_close_import_probe as original
from system_campaign_pxd_qualification_job import expected_request
import system_campaign_pxd_qualification_run
from probe import check_context


def qualify(request):
    fn=original.qualify
    checked=FunctionType(fn.__code__,dict(fn.__globals__,expected_request=expected_request),fn.__name__,fn.__defaults__)
    return checked(request)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True);args=parser.parse_args()
    check_context(os.environ);print(json.dumps(qualify(json.loads(args.request.read_bytes()))))
