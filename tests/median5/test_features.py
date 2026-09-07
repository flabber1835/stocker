from dataclasses import asdict
import json
import textwrap

import numpy as np
import pytest

from stock_strategy_shared.wealth_core import median5
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from sentinel.core.session import _feed_from_dict, _feed_to_dict
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from .oracle import SOURCE, namespace


def test_numerical_features_against_exact_research_statements_and_restart():
    scope = namespace()
    scope["n"] = 4
    start = SOURCE.index("    L=260\n")
    end = SOURCE.index("    # SPY normalized benchmark", start)
    exec(textwrap.dedent(SOURCE[start:end]), scope)
    start = SOURCE.index("            rawop=np.divide")
    end = SOURCE.index("            dt64=", start)
    transition = compile(textwrap.dedent(SOURCE[start:end]), "frozen_numerical_transition", "exec")
    meta = {str(i): SecurityMeta(str(i), f"T{i}", "Common Stock", str(i), first_session="0000") for i in range(4)}
    feed = Feed(meta)
    feed.restart_sessions = 260
    state = median5.fresh()
    feed.median5_state = state
    rng = np.random.default_rng(971)
    prices = np.array([50., 62., 100., 28.])
    factor = np.ones(4)
    for day in range(420):
        prices *= np.exp(rng.normal(.001, .018, 4))
        ratios = np.ones(4)
        if day in (141, 172, 314):
            ratios[0] = 2.
        factor *= ratios
        tids = np.array([i for i in range(4) if not (i == 3 and day in (51, 177))], np.int32)
        c = prices[tids].copy()
        cu = c/factor[tids]
        vol = np.full(len(tids), 2_000_000.)
        scope.update(gday=day, tids=tids, c=c, cu=cu, oo=c*.999, vol=vol,
                     g=type("G", (), {"dividend_per_share": type("C", (), {"to_numpy": lambda *a, **k: np.zeros(len(tids))})(),
                                       "split_ratio": type("C", (), {"to_numpy": lambda *a, **k: ratios[tids]})()})())
        exec(transition, scope)
        rows = [VendorBar(f"{day:04}", str(i), f"T{i}", float(prices[i]/factor[i]),
                          float(prices[i]*.999/factor[i]), float(2e6*factor[i]),
                          float(ratios[i]), signal_close=float(prices[i])) for i in tids]
        norm = feed.advance(f"{day:04}", rows)
        for row in norm.security_bars:
            i = int(row.security_id)
            if row.eligible:
                got = row.certified_signals
                j = list(tids).index(i)
                expected = (scope["mm"][j], scope["rr"][j], scope["fvol"][j], scope["sc"][j])
                assert got == expected, (day, i, got, expected)
        if day in (151, 280):
            state = json.loads(json.dumps(state))
            feed = _feed_from_dict(json.loads(json.dumps(_feed_to_dict(feed, set()))), meta, EligibilityConfig())
            feed.median5_state = state


def test_missing_current_bar_cannot_supply_stale_breadth():
    from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
    from sentinel.core.session import holdings_from_shadow
    meta = {"a": SecurityMeta("a", "A", "Common Stock", "a", first_session="0000")}
    feed = Feed(meta)
    for day in range(23):
        feed.advance(f"{day:04}", [VendorBar(f"{day:04}", "a", "A", 100.+day, 100.+day, 1e7)])
    state = PortfolioState.fresh(1000)
    state.episodes[0] = HoldingEpisode("a", "A", "P:a", 0, "0000", "0001", 101., 101., 1, 1,
                                      episode_peak_split_adjusted_close=122.)
    feed.advance("0023", [])
    holding = holdings_from_shadow(state, feed, {})[0]
    assert holding.own_dd is None
    assert holding.r21 is None
    assert holding.r63 is None


def test_unbound_economic_override_is_rejected_before_transition():
    from dataclasses import replace
    from sentinel.controller.frozen_rule import load
    from sentinel.controller.machine import Controller
    from sentinel.core.session import SessionState, PublishedSession
    from sentinel.core.decision import runtime_strategy_identity
    from sentinel.core.kernel import advance_session
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
    cfg = load()
    identity = runtime_strategy_identity(cfg)
    prior = SessionState.fresh(starting_cash=1000, controller=Controller(cfg), strategy_identity=identity)
    with pytest.raises(ValueError, match="economic configuration is not bound"):
        advance_session(prior, PublishedSession("2006-01-03", 1, [], {}, {}, []),
                        controller_config=cfg, strategy_identity=identity,
                        wealth_config=WealthCoreConfig(entry_weight=.99))


def test_peer_residuals_match_reference_and_exclude_current_return():
    import pandas as pd
    from stock_strategy_shared.wealth_core.feed import SecuritySeries
    from sentinel.controller.median5_breadth import _residuals, _correlation
    scope = namespace()
    rng = np.random.default_rng(776)
    market = rng.normal(.0003, .012, 300)
    common = rng.normal(0, .015, 300)
    closes = 50*np.exp(np.cumsum(np.column_stack([
        market+common+rng.normal(0, .004, 300),
        market+common+rng.normal(0, .004, 300)]), axis=0))
    dates = list(pd.bdate_range("2006-01-03", periods=300))
    spy = pd.DataFrame({"ret": market}, index=dates)
    day = 290
    ring = np.full((260, 2), np.nan, np.float32)
    for j in range(day-259, day+1):
        ring[j % 260] = closes[j].astype(np.float32)
    results = []
    for sid in range(2):
        series = SecuritySeries(str(sid), f"T{sid}", str(sid),
                                session_indices=list(range(day-259, day+1)),
                                signal_closes=closes[day-259:day+1, sid].tolist())
        actual = _residuals(series, day, dict(enumerate(market)))
        expected = scope["_prior_residuals"](sid, day, ring, spy, dates[:day])
        assert actual == expected
        series.signal_closes[-1] *= 100
        assert _residuals(series, day, dict(enumerate(market))) == expected
        results.append(actual)
    assert _correlation(*results) == scope["_peer_corr"](*results)


