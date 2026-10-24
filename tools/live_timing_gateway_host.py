"""One-campaign private handoff; no production deployment or native transport.

See docs/live-gateway-handoff-20261024.md. `check` is read-only. `run` is single
use and requires the actual eligible UTC session before claiming anything.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import time
import uuid


ROOT = Path('C:/GitHub/stocker/.codex-tmp')
CAMPAIGN = 'bcda30952e884cf58a252e63ccbd926b'
OPERATION = ROOT / 'live-timing-evidence-20261024' / CAMPAIGN
LAUNCHER = ROOT / 'run-live-timing-20261024.py'
LAUNCHER_SHA = 'b3ea4161ba7b3443396d66e3a58b2bebdfff19884038ded09f39ba073235cc8a'
PINNED = {
    'host-request.json': 'dcccb89f77e6d5ebb5d2a803158968b96165237ebc17c16568f5141035073368',
    'postgres.json': 'dedbe37f54d916803d55c9f97ec80462ca5d07f03cb5003f3230b7151c4c61f4',
    'campaign-seal.json': '5797f6dddbfe45638b499ef63add3a1426515130265109c1fab5edcea4cd2206',
    'evidence/campaign/campaign.json': 'a28150616976c1a775f352115b6f50050c2490e517f2901858e9cc86a3c8f646',
    'evidence/campaign/prepare-report.json': '7eaf95ef0fa017cbfe17887eca0fd0304ffd2c2794206c1f4ea0cf8e56158739',
}
PG_ID = 'f5c1280d5e172a303ee4f46045cc6f95af6bd3eab0102b4e37a0a141ac72518e'
SYSTEM_ID = '7700263374807466023'
EXECUTE = datetime(2026, 10, 26, 13, 31, tzinfo=timezone.utc)
SCHEMA = 'sentinel.private-gateway-host-handoff/1'
SUMMARY_SQL = (
    "SELECT json_build_object('enabled',enabled,'killed',kill_switch_engaged,"
    "'generation',generation,'commands',(SELECT count(*) FROM sentinel_commands),"
    "'cycles',(SELECT count(*) FROM sentinel_automation_cycles),"
    "'plans',(SELECT count(*) FROM sentinel_execution_plans)) "
    "FROM sentinel_automation_control WHERE id=1"
)


class HandoffRefused(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise HandoffRefused(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular_bytes(path, maximum=8 * 1024 ** 2):
    path = Path(path)
    for part in (path, *path.parents):
        require(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(),
                'LINKED_HANDOFF_PATH_FORBIDDEN')
    require(path.is_file(), 'REGULAR_HANDOFF_FILE_REQUIRED')
    with path.open('rb') as source:
        raw = source.read(maximum + 1)
    require(len(raw) <= maximum, 'HANDOFF_FILE_SIZE_EXCEEDED')
    return raw


def load_reviewed_host():
    raw = regular_bytes(LAUNCHER)
    require(sha(raw) == LAUNCHER_SHA, 'ORIGINAL_HOST_LAUNCHER_CHANGED')
    # Execute the authenticated bytes themselves, avoiding a second file read
    # between verification and loading. The old main() is never invoked here.
    spec = importlib.util.spec_from_loader('_sentinel_sealed_timing_host', loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(LAUNCHER)
    exec(compile(raw, str(LAUNCHER), 'exec'), module.__dict__)
    return module


def eligibility(now):
    require(isinstance(now, datetime) and now.tzinfo is not None, 'AWARE_ACTUAL_CLOCK_REQUIRED')
    return ('ELIGIBLE_REAL_SESSION' if EXECUTE - timedelta(minutes=10) <= now
            < EXECUTE + timedelta(seconds=540) else 'BLOCKED_MARKET_SESSION')


def retained_inputs():
    require(OPERATION.is_dir(), 'ORIGINAL_OPERATION_DIRECTORY_REQUIRED')
    values = {}
    for name, digest in PINNED.items():
        raw = regular_bytes(OPERATION / name)
        require(sha(raw) == digest, 'ORIGINAL_HANDOFF_EVIDENCE_CHANGED')
        values[name] = json.loads(raw)
    request, pg = values['host-request.json'], values['postgres.json']
    campaign, seal = values['evidence/campaign/campaign.json'], values['campaign-seal.json']
    require(request['campaign_id'] == campaign['campaign_id'] == CAMPAIGN
            and request['host_launcher_sha256'] == LAUNCHER_SHA
            and pg['container_id'] == PG_ID and pg['system_identifier'] == SYSTEM_ID
            and campaign['private_system_id'] == SYSTEM_ID
            and campaign['source_frontier'] == '2026-10-23'
            and seal['file_sha256'] == PINNED['evidence/campaign/campaign.json'],
            'PINNED_CAMPAIGN_SUBJECT_CHANGED')
    for name in ('gateway-claim.json', 'gateway-report.json', 'original-execute-clock.json'):
        require(not (OPERATION / 'evidence/campaign' / name).exists(),
                'ORIGINAL_GATEWAY_ALREADY_CONSUMED')
    require(not (OPERATION / 'gateway-host-claim.json').exists(), 'HOST_GATEWAY_ALREADY_CLAIMED')
    return request, pg, seal


def preflight():
    request, pg, seal = retained_inputs()
    host = load_reviewed_host()
    require(request['images'] == host.image_facts(), 'EXACT_IMAGES_CHANGED')
    host.profile()
    host.check_bundle(OPERATION, request['bundle'])
    require(host.pg_system(PG_ID, request) == SYSTEM_ID, 'PRIVATE_PHYSICAL_DATABASE_CHANGED')
    raw = host.command(['docker', 'exec', PG_ID, 'psql', '-h', '127.0.0.1', '-p', '5432',
        '-U', 'postgres', '-d', 'opening_latency_' + CAMPAIGN, '-v', 'ON_ERROR_STOP=1',
        '-At', '-c', SUMMARY_SQL])
    observed = json.loads(raw)
    require(observed == {'enabled': False, 'killed': True, 'generation': 1,
                         'commands': 0, 'cycles': 0, 'plans': 0},
            'UNCONSUMED_FENCED_PRIVATE_NAMESPACE_REQUIRED')
    return host, request, pg, seal


def check():
    _host, _request, _pg, _seal = preflight()
    now = datetime.now(timezone.utc)
    return {'schema': SCHEMA, 'result': eligibility(now), 'observed_at': now.isoformat(),
            'original_execute_at': EXECUTE.isoformat(), 'campaign_id': CAMPAIGN,
            'read_only': True, 'gateway_consumed': False, 'authority_effect': 'NONE',
            'live_money_qualified': False, 'production_opening_qualified': False}


def gateway_arguments(host, seal):
    return ['-B', '/qualification/tools/live_timing_qualification.py', 'gateway',
        '--campaign-dir', '/evidence/campaign', '--campaign-id', CAMPAIGN,
        '--database', 'postgresql://postgres@127.0.0.1:5432/opening_latency_' + CAMPAIGN,
        '--expected-system-id', SYSTEM_ID, '--production-system-id', host.PRODUCTION_SYSTEM_ID,
        '--runtime-image-digest', host.IMAGE, '--commit', host.RUNTIME_COMMIT,
        '--scheduler-profile', '/qualification/scheduler.json', '--assets', '6000',
        '--setup-budget-seconds', '3600', '--campaign-sha256', seal['campaign_sha256']]


def require_gateway_report(report, seal):
    require(report.get('schema') == 'sentinel.real-clock-timing-report/1'
            and report.get('mode') == 'gateway' and report.get('campaign_id') == CAMPAIGN
            and report.get('campaign_sha256') == seal['campaign_sha256']
            and report.get('result') == 'PASS' and report.get('gateway_qualified') is True
            and report.get('original_execute_at') == EXECUTE.isoformat()
            and report.get('book_preserved') is True
            and type(report.get('native_broker_calls')) is int and report['native_broker_calls'] == 0
            and report.get('authority_effect') == 'NONE'
            and report.get('live_money_qualified') is False
            and report.get('production_opening_qualified') is False,
            'ORIGINAL_POSITIVE_GATEWAY_REPORT_REQUIRED')
    first, complete = report.get('first_post_seconds'), report.get('complete_basket_seconds')
    require(type(first) in (int, float) and type(complete) in (int, float)
            and math.isfinite(first) and math.isfinite(complete)
            and 0 <= first <= 120 and first <= complete <= 300,
            'ORIGINAL_TIMING_LIMITS_REQUIRED')
    require(type(report.get('orders')) is int and report['orders'] > 0
            and type(report.get('legs')) is int and report['legs'] > 0,
            'POSITIVE_ORDER_AND_BASKET_EVIDENCE_REQUIRED')


def run():
    host, request, pg, seal = preflight()
    # No injected clock is accepted by the CLI. The frozen driver independently
    # validates the exchange calendar again inside its real runtime namespace.
    require(eligibility(datetime.now(timezone.utc)) == 'ELIGIBLE_REAL_SESSION',
            'ACTUAL_ELIGIBLE_MARKET_SESSION_REQUIRED')
    attempt = uuid.uuid4().hex
    host.write_new(OPERATION / 'gateway-host-claim.json', {
        'schema': SCHEMA, 'attempt': attempt, 'campaign_id': CAMPAIGN,
        'wrapper_sha256': sha(regular_bytes(Path(__file__))),
        'at': datetime.now(timezone.utc).isoformat(), 'original_execute_at': EXECUTE.isoformat(),
        'original_host_launcher_sha256': LAUNCHER_SHA,
        'original_request_sha256': PINNED['host-request.json'], 'authority_effect': 'NONE'})
    args = gateway_arguments(host, seal)
    created = host.command(['docker', 'create', '--pull=never', '--name',
        'sentinel-live-timing-gateway-' + attempt[:16],
        '--label', host.LABEL + '=' + CAMPAIGN, '--label', host.LABEL + '.role=gateway',
        '--network', 'container:' + PG_ID, '--restart=no', '--cpus=1', '--memory=2g',
        '--pids-limit=256', '--cap-drop=ALL', '--security-opt=no-new-privileges=true',
        '--log-driver=local', '--log-opt=max-size=10m', '--log-opt=max-file=2',
        '--mount', 'type=bind,src=' + str((OPERATION / 'bundle').resolve()) + ',dst=/qualification,readonly',
        '--mount', 'type=bind,src=' + str((OPERATION / 'evidence').resolve()) + ',dst=/evidence',
        '--env', 'PYTHONPATH=/qualification:/app', '--env', 'PYTHONDONTWRITEBYTECODE=1',
        '--env', 'PYTHONUNBUFFERED=1', '--workdir=/app', '--entrypoint=python', host.IMAGE, *args])
    require(host.CONTAINER.fullmatch(created), 'EXACT_NEW_PRIVATE_CONTAINER_REQUIRED')
    host.write_new(OPERATION / ('gateway-' + attempt + '.created.json'), {'container_id': created})
    host.check_runtime(host.inspect_id(created), request, OPERATION, pg, 'gateway', args)
    log = OPERATION / ('gateway-' + attempt + '.log')
    started, timed_out, attached_code = time.monotonic(), False, None
    try:
        with log.open('xb') as output:
            completed = subprocess.run(['docker', 'start', '-a', created], stdout=output,
                stderr=subprocess.STDOUT, timeout=1800)
            attached_code = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        item = host.inspect_id(created)
        host.check_runtime(item, request, OPERATION, pg, 'gateway', args)
        stopped = item['State']['Running']
        if stopped:
            host.command(['docker', 'stop', '--time=10', created], timeout=20)
            item = host.inspect_id(created)
            host.check_runtime(item, request, OPERATION, pg, 'gateway', args)
        host.write_new(OPERATION / ('gateway-' + attempt + '.host-result.json'), {
            'schema': SCHEMA, 'container_id': created, 'image': item['Image'],
            'exit_code': item['State']['ExitCode'], 'attach_exit_code': attached_code,
            'timed_out': timed_out, 'oom_killed': item['State']['OOMKilled'],
            'stopped_owned_runtime': stopped, 'log_sha256': sha(regular_bytes(log)),
            'host_elapsed_seconds': round(time.monotonic() - started, 6),
            'authority_effect': 'NONE', 'live_money_qualified': False,
            'production_opening_qualified': False})
    require(not timed_out and not stopped and attached_code == 0
            and item['State']['ExitCode'] == 0 and not item['State']['OOMKilled']
            and not item['State']['Running'], 'PRIVATE_GATEWAY_PROCESS_DID_NOT_COMPLETE')
    host.check_bundle(OPERATION, request['bundle'])
    require(host.pg_system(PG_ID, request) == SYSTEM_ID, 'PRIVATE_PHYSICAL_DATABASE_CHANGED')
    raw = regular_bytes(OPERATION / 'evidence/campaign/gateway-report.json')
    report = json.loads(raw)
    require_gateway_report(report, seal)
    summary = {'schema': SCHEMA, 'result': 'PASS', 'campaign_id': CAMPAIGN,
        'original_execute_at': EXECUTE.isoformat(), 'original_report_sha256': sha(raw),
        'first_post_seconds': report['first_post_seconds'],
        'complete_basket_seconds': report['complete_basket_seconds'],
        'qualification_scope': 'GENERATED_CURRENT_PROFILE_REAL_CLOCK_SOFTWARE_GATEWAY',
        'authority_effect': 'NONE', 'native_broker_calls': 0,
        'live_money_qualified': False, 'production_opening_qualified': False}
    host.write_new(OPERATION / 'gateway-host-accepted.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'run'))
    args = parser.parse_args(argv)
    try:
        result = check() if args.mode == 'check' else run()
    except Exception as exc:
        result = {'schema': SCHEMA, 'result': 'REFUSED',
            'failure_code': str(exc) if type(exc) is HandoffRefused else 'HANDOFF_OPERATION_REFUSED',
            'failure_type': type(exc).__name__, 'authority_effect': 'NONE',
            'live_money_qualified': False, 'production_opening_qualified': False}
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False), flush=True)
    return int(result['result'] == 'REFUSED')


if __name__ == '__main__':
    raise SystemExit(main())
