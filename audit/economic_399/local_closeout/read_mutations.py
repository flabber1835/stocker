"""Bounded-hash/ownership falsifiers and the two updated CI economic mutants."""
from pathlib import Path
import subprocess
import sys

from tools.sentinel_mutation_certify import MUTANTS as CI_MUTANTS

TEST = 'tests/sentinel/test_state_hash_allocations.py'
MUTANTS = [
    ('hash_copies_feed', 'sentinel/core/session.py',
     'return _hash(self._canonical_mapping(_copy_feed=False))',
     'return _hash(self.to_dict())', TEST + '::test_state_hash_has_no_universe_sized_feed_array_copy'),
    ('public_alias', 'sentinel/core/session.py',
     'return self._canonical_mapping(_copy_feed=True)',
     'return self._canonical_mapping(_copy_feed=False)',
     TEST + '::test_private_canonical_view_preserves_trimming_and_public_ownership'),
]
MUTANTS.extend((m.name, m.relative_path, m.original, m.replacement, m.test)
    for m in CI_MUTANTS if m.name in (
        'working-order-added-to-remaining-delta', 'cash-residual-adds-invested-notional'))


def run(tests):
    command = [sys.executable, '-m', 'pytest', *tests, '-q', '--tb=short', '-p', 'no:cacheprovider']
    print(command, flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    return result


def main():
    assert run(sorted({m[-1] for m in MUTANTS})).returncode == 0
    for name, filename, before, after, test in MUTANTS:
        path = Path(filename)
        original = path.read_bytes()
        assert original.count(before.encode()) == 1, name
        try:
            path.write_bytes(original.replace(before.encode(), after.encode()))
            result = run([test])
            assert result.returncode == 1 and 'FAILED ' in result.stdout, name
            assert test.rsplit('::', 1)[-1] in result.stdout, name
            assert 'ERROR collecting' not in result.stdout, name
            print('DETECTED', name, flush=True)
        finally:
            path.write_bytes(original)
    print('PASS: positive controls and 4/4 read/CI mutants', flush=True)


if __name__ == '__main__':
    main()
