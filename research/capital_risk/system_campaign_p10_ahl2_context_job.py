"""Old immutable P10 orchestration with exact new host/worker transport context."""
import argparse
import ast
import os
from pathlib import Path

from system_campaign_p10_ahl2_context import (HERE,REQUEST,WORKFLOW,entrypoint,
    host_expected_request,frozen_namespace)

def expected_request():
    return host_expected_request(Path(os.environ['GITHUB_WORKSPACE'])/'.github/workflows'/WORKFLOW)

def job_namespace():
    raw,nodes,namespace=frozen_namespace('system_campaign_p10_ahl2_job.py',
        ('main','inspect','worker_command','stopped_record'))
    namespace.update(expected_request=expected_request,entrypoint=entrypoint)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<p10-context-original-host-orchestration>','exec'),namespace)
    return namespace

def main(args):return job_namespace()['main'](args)
def inspect(name,identity=None):return job_namespace()['inspect'](name,identity)
def worker_command(*args,**kwargs):return job_namespace()['worker_command'](*args,**kwargs)
def stopped_record(*args,**kwargs):return job_namespace()['stopped_record'](*args,**kwargs)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
