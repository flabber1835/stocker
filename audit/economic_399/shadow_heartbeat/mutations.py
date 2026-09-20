"""Guard-removal falsifiers, only in the runner's disposable source copy."""
from pathlib import Path
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    source = Path('sentinel/shadow_supervisor.py')
    original = source.read_bytes()
    mutations = {
        'touch_boundary': ('supervisor_io.run(_write_heartbeat)', '_write_heartbeat()', 'stall'),
        'exception_cleanup': ('        if active is not None:\n            _terminate(active)\n        try:',
                              '        if False:\n            _terminate(active)\n        try:', 'error'),
        'refusal_order': ('            active = None\n            if code == EXIT_REFUSED:',
                          '            active = None\n            _touch()\n            if code == EXIT_REFUSED:', 'terminal'),
        'cleanup_boundary': ('supervisor_io.run(_remove_heartbeat)', '_remove_heartbeat()', 'cleanup_stall'),
    }
    failures = []
    for name, (old, new, mode) in mutations.items():
        text = original.decode()
        assert text.count(old) == 1, name
        selector = 'tests/sentinel/test_shadow_heartbeat_isolation.py::test_heartbeat_fault_never_leaves_an_unsupervised_worker[' + mode + ']'
        command = [sys.executable, '-m', 'pytest', selector, '-q', '--tb=short', '-p', 'no:cacheprovider']
        baseline = subprocess.run(command, capture_output=True, text=True, timeout=30)
        print(name + ' baseline:', baseline.stdout, baseline.stderr, flush=True)
        assert baseline.returncode == 0 and '1 passed' in baseline.stdout, name
        try:
            source.write_bytes(text.replace(old, new, 1).encode())
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            killed = result.returncode == 1 and '1 failed' in result.stdout
            print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
            print(result.stdout, result.stderr, flush=True)
            if not killed:
                failures.append(name)
        finally:
            source.write_bytes(original)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
