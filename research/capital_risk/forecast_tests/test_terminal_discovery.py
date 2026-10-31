"""Value-bearing falsifiers: never hide an event or invent ownership/consideration."""
from research.capital_risk.terminal_discovery import (
    anchor_events, category, complete_native_term, prioritize, security_refs,
)
from research.capital_risk.terminal_discovery_triage import action_priority


def test_unreferenced_ineligible_event_remains_in_queue():
    event = {"source_support": {"ever_eligible": False, "rows": 7}, "observed_references": {}}
    assert prioritize(event) == (4, "SOURCE_SUPPORTED_NO_OBSERVED_ELIGIBLE_ROW")
    event["known_blockers"] = [{"arm": "P01"}]
    assert prioritize(event)[0] == 0


def test_literal_reference_cannot_invent_owned_status():
    targets = {"1234567890123"}
    assert security_refs({"feed": {"1234567890123": [12]}}, targets) == targets
    event = {"source_support": {"ever_eligible": False, "rows": 7},
             "observed_references": {"P02": {"COMMITTED_JOURNAL_REFERENCE": {}}}}
    assert prioritize(event)[0] == 2
    event["observed_references"]["P02"]["OWNED_AT_CHECKPOINT"] = {}
    assert prioritize(event)[0] == 1


def test_delisted_does_not_mean_cash_and_bankruptcy_does_not_mean_zero():
    event = {"native": {"reference": "actions/delisted deal_value_musd=0", "kind": "CASH_MERGER"}, "provider_rows": []}
    assert category(event) == "LISTING_EXIT_WITHOUT_PROVEN_CONSIDERATION"
    assert not complete_native_term(event["native"])
    event["native"]["reference"] = "actions/bankruptcyliquidation deal_value_musd=0"
    assert category(event) == "BANKRUPTCY_OR_LIQUIDATION_NOT_AUTOMATIC_ZERO"
    assert not complete_native_term(event["native"])


def test_all_duplicate_native_dates_keep_source_witnesses():
    events = [{"native_session": d, "anchors": {"before": None, "on": [], "after": None}}
              for d in ("2022-03-04", "2022-03-04", "2022-03-07")]
    fields = {"session": 0}
    for row in (["2022-03-03"], ["2022-03-04"], ["2022-03-08"]):
        anchor_events(events, row, fields)
    assert events[0]["anchors"] == events[1]["anchors"]
    assert events[0]["anchors"]["on"] == [["2022-03-04"]]
    assert events[2]["anchors"]["before"] == ["2022-03-04"]
    assert events[2]["anchors"]["on"] == []
    assert events[2]["anchors"]["after"] == ["2022-03-08"]


def test_zero_cash_is_present_but_missing_conversion_leg_refuses():
    assert complete_native_term({"kind": "CASH_MERGER", "cash_per_share": "0"})
    assert not complete_native_term({"kind": "MIXED_MERGER", "cash_per_share": "3", "exchange_ratio": ".2"})
    assert not complete_native_term({"kind": "CASH_MERGER", "cash_per_share": "30", "disposition": "INCOMPLETE"})


def test_unit_group_uses_word_boundary_not_united_company_name():
    event = {"native": {"kind": "CASH_MERGER", "reference": "actions/acquisitionby"},
             "provider_rows": [{"name": "UNITEDHEALTH GROUP INC"}]}
    assert category(event) == "ACQUISITION_TERMS_OR_OTHER_UNRESOLVED"
    event["provider_rows"][0]["name"] = "DTE CORPORATE UNITS"
    assert category(event) == "UNIT_OR_COMPOSITE_INSTRUMENT"


def test_generic_history_is_distinct_from_explicit_selection():
    event = {"known_blockers": [], "source_support": {"ever_eligible": True},
             "observed_references": {"P02": {"CORE_STATE_REFERENCE": {}}}}
    assert action_priority(event)[0] == 3
    event["observed_references"]["P02"]["LEADERSHIP_AT_CHECKPOINT"] = {}
    assert action_priority(event)[0] == 2
    event["known_blockers"] = [{"arms": ["P02"]}]
    assert action_priority(event)[0] == 0


def test_sensor_model_is_not_a_settlement_or_unreachability_proof():
    event = {"known_blockers": [], "source_support": {"ever_eligible": False},
             "observed_references": {}, "conditional_p02_sensor_model": {"sensor_only": True}}
    assert action_priority(event)[0] == 5
