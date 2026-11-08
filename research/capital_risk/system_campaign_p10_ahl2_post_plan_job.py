"""Unchanged stopped-only crypto lifecycle, explicit Q capsule and new entrypoint."""
import argparse
import ast
import os
from pathlib import Path
import shutil

from system_campaign_p10_ahl2_contract import need
from system_campaign_p10_ahl2_context import frozen_namespace
from system_campaign_p10_ahl2_post_plan import (HERE,REQUEST,WORKFLOW,BUDGET,entrypoint,host_expected_request)
from system_campaign_p10_ahl2_post_plan_parent import admit_capsule
from system_campaign_p10_ahl2_post_plan_gate import qualification_valid


def expected_request():
    return host_expected_request(Path(os.environ['GITHUB_WORKSPACE'])/'.github/workflows'/WORKFLOW)


def retain_qualification(source,target):
    # All immutable qualifier bytes are explicitly retained as evidence. This
    # function is never a source of the suffix runtime; fresh OWN1 is enforced
    # independently in the worker and replay entrypoints.
    shutil.copytree(source,target)


def job_namespace():
    _,nodes,namespace = frozen_namespace('system_campaign_p10_ahl2_job.py',
        ('main','inspect','worker_command','stopped_record','qualified_for_suffix'))
    namespace.update(expected_request=expected_request,entrypoint=entrypoint,BUDGET=BUDGET,
        admit_own=admit_capsule,qualification_valid=qualification_valid,retain_qualification=retain_qualification)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<p10-post-plan-same-stopped-host-lifecycle>','exec'),namespace)
    exact_command = namespace['worker_command']
    def capsule_command(name,role,source,frozen,out,old,previous,evidence=None):
        previous = Path(previous)
        need(previous.name == 'own1' and (previous.parent/'capsule.json').is_file(),
             'P10_POST_PLAN_HOST_MOUNTS_ONLY_EXPLICIT_COMPOSITE_CAPSULE')
        return exact_command(name,role,source,frozen,out,old,previous.parent,evidence=evidence)
    namespace['worker_command'] = capsule_command
    return namespace


def main(args):return job_namespace()['main'](args)
def inspect(name,identity=None):return job_namespace()['inspect'](name,identity)
def stopped_record(*args,**kwargs):return job_namespace()['stopped_record'](*args,**kwargs)
def worker_command(*args,**kwargs):return job_namespace()['worker_command'](*args,**kwargs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
