"""Prove panel admission/cleanup/deployment guards with isolated mutations."""
from pathlib import Path
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    cases = {
        'capacity': ('sentinel/panel/app.py', '_PANEL_BUILD_SLOT = BoundedSemaphore(1)',
                     '_PANEL_BUILD_SLOT = BoundedSemaphore(2)',
                     'test_http_builds_share_one_slot[/panel.json-/]'),
        'route': ('sentinel/panel/app.py', '@app.get("/", response_class=HTMLResponse)\n@_one_panel_build',
                  '@app.get("/", response_class=HTMLResponse)',
                  'test_http_builds_share_one_slot[/panel.json-/]'),
        'release': ('sentinel/panel/app.py', '            _PANEL_BUILD_SLOT.release()', '            pass',
                    'test_failed_build_releases_admission[/panel.json]'),
        'worker': ('docker-compose.sentinel.yml', ', "--workers", "1"', '',
                   'test_deployed_panel_cannot_multiply_workers'),
    }
    failures = []
    for name, (path, old, new, test) in cases.items():
        command = [sys.executable, '-m', 'pytest', 'tests/sentinel/test_panel_concurrency.py::'+test,
                   '-q', '--tb=short', '-p', 'no:cacheprovider']
        positive = subprocess.run(command, capture_output=True, text=True, timeout=60)
        print(name+' baseline:', positive.stdout, positive.stderr, flush=True)
        assert positive.returncode == 0 and '1 passed' in positive.stdout, name
        source = Path(path)
        original = source.read_bytes()
        text = original.decode()
        assert text.count(old) == 1, name
        try:
            source.write_bytes(text.replace(old, new, 1).encode())
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            killed = result.returncode == 1 and '1 failed' in result.stdout
            print(name+(': KILLED' if killed else ': NOT PROVED'), flush=True)
            print(result.stdout, result.stderr, flush=True)
            if not killed:
                failures.append(name)
        finally:
            source.write_bytes(original)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
