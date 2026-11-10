"""Independent hosted-only review of the concentrated-episode diagnostic."""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys


FORBIDDEN = {"GH_TOKEN", "GITHUB_TOKEN", "CAPITAL_RISK_RESEARCH_KEY_20261027",
             "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID",
             "APCA_API_SECRET_KEY", "DATABASE_URL", "PGPASSWORD", "OPENAI_API_KEY"}


def need(value, message):
    if not value:
        raise ValueError(message)


def hosted():
    need(os.environ.get("CONCENTRATION_STOP_HOSTED") == "1", "HOSTED_ONLY")
    need(Path(__file__).resolve() == Path("/current/research/concentration_stop/review.py"),
         "EXACT_REVIEW_SOURCE_PATH")
    need(not any(os.environ.get(k) for k in FORBIDDEN), "NO_CREDENTIALS")
    route = Path("/proc/net/route")
    need(route.is_file() and not any(line.split()[0] != "lo"
         for line in route.read_text().splitlines()[1:] if line.split()), "NO_NETWORK_ROUTE")


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("sentinel", "stock_strategy_shared", "research.pooled_", "numpy", "pandas")):
            raise AssertionError("FORBIDDEN_DIAGNOSTIC_IMPORT:" + fullname)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def num(value):
    need(not isinstance(value, bool), "EXACT_FINITE_NUMBER")
    return Fraction(str(value))


def value(point, opening=False):
    return num(point["episode"]["current_shares"]) * num(point["raw_open" if opening else "raw_close"])


def units(point):
    e = point["episode"]
    return num(e["initial_shares"]) * num(e["entry_raw_open"]) / num(e["entry_split_adjusted_price"])


def first_signal(episode, minimum, *, ratchet=True):
    """Independent direct predicate scan; source Core quantities/NAV stay fixed."""
    hosted()
    active, floor, previous_peak = False, None, None
    activation, trace = None, []
    for point in episode["observations"]:
        close, nav = value(point), num(point["nav"])
        need(close > 0 and nav > 0 and point["price_status"] == "CURRENT", "CURRENT_POSITIVE_CLOSE")
        peak = units(point) * num(point["episode"]["episode_peak_split_adjusted_close"])
        need(peak > 0 and (previous_peak is None or peak >= previous_peak), "PEAK_VALUE_UNIT_CONTINUITY")
        previous_peak = peak
        need(abs(float(close / peak - 1) - float(point["own_dd"])) <= 1e-12,
             "RAW_AND_SIGNAL_UNIT_COHERENCE")
        weight = close / nav
        if not active and weight >= Fraction(1, 10):
            active, activation = True, point
        proposed = peak * Fraction(7, 10)
        distance = Fraction(3, 10)
        if active:
            distance = min(Fraction(3, 10), max(minimum, Fraction(3, 200) / weight))
            proposed = max(proposed, peak * (1 - distance))
        updated = proposed if floor is None or not ratchet else max(floor, proposed)
        need(not ratchet or floor is None or updated >= floor, "NO_DECREASING_FLOOR")
        floor = updated
        trace.append(dict(session=point["session"], current_value=str(close), peak_value=str(peak),
            weight=str(weight), armed=active, distance=str(distance), stop_value_floor=str(floor)))
        if close <= floor:
            return point, floor, activation, trace
    return None, None, activation, trace


