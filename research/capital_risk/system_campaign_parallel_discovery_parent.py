"""Diagnostic-only admission; the financial admission function stays unchanged."""
import ast
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import digest
import system_campaign_factual_admit as original
from system_campaign_parallel_discovery import body,compile_body,check_parent,reference


def admission_body():
    fn=body('system_campaign_factual_admit.py','admit')
    sites=[(i,n) for i,n in enumerate(fn.body) if isinstance(n,ast.If)
           and ast.unparse(n.test)=="spec.get('unadvanced_qualification_failure')"]
    need(len(sites)==1,'PARALLEL_ONE_FINANCIAL_CERTIFICATION_BRANCH_NOT_DIAGNOSTIC_AUTHORITY')
    i,node=sites[0]
    need(len(node.orelse)==1 and isinstance(node.orelse[0],ast.If)
         and ast.unparse(node.orelse[0].test)=="spec.get('review_refusal')",
         'PARALLEL_EXACT_ORIGINAL_FINANCIAL_REVIEW_BRANCH')
    fn.body[i:i+1]=ast.parse('validate_diagnostic_origin(spec,inventory,dest)').body
    return fn


def validate_diagnostic_origin(spec,inventory,dest):
    # This certifies transport/stop/state integrity only, never old performance.
    value=json.loads((Path(dest)/'economic-worker-inspect.json').read_bytes())
    need(digest(value['Config']['Cmd'])==spec['financial_entrypoint_sha256']
         and spec['prior_worker']['stopped'] is True and spec['prior_worker']['oom_killed'] is False
         and value['State']['ExitCode']==spec['prior_worker']['exit_code'],
         'PARALLEL_ACTUAL_PRIOR_FINANCIAL_STOP_AND_ENTRYPOINT')
    need({n:inventory[f'book/{n}.jsonl'] for n in spec['journals']}==spec['complete_journals'],
         'PARALLEL_ALL_ORIGINAL_JOURNAL_BYTES_AND_TAILS')


def admit(spec,root,key):
    namespace=dict(vars(original),validate_diagnostic_origin=validate_diagnostic_origin)
    dest=compile_body(admission_body(),namespace)(spec,root,key,max_zip_bytes=1024**3)
    need(sha256_file(dest/spec['selected_checkpoint'])==spec['selected_file']['sha256'],
         'PARALLEL_SELECTED_GZIP_BYTES')
    return dest
