"""Real disposable health dispatch must never import financial dependencies."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from sentinel.panel import verification_health


NOW = datetime(2031, 4, 21, 20, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]
DRIVER = r'''
import ast
from datetime import datetime
import importlib.abc
import json
from pathlib import Path
import runpy
import sys
import time

root, verifier, operational, instant, arguments, remove = sys.argv[1:]
sys.path.insert(0, root)
from sentinel.panel import verification_health
verification_health.VERIFIER_HEARTBEAT = Path(verifier)
verification_health.OPERATIONAL_HEARTBEAT = Path(operational)
fixed = datetime.fromisoformat(instant)
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return fixed
verification_health.datetime = Clock

class ForbiddenDependency(ImportError):
    pass
class StandardLibraryOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        allowed = {'sentinel', 'sentinel.panel',
                   'sentinel.panel.verification_service', 'sentinel.panel.verification_health'}
        if fullname not in allowed and fullname.partition('.')[0] not in sys.stdlib_module_names:
            raise ForbiddenDependency(fullname)
        return None
sys.meta_path.insert(0, StandardLibraryOnly())
sys.argv = ['sentinel.panel.verification_service', *json.loads(arguments)]
started = time.perf_counter()
blocked = None
code = None
try:
    if remove == 'yes':
        filename = Path(verification_health.__file__).with_name('verification_service.py')
        source = filename.read_text()
        tree = ast.parse(source)
        dispatch = [node for node in tree.body if isinstance(node, ast.If)
                    and "sys.argv[1:] == ['--health']" in ast.get_source_segment(source, node.test)]
        assert len(dispatch) == 1
        lines = source.splitlines(keepends=True)
        del lines[dispatch[0].lineno-1:dispatch[0].end_lineno]
        namespace = {'__name__': '__main__', '__package__': 'sentinel.panel',
                     '__file__': str(filename)}
        exec(compile(''.join(lines), str(filename), 'exec'), namespace)
    else:
        runpy.run_module('sentinel.panel.verification_service', run_name='__main__', alter_sys=True)
except SystemExit as exc:
    code = exc.code
except ForbiddenDependency as exc:
    code, blocked = 97, str(exc)
print(json.dumps(dict(code=code, blocked=blocked, elapsed_seconds=time.perf_counter()-started,
                     financial_loaded=sorted(name for name in sys.modules
                         if name.startswith('sentinel') and name not in {
                             'sentinel', 'sentinel.panel', 'sentinel.panel.verification_health',
                             'sentinel.panel.verification_service'}),
                     forbidden_loaded=sorted(name for name in sys.modules
                         if name.partition('.')[0] not in sys.stdlib_module_names
                         and name != '__main__' and not name.startswith('sentinel')))))
'''


def heartbeat_files(tmp_path, *, component=None, defect=None):
    paths = {'verifier': tmp_path/'verifier', 'operational': tmp_path/'operational'}
    for name, path in paths.items():
        value = NOW
        if name == component:
            if defect == 'missing':
                continue
            if defect == 'directory':
                path.mkdir()
                continue
            if defect == 'nonascii':
                path.write_bytes(b'\xff')
                continue
            if defect == 'malformed':
                path.write_text('not-a-timestamp', encoding='ascii')
                continue
            if defect == 'naive':
                value = NOW.replace(tzinfo=None)
            elif isinstance(defect, (int, float)):
                value = NOW-timedelta(seconds=defect)
        path.write_text(value.isoformat(), encoding='ascii')
    return paths


def entrypoint(paths, *, arguments=('--health',), removed=False):
    completed = subprocess.run([
        sys.executable, '-S', '-c', DRIVER, str(ROOT), str(paths['verifier']),
        str(paths['operational']), NOW.isoformat(), json.dumps(arguments),
        'yes' if removed else 'no',
    ], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['forbidden_loaded'] == [], 'the probe initialized a nonstandard dependency'
    assert result['financial_loaded'] == [], 'the probe initialized a financial dependency'
    return result


@pytest.mark.parametrize('component', ['verifier', 'operational'])
@pytest.mark.parametrize('defect,expected', [
    (0, 0), (45, 0), (45.000001, 1), (-.000001, 1),
    ('missing', 1), ('malformed', 1), ('naive', 1), ('nonascii', 1), ('directory', 1),
])
def test_actual_module_health_is_stdlib_only_with_original_both_heartbeat_bounds(
        tmp_path, component, defect, expected):
    paths = heartbeat_files(tmp_path, component=component, defect=defect)
    answer = entrypoint(paths)
    assert answer['blocked'] is None and answer['code'] == expected


def test_removed_early_dispatch_attempts_a_forbidden_dependency(tmp_path):
    paths = heartbeat_files(tmp_path)
    assert entrypoint(paths)['code'] == 0
    removed = entrypoint(paths, removed=True)
    assert removed['code'] == 97 and removed['blocked'] == 'psycopg'


@pytest.mark.parametrize('arguments', [(), ('--health', 'extra'), ('extra', '--health')])
def test_early_dispatch_matches_only_the_original_exact_health_command(tmp_path, arguments):
    answer = entrypoint(heartbeat_files(tmp_path), arguments=arguments)
    assert answer['code'] == 97 and answer['blocked'] == 'psycopg'


def test_equivalent_aware_offsets_preserve_the_original_heartbeat_predicate(tmp_path):
    paths = heartbeat_files(tmp_path)
    for path in paths.values():
        path.write_text(NOW.astimezone(timezone(timedelta(hours=2))).isoformat(), encoding='ascii')
    assert entrypoint(paths)['code'] == 0
    assert verification_health.health(verifier_path=paths['verifier'],
        operational_path=paths['operational'], now=NOW) == 0


def test_actual_cold_cli_negative_probe_records_imports_without_writing_default_paths(tmp_path):
    # These defaults are only inspected inside the isolated test container.
    # Every positive/boundary fixture above uses explicit private tmp paths.
    assert not verification_health.VERIFIER_HEARTBEAT.exists()
    assert not verification_health.OPERATIONAL_HEARTBEAT.exists()
    command = [sys.executable, '-X', 'importtime', '-m',
               'sentinel.panel.verification_service', '--health']
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
    elapsed = time.perf_counter()-started
    def imported(stderr):
        return [line.rsplit('|', 1)[-1].strip() for line in stderr.splitlines()
                if line.startswith('import time:') and '|' in line
                and not line.endswith('imported package')]
    imports = imported(completed.stderr)
    # The interpreter's site startup can load its setuptools hook before any
    # application code. Attribute only extra imports to the actual entrypoint.
    baseline = subprocess.run([sys.executable, '-X', 'importtime', '-c', 'pass'],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert baseline.returncode == 0
    baseline_imports = imported(baseline.stderr)
    application_imports = sorted(set(imports)-set(baseline_imports))
    (tmp_path/'cold-cli-negative.json').write_text(json.dumps(dict(
        command=command, elapsed_seconds=elapsed, returncode=completed.returncode,
        imported_modules=imports, interpreter_startup_imports=baseline_imports,
        application_imports=application_imports), indent=2))
    assert completed.returncode == 1 and completed.stdout == ''
    assert 'sentinel.panel.verification_health' in imports
    allowed = {'sentinel', 'sentinel.panel', 'sentinel.panel.verification_health'}
    assert all(name in allowed or name.partition('.')[0] in sys.stdlib_module_names
               for name in application_imports)
    assert not verification_health.VERIFIER_HEARTBEAT.exists()
    assert not verification_health.OPERATIONAL_HEARTBEAT.exists()
