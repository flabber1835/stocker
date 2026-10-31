"""Hosted encrypted diagnostics after exact stop proof; never financial admission."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import re
import shutil

from full_system_benchmark import need
from probe import check_context
from seal import sha256_file
from stage import SECRET
import system_campaign_evidence_export as original_export

LIMIT = 16 * 1024**2
EXPORT_SHA = 'ef647d332fb4a2f758d5f4e3a4085c894efd7c408d3f0357db5fcd5c5ed3f73d'


def seal_diagnostics(root,target,key,request,protocol_sha256):
    need(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) <= LIMIT,
         'DIAGNOSTIC_EXPLICIT_SMALL_INVENTORY_BOUND')
    source=Path(original_export.__file__).read_bytes()
    import hashlib
    need(hashlib.sha256(source).hexdigest()==EXPORT_SHA,'DIAGNOSTIC_EXACT_QUALIFIED_EXPORT_SOURCE')
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='seal']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Compare)
           and ast.unparse(n)=="stage == 'campaign-factual-suffix'"]
    need(len(sites)==1,'DIAGNOSTIC_EXACT_SINGLE_STAGE_GUARD_SITE')
    sites[0].comparators=[ast.Constant(value='campaign-stopped-diagnostics')]
    scope=dict(vars(original_export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<same-qualified-encryption-distinct-bounded-diagnostic-stage>','exec'),scope)
    return scope['seal'](root,target,key,request,'P02',stage='campaign-stopped-diagnostics',
                         protocol_sha256=protocol_sha256)


def stopped(inspection, metadata, role, run_id, request_name):
    x = inspection;h, c = x['HostConfig'], x['Config']
    need(metadata['stopped'] is True and metadata['oom_killed'] is False
         and x['Name'] == f'/capital-system-factual-p02-{role}-{run_id}-1'
         and re.fullmatch('[a-f0-9]{64}', x['Id']) is not None
         and not x['State']['Running'] and not x['State']['OOMKilled']
         and x['State']['ExitCode'] == metadata['exit_code'], 'DIAGNOSTIC_EXACT_ACTUAL_STOP')
    need(x['Image'] == 'sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
         and h['NetworkMode'] == 'none' and h['Memory'] == h['MemorySwap'] == 8*1024**3
         and h['NanoCpus'] == 2000000000 and h['ReadonlyRootfs'] and h['PidsLimit'] == 64
         and h['CapDrop'] == ['ALL'] and any(v.startswith('no-new-privileges') for v in h['SecurityOpt']),
         'DIAGNOSTIC_EXACT_PRIVATE_FENCES')
    mounts = {v['Destination']:v for v in x['Mounts'] if v['Type'] == 'bind'}
    need(set(mounts) == {'/variant','/frozen','/driver','/out','/old'} | ({'/evidence'} if role == 'review' else set())
         and mounts['/out']['RW'] and all(not v['RW'] for k,v in mounts.items() if k != '/out'),
         'DIAGNOSTIC_EXACT_DISJOINT_RO_INPUTS')
    mode = 'review' if role == 'review' else 'economic'
    need(c['WorkingDir'] == '/variant' and c['Cmd'] == ['-B','-u','/driver/system_campaign_p02_wwe_run.py',
        '--mode',mode,'--spec','/evidence/spec.json' if mode == 'review' else '/out/spec.json',
        '--request','/driver/'+request_name], 'DIAGNOSTIC_EXACT_KNOWN_ENTRYPOINT')
    need(not any(v.partition('=')[0] in {'GH_TOKEN','GITHUB_TOKEN',SECRET} and v.partition('=')[2]
                 for v in c['Env']), 'DIAGNOSTIC_NO_WORKER_CREDENTIALS')


def main(args):
    check_context(os.environ)
    need(os.name == 'posix' and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'DIAGNOSTIC_HOSTED_SINGLE_ATTEMPT')
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    need(str(temp) == '/home/runner/work/_temp', 'DIAGNOSTIC_EXACT_HOSTED_TEMP')
    source = temp/'p02-wwe-financial-output'
    request = json.loads(args.request.read_bytes());receipt = json.loads(args.receipt.read_bytes())
    need(receipt['head'] == os.environ['GITHUB_SHA'] and receipt['run_id'] == os.environ['GITHUB_RUN_ID']
         and receipt['request_sha256'] == sha256_file(args.request)
         and receipt['protocol_sha256'] == request['protocol_sha256'] and receipt['arm'] == 'P02'
         and receipt['production_contacted'] is False, 'DIAGNOSTIC_EXACT_ACTUAL_RECEIPT')
    root = temp/'p02-stopped-diagnostics';root.mkdir(mode=0o700)
    summary = dict(status='STOP_NOT_ADMITTED_NO_WORKER_OUTPUT_COLLECTED', source_run_id=receipt['run_id'],
                   source_head=receipt['head'], financial_admission=False, financial_snapshot_included=False,
                   source_receipt_status=receipt['status'], worker_output_collected=False,
                   reviewer_output_collected=False, production_contacted=False)
    names = []
    if receipt.get('worker',{}).get('stopped') and not receipt['worker']['oom_killed']:
        inspection = source/'economic-worker-inspect.json'
        stopped(json.loads(inspection.read_bytes()), receipt['worker'], 'worker', receipt['run_id'], args.request.name)
        names += ['economic-worker-inspect.json','economic-worker.log','phase-timing.json','request.json']
        summary.update(status='KNOWN_STOPPED_DIAGNOSTICS_ONLY', worker_output_collected=True)
        if receipt.get('reviewer',{}).get('stopped') and not receipt['reviewer']['oom_killed']:
            inspection = source/'independent-review-stop/worker-inspect.json'
            stopped(json.loads(inspection.read_bytes()), receipt['reviewer'], 'review', receipt['run_id'], args.request.name)
            names += ['independent-review-stop/worker-inspect.json','independent-review-stop/worker.log',
                      'independent-review-stop/phase-timing.json']
            summary['reviewer_output_collected'] = True
        names += [n for n in ('driver-failure.txt',) if (source/n).is_file()]
        need(all((source/n).is_file() for n in names) and sum((source/n).stat().st_size for n in names) <= LIMIT,
             'DIAGNOSTIC_COMPLETE_ALLOWLIST_BOUND_NO_TRUNCATION')
        for name in names:
            target = root/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source/name,target)
    (root/'diagnostic-scope.json').write_text(json.dumps(summary,indent=2)+'\n')
    key = base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'DIAGNOSTIC_KEY')
    try:
        asset = seal_diagnostics(root,args.output.parent/'p02-stopped-diagnostics.tar.crseal',key,args.request,
                                 request['protocol_sha256'])
    finally:
        key = None
    result = dict(schema='research.p02-stopped-diagnostic-receipt/1',run_id=receipt['run_id'],head=receipt['head'],
        request_sha256=receipt['request_sha256'],protocol_sha256=request['protocol_sha256'],
        diagnostic_driver_sha256=sha256_file(Path(__file__)),status=summary['status'],
        diagnostic_output=asset,financial_admission=False,financial_snapshot_included=False,production_contacted=False)
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('request','receipt','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
