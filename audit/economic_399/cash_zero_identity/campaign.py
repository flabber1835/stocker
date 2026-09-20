"""Offline falsifiers for zero-valued native cash identity retention."""
from pathlib import Path
import subprocess
import sys


TEST = 'tests/sentinel/test_alpaca_simulation_durability.py'
SELECT = 'cash_correction or zero_cash_identity'
MUTANTS = (
    ('decoder_drops_zero', 'sentinel/execution/alpaca.py',
     '            # The common-envelope validator above has already established',
     '            if amount == 0:\n                continue\n'
     '            # The common-envelope validator above has already established'),
    ('consumer_drops_zero', 'sentinel/execution/broker_cash.py',
     '    flow_id = broker_flow_id(\n',
     '    if activity.net_amount == 0:\n        return False\n'
     '    flow_id = broker_flow_id(\n'),
    ('native_replay_ignores_economics', 'sentinel/execution/broker_cash.py',
     '    if observed != expected:\n', '    if False:\n'),
    ('zero_session_changes', 'sentinel/execution/broker_cash.py',
     'or str(zero[0]) != activity.activity_date.isoformat()', 'or False'),
    ('zero_classification_changes', 'sentinel/execution/broker_cash.py',
     'or _read_json_state(zero[1], where=zero_name) != zero_payload', 'or False'),
)


def run(label):
    command = [sys.executable, '-m', 'pytest', TEST, '-k', SELECT,
               '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    print(f'\nCASE {label}: {command}', flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout, flush=True)
    print(result.stderr, flush=True)
    return result


def main():
    assert run('positive_controls').returncode == 0
    for name, filename, original, replacement in MUTANTS:
        path = Path(filename)
        source = path.read_bytes()
        before, after = original.encode(), replacement.encode()
        assert source.count(before) == 1, name
        try:
            path.write_bytes(source.replace(before, after))
            result = run(name)
            assert result.returncode == 1, (name, result.returncode)
            assert 'DID NOT RAISE' in result.stdout, name
            assert ('test_cash_correction_rolls_back_new_rows_and_preserves_cursor' in result.stdout
                    or 'test_zero_cash_identity_cannot_change_classification_or_session' in result.stdout)
            assert 'ERROR collecting' not in result.stdout, name
            print(f'DETECTED {name}: changed-economics refusal was bypassed', flush=True)
        finally:
            path.write_bytes(source)
    print('PASS: positive controls and 5/5 intended cash-identity mutants', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
