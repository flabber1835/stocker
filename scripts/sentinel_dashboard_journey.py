"""Run one bounded, unmodified dashboard journey using installed browser tools.

No browser installation, image build, database copy, deployment or recurring
monitor is performed. A completed capture may correctly FAIL UX acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit
import uuid


PROJECTS = ('webkit-iphone', 'chromium-pwa')
MAX_BYTES = 20 * 1024 * 1024
HEARTBEAT_TIMEOUT = 15
RECORDER_STARTUP_TIMEOUT = 45
INTEGRITY_CASES = frozenset({
    'records actual banner decoding and accepts a valid PNG',
    'records actual banner decoding and refuses an interrupted PNG',
    'retains a short amber transition and document.open replacement',
})
INPUTS = (
    'tests/browser/support/dashboard-journey-capture.cjs',
    'tests/browser/support/dashboard-journey-transport.cjs',
    'tests/browser/dashboard-journey.spec.js',
    'tests/browser/dashboard-journey.config.js',
    'tests/browser/package.json', 'tests/browser/package-lock.json',
    'scripts/sentinel_dashboard_journey.py',
)


def validate_url(value):
    if not isinstance(value, str) or any(ord(char) < 33 for char in value) or '\\' in value:
        raise ValueError('Dashboard URL contains whitespace or invalid characters')
    try:
        selected = urlsplit(value)
        port = selected.port
    except (TypeError, ValueError):
        raise ValueError('Explicit dashboard URL is invalid') from None
    if (selected.scheme not in {'http', 'https'} or not selected.hostname
            or selected.username is not None or selected.password is not None
            or selected.query or selected.fragment or selected.path not in {'', '/'}
            or (selected.scheme == 'http'
                and selected.hostname not in {'localhost', '127.0.0.1', '::1'})
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Use an explicit HTTPS origin or loopback HTTP origin, without credentials or query')
    return urlunsplit((selected.scheme, selected.netloc, '/', '', ''))


def assess_run(exit_code, reports, expected_projects, timed_out=False, *, opening=False):
    """Classify capture completeness independently of the product's verdict."""
    expected = set(expected_projects)
    problems = []
    if timed_out or type(exit_code) is not int or exit_code not in {0, 1}:
        problems.append('RUN_DID_NOT_COMPLETE')
    if not expected or len(expected) != len(expected_projects) or not expected <= set(PROJECTS):
        problems.append('INVALID_EXPECTED_PROJECTS')
    if not isinstance(reports, list) or len(reports) != len(expected):
        return dict(status='INCOMPLETE', reasons=problems + ['MISSING_OR_EXTRA_CAPTURE'])
    seen = set()
    findings = []
    for report in reports:
        if not isinstance(report, dict):
            problems.append('MALFORMED_CAPTURE')
            continue
        project = report.get('project')
        if not isinstance(project, str) or project not in expected or project in seen:
            problems.append('PROJECT_MISMATCH_OR_DUPLICATE')
        if isinstance(project, str):
            seen.add(project)
        capture = report.get('capture', {})
        acceptance = report.get('acceptance', {})
        physical = report.get('physical_home_screen', {})
        if (report.get('schema') != 'sentinel.dashboard-journey/1'
                or not isinstance(capture, dict) or capture.get('complete') is not True
                or capture.get('status') != 'COMPLETE'
                or capture.get('event_overflow') is not False
                or type(capture.get('expected_html_responses')) is not int
                or capture.get('expected_html_responses') != 3
                or not isinstance(report.get('responses'), list) or len(report['responses']) < 3
                or not isinstance(report.get('events'), list) or not report['events']):
            problems.append('INCOMPLETE_CAPTURE_EVIDENCE')
        if not isinstance(physical, dict) or physical.get('status') != 'NOT_RUN':
            problems.append('UNSUPPORTED_PHYSICAL_DEVICE_CLAIM')
        if opening and not complete_opening(report):
            problems.append('MISSING_OPENING_PHASES')
        if (not isinstance(acceptance, dict) or acceptance.get('status') not in {'PASS', 'FAIL'}
                or not isinstance(acceptance.get('findings'), list)
                or any(not isinstance(item, dict) or not isinstance(item.get('code'), str)
                       or not item['code'] for item in acceptance.get('findings', []))
                or bool(acceptance.get('findings')) != (acceptance.get('status') == 'FAIL')):
            problems.append('INVALID_ACCEPTANCE_RESULT')
        elif acceptance['status'] == 'FAIL':
            findings.append(dict(project=project, findings=acceptance['findings']))
    if seen != expected:
        problems.append('PROJECT_SET_INCOMPLETE')
    if (findings and exit_code != 1) or (not findings and exit_code != 0):
        problems.append('PROCESS_AND_ACCEPTANCE_DISAGREE')
    return dict(status='INCOMPLETE' if problems else 'OBSERVED_FAILURE' if findings
                else 'PASSED_DESKTOP', reasons=problems, findings=findings,
                physical_home_screen=dict(status='NOT_RUN', reason='Desktop capture only'))


