"""Remove each reviewed guard only inside an offline disposable source copy."""
from pathlib import Path
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    module = 'sentinel/core/rolling_inputs.py'
    cases = {
        'compact_route': ('sentinel/rolling_runtime.py',
            'binding, report = inputs.validate_status(conn, pub, now=now)',
            'binding, _, report = inputs.validate(conn, pub, now=now)',
            'test_status_does_not_materialize_warmup_and_keeps_economic_state'),
        'payload_hash': (module, '    rolling_store.verify_content(conn, candidate_id)\n', '',
            'test_compact_status_rejects_late_hash_corruption_despite_unchanged_counts'),
        'dated_identity': (module, 'if (row.security_id not in meta\n                or refs.resolver.resolve(row.ticker, day) != row.security_id):',
            'if False:', 'test_compact_reader_checks_dated_identity_after_valid_hashes'),
        'terminal_closure': (module, '    refs.terminals(start=warm[0], end=session)\n', '',
            'test_compact_reader_keeps_terminal_reference_refusal'),
        'domain_counts': (module, 'positive[name] += value is not None and value > 0', 'positive[name] += 1',
            'test_compact_coverage_matches_independent_sql_counts'),
    }
    failures = []
    for name, (path, old, new, test) in cases.items():
        command = [sys.executable,'-m','pytest','tests/sentinel/test_rolling_status_inputs.py::'+test,
                   '-q','--tb=short','-p','no:cacheprovider']
        baseline = subprocess.run(command,capture_output=True,text=True,timeout=180)
        print(name+' baseline:',baseline.stdout,baseline.stderr,flush=True)
        assert baseline.returncode == 0 and '1 passed' in baseline.stdout, name
        source = Path(path)
        original = source.read_bytes()
        text = original.decode()
        assert text.count(old)==1,name
        try:
            source.write_bytes(text.replace(old,new,1).encode())
            result = subprocess.run(command,capture_output=True,text=True,timeout=180)
            killed = result.returncode == 1 and '1 failed' in result.stdout
            print(name+(': KILLED' if killed else ': NOT PROVED'),flush=True)
            print(result.stdout,result.stderr,flush=True)
            if not killed: failures.append(name)
        finally:
            source.write_bytes(original)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
