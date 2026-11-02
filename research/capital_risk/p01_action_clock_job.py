"""One hosted component worker with durable admission notes and stopped encryption."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes
from seal import sha256_file
from stage import SECRET
from system_campaign_variants import build
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_pxd_financial_body import function
from p01_action_clock_parent import SPEC, PRIOR, PRIOR_SHA, specification, reference, admit
from p01_action_clock_contract import proposal, AUTHORITY
from p01_action_clock_export import STAGE, qualify_export, write_receipt, finish
import system_campaign_p01_accurate_job as previous
import system_campaign_p02_continue_job as inspector_source

HERE = Path(__file__).parent
REQUEST = 'p01_action_clock_request.json'
SOURCES = tuple(dict.fromkeys((*previous.SOURCES, PRIOR, SPEC,
    'p01_action_clock_contract.py','p01_action_clock_parent.py','p01_action_clock_run.py',
    'p01_action_clock_export.py','p01_action_clock_job.py','p01_action_clock_probe.py')))
PHASES = {'BEFORE_EXPORT_PROBE','EXPORT_PROBE_PASSED','BEFORE_INITIAL_DISK_GATE',
    'BEFORE_PARENT_FETCH','PARENT_ADMITTED','SOURCE_IDENTICAL','BEFORE_WORKER_RESOURCE_GATE',
    'WORKER_LAUNCH_ATTEMPTED','WORKER_STOPPED','STOP_UNKNOWN','BEFORE_EXPORT','FINISHED','FAILURE'}
PUBLIC_CODES = {'REFUSED_FULL_SYSTEM_P01_CLOCK_INITIAL_DISK_RESERVE',
    'REFUSED_FULL_SYSTEM_HOSTED_FACTUAL_DESTINATION_CAPACITY',
    'REFUSED_FULL_SYSTEM_P01_CLOCK_WORKER_RESOURCE_RESERVE',
    'REFUSED_FULL_SYSTEM_P01_CLOCK_EXACT_515_FINANCIAL_SOURCE'}


def expected_request():
    need(sha256_file(HERE/PRIOR) == PRIOR_SHA
         and json.loads((HERE/PRIOR).read_bytes()) == previous.expected_request(),
         'P01_CLOCK_UNCHANGED402_FINANCIAL_DRIVER_CLOSURE')
    spec = specification()
    return dict(schema='research.p01-action-clock-qualification-request/1', arm='P01',
        campaign='system-optimization-002', protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        authority=AUTHORITY, financial_authority=False, financial_replay_authorized=False,
        financial_predecessor_authorized=False, financial_source_changed=False,
        parent_file=SPEC, parent_sha256=sha256_file(HERE/SPEC), parent_reference=reference(spec),
        proposal=proposal(spec).model_dump(), original_inputs=8, financial_source_files=515,
        maximum_component_transitions=2, qualification_sessions=['2019-09-30','2019-10-01'],
        baseline_required_refusal='incomplete leadership cash terminal: 718647188059134933',
        baseline_required_transitions=0, financial_journal_commits=0, account_replay_performed=False,
        worker_wait_seconds=1800, artifact_retention_days=7, initial_min_disk_bytes=12*1024**3,
        preworker_min_disk_bytes=10*1024**3, preworker_min_memory_bytes=10*1024**3,
        actual_marker_roundtrip_before_parent=True, durable_allowlisted_phase_notes=True,
        exact_exchange_last_trade_notice_admitted=False, no_blind_rerun=True,
        primary_clock_sources=[
            'https://www.sec.gov/Archives/edgar/data/936340/000119312516727205/d243567d424b2.htm',
            'https://www.sec.gov/Archives/edgar/data/936340/000093634020000127/dteenergy2019123110k.htm'],
        sources={n:sha256_file(HERE/n) for n in SOURCES}, production_contacted=False)


def note(path, phase, error=None):
    need(phase in PHASES, 'P01_CLOCK_PUBLIC_PHASE_ALLOWLIST')
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(path.read_bytes()) if path.exists() else None
    message = str(error) if error is not None else ''
    value = dict(schema='research.p01-action-clock-public-phase/1', arm='P01', authority=AUTHORITY,
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], phase=phase,
        previous_phase=old['phase'] if old else None,
        free_disk_bytes=shutil.disk_usage(Path(os.environ['RUNNER_TEMP'])).free,
        available_memory_bytes=memory_bytes()['MemAvailable'],
        exception_class=type(error).__name__ if error is not None else None,
        invariant_code=message if message in PUBLIC_CODES else None,
        code_locations=[dict(file=Path(f.filename).name,function=f.name,line=f.lineno)
            for f in traceback.extract_tb(error.__traceback__)] if error is not None else [],
        exception_value_printed=False, financial_or_market_payload_included=False,
        telemetry_only=True, production_contacted=False)
    history = [] if old is None else old['phase_history']
    need(len(history) < 32, 'P01_CLOCK_BOUNDED_PUBLIC_PHASE_HISTORY')
    value['phase_history'] = [*history,dict(phase=phase,free_disk_bytes=value['free_disk_bytes'],
        available_memory_bytes=value['available_memory_bytes'])]
    value['last_failure'] = dict(exception_class=value['exception_class'],
        invariant_code=value['invariant_code'],code_locations=value['code_locations'],phase=phase) \
        if error is not None else old.get('last_failure') if old else None
    pending = path.with_suffix('.partial')
    with pending.open('w',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2)+'\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(pending,path)


def entrypoint():
    return ['-B','-u','/driver/p01_action_clock_run.py','--spec','/out/spec.json']


def inspect(name, identity=None):
    value = function('system_campaign_p02_continue_job.py', 'inspect', {
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-p01-action-clock-worker-[0-9]+-1'}, vars(inspector_source))(name,identity)
    need(value['Config']['Cmd'] == entrypoint(), 'P01_CLOCK_EXACT_WORKER_ENTRYPOINT')
    return value


def worker_command(name, source, frozen, out, old):
    values = previous.worker_command(name,'economic',source,frozen,out,old)
    values[values.index('-B'):] = entrypoint()
    return values


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'P01_CLOCK_NO_BLIND_RERUN')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(), 'P01_CLOCK_EXACT_FROZEN_REQUEST')
    stage_valid(json.loads(args.staging.read_bytes()))
    temp = Path(os.environ['RUNNER_TEMP']); args.output.parent.mkdir(parents=True,exist_ok=True)
    phase = args.output.parent/'p01-action-clock-phase.json'
    receipt = dict(schema='research.p01-action-clock-qualification-receipt/1', arm='P01', stage=STAGE,
        authority=AUTHORITY, financial_authority=False, production_contacted=False,
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request), protocol_sha256=request['protocol_sha256'],
        strict_parent_outer_sha256=specification()['outer_sha256'], status='BEFORE_EXPORT_PROBE')
    write_receipt(args.output,receipt)
    out = temp/'p01-action-clock-output'; out.mkdir(mode=0o700)
    known = False; key = None
    try:
        note(phase,'BEFORE_EXPORT_PROBE')
        proof = qualify_export(temp/'p01-action-clock-export-probe', args.request)
        probe_path = args.output.parent/'p01-action-clock-export-qualification.json'
        probe_path.write_bytes((json.dumps(proof,sort_keys=True,indent=2)+'\n').encode())
        receipt['export_qualification_sha256'] = sha256_file(probe_path)
        note(phase,'EXPORT_PROBE_PASSED')
        key = base64.b64decode(os.environ.pop(SECRET,''),validate=True)
        need(len(key) == 32, 'P01_CLOCK_SEPARATE_KEY')
        note(phase,'BEFORE_INITIAL_DISK_GATE')
        need(shutil.disk_usage(temp).free >= request['initial_min_disk_bytes'], 'P01_CLOCK_INITIAL_DISK_RESERVE')
        note(phase,'BEFORE_PARENT_FETCH')
        old = admit(temp/'campaign-factual-transfer-p01-action-clock',key)
        note(phase,'PARENT_ADMITTED')
        frozen = temp/'capital-risk-stage-001/inputs'; source = temp/'p01-action-clock-source'
        binding = json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',source,binding['parameters']) == binding,
             'P01_CLOCK_EXACT_515_FINANCIAL_SOURCE')
        note(phase,'SOURCE_IDENTICAL')
        for directory in (source, old):
            for path in directory.rglob('*'):
                os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(directory,0o555)
        os.environ.pop('GH_TOKEN',None)
        note(phase,'BEFORE_WORKER_RESOURCE_GATE')
        need(memory_bytes()['MemAvailable'] >= request['preworker_min_memory_bytes']
             and shutil.disk_usage(temp).free >= request['preworker_min_disk_bytes'],
             'P01_CLOCK_WORKER_RESOURCE_RESERVE')
        for name,path in [('spec.json',HERE/SPEC),('request.json',args.request),
                          ('source-bindings.json',old/'source-bindings.json')]:
            shutil.copyfile(path,out/name)
        receipt['status'] = 'COMPONENT_LAUNCH_ATTEMPTED'; write_receipt(args.output,receipt)
        note(phase,'WORKER_LAUNCH_ATTEMPTED')
        name = 'capital-system-p01-action-clock-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['worker'] = stopped_run(worker_command(name,source,frozen,out,old),name,out,
            deadline=request['worker_wait_seconds'],inspector=inspect)
        known = True; note(phase,'WORKER_STOPPED')
        receipt['status'] = 'STOPPED_COMPONENT_OBSERVATION_PENDING_CLIENT_REVIEW'
        if receipt['worker']['exit_code'] != 0 or receipt['worker']['oom_killed']:
            receipt['status'] = 'STOPPED_COMPONENT_REFUSAL_PRESERVED'
    except StopUnknown as error:
        known = False; receipt['status'] = 'COMPONENT_STOP_UNKNOWN_NO_SNAPSHOT'
        note(phase,'STOP_UNKNOWN',error)
    except Exception as error:
        receipt['status'] = 'COMPONENT_REFUSED_KNOWN_STOP' if known else 'COMPONENT_REFUSED_BEFORE_STOP_PROOF'
        note(phase,'FAILURE',error)
        if known:
            (out/'driver-failure.txt').write_text(traceback.format_exc())
    note(phase,'BEFORE_EXPORT')
    finish(receipt,out,args.output,key,args.request,known=known); key = None
    note(phase,'FINISHED')
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status'] == 'STOPPED_COMPONENT_OBSERVATION_PENDING_CLIENT_REVIEW' else 2)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('request','staging','output'):
        p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