def complete_opening(report):
    progress = report.get('opening') or {}
    try:
        if not isinstance(progress['identity'], str) or len(progress['identity']) != 64:
            return False
        waiting, executing, completed, paper, shadow, displayed = (
            datetime.fromisoformat(progress[key]) for key in (
                'waiting_at', 'executing_at', 'completed_at', 'PAPER', 'SHADOW', 'displayed_at'))
        return (all(t.utcoffset() is not None for t in (waiting, executing, completed, paper, shadow, displayed))
                and waiting < executing <= completed <= min(paper, shadow) <= max(paper, shadow) <= displayed
                and continuous_opening(report['events'], executing, displayed)
                and any(item.get('document', {}).get('generated_at') == progress['displayed_at']
                        for item in report['responses'])
                and any(event.get('type') == 'meaningful-content'
                        and event.get('generated_at') == progress['displayed_at'] for event in report['events']))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def continuous_opening(events, executing, displayed):
    samples = [item for item in events if item.get('type') == 'coverage-sample']
    try:
        wall = [item['wall_time_ms'] / 1000 for item in samples]
        monotonic = [item['node_ms'] / 1000 for item in samples]
        return (len(samples) >= 2 and wall[0] <= executing.timestamp()
                and displayed.timestamp() - HEARTBEAT_TIMEOUT <= wall[-1]
                and all(0 <= b-a <= HEARTBEAT_TIMEOUT for a, b in zip(wall, wall[1:]))
                and all(0 <= b-a <= HEARTBEAT_TIMEOUT for a, b in zip(monotonic, monotonic[1:])))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def publish_coverage(root, status, recorder=None):
    pending = root / '.coverage.pending'
    write_new(pending, dict(status=status, updated_at=time.time(), recorder_at=recorder))
    pending.replace(root / 'coverage.json')


def coverage_status(root, now):
    try:
        report = read_json(root / 'coverage.json')
        status = report['status']
        age = now - report['updated_at']
        if status in {'STARTING', 'RUNNING'}:
            if not 0 <= age <= HEARTBEAT_TIMEOUT:
                return 'STALE_OWNER'
            if status == 'RUNNING' and not 0 <= now - report['recorder_at'] <= HEARTBEAT_TIMEOUT:
                return 'STALE_RECORDER'
            return status
        if status in {'FINISHED', 'INCOMPLETE'}:
            return status
    except (KeyError, OSError, TypeError, ValueError):
        pass
    return 'UNKNOWN'


def playwright_matches(data, reports, projects, phase):
    """A report cannot hide extra, skipped, retried or infrastructure cases."""
    if not isinstance(data, dict) or data.get('errors'):
        return False
    cases = INTEGRITY_CASES if phase == 'integrity' else {'records cold navigation and two actual HTML refreshes'}
    expected_group = 'Recorder integrity' if phase == 'integrity' else 'Unmodified dashboard journey'
    observed = []
    def collect(suites, parents=()):
        for suite in suites:
            names = parents + (suite.get('title', ''),)
            for spec in suite.get('specs', []):
                observed.extend((names, spec.get('title'), item) for item in spec.get('tests', []))
            collect(suite.get('suites', []), names)
    try:
        collect(data['suites'])
        if len(observed) != len(projects) * len(cases):
            return False
        expected = {report['project']: report['acceptance']['status'] for report in reports}
        if phase == 'integrity':
            expected = {project: 'PASS' for project in projects}
        if set(expected) != set(projects):
            return False
        seen = set()
        for groups, title, item in observed:
            project = item['projectName']
            if (project not in expected or (project, title) in seen or expected_group not in groups
                    or title not in cases or item['expectedStatus'] != 'passed'
                    or len(item['results']) != 1):
                return False
            seen.add((project, title))
            result = item['results'][0]
            passing = expected[project] == 'PASS'
            if (item['status'] != ('expected' if passing else 'unexpected')
                    or result['status'] != ('passed' if passing else 'failed')
                    or result.get('retry', 0) != 0
                    or len(result.get('errors', [])) != (0 if passing else 1)):
                return False
        failed = sum(value == 'FAIL' for value in expected.values())
        stats = data['stats']
        return (len(seen) == len(observed) and stats['expected'] == len(observed)-failed
                and stats['unexpected'] == failed and stats['skipped'] == 0 and stats['flaky'] == 0)
    except (KeyError, TypeError, AttributeError):
        return False