def test_declared_split_preserves_owned_basis_across_vendor_rebase_and_restart():
    meta = {"a": SecurityMeta("a", "A", "Common Stock", "a", first_session="0000")}
    feed = Feed(meta)
    feed.restart_sessions = 260
    feed.median5_state = median5.fresh()
    feed.advance("0000", [VendorBar("0000", "a", "A", 100., 100., 1e6, signal_close=100.)])
    feed.advance("0001", [VendorBar("0001", "a", "A", 50., 50., 2e6, split_ratio=2., signal_close=50.)])
    assert feed.series["a"].signal_closes == [100., 100.]
    features = json.loads(json.dumps(feed.median5_state))
    feed = _feed_from_dict(json.loads(json.dumps(_feed_to_dict(feed, set()))), meta, EligibilityConfig())
    feed.median5_state = features
    result = feed.advance("0002", [VendorBar("0002", "a", "A", 51., 51., 2e6, signal_close=51.)])
    assert feed.series["a"].signal_closes[-1] == 102.
    assert result.bars[0].raw_open == 51.


def test_breadth_return_preserves_double_current_close_at_zero_boundary():
    from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
    from sentinel.controller.median5_breadth import breadth
    meta = {"a": SecurityMeta("a", "A", "Common Stock", "a", first_session="0000")}
    feed = Feed(meta)
    for day in range(64):
        price = 100.000001 if day == 63 else 100.
        feed.advance(f"{day:04}", [VendorBar(f"{day:04}", "a", "A", price, price, 1e7)])
    state = PortfolioState.fresh(1000)
    state.episodes[0] = HoldingEpisode("a", "A", "SID:a", 0, "0000", "0000", 100., 100., 1, 1,
        market_sessions_held=63, episode_peak_split_adjusted_close=100.000001)
    result, holdings = breadth(state, feed, [], {"a": ["A", "0000", "a"]})
    expected = float(np.float64(100.000001)/np.float32(100.)-1)
    assert holdings[0].r21 == holdings[0].r63 == expected > 0
    assert result.green_breadth == 1.


def test_peer_ties_keep_first_identity_across_rename_and_restart():
    from dataclasses import replace
    import pandas as pd
    from sentinel.breadth.classifier import is_green, is_red
    from sentinel.controller.median5_breadth import breadth
    from sentinel.controller import median5 as controller
    from stock_strategy_shared.wealth_core.feed import SecuritySeries
    from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode
    rng = np.random.default_rng(776)
    n = 160
    prices = 50*np.exp(np.cumsum(rng.normal(0, .005, n)))
    prices[-1] = prices[-22]*.99
    meta = {str(i): SecurityMeta(str(i), ticker, "Common Stock", str(i), first_session="0000")
            for i, ticker in enumerate(("A", "C", "D", "Y", "Z"))}
    feed = Feed(meta)
    feed._session_index = n-1
    book = PortfolioState.fresh(1000, 20)
    state = controller.fresh()
    controller.remember_peer_keys(state, meta)
    for i, item in enumerate(meta.values()):
        feed.series[item.security_id] = SecuritySeries(item.security_id, item.ticker,
            "SID:"+item.security_id, session_indices=list(range(n)), signal_closes=prices.tolist())
        book.episodes[i] = HoldingEpisode(item.security_id, item.ticker, "SID:"+item.security_id,
            i, "0000", "0000", 50., 50., 1, 1, market_sessions_held=159,
            episode_peak_split_adjusted_close=float(prices[-1])/(.88 if i in (1, 2) else .92))
    market = rng.normal(0, .003, n)
    spy_history = [[i, 100., float(value)] for i, value in enumerate(market)]
    baseline, held = breadth(book, feed, spy_history, state["peer_keys"])
    dates = list(pd.bdate_range("2006-01-03", periods=n))
    spy = pd.DataFrame({"ret": market}, index=dates)
    ring = np.full((260, 5), np.nan, np.float32)
    ring[:n] = prices[:, None]
    oracle_held = [(i, None, h.own_dd, h.r21, h.r63, h.age_sessions, is_green(h), is_red(h))
                   for i, h in enumerate(held)]
    expected = namespace()["dynamic_peer_breadth"](oracle_held, n-1, ring, spy, dates[:-1])
    assert (baseline.green_breadth, baseline.damaged_breadth) == expected
    assert baseline.labels[0].amber
    state = controller.validate(json.loads(json.dumps(state)))
    meta["1"] = replace(meta["1"], ticker="ZZ")
    feed.series["1"].ticker = "ZZ"
    book.episodes[1].ticker = "ZZ"
    controller.remember_peer_keys(state, meta)
    after, _ = breadth(book, feed, spy_history, state["peer_keys"])
    assert (after.green_breadth, after.damaged_breadth) == expected
    assert after.labels[0].amber
