"""Bind an auxiliary host verification command to the installed PAPER application."""
from pathlib import Path
import re

from . import qualification
from .model import digest, handoff_mode, require


COMMAND = 'scripts/sentinel_backed_local_patch.py'
TESTS = frozenset('tests/scripts/'+name for name in (
    'test_reactivated_startup_witness.py', 'test_reactivated_startup_recovery.py',
    'test_recovery_host_tool.py', 'test_sentinel_reactivated_local_patch.py',
    'test_reactivated_normal_start.py'))
HOST_DELTA = TESTS | {
    COMMAND, 'docs/nov18-posttrade-local-delivery.md', 'docs/posttrade-reactivated-installation.md',
    'docs/posttrade-startup-health.md',
    *('scripts/sentinel_local_delivery/'+name for name in (
        'cli.py', 'coordinator.py', 'evidence.py', 'reactivated.py', 'reactivated_startup.py',
        'reactivated_readiness.py', 'recovery_host_tool.py', 'verification_recovery.py'))}


def _pytest_files(command):
    """Only positional, whole test modules from an explicit pytest invocation."""
    args = list(command)
    if args[:2] == ['docker', 'run']:
        # The launcher sets the entrypoint explicitly on a content-addressed
        # image. Arguments before the image belong to Docker, never to pytest.
        indices = [i for i, arg in enumerate(args) if re.fullmatch(r'sha256:[0-9a-f]{64}', arg)]
        require(len(indices) == 1, 'RECOVERY_HOST_TEST_LAUNCHER')
        image = indices[0]
        require(args.count('--entrypoint') == 1 and '--entrypoint' in args[:image]
                and args[args.index('--entrypoint')+1] in {'python','python3'}
                and args[image+1:image+3] == ['-m','pytest'], 'RECOVERY_HOST_TEST_LAUNCHER')
        args = args[image+3:]
    elif args and Path(args[0]).name == 'pytest':
        args = args[1:]
    else:
        require(args and re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(args[0]).name)
                and args[1:3] == ['-m','pytest'], 'RECOVERY_HOST_TEST_LAUNCHER')
        args = args[3:]
    selected = set()
    i = 0
    while i < len(args):
        value = args[i]
        if value == '-p' and args[i+1:i+2] == ['no:cacheprovider']:
            i += 2
            continue
        if value not in {'-q','-x','--tb=short','--disable-warnings'}:
            require(re.fullmatch(r'tests/(?:[\w-]+/)*test_[\w-]+\.py', value),
                    'RECOVERY_HOST_TESTS_FILTERED')
            selected.add(value)
        i += 1
    return selected


def identify(executable, report_path, report_sha256, request):
    require(handoff_mode(request) == 'POST_TRADE_REACTIVATED', 'RECOVERY_HOST_MODE_REFUSED')
    executable = Path(executable).absolute()
    root = Path(__file__).resolve().parents[2]
    require(executable == root/COMMAND and executable.resolve() == executable,
            'RECOVERY_HOST_EXECUTABLE_CHANGED')
    require(report_path and Path(report_path).is_absolute(), 'RECOVERY_HOST_REPORT_REQUIRED')
    commit = qualification.git(root, 'rev-parse', 'HEAD')
    installed = request['candidate']['commit']
    base = installed if commit != installed else request['predecessor']['commit']
    report = qualification.validate_report(report_path, report_sha256, root, commit, base)
    require(report.get('schema') == qualification.OPERATIONAL_SCHEMA
            and report.get('source_scope') == qualification.OPERATIONAL_SCOPE,
            'RECOVERY_HOST_QUALIFICATION_SCOPE_REQUIRED')
    if commit != installed:
        changes = qualification.git(root, 'diff', '--name-status', '--no-renames', installed, commit).splitlines()
        require(changes and all(row[:2] in {'A\t','M\t'} and row[2:] in HOST_DELTA for row in changes),
                'RECOVERY_HOST_DELTA_REFUSED')
    else:
        require(report_sha256 == request['qualification']['report_sha256'],
                'RECOVERY_HOST_APPLICATION_QUALIFICATION_CHANGED')
    inputs = report['source_files']
    required_modules = {COMMAND, 'scripts/sentinel_local_delivery/reactivated_startup.py',
                        'scripts/sentinel_local_delivery/recovery_host_tool.py'}
    require(required_modules <= inputs.keys()
            and qualification.sha256_file(executable) == inputs[COMMAND], 'RECOVERY_HOST_SOURCE_CHANGED')
    selected = set()
    for row in report['results']:
        args = row['command']
        if TESTS.intersection(args):
            selected.update(_pytest_files(args))
    require(TESTS <= selected, 'RECOVERY_HOST_TESTS_MISSING')
    return dict(source=str(root), commit=commit, application_commit=installed,
                image=request['candidate']['image'], request_sha256=digest(request),
                executable_sha256=inputs[COMMAND], source_manifest_sha256=digest(inputs),
                qualification=str(Path(report_path)), qualification_sha256=report_sha256)


def revalidate(tool, request):
    current = identify(Path(__file__).resolve().parents[1]/'sentinel_backed_local_patch.py',
                       tool['qualification'], tool['qualification_sha256'], request)
    require(current == tool, 'RECOVERY_HOST_TOOL_CHANGED')