def digest(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Required input absent or linked: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def write_new(path, value):
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        json.dump(value, output, sort_keys=True, indent=2)
        output.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--phase', choices=('integrity', 'capture', 'opening'), default='capture')
    parser.add_argument('--profile', choices=('direct', 'slow-refresh'), default='direct')
    parser.add_argument('--dependency-cache', type=Path,
                        help='Existing node_modules containing Playwright; never downloaded')
    parser.add_argument('--evidence-dir', type=Path, help='An unused private evidence directory')
    parser.add_argument('--check-coverage', type=Path, help='Inspect an existing opening capture')
    parser.add_argument('--project', choices=PROJECTS, action='append')
    parser.add_argument('--channel', default='msedge' if os.name == 'nt' else 'chromium')
    args = parser.parse_args()
    if args.check_coverage is not None:
        status = coverage_status(args.check_coverage, time.time())
        print(json.dumps(dict(status=status, evidence=str(args.check_coverage))))
        return 0 if status in {'STARTING', 'RUNNING', 'FINISHED'} else 1
    if args.url is None or args.dependency_cache is None:
        parser.error('--url and --dependency-cache are required for capture')
    target = validate_url(args.url)
    if args.phase == 'integrity' and args.profile != 'direct':
        raise ValueError('Transport profiles apply only to the real capture phase')
    source = Path(__file__).resolve().parent.parent
    cache = args.dependency_cache.resolve(strict=True)
    node = shutil.which('node')
    if node is None:
        raise ValueError('Installed Node is required; no installation attempted')
    cli = cache / '@playwright/test/cli.js'
    version = read_json(source / 'tests/browser/package.json')['devDependencies']['@playwright/test']
    for name in ('@playwright/test', 'playwright', 'playwright-core'):
        if read_json(cache / name / 'package.json')['version'] != version:
            raise ValueError('Installed Playwright does not match the repository lock')
    if not cli.is_file():
        raise ValueError('Installed Playwright CLI absent')
    if args.channel not in {'chromium', 'msedge', 'chrome'}:
        raise ValueError('Use an installed Chromium channel; no download attempted')
    projects = args.project or list(PROJECTS)
    if args.phase == 'opening' and (len(projects) != 1 or args.profile != 'direct'):
        raise ValueError('Use one --project and the direct profile per foreground opening capture')
    if len(set(projects)) != len(projects):
        raise ValueError('Duplicate project')
    before = {name: digest(source / name) for name in INPUTS}
    head = subprocess.check_output(
        ['git', '--no-optional-locks', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    root = source / '.codex-tmp' / ('dashboard-journey-' + args.phase + '-'
            + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    if args.evidence_dir is not None:
        root = args.evidence_dir.absolute()
    root.mkdir(parents=True, mode=0o700)
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
        'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HOMEDRIVE', 'HOMEPATH', 'HOME', 'LANG'}}
    environment.update(NODE_PATH=str(cache), SENTINEL_JOURNEY_BASE_URL=target,
                       SENTINEL_BROWSER_CHANNEL=args.channel, NO_COLOR='1', CI='1')
    if args.profile == 'slow-refresh':
        environment['SENTINEL_JOURNEY_REFRESH_FLOOR_MS'] = '6400'
    if args.phase == 'opening':
        environment['SENTINEL_JOURNEY_OPENING'] = '1'
    command = [node, str(cli), 'test', '--config', str(source / 'tests/browser/dashboard-journey.config.js'),
               '--grep', 'Recorder integrity' if args.phase == 'integrity' else 'Unmodified dashboard journey',
               '--workers', '1', '--retries', '0', '--reporter', 'json', '--output', str(root / 'artifacts')]
    for project in projects:
        command.extend(('--project', project))
    write_new(root / 'owner.json', dict(schema='sentinel.dashboard-journey-run/1',
              source_head=head, source_files=before, phase=args.phase, profile=args.profile, target_origin=target,
              projects=projects, command=command, maximum_bytes=MAX_BYTES,
              physical_home_screen='NOT_RUN'))
    started = time.monotonic()
    timed_out = False
    budget_exceeded = False
    opening = args.phase == 'opening'
    coverage_gap = False
    interrupted = False
    publish_at = started
    if opening:
        publish_coverage(root, 'STARTING')
    with (root / 'playwright.json').open('xb') as output, (root / 'stderr.log').open('xb') as error:
        process = subprocess.Popen(command, cwd=source / 'tests/browser', env=environment,
                                   stdout=output, stderr=error,
                                   **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt'
                                      else {'start_new_session': True}))
        try:
            while process.poll() is None:
                now = time.monotonic()
                if now - started > (1280 if opening else 280):
                    timed_out = True
                    break
                if opening and now >= publish_at:
                    stamp = max((p.stat().st_mtime for p in
                                 (root / 'artifacts').rglob('opening-heartbeat')), default=None)
                    if (stamp is None and now-started > RECORDER_STARTUP_TIMEOUT
                            or stamp is not None and not 0 <= time.time()-stamp <= HEARTBEAT_TIMEOUT):
                        coverage_gap = True
                        break
                    publish_coverage(root, 'STARTING' if stamp is None else 'RUNNING', stamp)
                    publish_at = now + 2
                if sum(path.stat().st_size for path in root.rglob('*') if path.is_file()) > MAX_BYTES:
                    budget_exceeded = True
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=20)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait(timeout=10)
                finally:
                    if os.name != 'nt':
                        # Node can exit before a browser child accepts SIGTERM.
                        # This session belongs only to the current invocation.
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
    budget_exceeded = budget_exceeded or sum(
        path.stat().st_size for path in root.rglob('*') if path.is_file()) > MAX_BYTES
    try:
        data = read_json(root / 'playwright.json')
    except (ValueError, OSError):
        data = {}
    reports, report_files = [], []
    for path in sorted((root / 'artifacts').rglob('journey.json')):
        report_limit = (10 if args.phase == 'opening' else 2) * 1024 * 1024
        if path.is_symlink() or path.stat().st_size > report_limit:
            raise ValueError('Journey report unsafe or larger than its budget')
        reports.append(read_json(path))
        report_files.append(dict(path=str(path.relative_to(root)), sha256=digest(path)))
    changed = before != {name: digest(source / name) for name in INPUTS}
    raw_matches = playwright_matches(data, reports, projects, args.phase)
    if args.phase == 'integrity':
        stats = data.get('stats', {})
        passed = (raw_matches and process.returncode == 0 and not timed_out and not budget_exceeded and not changed
                  and stats.get('expected') == len(projects)*len(INTEGRITY_CASES)
                  and all(stats.get(key) == 0 for key in ('skipped', 'unexpected', 'flaky')))
        verdict = dict(status='RECORDER_VERIFIED' if passed else 'INCOMPLETE',
                       physical_home_screen='NOT_RUN')
    else:
        verdict = assess_run(process.returncode, reports, projects, opening=args.phase == 'opening',
                             timed_out=(timed_out or budget_exceeded or changed or not raw_matches
                                        or coverage_gap or interrupted))
    result = dict(schema='sentinel.dashboard-journey-run/1', source_head=head,
                  phase=args.phase, profile=args.profile, source_files=before, source_files_unchanged=not changed,
                  exit_code=process.returncode, timed_out=timed_out,
                  budget_exceeded=budget_exceeded, duration_ms=round((time.monotonic()-started)*1000),
                  interrupted=interrupted, coverage_gap=coverage_gap,
                  raw_playwright_matches=raw_matches,
                  stats=data.get('stats', {}), reports=report_files, verdict=verdict,
                  raw_json_sha256=digest(root / 'playwright.json'))
    write_new(root / 'result.json', result)
    if opening:
        publish_coverage(root, 'INCOMPLETE' if verdict['status'] == 'INCOMPLETE' else 'FINISHED')
    print(json.dumps(dict(evidence=str(root), **result), sort_keys=True))
    return 0 if verdict['status'] in {'RECORDER_VERIFIED', 'PASSED_DESKTOP'} else 1


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