def evaluate(episode, minimum, axis):
    hosted()
    points = episode["observations"]
    need(len(episode["sids"]) == 1 and len(episode["tickers"]) == 1
         and episode["endpoint_kind"] in ("SELL", "END_MARK"), "ORDINARY_SINGLE_SOURCE_EPISODE")
    source_unit = units(points[0])
    prior_shares = None
    for point in points:
        e = point["episode"]
        need(e["slot_id"] == episode["slot_id"] and e["signal_date"] == episode["signal_date"]
             and e["entry_date"] == episode["entry_date"] and e["security_id"] == episode["sids"][0]
             and units(point) == source_unit, "FIXED_SOURCE_EPISODE_AND_UNITS")
        q = num(e["current_shares"])
        if prior_shares is not None and q != prior_shares:
            splits = [event for event in episode["source_events"]
                      if event["event_type"] == "SPLIT" and event["session"] == point["session"]]
            need(len(splits) == 1 and q == prior_shares * num(splits[0]["detail"]["ratio"]),
                 "AUTHENTICATED_QUANTITY_CHANGE")
        prior_shares = q
    for event in episode["source_events"]:
        need(event["event_type"] in ("BUY", "SELL", "DIVIDEND_ACCRUED", "DIVIDEND_PAID", "SPLIT"),
             "NO_MATERIAL_ACTION_IN_ELIGIBLE_EPISODE")
        if event["event_type"] == "SPLIT":
            need(episode["tickers"][0] == "AGNT" and num(event["detail"]["ratio"]) == 2
                 and num(event["cash_delta"]) == 0, "DECLARED_AGNT_PURE_SPLIT")
    activation = next((p for p in points if value(p) / num(p["nav"]) >= Fraction(1, 10)), None)
    need(activation is not None, "ACTIVATED_EPISODE_REQUIRED")
    maximum = max(points, key=lambda p: value(p) / num(p["nav"]))
    original = episode["original_sell"]
    endpoint = episode["endpoint_session"]
    if original:
        need(original["reason"] == "EXIT_TRAILING_STOP" and original["session"] == endpoint,
             "ORIGINAL_STOP_ENDPOINT")
        original_gross = -num(original["shares_delta"]) * num(original["price"])
        original_fee = original_gross / 1000
        need(abs(original_fee - num(original["fees"])) <= Fraction(1, 10_000_000), "ORIGINAL_10BP_FEE")
    else:
        need(points[-1]["session"] == endpoint, "END_MARK_COMPLETE")
        original_gross, original_fee = value(points[-1]), Fraction(0)
    original_net = original_gross - original_fee
    accrued = [e for e in episode["source_events"] if e["event_type"] == "DIVIDEND_ACCRUED"
               and e["session"] <= endpoint]
    for event in accrued:
        need(num(event["detail"]["amount"]) >= 0, "NONNEGATIVE_SOURCE_ENTITLEMENT")
        need(abs(num(event["detail"]["amount"]) - num(event["price"]) * num(event["detail"]["shares"]))
             <= Fraction(1, 10_000_000), "SOURCE_ENTITLEMENT_AMOUNT")
    original_dividends = sum((num(e["detail"]["amount"]) for e in accrued), Fraction(0))
    need(len({(e["session"], e["security_id"]) for e in accrued}) == len(accrued),
         "ONE_ENTITLEMENT_PER_SOURCE_EX_DATE")
    signal, stop_floor, _, trace = first_signal(episode, minimum)
    opening = None
    unexecuted = False
    if signal:
        index = axis.index(signal["session"])
        if index + 1 == len(axis):
            unexecuted = True
        else:
            next_day = axis[index + 1]
            need(next_day <= endpoint, "NO_EXTENSION_PAST_ORIGINAL_EPISODE")
            matched = [p for p in episode["openings"] if p["session"] == next_day]
            need(len(matched) == 1 and matched[0]["price_status"] == "RAW_OPEN"
                 and num(matched[0]["raw_open"]) > 0, "EXACT_NEXT_SESSION_RAW_OPEN")
            opening = matched[0]
            need(signal["session"] < opening["session"], "NO_SAME_CLOSE_OR_BACKDATED_FILL")
    if opening:
        exit_gross = value(opening, opening=True)
        fee = exit_gross / 1000
        net = exit_gross - fee
    else:
        exit_gross, fee, net = original_gross, original_fee, original_net
    early = opening is not None and (opening["session"] < endpoint or
        episode["endpoint_kind"] == "END_MARK" and opening["session"] == endpoint)
    candidate_dividends = (sum((num(e["detail"]["amount"]) for e in accrued
                               if e["session"] <= opening["session"]), Fraction(0))
                           if early else original_dividends)
    difference = net + candidate_dividends - original_net - original_dividends
    peak_after = None
    forgone = Fraction(0)
    if early:
        later = [value(p) for p in points if p["session"] >= opening["session"]]
        peak_after = max([exit_gross, original_gross] + later)
        forgone = max(Fraction(0), peak_after / exit_gross - 1)
    result = dict(key=episode["key"], ticker=episode["tickers"][0], security_id=episode["sids"][0],
        slot_id=episode["slot_id"],
        signal_date=episode["signal_date"], entry_date=episode["entry_date"], anchor_held=episode["anchor_held"],
        activation_session=activation["session"], activation_nav=str(num(activation["nav"])),
        max_weight=str(value(maximum) / num(maximum["nav"])), max_weight_session=maximum["session"],
        endpoint_session=endpoint, endpoint_kind="SELL" if original else "END_MARK",
        original_signal_session=points[-1]["session"] if original else None,
        signal_session=signal["session"] if signal else None,
        fill_session=opening["session"] if opening else None, early_exit=early, unexecuted_signal=unexecuted,
        fill_shares=str(num(opening["episode"]["current_shares"])) if opening else None,
        fill_raw_open=str(num(opening["raw_open"])) if opening else None,
        exit_value=str(net), original_terminal_value=str(original_net), exit_fee=str(fee),
        original_exit_fee=str(original_fee), original_dividends=str(original_dividends),
        candidate_dividends=str(candidate_dividends), net_difference=str(difference),
        normalized_difference=str(difference / num(activation["nav"])),
        floor_at_signal=str(stop_floor) if stop_floor is not None else None,
        price_peak_after_exit=str(peak_after) if peak_after is not None else None,
        forgone_upside_fraction=str(forgone),
        peak_position_value_after_exit=str(peak_after) if peak_after is not None else None,
        fill_gross_value=str(exit_gross) if opening else None,
        source_unit_multiplier=str(source_unit), trace=trace, trace_sha256=digest(trace))
    return result


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if len(ordered) % 2 else sum(ordered[len(ordered)//2-1:len(ordered)//2+1], Fraction(0))/2


def stats(records):
    hosted()
    scores = [num(r["normalized_difference"]) for r in records]
    changes = [num(r["net_difference"]) for r in records]
    return dict(count=len(records), early_exits=sum(r["early_exit"] for r in records),
        wins=sum(x > 0 for x in changes), losses=sum(x < 0 for x in changes), ties=sum(x == 0 for x in changes),
        total_net_difference=str(sum(changes, Fraction(0))),
        mean_normalized_difference=str(sum(scores, Fraction(0)) / len(scores)) if scores else None,
        median_normalized_difference=str(median(scores)) if scores else None)


def summarize(records):
    hosted()
    closed = [r for r in records if r["endpoint_kind"] == "SELL"]
    opened = [r for r in records if r["endpoint_kind"] == "END_MARK"]
    result = {"closed": stats(closed), "open_marked": stats(opened), "all_episodes": stats(records)}
    result["closed"]["blocks"] = {
        label: stats([r for r in closed if low <= r["endpoint_session"] <= high])
        for label, low, high in (("2018-20", "2018-01-01", "2020-12-31"),
                                  ("2021-23", "2021-01-01", "2023-12-31"),
                                  ("2024-26", "2024-01-01", "2026-12-31"))}
    largest = max(closed, key=lambda r: (num(r["normalized_difference"]), r["key"]))
    rest = [r for r in closed if r["key"] != largest["key"]]
    remainder = stats(rest)
    result["closed"]["leave_best_out"] = dict(omitted_key=largest["key"],
        omitted_normalized_difference=largest["normalized_difference"], count=len(rest),
        mean_normalized_difference=remainder["mean_normalized_difference"],
        total_net_difference=remainder["total_net_difference"])
    return result


def failure_required(call, name):
    try:
        call()
    except (ValueError, TypeError, KeyError, AssertionError):
        return
    raise ValueError("FALSIFIER_NOT_DETECTED:" + name)


def compare_result(actual, expected, label):
    hosted()
    for key, val in expected.items():
        need(actual[key] == val, "INDEPENDENT_EPISODE_FIELD:" + label + ":" + expected["key"] + ":" + key)


def review(args):
    hosted()
    need(args.book == Path("/p00/book") and args.evidence == Path("/evidence/worker")
         and args.out == Path("/out/review"), "EXACT_REVIEW_MOUNTS")
    sys.meta_path.insert(0, NoCanonical())
    import data
    need(Path(data.__file__).resolve() == Path("/current/research/concentration_stop/data.py"), "EXACT_DATA_READER")
    source = data.load_book(args.book)
    report = json.loads((args.evidence / "report.json").read_bytes())
    need(report["status"] == "COMPLETE_REVIEW_REQUIRED" and report["new_Core_steps"] == 0
         and report["new_Sentinel_steps"] == 0 and report["portfolio_CAGR_or_drawdown_claim"] is False
         and report["performance_admitted"] is False, "DIAGNOSTIC_ONLY_WORKER_SCOPE")
    need(report["worker_sha256"] == file_sha(Path("/current/research/concentration_stop/worker.py"))
         and report["data_sha256"] == file_sha(Path(data.__file__)), "ACTUAL_FROZEN_DIAGNOSTIC_SOURCE")
    need(report["synthetic"]["status"] == "PASS" and report["synthetic"]["financial_tests_hosted_only"] is True,
         "HOSTED_WORKER_CHECKS_PASSED")
    need(report["identity"] == source["identity"], "IMMUTABLE_ORIGINAL_SOURCE")
    axis = [r["session"] for r in source["rows"]]
    episodes = source["episodes"]
    eligible = {key: ep for key, ep in episodes.items()
                if any(value(p) / num(p["nav"]) >= Fraction(1, 10) for p in ep["observations"])}
    need(len(eligible) == 17, "EXACT_SEVENTEEN_ELIGIBLE_EPISODES")
    need(report["eligible_keys"] == sorted(eligible), "EXACT_CAUSAL_ELIGIBLE_KEYS")
    need(sum(ep["original_sell"] is not None for ep in eligible.values()) == 16, "SIXTEEN_CLOSED_ONE_MARKED")
    expected_arms = {}
    for label, arm in report["arms"].items():
        minimum = num(arm["minimum_distance"])
        need(minimum in map(num, ("0.30", "0.06", "0.10", "0.15", "0.20", "0.25")), "FROZEN_MINIMUM_SET")
        observed = {r["key"]: r for r in arm["episodes"]}
        need(len(arm["episodes"]) == len(observed) == 17 and set(observed) == set(eligible), "COMPLETE_ELIGIBLE_COVERAGE")
        expected = [evaluate(ep, minimum, axis) for key, ep in sorted(eligible.items())]
        for item in expected:
            actual = observed[item["key"]]
            compare_result(actual, item, label)
        expected_summary = summarize(expected)
        need(arm["summary"] == expected_summary, "INDEPENDENT_ARM_AGGREGATES:" + label)
        expected_arms[label] = {"minimum_distance": str(minimum), "episodes": expected, "summary": expected_summary}
        if minimum == Fraction(3, 10):
            for result in expected:
                need(num(result["net_difference"]) == 0 and not result["early_exit"], "CONTROL_ZERO_DELTA")
                if result["endpoint_kind"] == "SELL":
                    need(result["signal_session"] == result["original_signal_session"]
                         and result["fill_session"] == result["endpoint_session"], "ORIGINAL_30_STOP_CALIBRATION")
    need(len(expected_arms) == 6 and len({v["minimum_distance"] for v in expected_arms.values()}) == 6,
         "EXACT_SIX_ARMS_NO_DUPLICATE_MINIMUM")
    ordered = sorted(expected_arms,
        key=lambda label: (num(expected_arms[label]["summary"]["closed"]["mean_normalized_difference"]),
                           num(expected_arms[label]["minimum_distance"])), reverse=True)
    # Producer ranking shape is checked after its immutable numerical values.
    need(report["ranking"] == ordered, "INDEPENDENT_CLOSED_EPISODE_RANKING")
    need(report["best_in_this_screen"] == ordered[0], "DECLARED_BEST_IN_SCREEN")
    negatives = []
    earliest = next((r for a in expected_arms.values() for r in a["episodes"] if r["early_exit"]), None)
    need(earliest is not None, "EARLY_EXIT_NEGATIVE_CASE_COVERAGE")
    key = earliest["key"]
    ep = deepcopy(eligible[key])
    floor = next(num(a["minimum_distance"]) for a in expected_arms.values() if earliest in a["episodes"])
    sig = earliest["signal_session"]
    fill = earliest["fill_session"]
    ep["openings"] = [p for p in ep["openings"] if p["session"] != fill]
    failure_required(lambda: evaluate(ep, floor, axis), "missing_next_open")
    negatives.append("missing_next_open")
    ep = deepcopy(eligible[key])
    for p in ep["observations"]:
        if p["session"] > sig:
            p["raw_close"] = float(p["raw_close"]) * 2
    before = first_signal(eligible[key], floor)[0]
    after = first_signal(ep, floor)[0]
    need(before["session"] == after["session"], "FUTURE_CLOSE_CANNOT_CHANGE_EARLIER_SIGNAL")
    negatives.append("future_close_does_not_change_earlier_signal")
    bad_axis = list(axis)
    bad_axis[bad_axis.index(sig) + 1] = sig
    failure_required(lambda: evaluate(eligible[key], floor, bad_axis), "same_close_fill")
    negatives.append("same_close_fill")
    # A source-domain mutant must be rejected on AGNT before its pure split.
    agnt = next(ep for ep in eligible.values() if ep["tickers"] == ["AGNT"])
    before_split = next(p for p in agnt["observations"] if num(p["episode"]["current_shares"]) == 85)
    failure_required(lambda: need(abs(float(num(before_split["raw_close"])
        / num(before_split["episode"]["episode_peak_split_adjusted_close"]) - 1)
        - float(before_split["own_dd"])) <= 1e-12, "MISSING_SPLIT_UNIT_FACTOR"), "missing_split_units")
    negatives.append("missing_split_units")
    # Fixed arithmetic fixture: lower weight would loosen a fresh percentage
    # floor, but the absolute stop price must remain at 90.
    samples = []
    for day, price, nav in (("2018-01-02", "100", "500"), ("2018-01-03", "95", "1000"),
                            ("2018-01-04", "88", "1000"), ("2018-01-05", "88", "1000")):
        samples.append(dict(session=day, raw_close=price, price_status="CURRENT", nav=nav,
            own_dd=float(num(price)/100-1), episode=dict(initial_shares=1, current_shares=1,
                entry_raw_open=100, entry_split_adjusted_price=100, episode_peak_split_adjusted_close=100)))
    normal = first_signal({"observations": samples}, Fraction(1, 10))[0]
    mutant = first_signal({"observations": samples}, Fraction(1, 10), ratchet=False)[0]
    need(normal["session"] == "2018-01-04" and mutant is None, "RATCHET_FIXTURE_DISCRIMINATES")
    failure_required(lambda: need(mutant is not None, "RATCHET_MUTANT_MISSES_EXIT"), "removed_floor_ratchet")
    negatives.append("removed_floor_ratchet")
    # Synthetic distribution dates exercise actual terminal comparison at an
    # observed early fill. The ex-date-open seller keeps that day's claim.
    ep = deepcopy(eligible[key])
    later_day = axis[axis.index(fill) + 1]
    need(later_day <= ep["endpoint_session"], "DIVIDEND_NEGATIVE_CASE_WINDOW")
    ep["source_events"] = [event for event in ep["source_events"] if event["event_type"] != "DIVIDEND_ACCRUED"]
    shares = num(next(p for p in ep["openings"] if p["session"] == fill)["episode"]["current_shares"])
    ep["source_events"] += [dict(event_type="DIVIDEND_ACCRUED", session=day,
        security_id=ep["sids"][0], price=str(amount/shares), detail={"amount": str(amount), "shares": str(shares)})
        for day, amount in ((fill, Fraction(2)), (later_day, Fraction(3)))]
    distribution_result = evaluate(ep, floor, axis)
    need(num(distribution_result["original_dividends"]) == 5 and
         num(distribution_result["candidate_dividends"]) == 2, "EX_DATE_OPEN_ENTITLEMENT_BOUNDARY")
    failure_required(lambda: need(num(distribution_result["candidate_dividends"]) == 0,
        "EX_DATE_SELLER_CLAIM_DROPPED"), "discarded_ex_date_claim")
    negatives.append("discarded_ex_date_claim")
    failure_required(lambda: need(num(distribution_result["candidate_dividends"]) == 5,
        "POST_EXIT_CLAIM_WRONGLY_RETAINED"), "retained_post_exit_claim")
    negatives.append("retained_post_exit_claim")
    # Opening and closing are different economic phases even when their ISO
    # session dates agree. A last-date open sale precedes an END_MARK close.
    phase_samples = []
    phase_days = ["2018-01-02", "2018-01-03", "2018-01-04"]
    for index, (day, price) in enumerate(zip(phase_days, (100, 80, 70), strict=True)):
        phase_samples.append(dict(index=index, session=day, raw_close=price, price_status="CURRENT", nav=500,
            own_dd=float(Fraction(price, 100)-1), episode=dict(slot_id=0, signal_date="2017-12-29",
                entry_date="2018-01-02", security_id="SYNTH:PHASE", initial_shares=1, current_shares=1,
                entry_raw_open=100, entry_split_adjusted_price=100, episode_peak_split_adjusted_close=100)))
    phase_episode = dict(key="0|2017-12-29", slot_id=0, signal_date="2017-12-29", entry_date="2018-01-02",
        anchor_held=False, sids=["SYNTH:PHASE"], tickers=["PHASE"], observations=phase_samples,
        openings=[dict(index=2, session="2018-01-04", raw_open=90, price_status="RAW_OPEN",
                       episode=deepcopy(phase_samples[-1]["episode"]))], source_events=[],
        endpoint_session="2018-01-04", endpoint_kind="END_MARK", original_sell=None)
    phase_result = evaluate(phase_episode, Fraction(1, 10), phase_days)
    need(phase_result["fill_session"] == phase_result["endpoint_session"] and phase_result["early_exit"]
         and num(phase_result["net_difference"]) == Fraction(1991, 100), "END_MARK_OPEN_PRECEDES_SAME_DATE_CLOSE")
    bad_phase = deepcopy(phase_result)
    bad_phase["early_exit"] = False
    failure_required(lambda: compare_result(bad_phase, phase_result, "PHASE"), "same_date_end_mark_phase")
    phase_control = evaluate(phase_episode, Fraction(3, 10), phase_days)
    need(phase_control["unexecuted_signal"] and phase_control["fill_session"] is None
         and num(phase_control["net_difference"]) == 0, "NO_INVENTED_OPEN_AFTER_LAST_CLOSE")
    negatives.append("same_date_end_mark_phase")
    corrupted = deepcopy(report)
    corrupted["arms"][ordered[0]]["episodes"][0]["net_difference"] = "999999999"
    expected = expected_arms[ordered[0]]["episodes"][0]
    failure_required(lambda: compare_result(corrupted["arms"][ordered[0]]["episodes"][0],
        expected, ordered[0]), "altered_outcome")
    negatives.append("altered_outcome")
    altered_identity = deepcopy(report["identity"])
    altered_identity["daily_sha256"] = "0" * 64
    failure_required(lambda: need(altered_identity == source["identity"], "ALTERED_INPUT_IDENTITY"),
                     "altered_input_identity")
    negatives.append("altered_input_identity")
    need(not args.out.exists(), "NEW_REVIEW_OUTPUT")
    args.out.mkdir(parents=True)
    verdict = dict(status="CONCENTRATION_STOP_DIAGNOSTIC_REVIEW_PASSED", identity=source["identity"],
        episode_count=17, closed_count=16, marked_count=1, arms_verified=6,
        independent_episode_comparisons=102, ranking=ordered,
        report_sha256=file_sha(args.evidence / "report.json"), review_source_sha256=file_sha(Path(__file__)),
        negative_checks=negatives, portfolio_performance_admitted=False,
        new_Core_steps=0, new_Sentinel_steps=0, full_strategy_backtest=False)
    (args.out / "independent-review.json").write_bytes(encoded(verdict) + b"\n")
    print(json.dumps({"status": verdict["status"], "episodes": 17, "arms": 6}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ("book", "evidence", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    hosted()
    review(args)


if __name__ == "__main__":
    main()
