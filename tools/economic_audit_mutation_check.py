"""Run a passing acceptance case, then require its in-memory mutant to fail."""
from __future__ import annotations

import argparse
import inspect
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def case(name):
    from sentinel.automation import outbox
    from sentinel.execution import fill_integrity
    from sentinel.feed import action_history

    if name == 'fills':
        return (fill_integrity, 'validate', lambda *args: None,
                'tests/sentinel/test_native_fill_acceptance.py::'
                'test_native_fill_authority_requires_order_economic_coherence')
    if name == 'coverage':
        return (action_history, 'verify_coverage_chain', lambda *args, **kwargs: None,
                'tests/sentinel/test_retained_coverage_closure.py::'
                'test_missing_required_coverage_refuses_before_reconciliation[1]')
    source = inspect.getsource(outbox.mark_failed)
    for old, new in (
        (' AND delivery_holder=%s AND attempt_count=%s', ' AND delivery_holder=%s'),
        ('(alert_id, holder_id, attempt)', '(alert_id, holder_id)')):
        assert source.count(old) == 1, 'mutation seam disappeared'
        source = source.replace(old, new)
    namespace = dict(outbox.__dict__)
    exec(compile(source, outbox.__file__, 'exec'), namespace)
    mutant = namespace['mark_failed']
    return (outbox, 'mark_failed', mutant,
            'tests/sentinel/test_alert_attempt_fencing.py::'
            'test_old_attempt_cannot_finish_successor_even_with_same_holder[failure]')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mutation', choices=('fills', 'coverage', 'attempt'))
    name = parser.parse_args().mutation
    module, attribute, mutant, selection = case(name)
    args = [selection, '-q', '--tb=short', '--show-capture=no', '-p', 'no:cacheprovider']
    if pytest.main(args) != pytest.ExitCode.OK:
        raise SystemExit('Unmodified acceptance case must pass first')
    with patch.object(module, attribute, mutant):
        result = pytest.main(args)
    if result != pytest.ExitCode.TESTS_FAILED:
        raise SystemExit(f'Mutation was not detected: {name} ({result})')
    print(f'MUTATION_RESULT {name}: KILLED')


if __name__ == '__main__':
    main()
