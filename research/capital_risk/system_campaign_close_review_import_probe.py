"""Qualify only metadata imports and the exact review-only request."""
import argparse
import json
from pathlib import Path
from types import FunctionType

import system_campaign_close_import_probe as original
from system_campaign_close_review_job import expected_request
from probe import check_context
import os


def qualify(request):
    fn=original.qualify
    checked=FunctionType(fn.__code__,dict(fn.__globals__,expected_request=expected_request),fn.__name__,fn.__defaults__)
    return checked(request)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    check_context(os.environ);print(json.dumps(qualify(json.loads(args.request.read_bytes()))))
