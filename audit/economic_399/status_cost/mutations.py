"""Serialization falsifiers, only in a disposable offline source copy."""
from pathlib import Path
import subprocess
import sys


def main():
    assert Path.cwd() == Path('/tmp/repo') and Path('/source').is_dir()
    source = Path('sentinel/core/session.py')
    original = source.read_bytes()
    cases = {
        'complete-tail': ('range(0, len(item), 256)', 'range(0, len(item)-1, 256)',
                          'test_batched_json_matches_independent_standard_encoder[257]'),
        'strict-finite': ('separators=(",", ":"), allow_nan=False',
                          'separators=(",", ":"), allow_nan=True',
                          'test_batched_json_rejects_invalid_value_in_last_batch[nan]'),
        'cycle-refusal': ('raise ValueError("Circular reference detected")', 'return',
                          'test_batched_json_refuses_cycles_but_allows_shared_children'),
        'bounded-batches': ('yield from walk(value)', 'yield encoder.encode(value)',
                            'test_batched_json_never_encodes_a_whole_large_array'),
    }
    for name, (old, new, test) in cases.items():
        command = [sys.executable, '-m', 'pytest', 'tests/sentinel/test_status_memory.py::'+test,
                   '-q', '--tb=short', '-p', 'no:cacheprovider']
        baseline = subprocess.run(command, capture_output=True, text=True, timeout=120)
        print(name+' baseline:', baseline.stdout, baseline.stderr, flush=True)
        assert baseline.returncode == 0 and '1 passed' in baseline.stdout
        assert original.decode().count(old) == 1
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
