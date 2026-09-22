"""Read-only full-history gate and economic-attribution diagnostics."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys


START = "2006-07-31"


def metrics(rows, name):
    values = [float(row[name + "_economics"]["strategy_nav"]) for row in rows]
    peak, peak_day = values[0], rows[0]["session"]
    worst, trough, worst_peak = 0., None, None
    underwater = longest = 0
    for row, value in zip(rows, values):
        if value >= peak:
            peak, peak_day, underwater = value, row["session"], 0
        else:
            underwater += 1
            longest = max(longest, underwater)
        if value/peak-1 < worst:
            worst, trough, worst_peak = value/peak-1, row["session"], peak_day
    log_returns = [math.log(b/a) for a, b in zip(values, values[1:])]
    mean = sum(log_returns)/len(log_returns)
    volatility = math.sqrt(sum((x-mean)**2 for x in log_returns)/(len(log_returns)-1)*252)
    return dict(multiple=values[-1]/values[0], max_drawdown=worst,
                peak_date=worst_peak, trough_date=trough,
                annualized_log_return_volatility=volatility,
                longest_underwater_sessions=longest)


def finite(x):
    return x is not None and math.isfinite(x)


def quantiles(values):
    ordered = sorted(value for value in values if finite(value))
    result = {"finite_count": len(ordered), "unique_values": len(set(ordered))}
    for q in (0., .01, .05, .25, .5, .75, .95, .99, 1.):
        index = (len(ordered)-1)*q
        left, right = math.floor(index), math.ceil(index)
        result[str(q)] = ordered[left]+(ordered[right]-ordered[left])*(index-left)
    return result


def episode_attribution(rows):
    episodes = []
    start = None
    for i, row in enumerate(rows):
        if row["owned55"]["active"] and start is None:
            start = i
        if start is not None and not row["owned55"]["active"]:
            if start == 0 or i+1 >= len(rows):
                raise ValueError("complete entry and next-open release evidence required")
            begin, end = rows[start-1], rows[i+1]
            def ratio(x):
                return Decimal(x["owned55_economics"]["strategy_nav"])/Decimal(x["current_economics"]["strategy_nav"])
            before, after = ratio(begin), ratio(end)
            episodes.append(dict(entry_signal=rows[start]["session"], first_execution=rows[start+1]["session"],
                release_signal=row["session"], release_execution=end["session"],
                active_closes=i-start, different_targets=sum(r["current"]["target"] != r["owned55"]["target"] for r in rows[start:i]),
                relative_factor=str(after/before), relative_change=float(after/before-1)))
            start = None
    if start is not None:
        raise ValueError("owned episode has not recovered")
    return episodes


def sensor_probes():
    from sentinel.controller.champion_frozen import CandidateA
    from sentinel.regime.spy import rolling_std, volatility_acceleration
    quiet = [-.001, .001, -.001, .001, 0.]*4
    loud = [10*x for x in quiet]
    def response(owned_r20):
        control = CandidateA()
        control.episode = True
        control.recent_positive_streak = 7
        return control.step(1., 1., -.05, .02, -.05, .02, owned_r20)
    return dict(volatility=dict(quiet_std20=rolling_std(quiet, 20), loud_std20=rolling_std(loud, 20),
                               quiet_signal=volatility_acceleration(quiet), loud_signal=volatility_acceleration(loud)),
                recovery_comparison=dict(owned_r20_1pct=response(.01), owned_r20_3pct=response(.03),
                    fixed_leaders_r20=.02, fixed_leaders_r40=-.05, fixed_spy_r20=.02))


def analyze(root):
    from sentinel.controller.champion_frozen import CandidateA
    import exchange_calendars as calendars
    rows, daily, hashes = [], [], {}
    for directory in sorted(root.glob("segment-*")):
        if not directory.is_dir():
            continue
        path = directory/"comparison.jsonl"
        raw = path.read_bytes()
        hashes[directory.name] = hashlib.sha256(raw).hexdigest()
        rows.extend(json.loads(line) for line in raw.splitlines())
        daily.extend(json.loads(line) for line in (directory/"daily.jsonl").read_bytes().splitlines())
    assert len(rows) == 5176 and rows[-1]["session"] == "2026-07-31"
    assert [r["session"] for r in rows] == [r["date"] for r in daily]
    assert all(a["session"] < b["session"] for a, b in zip(rows, rows[1:]))
    calendar = calendars.get_calendar("XNYS", start="2006-01-01", end="2026-08-01")
    expected = [str(x.date()) for x in calendar.sessions_in_range("2006-01-03", "2026-07-31")]
    assert [r["session"] for r in rows] == expected
    measured = [row for row in rows if row["session"] >= START]
    assert len(measured) == 5032
    counts = Counter()
    fast_missing, fast_single, slow_missing, slow_single = Counter(), Counter(), Counter(), Counter()
    exposure, reasons, owned_overlap = Counter(), Counter(), Counter()
    recovery_failures, recovery_single_failures = Counter(), Counter()
    recovery = CandidateA()
    effective = previous_native = 1.
    leader_streak = 0
    recovery_detail = []
    for row in rows:
        ob, leads = row["observation"], row["leadership"]
        st = row["native_evidence"]["native_snapshot"]["state"]
        target, native = row["current"]["target"], row["current"]["native"]
        replay_target, replay_reason = recovery.step(native, effective, ob["shadow_drawdown"],
            leads["recent_r20"], leads["recent_r40"], ob["spy_r20"], ob["shadow_r20"])
        assert (replay_target, replay_reason) == (target, row["recovery_reason"])
        effective, previous_native = previous_native, native
        full_health = (finite(leads["recent_r20"]) and finite(leads["recent_r40"])
                       and leads["recent_r20"] > 0 and leads["recent_r40"] > -.04)
        leader_streak = leader_streak+1 if full_health else 0
        if row["session"] < START:
            continue
        counts["sessions"] += 1
        exposure[str(target)] += 1
        reasons[row["recovery_reason"]] += 1
        for key in ("ordinary", "base_fast", "fast", "slow"):
            counts[key+"_active"] += bool(st[key])
        counts["fast_and_slow_active"] += st["fast"] and st["slow"]
        counts["native_zero"] += native == 0
        counts["recovery_only_zero"] += native == 1 and target == 0
        counts["leadership_partial"] += target == .55
        counts["damage_100pct"] += ob["damaged_breadth"] == 1
        counts["green_zero"] += ob["green_breadth"] == 0
        assert ob["damaged_breadth"]+ob["green_breadth"] <= 1+1e-12
        counts["fast_damage_passes_green_fails"] += ob["damaged_breadth"] >= .88 and ob["green_breadth"] > .2
        counts["slow_damage_passes_green_fails"] += ob["damaged_breadth"] >= .75 and ob["green_breadth"] > .25
        counts["ordinary_base_duration_capped"] += st["base_dur"] == 30
        healthy = (finite(ob["shadow_r20"]) and ob["shadow_r20"] > 0
                   and ob["damaged_breadth"] <= .63 and ob["green_breadth"] >= .2)
        counts["fast_healthy_streak_blocked_only_by_min_age"] += (
            st["fast"] and healthy and st["fast_h"] >= 3 and st["fast_age"]+1 < 10)
        counts["slow_healthy_streak_blocked_only_by_min_age"] += (
            st["slow"] and healthy and st["slow_h"] >= 6 and st["slow_age"]+1 < 20)
        gates = dict(drawdown=finite(ob["shadow_drawdown"]) and ob["shadow_drawdown"] <= -.1,
                     damage=ob["damaged_breadth"] >= .88,
                     green=ob["green_breadth"] <= .2,
                     short_return=(finite(ob["shadow_r5"]) and ob["shadow_r5"] <= -.05)
                         or (finite(ob["shadow_r10"]) and ob["shadow_r10"] <= -.08),
                     damage_acceleration=finite(ob["damaged_breadth_delta5"]) and ob["damaged_breadth_delta5"] >= .3,
                     volatility=finite(ob["spy_vol_ratio"]) and ob["spy_vol_ratio"] >= .04,
                     confirmation=(finite(ob["spy_r20"]) and ob["spy_r20"] <= -.01)
                         or (finite(ob["shadow_r10"]) and ob["shadow_r10"] <= -.1))
        assert all(gates.values()) == row["native_evidence"]["fast_signal"]
        impossible = (finite(ob["damaged_breadth_delta5"])
                      and ob["damaged_breadth"]-ob["damaged_breadth_delta5"] > .7+1e-12)
        counts["damage_acceleration_mathematically_unreachable"] += impossible
        severely_damaged = all(gates[k] for k in ("drawdown", "damage", "green"))
        if severely_damaged:
            counts["severely_damaged_book"] += 1
            counts["severely_damaged_acceleration_unreachable"] += impossible
            counts["severely_damaged_final_full"] += target == 1
            counts["severely_damaged_final_full_unreachable_acceleration"] += target == 1 and impossible
            failed = [key for key, yes in gates.items() if not yes]
            fast_missing.update(failed)
            if len(failed) == 1:
                fast_single.update(failed)
                counts["only_"+failed[0]+"_fails_while_final_full"] += target == 1
                counts["only_"+failed[0]+"_fails_while_final_full_and_fast_armed"] += target == 1 and st["fast_armed"]
        base = st["ordinary"] or st["base_fast"]
        if base:
            slow = dict(timer=st["base_dur"] >= 30,
                        extra_loss=ob["shadow_nav"]/st["base_anchor"]-1 <= -.02,
                        r40=finite(ob["shadow_r40"]) and ob["shadow_r40"] <= -.03,
                        damage=ob["damaged_breadth"] >= .75,
                        green=ob["green_breadth"] <= .25)
            assert all(slow.values()) == row["native_evidence"]["slow_signal"]
            counts["slow_base_active"] += 1
            failed = [key for key, yes in slow.items() if not yes]
            slow_missing.update(failed)
            if len(failed) == 1:
                slow_single.update(failed)
        if finite(ob["shadow_r20"]) and finite(leads["recent_r20"]):
            counts["owned_positive_leaders_nonpositive"] += ob["shadow_r20"] > 0 and leads["recent_r20"] <= 0
            counts["owned_nonpositive_leaders_positive"] += ob["shadow_r20"] <= 0 and leads["recent_r20"] > 0
        if native == 1 and target == 0:
            counts["recovery_only_zero_leaders_currently_healthy"] += full_health
            counts["recovery_only_zero_leaders_r20_nonpositive"] += leads["recent_r20"] <= 0
            counts["recovery_only_zero_leaders_r40_not_above_floor"] += leads["recent_r40"] <= -.04
            counts["recovery_only_zero_owned_positive"] += ob["shadow_r20"] > 0
            counts["recovery_only_zero_owned_healthy"] += healthy
            counts["recovery_only_zero_owned_new_peak"] += ob["shadow_drawdown"] >= -1e-12
            cross = dict(positive_persistence=recovery.recent_positive_streak >= 8,
                         owned_return_positive=ob["shadow_r20"] > 0,
                         leaders_at_least_owned=leads["recent_r20"] >= ob["shadow_r20"],
                         spy_at_least_owned=ob["spy_r20"] >= ob["shadow_r20"])
            failures = [key for key, yes in cross.items() if not yes]
            recovery_failures.update(failures)
            if len(failures) == 1:
                recovery_single_failures.update(failures)
            recovery_detail.append(dict(date=row["session"], owned_r20=ob["shadow_r20"],
                leaders_r20=leads["recent_r20"], leaders_r40=leads["recent_r40"],
                leader_streak=leader_streak, owned_healthy=healthy, spy_r20=ob["spy_r20"]))
        if row["owned55"]["active"]:
            owned_overlap[str(target)] += 1
        counts["owned55_additional_partial_sessions"] += row["owned55"]["target"] != target
    episodes = episode_attribution(rows)
    product = math.prod(float(e["relative_factor"]) for e in episodes)
    actual_relative = float(Decimal(rows[-1]["owned55_economics"]["strategy_nav"])/Decimal(rows[-1]["current_economics"]["strategy_nav"]))
    assert abs(product-actual_relative) < 1e-12
    dynamic = {key: quantiles([r["observation"][key] for r in measured])
               for key in ("shadow_drawdown", "shadow_r5", "shadow_r10", "shadow_r20", "shadow_r40",
                           "damaged_breadth", "green_breadth", "damaged_breadth_delta5", "spy_r20", "spy_vol_ratio")}
    dynamic.update({key: quantiles([r["leadership"][key] for r in measured])
                    for key in ("recent_r20", "recent_r40")})
    held_counts = Counter(r["held_count"] for r in daily if r["date"] >= START)
    quantization = []
    for n, count in sorted(held_counts.items()):
        assert n > 0
        minimum = math.ceil(.88*n-1e-12)
        quantization.append(dict(holdings=n, sessions=count, one_label_step=1/n,
            minimum_damaged_count=minimum, effective_damage_threshold=minimum/n))
    for row, d in zip(rows, daily):
        if row["session"] >= START:
            for key in ("green_breadth", "damaged_breadth"):
                amount = row["observation"][key]*d["held_count"]
                assert abs(amount-round(amount)) < 1e-10
    return dict(schema="owned55-mechanical-assessment/1", source_trace_hashes=hashes,
        independent_calendar=dict(name="XNYS", package_version=calendars.__version__,
                                  expected_sessions=len(expected), missing=0, duplicate=0, extra=0),
        measurement_start=START, measured_sessions=len(measured), counts=counts,
        current_target_distribution=exposure, reasons=reasons,
        fast_failed_gates_within_severely_damaged=fast_missing,
        fast_only_failed_gate_within_severely_damaged=fast_single,
        slow_failed_gates_when_base_active=slow_missing,
        slow_only_failed_gate_when_base_active=slow_single,
        current_target_during_owned_active=owned_overlap, owned_episodes=episodes,
        concordance_failed_gates_on_recovery_only_zero=recovery_failures,
        concordance_only_failed_gate_on_recovery_only_zero=recovery_single_failures,
        episode_product_relative_factor=product, actual_relative_factor=actual_relative,
        relative_factor_excluding_2011=product/next(float(e["relative_factor"]) for e in episodes if e["entry_signal"].startswith("2011")),
        metrics={key: metrics(measured, key) for key in ("current", "owned55")},
        signal_quantiles=dynamic, breadth_resolution=quantization,
        structural_probes=sensor_probes(),
        recovery_blocked_rows=recovery_detail)


if __name__ == "__main__":
    print(json.dumps(analyze(Path(sys.argv[1])), indent=2, allow_nan=False))
