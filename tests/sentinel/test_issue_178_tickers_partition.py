from __future__ import annotations

from sentinel.feed import coherence, sharadar, universe


def _ticker(table: str, category: str):
    return {
        "table": table,
        "permaticker": "P-AAA",
        "ticker": "AAA",
        "category": category,
        "relatedtickers": "",
        "firstpricedate": "2000-01-03",
        "lastpricedate": "2026-08-18",
        "sector": "Technology",
        "isdelisted": "N",
    }


def _sep():
    return {
        "ticker": "AAA",
        "date": "2026-08-18",
        "close": 100.0,
        "closeunadj": 100.0,
        "open": 99.0,
        "volume": 1_000_000,
    }


def test_non_sep_partition_cannot_change_or_enter_tickers_authority():
    sep = _ticker("SEP", "Domestic Common Stock")
    observations = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal observations
        if table == sharadar.TICKERS:
            observations += 1
            # Same identity, deliberately conflicting category. Its movement
            # between complete observations is irrelevant to the SEP strategy
            # universe and must neither contaminate it nor create false churn.
            sf1 = _ticker(
                "SF1",
                "ADR Common Stock" if observations == 1 else "Canadian Stock")
            return [sep, sf1]
        if table == sharadar.SEP:
            return [_sep()]
        return []

    guarded = coherence.StableSharadarFetch(fetch)
    selected = guarded(sharadar.TICKERS)
    assert selected == [sep]
    assert list(guarded(sharadar.SEP, {
        "date.gte": "2026-08-18", "date.lte": "2026-08-18"})) == [_sep()]
    assert observations == 2


class _Cursor:
    def __init__(self, payloads):
        self.payloads = payloads

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def executemany(self, _sql, payload):
        self.payloads.extend(payload)


class _Conn:
    def __init__(self):
        self.payloads = []
        self.commits = 0

    def cursor(self):
        return _Cursor(self.payloads)

    def commit(self):
        self.commits += 1


def test_universe_writer_defensively_drops_non_sep_product_rows():
    conn = _Conn()
    written = universe.write_universe(
        conn,
        [_ticker("SEP", "Domestic Common Stock"),
         _ticker("SF1", "ADR Common Stock")],
        "2026-08-18",
        run_id="candidate-run",
    )

    assert written == 1
    assert len(conn.payloads) == 1
    assert conn.payloads[0][2] == "Domestic Common Stock"
    assert conn.commits == 1
