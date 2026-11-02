"""Host-only workflow/source/capacity gate; worker request check stays flat."""
import argparse
import ast
import json
from pathlib import Path
import sys

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery_probe import Fence
import p01_iac_unit_probe as previous

SOURCE_SHA='85fcc423a974a5c50fa01f01a29deded7cea2b20a1a681c40894565656f6621c'
sys.meta_path.insert(0,Fence())


def main(args):
    from p01_iac_namespace_job import expected_request,HERE,WORKFLOW,WORKFLOW_SHA,encoded_request
    value=expected_request()
    need(args.request.read_bytes()==encoded_request(value),'RECOVERY_WHOLE_HOST_REQUEST_PREIMAGE')
    need(sha256_file(HERE.parents[1]/'.github/workflows'/WORKFLOW)==WORKFLOW_SHA,
         'RECOVERY_ACTUAL_HOST_WORKFLOW_BYTES_NOT_WORKER_LAYOUT')
    raw=Path(previous.__file__).read_bytes()
    need(sha256_file(Path(previous.__file__))==SOURCE_SHA,'RECOVERY_EXACT_484_METADATA_CAPACITY_PROBE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    changes=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            if item.module=='p01_iac_unit_job':item.module='p01_iac_namespace_job';changes.append(item)
            return item
    node=Scope().visit(node);need(len(changes)==1,'RECOVERY_ONE_EXACT_METADATA_PROBE_IMPORT')
    values=dict(vars(previous),__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-fixture-metadata-capacity-probe>','exec'),values)
    return values['main'](args)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--capacity',type=Path,required=True);main(parser.parse_args())
