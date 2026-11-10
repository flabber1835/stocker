"""Independent, hosted-only review of the frozen wider-stop episode screen."""
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


FORBIDDEN = ("GH_TOKEN", "GITHUB_TOKEN", "CAPITAL_RISK_RESEARCH_KEY_20261027",
             "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID",
             "APCA_API_SECRET_KEY", "DATABASE_URL", "PGPASSWORD", "OPENAI_API_KEY",
             "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def hosted():
    need(os.environ.get("WIDER_STOP_HOSTED") == "1", "HOSTED_ONLY")
    need(Path(__file__).resolve() == Path("/current/research/wider_stop/review.py"),
         "EXACT_REVIEW_SOURCE_PATH")
    need(not any(os.environ.get(name) for name in FORBIDDEN), "NO_CREDENTIALS")
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
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def num(value):
    need(type(value) in (str, int, float, Fraction), "EXACT_FINITE_SCALAR")
    return value if isinstance(value, Fraction) else Fraction(str(value))


def stock(point, opening=False):
    return num(point["episode"]["current_shares"]) * num(point["raw_open" if opening else "raw_close"])


def source_units(point):
    item = point["episode"]
    return num(item["initial_shares"]) * num(item["entry_raw_open"]) / num(item["entry_split_adjusted_price"])


def activation(ep):
    hosted()
    return next((point for point in ep["observations"]
                 if stock(point) / num(point["nav"]) >= Fraction(1, 10)), None)


def original_check(ep, axis):
    """Reproduce the immutable 30% stop, independently of the wider worker."""
    hosted()
    need(len(ep["sids"]) == len(ep["tickers"]) == 1, "SINGLE_SOURCE_IDENTITY")
    unit = source_units(ep["observations"][0])
    prior_peak, prior_q = None, None
    signal = None
    for point in ep["observations"]:
        item = point["episode"]
        close = stock(point)
        peak = unit * num(item["episode_peak_split_adjusted_close"])
        need(point["price_status"] == "CURRENT" and close > 0 and num(point["nav"]) > 0,
             "POSITIVE_CURRENT_SOURCE_CLOSE")
        need(source_units(point) == unit and item["security_id"] == ep["sids"][0]
             and item["slot_id"] == ep["slot_id"] and item["signal_date"] == ep["signal_date"]
             and item["entry_date"] == ep["entry_date"], "FIXED_SOURCE_LINEAGE_UNITS")
        need(peak > 0 and (prior_peak is None or peak >= prior_peak), "MONOTONE_SOURCE_PEAK")
        need(abs(close / peak - 1 - num(point["own_dd"])) <= Fraction(1, 10**12),
             "SOURCE_RAW_ADJUSTED_UNIT_COHERENCE")
        q = num(item["current_shares"])
        need(q > 0 and num(point["raw_close"]) > 0 and unit > 0, "POSITIVE_SOURCE_QUANTITY_PRICE_UNITS")
        if prior_q is not None and q != prior_q:
            splits = [event for event in ep["source_events"]
                      if event["event_type"] == "SPLIT" and event["session"] == point["session"]]
            need(len(splits) == 1 and q == prior_q * num(splits[0]["detail"]["ratio"]),
                 "AUTHENTICATED_SOURCE_SPLIT")
        prior_peak, prior_q = peak, q
        if signal is None and close <= peak * Fraction(7, 10):
            signal = point
    for event in ep["source_events"]:
        need(event["event_type"] in ("BUY", "SELL", "SPLIT", "DIVIDEND_ACCRUED", "DIVIDEND_PAID"),
             "SUPPORTED_SOURCE_ACTION")
    sale = ep["original_sell"]
    if sale is None:
        need(ep["endpoint_kind"] == "END_MARK" and ep["endpoint_session"] == axis[-1], "OPEN_SOURCE_END")
        need(signal is None or signal["session"] == axis[-1], "NO_UNEXECUTED_PRIOR_SOURCE_SIGNAL")
    else:
        need(sale["reason"] == "EXIT_TRAILING_STOP" and signal is not None
             and axis[axis.index(signal["session"]) + 1] == sale["session"] == ep["endpoint_session"],
             "EXACT_ORIGINAL_30_SIGNAL_AND_FILL")
        opens = [point for point in ep["openings"] if point["session"] == sale["session"]]
        need(len(opens) == 1 and opens[0]["price_status"] == "RAW_OPEN"
             and num(opens[0]["raw_open"]) == num(sale["price"])
             and num(opens[0]["episode"]["current_shares"]) == -num(sale["shares_delta"]),
             "EXACT_ORIGINAL_RAW_OPEN_AND_SHARES")
        gross = -num(sale["shares_delta"]) * num(sale["price"])
        need(abs(gross / 1000 - num(sale["fees"])) <= Fraction(1, 10**7)
             and abs(gross * Fraction(999, 1000) - num(sale["cash_delta"])) <= Fraction(1, 10**7),
             "ORIGINAL_TEN_BP_SALE_FEE")
    return unit


def median(values):
    ordered = sorted(values)
    size = len(ordered)
    return ordered[size // 2] if size % 2 else (ordered[size // 2 - 1] + ordered[size // 2]) / 2


def quote_num(value):
    """The archived CSV's binary64 reader domain, then exact rational arithmetic."""
    return num(str(float(value)))


def accrued_source(ep):
    hosted()
    events = [event for event in ep["source_events"] if event["event_type"] == "DIVIDEND_ACCRUED"]
    need(len({(event["session"], event["security_id"]) for event in events}) == len(events),
         "UNIQUE_ORIGINAL_DIVIDEND_CLAIMS")
    for event in events:
        need(num(event["detail"]["amount"]) >= 0
             and abs(num(event["detail"]["amount"]) - num(event["price"]) * num(event["detail"]["shares"]))
             <= Fraction(1, 10**7), "ORIGINAL_ENTITLEMENT_ARITHMETIC")
    return sum((num(event["detail"]["amount"]) for event in events), Fraction(0))


def bounded_quotes(ep, corpus, axis):
    hosted()
    sale = ep["original_sell"]
    if sale is None:
        return [], None, False
    start = axis.index(sale["session"])
    complete = start + 60 < len(axis)
    endpoint = start + 60 if complete else len(axis) - 1
    days = axis[start:endpoint + 1]
    sid = ep["sids"][0]
    quotes = corpus["quotes"][sid]
    prior = quotes[axis[start - 1]]
    need(quote_num(prior["raw_close"]) == num(ep["observations"][-1]["raw_close"]),
         "ARCHIVE_LAST_HELD_CLOSE_BRIDGE")
    points = []
    actions = [row for row in corpus["actions"] if row["security_id"] == sid
               and days[0] <= row["effective_session"] <= days[-1]]
    terminals = [row for row in corpus["terminals"] if row["security_id"] == sid
                 and days[0] <= row["effective_session"] <= days[-1]]
    need(not terminals, "NO_UNSUPPORTED_EXTENSION_TERMINAL")
    need(len({(row["effective_session"], row["action"]) for row in actions}) == len(actions),
         "UNIQUE_EXTENSION_ACTION")
    q = num(ep["observations"][-1]["episode"]["current_shares"])
    for day in days:
        need(day in quotes, "EXACT_BOUNDED_SOURCE_QUOTE:" + sid + ":" + day)
        row = quotes[day]
        need(row["session"] == day and row["security_id"] == sid and row["tradeable"] in ("1", "True", "true"),
             "SOURCE_QUOTE_IDENTITY_AND_TRADEABILITY")
        opening, closing = quote_num(row["raw_open"]), quote_num(row["raw_close"])
        ratio, dividend = quote_num(row["split_ratio"]), quote_num(row["dividend_per_share"])
        need(opening > 0 and closing > 0 and ratio == 1 and dividend >= 0,
             "POSITIVE_FINITE_SOURCE_PRICE_NO_EXTENSION_SPLIT")
        day_actions = [action for action in actions if action["effective_session"] == day]
        for action in day_actions:
            need(action["known_by"] <= day and action["action"] == "dividend"
                 and quote_num(action["canonical_value"]) > 0, "CAUSAL_SUPPORTED_ACTION")
            if action["action"] == "dividend":
                need(action["disposition"] == "RAW_SHARE_DOMAIN_CONVERTED"
                     and action["authority"] == "PIT_ACTIONS_PLUS_SAME_SESSION_PRICE_DOMAIN"
                     and quote_num(action["canonical_value"]) == dividend, "QUALIFIED_RAW_SHARE_DIVIDEND")
        need((ratio == 1) == (not any(action["action"] == "split" for action in day_actions))
             and (dividend == 0) == (not any(action["action"] == "dividend" for action in day_actions)),
             "NO_UNEXPLAINED_CORPORATE_ACTION")
        points.append(dict(session=day, shares=q, raw_open=opening, raw_close=closing,
                           dividend=dividend, index=axis.index(day)))
    first = points[0]
    need(first["shares"] == -num(sale["shares_delta"])
         and first["raw_open"] == num(sale["price"]), "ARCHIVE_ORIGINAL_SALE_RAW_CORROBORATION")
    return points, axis[endpoint], complete


def evaluate(ep, corpus, axis, distance):
    """Recompute the full path using only DATA-loader fields, never worker calls."""
    hosted()
    unit = original_check(ep, axis)
    activated = activation(ep)
    need(activated is not None and distance in map(num, ("0.30", "0.35", "0.40")), "FROZEN_ELIGIBLE_ARM")
    common = accrued_source(ep)
    sale = ep["original_sell"]
    extra, endpoint, complete = bounded_quotes(ep, corpus, axis)
    source_points = ep["observations"]
    armed, level, signal, fill = False, None, None, None
    trace = []
    peak = None
    for point in source_points:
        peak = unit * num(point["episode"]["episode_peak_split_adjusted_close"])
        if point["session"] == activated["session"]:
            armed, level = True, None
        proposed = peak * (1 - (distance if armed else Fraction(3, 10)))
        level = proposed if level is None else max(level, proposed)
        trace.append(dict(session=point["session"], phase="CLOSE",
            shares=str(num(point["episode"]["current_shares"])), raw_price=str(num(point["raw_close"])),
            peak_value=str(peak), stop_value_floor=str(level), signal=stock(point) <= level))
        if stock(point) <= level and signal is None:
            signal = point["session"]
            break
    original_signal = source_points[-1]["session"] if sale else None
    if sale is None:
        need(signal is None or signal == axis[-1], "NO_EARLIER_REFERENCE_EXIT")
        signal = None
        gross = stock(source_points[-1])
        q = num(source_points[-1]["episode"]["current_shares"])
        raw_price = num(source_points[-1]["raw_close"])
        base_net, original_fee = gross, Fraction(0)
        reason, phase, endpoint, classification = "OPEN_REFERENCE", "CLOSE", axis[-1], "OPEN_REFERENCE"
        fee, extra_div = Fraction(0), Fraction(0)
        held, worst, minimum_return, stock_return = [], None, None, None
    else:
        original_gross = -num(sale["shares_delta"]) * num(sale["price"])
        original_fee = original_gross / 1000
        base_net = original_gross - original_fee
        held, extra_div = [], Fraction(0)
        worst, minimum_return = None, None
        for point in extra:
            day = point["session"]
            if day > sale["session"]:
                extra_div += point["shares"] * point["dividend"]
            if signal is not None:
                need(axis.index(day) == axis.index(signal) + 1, "AUTHENTICATED_NEXT_SESSION_OPEN")
                fill, reason, phase = point, "TRAILING_STOP", "OPEN"
                break
            if complete and day == endpoint:
                fill, reason, phase = point, "FORCED_HORIZON", "OPEN"
                break
            closing = point["shares"] * point["raw_close"]
            peak = max(peak, closing)
            level = max(level, peak * (1 - distance))
            held.append(point)
            drawdown = closing / peak - 1
            relative = closing / original_gross - 1
            worst = drawdown if worst is None else min(worst, drawdown)
            minimum_return = relative if minimum_return is None else min(minimum_return, relative)
            trace.append(dict(session=day, phase="CLOSE", shares=str(point["shares"]),
                raw_price=str(point["raw_close"]), peak_value=str(peak), stop_value_floor=str(level),
                signal=closing <= level))
            if closing <= level:
                signal = day
        classification = "COMPLETE" if complete else "CENSORED"
        if fill is None:
            need(not complete, "COMPLETE_ENDPOINT_OPEN_REQUIRED")
            point = extra[-1]
            gross = point["shares"] * point["raw_close"]
            q, raw_price = point["shares"], point["raw_close"]
            fee, reason, phase = Fraction(0), "CENSORED_MARK", "CLOSE"
        else:
            q, raw_price = fill["shares"], fill["raw_open"]
            gross = q * raw_price
            fee = gross / 1000
        stock_return = gross / original_gross - 1
    terminal = gross - fee + common + extra_div
    baseline = base_net + common
    delta = terminal - baseline
    result = dict(key=ep["key"], ticker=ep["tickers"][0], security_id=ep["sids"][0], slot_id=ep["slot_id"],
        signal_date=ep["signal_date"], entry_date=ep["entry_date"], anchor_held=ep["anchor_held"],
        activation_session=activated["session"], activation_nav=str(num(activated["nav"])),
        original_signal_session=original_signal, original_sale_session=sale["session"] if sale else None,
        original_sale_shares=str(-num(sale["shares_delta"])) if sale else None,
        original_sale_raw_open=str(num(sale["price"])) if sale else None,
        classification=classification, complete_followup=complete,
        followup_sessions_available=len(extra)-1 if sale else 0,
        endpoint_session=endpoint, endpoint_phase="OPEN" if complete else "CLOSE",
        signal_session=signal, fill_session=fill["session"] if fill else None, exit_reason=reason,
        exit_shares=str(q), exit_raw_price=str(raw_price), exit_gross_value=str(gross), exit_fee=str(fee),
        original_exit_fee=str(original_fee), original_dividends=str(common),
        post_original_exit_dividends=str(extra_div), candidate_dividends=str(common + extra_div),
        baseline_terminal_value=str(baseline), terminal_value=str(terminal), net_difference=str(delta),
        normalized_difference=str(delta / num(activated["nav"])), additional_occupied_sessions=len(held),
        max_close_drawdown_fraction=str(worst) if worst is not None else None,
        minimum_close_return_from_original_sale=str(minimum_return) if minimum_return is not None else None,
        stock_gross_return_from_original_sale_to_exit=str(stock_return) if stock_return is not None else None,
        trace=trace, trace_sha256=digest(trace))
    return result


def stats(records):
    hosted()
    changes = [num(row["net_difference"]) for row in records]
    scores = [num(row["normalized_difference"]) for row in records]
    return dict(count=len(records), wins=sum(value > 0 for value in changes),
        losses=sum(value < 0 for value in changes), ties=sum(value == 0 for value in changes),
        total_net_difference=str(sum(changes, Fraction(0))),
        mean_normalized_difference=str(sum(scores, Fraction(0)) / len(scores)) if scores else None,
        median_normalized_difference=str(median(scores)) if scores else None)


def summarize(records):
    hosted()
    complete = [row for row in records if row["classification"] == "COMPLETE"]
    result = dict(complete=stats(complete),
        censored=stats([row for row in records if row["classification"] == "CENSORED"]),
        open_reference=stats([row for row in records if row["classification"] == "OPEN_REFERENCE"]),
        all_episodes=stats(records))
    result["complete"]["blocks"] = {
        label: stats([row for row in complete if low <= row["original_sale_session"] <= high])
        for label, low, high in (("2018-20", "2018-01-01", "2020-12-31"),
                                 ("2021-23", "2021-01-01", "2023-12-31"),
                                 ("2024-26", "2024-01-01", "2026-12-31"))}
    best = max(complete, key=lambda row: (num(row["normalized_difference"]), row["key"]))
    rest = [row for row in complete if row["key"] != best["key"]]
    remaining = stats(rest)
    result["complete"]["leave_best_out"] = dict(omitted_key=best["key"],
        omitted_normalized_difference=best["normalized_difference"], count=len(rest),
        mean_normalized_difference=remaining["mean_normalized_difference"],
        total_net_difference=remaining["total_net_difference"])
    return result


def failure_required(call, name):
    try:
        call()
    except (ValueError, KeyError, TypeError, AssertionError):
        return
    raise ValueError("FALSIFIER_NOT_DETECTED:" + name)


def compare(actual, expected, label):
    hosted()
    for key, value in expected.items():
        need(actual[key] == value, "INDEPENDENT_RESULT:" + label + ":" + expected["key"] + ":" + key)


def synthetic_checks():
    """Actual evaluator falsifiers, executed only inside the hosted reviewer."""
    hosted()
    axis = ["T" + str(index).zfill(3) for index in range(63)]
    raw_ep = dict(slot_id=0, signal_date="PRE", entry_date=axis[0], security_id="SYNTH",
                  initial_shares=1, current_shares=1, entry_raw_open=100,
                  entry_split_adjusted_price=100, episode_peak_split_adjusted_close=100)
    observations = [dict(index=index, session=axis[index], episode=deepcopy(raw_ep),
        raw_close=price, price_status="CURRENT", nav=500, own_dd=str(Fraction(price, 100)-1))
        for index, price in enumerate((100, 70))]
    observations[0]["nav"] = 2000
    ep = dict(key="0|PRE", slot_id=0, signal_date="PRE", entry_date=axis[0], anchor_held=False,
        sids=["SYNTH"], tickers=["TEST"], observations=observations,
        openings=[dict(session=axis[2], raw_open=70, price_status="RAW_OPEN", episode=deepcopy(raw_ep))],
        source_events=[], endpoint_session=axis[2], endpoint_kind="SELL",
        original_sell=dict(reason="EXIT_TRAILING_STOP", session=axis[2], shares_delta=-1,
                           price=70, fees="0.07", cash_delta="69.93"))
    quotes = {day: dict(session=day, security_id="SYNTH", tradeable="1", raw_open="90",
                       raw_close="90", split_ratio="1", dividend_per_share="0") for day in axis[1:]}
    quotes[axis[1]]["raw_close"] = "70"
    quotes[axis[2]].update(raw_open="70", raw_close="64")
    quotes[axis[3]].update(raw_open="80", raw_close="120", dividend_per_share="1")
    quotes[axis[4]].update(raw_open="117", raw_close="71", dividend_per_share="2")
    actions = [dict(effective_session=axis[index], security_id="SYNTH", action="dividend",
        canonical_value=str(amount), known_by=axis[index], disposition="RAW_SHARE_DOMAIN_CONVERTED",
        authority="PIT_ACTIONS_PLUS_SAME_SESSION_PRICE_DOMAIN") for index, amount in ((3, 1), (4, 2))]
    corpus = dict(quotes={"SYNTH": quotes}, actions=actions, terminals=[])
    control = evaluate(ep, corpus, axis, num("0.30"))
    wider = evaluate(ep, corpus, axis, num("0.35"))
    widest = evaluate(ep, corpus, axis, num("0.40"))
    need(control["fill_session"] == axis[2] and num(control["net_difference"]) == 0,
         "SYNTH_ORIGINAL_30_CALIBRATION")
    need(wider["fill_session"] == axis[3] and wider["additional_occupied_sessions"] == 1
         and num(wider["post_original_exit_dividends"]) == 1
         and num(wider["net_difference"]) == Fraction(1099, 100), "ACTIVATION_RESET_AND_EX_DATE_SALE")
    need(widest["signal_session"] == axis[4] and widest["fill_session"] == axis[5],
         "POST_EXIT_NEW_PEAK_MUST_ADVANCE_STOP")
    failure_required(lambda: compare(control, wider, "retained_30_cap"), "retained_30_cap")
    altered = deepcopy(wider)
    altered["post_original_exit_dividends"] = "0"
    failure_required(lambda: compare(altered, wider, "lost_ex_date_claim"), "lost_ex_date_claim")
    altered["post_original_exit_dividends"] = "3"
    failure_required(lambda: compare(altered, wider, "retained_later_claim"), "retained_later_claim")
    missing = deepcopy(corpus)
    del missing["quotes"]["SYNTH"][axis[3]]
    failure_required(lambda: evaluate(ep, missing, axis, num("0.35")), "missing_next_open")
    changed = deepcopy(corpus)
    changed["quotes"]["SYNTH"][axis[3]]["raw_close"] = "100"
    no_new_peak = evaluate(ep, changed, axis, num("0.40"))
    failure_required(lambda: compare(no_new_peak, widest, "post_exit_new_peak"), "post_exit_new_peak")
    changed = deepcopy(ep)
    changed["observations"][-1].update(raw_close=50, own_dd="-0.5")
    changed_corpus = deepcopy(corpus)
    changed_corpus["quotes"]["SYNTH"][axis[1]]["raw_close"] = "50"
    same_open = evaluate(changed, changed_corpus, axis, num("0.40"))
    need(same_open["fill_session"] == axis[2] and num(same_open["net_difference"]) == 0,
         "WIDER_BREACH_EXECUTES_ORIGINAL_OPEN")
    endpoint_case = deepcopy(corpus)
    endpoint_case["actions"] = []
    for row in endpoint_case["quotes"]["SYNTH"].values():
        row.update(raw_open="90", raw_close="90", dividend_per_share="0")
    endpoint_case["quotes"]["SYNTH"][axis[1]]["raw_close"] = "70"
    endpoint_case["quotes"]["SYNTH"][axis[2]]["raw_open"] = "70"
    endpoint_case["quotes"]["SYNTH"][axis[-1]].update(raw_open="95", raw_close="10")
    forced = evaluate(ep, endpoint_case, axis, num("0.35"))
    need(forced["exit_reason"] == "FORCED_HORIZON" and forced["fill_session"] == axis[-1]
         and forced["signal_session"] is None and num(forced["exit_raw_price"]) == 95
         and forced["additional_occupied_sessions"] == 60, "SCHEDULED_ENDPOINT_OPEN_PRECEDES_CLOSE")
    short_axis = axis[:6]
    endpoint_case["quotes"]["SYNTH"][short_axis[-1]]["raw_close"] = "60"
    censored = evaluate(ep, endpoint_case, short_axis, num("0.35"))
    need(censored["classification"] == "CENSORED" and censored["signal_session"] == short_axis[-1]
         and censored["fill_session"] is None and num(censored["exit_fee"]) == 0
         and censored["endpoint_phase"] == "CLOSE", "LAST_CLOSE_NO_FUTURE_OPEN_OR_CENSOR_SALE")
    changed = deepcopy(ep)
    changed["observations"][-1]["episode"]["entry_split_adjusted_price"] = 50
    failure_required(lambda: evaluate(changed, corpus, axis, num("0.35")), "changed_source_share_units")
    changed_corpus = deepcopy(corpus)
    changed_corpus["quotes"]["SYNTH"][axis[5]]["split_ratio"] = "2"
    failure_required(lambda: evaluate(ep, changed_corpus, axis, num("0.35")), "unexpected_extension_split")
    return ["retained_30_cap", "lost_ex_date_claim", "retained_later_claim", "missing_next_open",
            "post_exit_new_peak", "same_original_open_wider_breach", "endpoint_open_before_close",
            "insufficient_followup_not_primary", "last_close_no_future_open",
            "changed_source_share_units", "unexpected_extension_split"]


def replacement_identity(result, ep, episodes, axis):
    hosted()
    matches = []
    if ep["original_sell"] and result["additional_occupied_sessions"]:
        start = axis.index(ep["original_sell"]["session"])
        last = axis[start + result["additional_occupied_sessions"] - 1]
        matches = [dict(key=other["key"], ticker=other["tickers"][0], entry_date=other["entry_date"])
            for other in episodes.values() if other["slot_id"] == ep["slot_id"] and other["key"] != ep["key"]
            and ep["original_sell"]["session"] <= other["entry_date"] <= last]
    return dict(status="UNAVAILABLE" if matches else "NO_DIRECT_REPLACEMENT",
        identities=sorted(matches, key=lambda item: (item["entry_date"], item["key"])),
        reason="PAIRED_RETURNS_UNAVAILABLE" if matches else "NO_ENTRY_DURING_DELAY")


def review(args):
    hosted()
    need(args.book == Path("/p00/book") and args.archive == Path("/frozen/archive/corpus.zip")
         and args.bundle == Path("/frozen/bundle") and args.evidence == Path("/evidence/worker")
         and args.out == Path("/out/review"), "EXACT_REVIEW_MOUNTS")
    sys.meta_path.insert(0, NoCanonical())
    import data
    need(Path(data.__file__).resolve() == Path("/current/research/wider_stop/data.py"), "EXACT_DATA_READER")
    source = data.load_original(args.book)
    axis = [row["session"] for row in source["rows"]]
    selected = {key: ep for key, ep in source["episodes"].items() if activation(ep) is not None}
    need(len(selected) == 17 and sum(ep["original_sell"] is not None for ep in selected.values()) == 16,
         "EXACT_SEVENTEEN_CONCENTRATED_EPISODES")
    corpus = data.load_corpus(args.archive, args.bundle, source, sorted(selected))
    report = json.loads((args.evidence / "report.json").read_bytes())
    need(report["status"] == "WIDER_STOP_DIAGNOSTIC_COMPLETE"
         and report["proofs"]["status"] == "PASSED", "WORKER_COMPLETED_WITH_HOSTED_PROOFS")
    need(report["identity"] == source["identity"] and report["corpus_identity"] == corpus["corpus_identity"],
         "IMMUTABLE_SOURCE_IDENTITIES")
    need(report["source_sha256"] == file_sha(Path("/current/research/wider_stop/worker.py")),
         "EXACT_FROZEN_WORKER_SOURCE")
    need(set(report["arms"]) == {"0.30", "0.35", "0.40"}, "EXACT_THREE_ARMS")
    expected_arms = {}
    for label in ("0.30", "0.35", "0.40"):
        arm = report["arms"][label]
        need(arm["stop_distance"] == label, "ARM_LABEL_AND_DISTANCE")
        outcomes = {row["key"]: row for row in arm["episodes"]}
        need(len(arm["episodes"]) == len(outcomes) == 17 and set(outcomes) == set(selected),
             "ALL_ELIGIBLE_EPISODES_VISIBLE")
        expected = []
        for key, ep in sorted(selected.items()):
            calculated = evaluate(ep, corpus, axis, num(label))
            calculated["replacement_opportunity"] = replacement_identity(calculated, ep, source["episodes"], axis)
            compare(outcomes[key], calculated, label)
            expected.append(calculated)
            if label == "0.30":
                need(num(calculated["net_difference"]) == 0
                     and calculated["additional_occupied_sessions"] == 0, "ORIGINAL_CONTROL_ZERO_DIFFERENCE")
                if ep["original_sell"]:
                    need(calculated["signal_session"] == calculated["original_signal_session"]
                         and calculated["fill_session"] == ep["original_sell"]["session"],
                         "ALL_SIXTEEN_ORIGINAL_STOP_CALIBRATIONS")
        aggregated = summarize(expected)
        need(aggregated["complete"]["count"] == 13 and aggregated["censored"]["count"] == 3
             and aggregated["open_reference"]["count"] == 1, "FIXED_COVERAGE_THIRTEEN_THREE_ONE")
        need(arm["summary"] == aggregated, "INDEPENDENT_ARM_AGGREGATES:" + label)
        expected_arms[label] = dict(episodes=expected, summary=aggregated)
    ranking = sorted(expected_arms,
        key=lambda label: (-num(expected_arms[label]["summary"]["complete"]["mean_normalized_difference"]), num(label)))
    need(report["ranking"] == ranking and report["best_in_this_screen"] == ranking[0],
         "INDEPENDENT_FULL_FOLLOWUP_RANKING")
    negatives = synthetic_checks()
    altered = deepcopy(expected_arms["0.35"]["episodes"][0])
    altered["net_difference"] = "999999999"
    failure_required(lambda: compare(altered, expected_arms["0.35"]["episodes"][0], "altered_output"), "altered_output")
    negatives.append("altered_output")
    altered_identity = deepcopy(report["identity"])
    altered_identity["daily_sha256"] = "0" * 64
    failure_required(lambda: need(altered_identity == source["identity"], "ALTERED_SOURCE_IDENTITY"), "altered_identity")
    negatives.append("altered_identity")
    agnt = next(ep for ep in selected.values() if ep["tickers"] == ["AGNT"])
    wrong = deepcopy(agnt)
    point = next(point for point in wrong["observations"] if num(point["episode"]["current_shares"]) == 85)
    point["episode"]["current_shares"] = 170
    failure_required(lambda: original_check(wrong, axis), "missing_split_basis")
    negatives.append("missing_split_basis")
    need(not args.out.exists(), "NEW_REVIEW_OUTPUT")
    args.out.mkdir(parents=True)
    verdict = dict(status="WIDER_STOP_DIAGNOSTIC_REVIEW_PASSED", identity=source["identity"],
        corpus_identity=corpus["corpus_identity"], episode_count=17, complete_count=13, censored_count=3,
        open_reference_count=1, arms_verified=3, independent_episode_comparisons=51,
        original_stop_calibrations=16, ranking=ranking, negative_checks=negatives,
        report_sha256=file_sha(args.evidence / "report.json"), review_source_sha256=file_sha(Path(__file__)),
        portfolio_performance_admitted=False, new_Core_steps=0, new_Sentinel_steps=0,
        full_strategy_backtest=False)
    (args.out / "independent-review.json").write_bytes(encoded(verdict) + b"\n")
    print(json.dumps(dict(status=verdict["status"], episodes=17, arms=3)), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ("book", "archive", "bundle", "evidence", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    hosted()
    review(args)


if __name__ == "__main__":
    main()
