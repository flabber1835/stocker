"""Restore each materializing caller in an isolated disposable source copy."""
from pathlib import Path
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    module = 'sentinel/feed/rolling_go_inputs.py'
    cases = {
        'assessment': (module,
            'return _assess(conn, pub, target=snapshots.source_final_session(instant), summary_only=True)[2]',
            'return _assess(conn, pub, target=snapshots.source_final_session(instant))[2]'),
        'readiness': (module, '_, report = validate_status(conn, pub, now=now)',
            '_, _, report = validate(conn, pub, now=now)'),
        'prepare': (module, 'binding, _ = validate_status(conn, held)',
            'binding, _, _ = validate(conn, held)'),
        'first_publication': (module, 'checked, _ = validate_status(conn, held)',
            'checked, _, _ = validate(conn, held)'),
        'operational_validation': ('sentinel/feed/operational_snapshot.py',
            '    from sentinel.core.rolling_inputs import readiness_inputs',
            '    from sentinel.core.rolling_inputs import cold_start_inputs as readiness_inputs'),
        'execution': ('sentinel/execution/feed_inputs.py',
            'rolling_go_inputs.validate_status(conn, pub, now=datetime.fromisoformat(today))[1]',
            'rolling_go_inputs.validate(conn, pub, now=datetime.fromisoformat(today))[2]'),
        'runtime_retry': ('sentinel/rolling_runtime.py', '                inputs.validate_status(conn, pub)',
            '                inputs.validate(conn, pub)'),
        'recovery_admission': ('sentinel/rolling_recovery.py',
            '                inputs.validate_reconstruction(conn, pub, summary_only=True)',
            '                inputs.validate_reconstruction(conn, pub)'),
        'recovery_receipt': ('sentinel/rolling_recovery.py',
            '            _, _, report = inputs.validate_reconstruction(conn, pub, summary_only=True)',
            '            _, _, report = inputs.validate_reconstruction(conn, pub)'),
    }
    if sys.argv[1:]:
        cases = {name: cases[name] for name in sys.argv[1:]}
    failures = []
    for name, (path, old, new) in cases.items():
        test_file = 'tests/sentinel/test_rolling_report_consumers.py'
        test = ('test_first_acquisition_verification_never_materializes' if name in {'first_publication', 'operational_validation'}
                else 'test_report_only_entrypoints_never_materialize[' + name + ']')
        if name.startswith('recovery_'):
            test_file = 'tests/sentinel/test_rolling_recovery_report_inputs.py'
            test = 'test_recovery_gates_do_not_materialize_warmup[' + ('False' if name == 'recovery_admission' else 'True') + ']'
        command = [sys.executable, '-m', 'pytest', test_file+'::'+test,
                   '-q', '--tb=short', '-p', 'no:cacheprovider']
        positive = subprocess.run(command, capture_output=True, text=True, timeout=180)
        print(name+' baseline:', positive.stdout, positive.stderr, flush=True)
        assert positive.returncode == 0 and '1 passed' in positive.stdout, name
        source = Path(path)
        original = source.read_bytes()
        text = original.decode()
        assert text.count(old) == 1, name
        try:
            source.write_bytes(text.replace(old, new, 1).encode())
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            killed = (result.returncode == 1 and '1 failed' in result.stdout
                      and 'report-only caller retained the complete strategy warmup' in result.stdout)
            print(name+(': KILLED' if killed else ': NOT PROVED'), flush=True)
            print(result.stdout, result.stderr, flush=True)
            if not killed:
                failures.append(name)
        finally:
            source.write_bytes(original)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
