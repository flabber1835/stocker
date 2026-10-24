"""Finite manual worker-recovery owner. This is never activation authority."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'config/current-session-qualification.json'
OWNER = 'execution.current-session-worker-recovery'
MODULE = 'tools/current_session_service_recovery.py'
CASE = 'test_current_whole_service_restart_takes_over_real_lease_without_reposting_unknown'
SELECTOR = MODULE + '::' + CASE
EXPECTED = {
    'schema': 'sentinel.current-session-qualification-owner/1', 'owner': OWNER,
    'selector': SELECTOR, 'invocation': 'MANUAL_ONLY', 'expected_scenarios': 1,
    'qualification_scope': 'GENERATED_FUNCTIONAL_WHOLE_WORKER_CURRENT_SESSION',
    'financial_clocks': 'SYNTHETIC', 'service_and_lease_clocks': 'ACTUAL',
    'installation_gate': False, 'authority_effect': 'NONE', 'native_broker_calls': 0,
    'live_money_qualified': False, 'opening_timing_qualified': False,
}


class SessionQualificationRefused(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise SessionQualificationRefused(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path, maximum):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum,
            'BOUNDED_MANUAL_EVIDENCE_FILE_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, 'MANUAL_EVIDENCE_SIZE_EXCEEDED')
    return sha(raw)


def read_registry(path=REGISTRY):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'REGULAR_OWNER_REGISTRY_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(4097)
    require(len(raw) <= 4096, 'OWNER_REGISTRY_SIZE_EXCEEDED')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'DUPLICATE_OWNER_REGISTRY_KEY')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
        # Canonical byte comparison distinguishes false/zero and true/one.
        require(canonical(value) == canonical(EXPECTED), 'EXACT_MANUAL_OWNER_REQUIRED')
    except (ValueError, TypeError, RecursionError) as exc:
        raise SessionQualificationRefused('INVALID_OWNER_REGISTRY') from exc
    require((ROOT / MODULE).is_file(), 'OWNED_MANUAL_MODULE_REQUIRED')
    return value, sha(raw)


def session_status(now):
    from sentinel.automation.model import AutomationConfig
    from sentinel.automation.schedule import for_clock
    require(isinstance(now, datetime) and now.utcoffset() is not None, 'AWARE_ACTUAL_CLOCK_REQUIRED')
    schedule = for_clock(now, AutomationConfig())
    return {'result': 'ELIGIBLE_PREOPEN_SESSION' if now < schedule.execute_at else 'BLOCKED_CURRENT_SESSION',
            'observed_at': now.isoformat(), 'decision_session': str(schedule.decision_session),
            'effective_session': str(schedule.effective_session), 'original_execute_at': schedule.execute_at.isoformat()}


def require_private_host(values):
    require(not any(value and name.startswith(('ALPACA_', 'NDL_', 'SHARADAR_', 'OPENFIGI_'))
                    for name, value in values.items()), 'PROVIDER_CREDENTIAL_ENVIRONMENT_FORBIDDEN')
    names = ('SENTINEL_PRIVATE_PG16_URL', 'SENTINEL_PRIVATE_PG16_SYSTEM_ID',
             'SENTINEL_PRIVATE_QUALIFICATION_TOKEN')
    require(all(values.get(name) for name in names), 'OWNED_PRIVATE_POSTGRES_CONTEXT_REQUIRED')
    require(values[names[1]] != '7691913275518591014', 'PRODUCTION_DATABASE_FORBIDDEN')
    from tests.support import private_postgres16
    private_postgres16.activate(*(values[name] for name in names))


def require_junit(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2 * 1024 ** 2,
            'BOUNDED_OWNED_JUNIT_REQUIRED')
    try:
        root = ET.fromstring(path.read_bytes())
    except ET.ParseError as exc:
        raise SessionQualificationRefused('INVALID_OWNED_JUNIT') from exc
    cases = list(root.iter('testcase'))
    require(len(cases) == 1 and cases[0].get('name') == CASE
            and cases[0].get('classname') == 'tools.current_session_service_recovery'
            and not any(node.tag in {'failure', 'error', 'skipped'} for node in root.iter()),
            'EXACT_PASSING_MANUAL_SCENARIO_REQUIRED')
    return sha(path.read_bytes())


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def run(evidence_dir):
    owner, owner_sha = read_registry()
    status = session_status(datetime.now(timezone.utc))
    require(status['result'] == 'ELIGIBLE_PREOPEN_SESSION', 'CURRENT_PREOPEN_SESSION_UNAVAILABLE')
    require(sys.platform == 'linux', 'LINUX_PRIVATE_PROCESS_PROFILE_REQUIRED')
    output = Path(evidence_dir)
    require(not output.exists() and not output.is_symlink(), 'FRESH_MANUAL_EVIDENCE_DIRECTORY_REQUIRED')
    output.mkdir()
    claim = {**owner, **status, 'registry_sha256': owner_sha,
             'scenario_sha256': file_sha(ROOT / MODULE, 64 * 1024)}
    write_new(output / 'claim.json', claim)
    result = {**claim, 'result': 'REFUSED'}
    try:
        require_private_host(os.environ)
        import pytest
        with (output / 'scenario.log').open('x', encoding='utf8') as log, redirect_stdout(log), redirect_stderr(log):
            code = pytest.main([str(ROOT / MODULE) + '::' + CASE, '-q', '-ra',
                                '--tb=short', '-p', 'no:cacheprovider',
                                '--junitxml=' + str(output / 'scenario.xml')])
        require(code == 0, 'MANUAL_SCENARIO_DID_NOT_PASS')
        result.update(result='PASS', passed=1, skipped=0, deselected=0,
                      junit_sha256=require_junit(output / 'scenario.xml'))
    except Exception as exc:
        result.update(failure_type=type(exc).__name__,
            failure_code=str(exc) if type(exc) is SessionQualificationRefused else 'MANUAL_QUALIFICATION_REFUSED')
    finally:
        log = output / 'scenario.log'
        if log.is_file():
            result['log_sha256'] = file_sha(log, 8 * 1024 ** 2)
        write_new(output / 'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('status', 'run'))
    parser.add_argument('--evidence-dir', type=Path)
    args = parser.parse_args(argv)
    if args.mode == 'run' and args.evidence_dir is None:
        parser.error('run requires --evidence-dir NEW_DIRECTORY')
    try:
        owner, owner_sha = read_registry()
        result = ({**owner, **session_status(datetime.now(timezone.utc)), 'registry_sha256': owner_sha}
                  if args.mode == 'status' else run(args.evidence_dir))
    except Exception as exc:
        result = {'result': 'REFUSED', 'owner': OWNER, 'authority_effect': 'NONE',
            'live_money_qualified': False, 'opening_timing_qualified': False,
            'failure_type': type(exc).__name__,
            'failure_code': str(exc) if type(exc) is SessionQualificationRefused else 'MANUAL_QUALIFICATION_REFUSED'}
    print(canonical(result).decode(), flush=True)
    return 0 if result['result'] in {'PASS', 'ELIGIBLE_PREOPEN_SESSION'} else 3


if __name__ == '__main__':
    raise SystemExit(main())
