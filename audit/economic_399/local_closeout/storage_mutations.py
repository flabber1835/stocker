"""Detect loss of storage-integrity guards in a disposable offline copy."""
from pathlib import Path
import subprocess
import sys

TEST = 'tests/sentinel/test_observation_storage_envelope.py'
STORAGE = 'sentinel/observation_storage.py'
MUTANTS = (
    ('checksum', STORAGE, [("hashlib.sha256(raw).hexdigest() == group['sha256']", 'True')],
     'test_storage_envelope_refuses_incomplete_or_contradictory_evidence[checksum]'),
    ('schema', STORAGE, [("envelope['schema'] == STORAGE_SCHEMA", 'True')],
     'test_storage_envelope_refuses_incomplete_or_contradictory_evidence[schema]'),
    ('inline', STORAGE, [("isinstance(feed, dict) and feed.get('series') == {}", 'True')],
     'test_storage_envelope_refuses_incomplete_or_contradictory_evidence[inline]'),
    ('duplicate_inventory', STORAGE, [('not series.keys() & batch.keys()', 'True'),
                                   ('len(series) == count', 'True')],
     'test_storage_envelope_refuses_incomplete_or_contradictory_evidence[duplicate-group]'),
    ('uncompressed_bound', STORAGE, [('0 < length <= MAX_GROUP_BYTES', '0 < length')],
     'test_valid_larger_group_cannot_bypass_the_decompression_budget'),
    ('trailing_stream', STORAGE, [('and not inflater.unused_data', '')],
     'test_storage_envelope_refuses_incomplete_or_contradictory_evidence[trailing]'),
    ('rounded_retry', 'sentinel/shadow_observation.py',
     [('number_type=Decimal if exact_numbers else float', 'number_type=float')],
     'test_persisted_sub_float_group_change_cannot_pass_exact_retry'),
    ('decoder_bypass', STORAGE, [('if STORAGE_KEY not in value:', 'if True:')],
     'test_persisted_envelope_restarts_with_the_complete_original_value'),
)


def run(label):
    command = [sys.executable, '-m', 'pytest', TEST, '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    print('CASE', label, command, flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    return result


def main():
    assert run('positive_controls').returncode == 0
    for name, filename, changes, expected in MUTANTS:
        path = Path(filename)
        original = path.read_bytes()
        changed = original
        for before, after in changes:
            assert changed.count(before.encode()) == 1, (name, before)
            changed = changed.replace(before.encode(), after.encode())
        try:
            path.write_bytes(changed)
            result = run(name)
            assert result.returncode == 1 and expected in result.stdout, name
            assert 'FAILED ' in result.stdout and 'ERROR collecting' not in result.stdout, name
            print('DETECTED', name, expected, flush=True)
        finally:
            path.write_bytes(original)
    print('PASS: positive controls and 8/8 storage mutants', flush=True)


if __name__ == '__main__':
    main()
