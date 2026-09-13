"""Run each #373 regression with its defect restored in an isolated process.

No source files are modified. A pytest assertion failure is required for every
mutation; collection errors and skipped witnesses are not successful falsifiers.
Run with the normal Sentinel test dependencies and ephemeral PostgreSQL support.
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'shared'), str(ROOT)]
ENT = 'tests/wealth_core/test_conversion_entitlements.py'
OPEN = 'tests/v5/test_opening_rounding.py'
CASES = {
    'E1': ENT + '::test_holder_integral_delivery_does_not_require_cil',
    'E1-convention': ENT + '::test_unsupported_holder_convention_refuses_before_economic_mutation',
    'E2': 'tests/sentinel/test_split_source_precision.py::test_noninteger_contractual_ratios_are_preserved',
    'E3': 'tests/sentinel/test_terminal_historical_relevance.py::test_historical_holder_receives_daily_terminal_without_event_day_price',
    'E4': OPEN + '::test_issue373_exact_cash_booking_and_neighbors',
    'E4-guard': OPEN + '::test_canonical_entry_guard_refuses_overspending_before_mutation',
    'E5': 'tests/backup/test_service_backup_policy.py::test_baked_image_policy_survives_removal_of_environment_flag',
    'E5-standby': 'tests/backup/test_service_backup_policy.py::test_supported_service_media_faults_refuse_before_mutation',
    'E5-malformed': 'tests/backup/test_service_backup_policy.py::test_malformed_baked_policy_refuses',
    'E5-unknown': 'tests/backup/test_service_backup_policy.py::test_unknown_environment_policy_refuses',
    'E6': ENT + '::test_contractual_floor_is_independent_of_decimal_context',
    'E7': ENT + '::test_extreme_reverse_split_refuses_before_the_first_material_loss',
    'E7-preflight': ENT + '::test_split_preflight_refuses_the_whole_batch_before_partial_mutation',
}


def rewrite(module, function, old, new):
    source = inspect.getsource(getattr(module, function))
    if old not in source:
        raise RuntimeError(f'mutation no longer matches {module.__name__}.{function}')
    exec(compile(source.replace(old, new), '<issue373-mutation>', 'exec'), module.__dict__)


def mutate(case):
    def core(name):
        return importlib.import_module('stock_strategy_shared.wealth_core.' + name)

    if case == 'E1':
        terminal = core('terminal')

        def per_episode(held, terms, cash_before):
            result = []
            for _, ep in held:
                whole, fraction = terminal._split_entitlement(ep.current_shares, terms.exchange_ratio)
                cash = ep.current_shares * (terms.cash_per_share or 0)
                lieu = float(fraction) * (terms.cash_in_lieu_price_per_delivered_share or 0)
                cash_before += cash + lieu
                result.append(terminal._ConversionAllocation(whole, fraction, cash, lieu, cash_before))
            return result
        terminal._conversion_allocations = per_episode
    elif case == 'E1-convention':
        rewrite(core('terminal'), 'apply_terminal',
                '    if (terms.kind in (TerminalKind.CONVERSION, TerminalKind.CASH_PLUS_STOCK)\n'
                '            and terms.entitlement_aggregation != "HOLDER"):\n'
                '        raise TermsIncomplete("UNSUPPORTED_ENTITLEMENT_AGGREGATION")\n', '')
    elif case == 'E2':
        module = importlib.import_module('stock_strategy_shared.split_reconciliation')

        def broad_snap(stated, *args):
            if 0 < stated < 1:
                reciprocal = 1 / round(1 / stated)
                if abs(stated - reciprocal) <= .01 * max(stated, reciprocal):
                    return reciprocal
            return stated
        module.canonical_split_multiplier = broad_snap
    elif case == 'E3':
        module = importlib.import_module('sentinel.core.terminal')
        # Restore the old window for both prices and rejection evidence.
        source = Path(module.__file__).read_text()
        import ast
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == '_corpus_tickers')
        original = ast.get_source_segment(source, node)
        original = original.replace('session <= %s', 'session BETWEEN %s AND %s')
        original = original.replace('(end,)', '(start, end)').replace('"0001-01-01", end', 'start, end')
        exec(compile(original, '<issue373-mutation>', 'exec'), module.__dict__)
        rewrite(module, 'load_terminal_events', '        if resolve_with_reason is not None:',
                '        priced = _corpus_tickers(conn, start, end)\n'
                '        if priced and tk.upper() not in priced:\n'
                '            audit.append(_row("excluded", EXCLUDED_ABSENT_FROM_CORPUS))\n'
                '            continue\n'
                '        if resolve_with_reason is not None:')
    elif case == 'E4':
        engine = core('engine')
        engine.entry_cost = lambda shares, raw_open, cfg: shares * raw_open * (1 + cfg.transaction_cost_bps / 10000)
    elif case == 'E4-guard':
        rewrite(core('engine'), 'apply_entry',
                '    if not math.isfinite(cost) or cost < 0 or cost > state.cash:\n'
                '        raise ValueError("entry cost exceeds canonical cash budget")\n', '')
    elif case in {'E5', 'E5-malformed', 'E5-unknown'}:
        module = importlib.import_module('sentinel.backup_runtime_authority')
        module.enabled = lambda: module.os.environ.get(module.AUTHORITY_ENV) == module.AUTHORITY_VALUE
    elif case == 'E5-standby':
        import yaml
        load = yaml.safe_load

        def omit_flag(stream):
            value = load(stream)
            standby = value.get('services', {}).get('sentinel-automation-standby')
            if standby:
                standby['environment'].pop('SENTINEL_RUNTIME_BACKUP_AUTHORITY', None)
            return value
        yaml.safe_load = omit_flag
    elif case == 'E6':
        from decimal import Decimal, ROUND_FLOOR
        from fractions import Fraction

        def context_rounded(shares, ratio):
            if isinstance(shares, Fraction):
                shares = Decimal(shares.numerator) / Decimal(shares.denominator)
            exact = Decimal(str(shares)) * Decimal(str(ratio))
            whole = int(exact.to_integral_value(rounding=ROUND_FLOOR))
            return whole, Fraction(exact - whole)
        core('terminal')._split_entitlement = context_rounded
    elif case == 'E7':
        shares = core('shares')
        rewrite(shares, 'split_shares',
                '    error = abs(Fraction(str(result)) - exact)', '    return result\n    error = abs(Fraction(str(result)) - exact)')
    elif case == 'E7-preflight':
        rewrite(core('adapter'), 'apply_splits', '    _preflight_splits(state, bars, pending)\n', '')


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--case':
        case = sys.argv[2]
        mutate(case)
        import pytest
        return pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short', CASES[case]])
    failures = []
    for case in CASES:
        result = subprocess.run([sys.executable, __file__, '--case', case], cwd=ROOT,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        lines = result.stdout.strip().splitlines()
        summary = lines[-1] if lines else '(no output)'
        detected = result.returncode == 1 and 'failed' in summary and 'error' not in summary
        print(f'{case}: {"DETECTED" if detected else "INVALID"}: {summary}', flush=True)
        if not detected:
            print(result.stdout, flush=True)
            failures.append(case)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
