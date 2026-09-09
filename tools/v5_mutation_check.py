#!/usr/bin/env python3
"""Falsify V5 sizing, state and execution-boundary guards in memory."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _pytest.outcomes import Failed
from tools.median5_mutation_check import rewritten
from tests.v5 import test_v5 as checks
from tests.v5 import test_opening as opening_checks
from sentinel.controller import ex3_v6
from sentinel.core import decision
from sentinel.execution import opening_prices, opening_sizing, executor, target_reprojection
from sentinel.execution.plan import OpeningIntent
from sentinel.paper import targets
from stock_strategy_shared.wealth_core import v5, adapter


def run():
    cases = (
        ("close_reserve_excluded_from_one_share_feasibility",
         checks.test_agn1_uses_total_cash_and_amzn_is_rejected,
         v5, "admission", rewritten(v5.admission,
             "if cash + EPSILON <", "if cash - reserve + EPSILON <")),
        ("opening_price_replaced_by_close_sizing",
         checks.test_open_budget_uses_actual_price_cash_and_released_cushion,
         v5, "opening_quantity", rewritten(v5.opening_quantity,
             "(price * (1 + cost_bps / 10_000))", "(100.0 * (1 + cost_bps / 10_000))")),
        ("negative_cost_accepted", lambda: checks.test_invalid_costs_refuse(-1.),
         v5, "admission", rewritten(v5.admission, " or cost_bps < 0", "")),
        ("r40_equality_accepted", checks.test_rec8_strict_r40_boundary_and_latch_release,
         ex3_v6, "R40_FLOOR", -.04000000001),
        ("rec7_releases", checks.test_rec8_strict_r40_boundary_and_latch_release,
         ex3_v6, "RECOVERY_SESSIONS", 7),
        ("close_bound_pending_quantity_accepted",
         checks.test_old_quantity_intent_is_rejected_before_state_mutation,
         adapter.PendingOrder, "validate_sizing", lambda *args, **kwargs: None),
        ("old_empty_book_profile_accepted",
         checks.test_missing_profile_refuses_before_advancing_book,
         checks, "step_session", rewritten(adapter.step_session,
             "if state.entry_sizing_profile != expected_sizing:", "if False:")),
        ("pending_dollars_silently_erased",
         checks.test_dollar_intent_cannot_silently_disappear_from_executable_target,
         decision, "shadow_target", rewritten(decision.shadow_target,
             "if pending.intended_dollars is not None:", "if False:")),
        ("controller_overridden_by_pinned_rollout",
         checks.test_v5_controller_cannot_be_silently_pinned_to_full_exposure,
         decision, "build_execution_plan", rewritten(decision.build_execution_plan,
             "or is_ex3_v6(canonical.strategy_identity)", "or False")),
        ("opening_price_timestamp_ignored",
         lambda: opening_checks.test_invalid_opening_market_evidence_refuses("wrong_minute"),
         opening_checks, "parse_bars", rewritten(opening_prices.parse_bars,
             "timestamp != opened or ", "")),
        ("opening_response_pagination_ignored",
         lambda: opening_checks.test_invalid_opening_market_evidence_refuses("partial"),
         opening_checks, "parse_bars", rewritten(opening_prices.parse_bars,
             'or payload.get("next_page_token") is not None', 'or False')),
        ("opening_cost_ignored", opening_checks.test_sale_proceeds_and_slot_order_fund_the_opening_once,
         opening_sizing, "COST", opening_checks.D(0)),
        ("opening_dollars_omitted_from_identity",
         opening_checks.test_close_plan_preserves_dollars_and_identity_binds_them,
         OpeningIntent, "to_dict", lambda item: {"security_id": item.security_id,
             "slot_id": item.slot_id, "intended_dollars": "5000"}),
        ("opening_entries_treated_as_empty_noop",
         opening_checks.test_dollar_intents_cannot_use_empty_book_authority_bypass,
         targets, "_provably_clean_empty_noop", rewritten(targets._provably_clean_empty_noop,
             "not opening_intents", "True")),
        ("opening_submit_slot_order_lost",
         opening_checks.test_entry_submit_order_preserves_slots_after_reductions,
         executor, "order_of_operations", rewritten(executor.order_of_operations,
             "{item.security_id: item.slot_id for item in opening_intents}", "{}")),
        ("opening_projection_requirement_removed",
         opening_checks.test_executor_requires_opening_projection_before_execution,
         executor, "execute_session", rewritten(executor.execute_session,
             "if plan.opening_intents and target_projection is None:", "if False:")),
        ("opening_evidence_requirement_removed",
         opening_checks.test_persisted_unit_only_projection_is_insufficient_for_dollar_intent,
         target_reprojection, "assert_projection", rewritten(target_reprojection.assert_projection,
             "if bool(plan.opening_intents) != (projection.opening_sizing is not None):", "if False:")),
    )
    results = []
    for name, falsifier, module, attribute, mutant in cases:
        falsifier()
        with patch.object(module, attribute, mutant):
            try:
                falsifier()
            except (AssertionError, Failed):
                results.append({"mutation": name, "status": "KILLED"})
            else:
                raise AssertionError("SURVIVED: " + name)
    return {"status": "PASS", "mutations": results}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
