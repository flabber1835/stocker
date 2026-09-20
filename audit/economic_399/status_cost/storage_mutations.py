"""Atomic full-value PostgreSQL write falsifiers in a disposable source copy."""
from pathlib import Path
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    cases = {
        'full-genesis': ('sentinel/shadow_observation.py', 'and observation_storage.exact_value_equal(row[1], expected)',
            'and row[1].get("genesis_sha256") == expected.get("genesis_sha256")',
            'test_database_genesis_comparison_checks_complete_payload_and_row_session', 1),
        'genesis-date': ('sentinel/shadow_observation.py', 'str(row[0]) == expected["first_session"]',
            'True', 'test_database_genesis_comparison_checks_complete_payload_and_row_session', 1),
        'exact-decimals': ('sentinel/shadow_observation.py', 'self._compact_decoder(cur, exact_numbers=True)',
            'self._compact_decoder(cur)', 'test_database_retry_refuses_sub_float_precision_corruption[True]', 3),
        'write-tail': ('sentinel/observation_storage.py', '            count += 1',
            '            count += 1\n            break',
            'test_database_batched_insert_preserves_complete_value_and_rollback[129-False]', 1),
        'immutable-conflict': ('sentinel/observation_storage.py', 'ON CONFLICT (cursor_name) DO NOTHING',
            'ON CONFLICT (cursor_name) DO UPDATE SET state=EXCLUDED.state',
            'test_database_batched_insert_preserves_complete_value_and_rollback[129-False]', 2),
        'source-identity': ('sentinel/core/decision.py', '    "sentinel.observation_storage",\n', '',
            'test_observation_storage_is_part_of_economic_source_identity', 1),
    }
    for name, (path, old, new, test, count) in cases.items():
        command = [sys.executable, '-m', 'pytest', 'tests/sentinel/test_status_memory.py::'+test,
                   '-q', '--tb=short', '-p', 'no:cacheprovider']
        baseline = subprocess.run(command, capture_output=True, text=True, timeout=120)
        print(name+' baseline:', baseline.stdout, baseline.stderr, flush=True)
        assert baseline.returncode == 0 and '1 passed' in baseline.stdout
        source = Path(path)
        original = source.read_bytes()
        assert original.decode().count(old) == count, name
        try:
            source.write_bytes(original.decode().replace(old, new).encode())
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            print(name, result.stdout, result.stderr, flush=True)
            assert result.returncode == 1 and '1 failed' in result.stdout, name
            print(name+': KILLED', flush=True)
        finally:
            source.write_bytes(original)


if __name__ == '__main__':
    main()
