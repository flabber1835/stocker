from __future__ import annotations

from sentinel.feed import coherence, sharadar


def _ticker():
    return {
        "table": "SEP",
        "permaticker": "P-AAA",
        "ticker": "AAA",
        "category": "Domestic Common Stock",
        "relatedtickers": "",
        "firstpricedate": "2000-01-03",
        "lastpricedate": "2026-08-18",
        "sector": "Technology",
        "isdelisted": "N",
    }


def _sep(day: str):
    return {
        "ticker": "AAA",
        "date": day,
        "close": 100.0,
        "closeunadj": 100.0,
        "open": 99.0,
        "volume": 1_000_000,
    }


def test_multi_year_seed_keeps_actions_pending_until_final_sep_chunk():
    action_calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal action_calls
        if table == sharadar.TICKERS:
            return [_ticker()]
        if table == sharadar.ACTIONS:
            action_calls += 1
            return [{
                "ticker": "AAA", "date": "2020-06-01",
                "action": "dividend", "value": 0.25,
                "name": None, "contraticker": None, "contraname": None,
            }]
        if table == sharadar.SFP:
            return [{"ticker": "SPY", "date": "2021-12-31",
                     "closeadj": 500.0}]
        assert table == sharadar.SEP
        hi = str((params or {}).get("date.lte") or "")
        return [_sep("2020-06-01" if hi.startswith("2020") else "2021-06-01")]

    final = lambda params: str(params.get("date.lte") or "") == "2021-12-31"
    guarded = coherence.StableSharadarFetch(
        fetch,
        protect_sep=lambda _params: True,
        corroborate_reference=final,
        seed_mode=False,
    )
    guarded(sharadar.TICKERS)
    guarded(sharadar.ACTIONS, {
        "date.gte": "2020-01-01", "date.lte": "2021-12-31"})
    guarded(sharadar.SFP, {
        "ticker": "SPY", "date.gte": "2020-01-01",
        "date.lte": "2021-12-31"})

    # Each SEP year is independently observed twice, but the reference sources
    # remain on their first observation until the final chunk brackets them.
    assert list(guarded(sharadar.SEP, {
        "date.gte": "2020-01-01", "date.lte": "2020-12-31"}))
    assert action_calls == 1

    assert list(guarded(sharadar.SEP, {
        "date.gte": "2021-01-01", "date.lte": "2021-12-31"}))
    assert action_calls == 2


def test_daily_default_still_corroborates_actions_on_its_one_window():
    action_calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal action_calls
        if table == sharadar.ACTIONS:
            action_calls += 1
            return []
        assert table == sharadar.SEP
        return [_sep("2026-08-18")]

    guarded = coherence.StableSharadarFetch(fetch)
    guarded(sharadar.ACTIONS, {
        "date.gte": "2026-08-01", "date.lte": "2026-08-18"})
    assert list(guarded(sharadar.SEP, {
        "date.gte": "2026-08-01", "date.lte": "2026-08-18"}))
    assert action_calls == 2
