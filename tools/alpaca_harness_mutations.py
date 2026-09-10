"""Falsify representative Alpaca guards in disposable source overlays."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sentinel_mutation_certify import Mutant, _run

MUTANTS = (
    Mutant("empty-exact-200-is-absence", "sentinel/execution/alpaca.py",
           '            if not isinstance(payload, dict) or not payload:\n',
           '            if False:\n',
           "tests/sentinel/test_alpaca_simulation_harness.py::"
           "test_empty_successful_exact_lookup_is_corruption_not_absence"),
    Mutant("stable-asset-id-is-replaced-by-symbol", "sentinel/execution/alpaca.py",
           '            "symbol": str(instrument.broker_id),\n',
           '            "symbol": str(instrument.symbol),\n',
           "tests/sentinel/test_alpaca_simulation_harness.py::"
           "test_stable_asset_handle_is_used_at_post"),
    Mutant("order-race-detector-disabled", "sentinel/execution/alpaca.py",
           '              or _fingerprint(recheck) != _fingerprint(orders)\n',
           '              or False\n',
           "tests/sentinel/test_alpaca_simulation_harness.py::"
           "test_fill_between_order_and_position_reads_is_inconsistent_then_converges"),
    Mutant("external-capital-counted-as-income", "sentinel/execution/broker_cash.py",
           '        return ("EXTERNAL" if self.activity_type in EXTERNAL_ACTIVITY_TYPES\n',
           '        return ("EXTERNAL" if False\n',
           "tests/sentinel/test_alpaca_simulation_cash.py::"
           "test_deposit_withdrawal_fees_and_dividends_have_distinct_attribution"),
)

POSTGRES_MUTANT = Mutant(
    "cash-cursor-reused-after-ledger-loss", "sentinel/execution/broker_cash.py",
    '        if Decimal(str(ledger_total)) != prior.balance_total:\n',
    '        if False:\n',
    "tests/sentinel/test_alpaca_execution_entrypoint.py::"
    "test_cash_cursor_total_detects_nonlast_ledger_loss")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-postgres", action="store_true")
    args = parser.parse_args()
    mutants = MUTANTS + ((POSTGRES_MUTANT,) if args.include_postgres else ())
    records = [_run(mutant) for mutant in mutants]
    passed = all(r["mutant_killed"] for r in records)
    result = dict(schema="sentinel.alpaca-mutations/1",
                  all_mutants_killed=passed, mutants=records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"all_mutants_killed": passed,
                      "mutants": [{"name": r["name"], "killed": r["mutant_killed"]}
                                  for r in records]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
