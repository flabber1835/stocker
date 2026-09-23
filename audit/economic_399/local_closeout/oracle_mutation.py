"""Ensure an invented dollar cannot pass the independent accounting probe."""
from pathlib import Path
import subprocess
import sys

TEST = ('tests/sentinel/test_rolling_restore_integrity.py::'
        'test_published_price_oracle_refuses_a_dollar_of_invented_cash')


def run():
    result = subprocess.run([sys.executable, '-m', 'pytest', TEST, '-q', '--tb=short',
        '-p', 'no:cacheprovider'], capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    return result


def main():
    assert run().returncode == 0
    # The restore fixture now forms a historical book. Keep the retained cold
    # oracle unchanged; mutate the independent oracle this live witness uses.
    path = Path('tests/support/formed_accounting.py')
    original = path.read_bytes()
    before = b"_near(book['cash'], cash, 'cash mismatch')"
    assert original.count(before) == 1
    try:
        path.write_bytes(original.replace(before, b'pass'))
        result = run()
        assert result.returncode == 1 and 'DID NOT RAISE' in result.stdout
        assert 'FAILED ' in result.stdout and 'ERROR collecting' not in result.stdout
        print('PASS: positive accounting control and invented-cash mutant detected', flush=True)
    finally:
        path.write_bytes(original)


if __name__ == '__main__':
    main()
