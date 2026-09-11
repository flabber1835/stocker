#!/usr/bin/env python3
"""Prove the Median-5 promotion regressions reject reviewed mutations.

Only in-memory functions are changed. This never edits production source or
imports a broker client into a test flow.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import sys
from types import FunctionType
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _pytest.outcomes import Failed
from tests.median5 import test_book, test_components, test_features, test_equivalence_gate
from sentinel.core import session, kernel
from sentinel.controller import median5_breadth as breadth
from sentinel.cli import authority
from sentinel.controller.frozen_rule import load as frozen
from sentinel.controller import median5 as controller
from sentinel import strategy, empty_account_authority
from sentinel.core.decision import runtime_strategy_identity
from stock_strategy_shared.wealth_core import adapter
from tools import median5_equivalence as equivalence


def rewritten(function, old, new, *, last=False):
    from textwrap import dedent
    source = dedent(inspect.getsource(function))
    if last:
        index = source.rfind(old)
        if index < 0:
            raise ValueError("mutation seam disappeared")
        source = source[:index] + source[index:].replace(old, new, 1)
    else:
        if source.count(old) != 1:
            raise ValueError("mutation seam is not unique")
        source = source.replace(old, new, 1)
    scope = dict(function.__globals__)
    exec(compile(source, "reviewed_median5_mutant", "exec"), scope)
    compiled = scope[function.__name__]
    # Preserve the real module's globals so dependency fixtures still exercise
    # the same boundaries around the changed code object.
    mutant = FunctionType(compiled.__code__, function.__globals__,
                          function.__name__, function.__defaults__)
    mutant.__kwdefaults__ = function.__kwdefaults__
    return mutant


def run():
    def with_monkeypatch(test):
        with MonkeyPatch.context() as fixture:
            test(fixture)
    def with_tmp_path(test):
        with TemporaryDirectory(prefix="median5-falsifier-") as directory:
            test(Path(directory))
    cases = (
        ("stale_current_bar", test_features.test_missing_current_bar_cannot_supply_stale_breadth,
         session, "holdings_from_shadow", rewritten(session.holdings_from_shadow,
             "and series.session_indices[-1] == feed._session_index", "and True")),
        ("unbound_economic_override", test_features.test_unbound_economic_override_is_rejected_before_transition,
         kernel, "advance_session", rewritten(kernel.advance_session,
             "if (signed is not None and signed != config_digest(value)) or (signed is None and value != default):",
             "if False:")),
        ("legacy_authority_default", test_components.test_authority_and_execution_use_one_production_strategy,
         authority, "_current_system_identities", lambda: ({}, runtime_strategy_identity(frozen()))),
        ("carried_claim_admission", test_book.test_carried_terminal_value_does_not_fund_new_median5_admissions,
         test_book, "step_session", rewritten(adapter.step_session,
             'if cfg.economic_profile != "wealth-core-v1":', 'if False:', last=True)),
        ("rounded_current_breadth_close", test_features.test_breadth_return_preserves_double_current_close_at_zero_boundary,
         breadth, "breadth", rewritten(breadth.breadth,
             "np.float64(close)/np.float32(previous)", "close/np.float32(previous)")),
        ("peer_order_rewritten_by_rename", test_features.test_peer_ties_keep_first_identity_across_rename_and_restart,
         controller, "remember_peer_keys", rewritten(controller.remember_peer_keys,
             '.setdefault(sid,', '.__setitem__(sid,')),
        ("controller_rule_digest_unbound", test_components.test_authority_controller_configuration_matches_named_strategy,
         strategy, "controller_for_identity", rewritten(strategy.controller_for_identity,
             'if controller.digest != identity.get("controller_rule_sha256"):', 'if False:')),
        ("signed_controller_claim_reused", lambda: with_monkeypatch(test_components.test_empty_binding_recomputes_controller_claim),
         empty_account_authority, "current_bindings", rewritten(empty_account_authority.current_bindings,
             '    seed["controller"] = {\n        "rule_sha256": controller.digest,\n        "config_sha256": authority.canonical_sha256(controller.to_dict()),\n    }\n', '')),
        ("previous_gate_pass_reused", lambda: with_tmp_path(test_equivalence_gate.test_previous_pass_cannot_survive_into_a_new_gate_run),
         test_equivalence_gate, "prepare_output", rewritten(test_equivalence_gate.prepare_output,
             'if output.exists() and any(output.iterdir()):', 'if False:')),
        ("opening_audit_replaces_production_refusal", lambda: with_monkeypatch(test_equivalence_gate.test_opening_audit_preserves_strict_production_result_and_prefill_boundary),
         equivalence, "advance_with_open_audit", rewritten(equivalence.advance_with_open_audit,
             '        return resolved', '        return observations[-1][0], ()')),
        ("missing_open_price_assumed_zero", test_equivalence_gate.test_opening_audit_refuses_missing_prior_price,
         equivalence, "opening_estimate", rewritten(equivalence.opening_estimate,
             'raise ValueError("opening audit lacks current and prior raw price: " + sid)', 'price = 0.0')),
        ("duplicate_opening_boundary_accepted", lambda: with_monkeypatch(test_equivalence_gate.test_opening_audit_refuses_duplicate_boundary),
         equivalence, "advance_with_open_audit", rewritten(equivalence.advance_with_open_audit,
             'if len(observations) != 1:', 'if False:')),
    )
    results = []
    for name, falsifier, module, attribute, mutant in cases:
        falsifier()
        with patch.object(module, attribute, mutant):
            try:
                falsifier()
            except (AssertionError, Failed) as exc:
                results.append({"mutation": name, "status": "KILLED",
                                "failure_type": type(exc).__name__})
            else:
                raise AssertionError("SURVIVED: " + name)
    return {"status": "PASS", "mutations": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(run(), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
    print(result, end="")


if __name__ == "__main__":
    main()
