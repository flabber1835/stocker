"""The window's leading edge derived "no split", and then WROTE it over a good one.

THE DEFECT. `normalise_sep_rows` recovers a split by comparing a bar against the
previous observation of the same security, and started every call with an empty
map. Both callers invoke it on a window — `seed` a calendar year, `daily` the
last fourteen days — so the FIRST bar of each security in each window had no
predecessor and `split_ratio_from_domains(None, None, ...)` returned 1.0.

That alone is a detection gap. What made it corruption is the upsert:
`split_ratio = EXCLUDED.split_ratio`, unconditional. The daily overlap exists to
absorb vendor restatements, it runs every evening, and at its leading edge it
recomputed 1.0 and wrote it over a correct 2.0 that an earlier run had derived
when that same session sat mid-window. **The mechanism built to repair data was
degrading it at its own boundary.**

Only `authoritative_splits` protected anything, and the ingest's own
SPLIT_ONLY_DERIVED warning exists precisely because ACTIONS coverage is not
complete.

THREE RULES CLOSE IT, and they are separable — each is tested on its own here:

    1  prior_observations   seed `prev` from the corpus, so the leading edge has
                            a predecessor at all
    2  non-downgrade        an incoming 1.0 never overwrites a stored ratio;
                            absence of evidence must not overwrite evidence
    3  seam caution         a split derived against a SEEDED predecessor with no
                            ACTIONS corroboration is recorded, NOT applied — the
                            two closes may straddle vendor adjustment vintages,
                            and a stale one derives a spurious reverse split

Rule 3 is the one that could be argued the other way, so it is worth being
explicit: it trades a missed split (recorded, visible, auditable) against an
INVENTED one (silent, and wrong in the share count). On a value that becomes a
share count, the conservative reading of a suspicious input is the ordinary one —
the same argument the trailing stop uses for a zero volatility.

Contract: docs/sentinel-execution-contract.md §9.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import domains, ingest, repair, sharadar  # noqa: E402
from sentinel.feed import store as S  # noqa: E402


# ---------------------------------------------------------------------------
# A 2:1 forward split, expressed the way SEP expresses one.
#
# SEP.close is SPLIT-ADJUSTED under the vendor's CURRENT view and closeunadj is
# as-traded, so their ratio IS the cumulative adjustment factor — 2 before the
# ex-date, 1 from it on. The factor FALLS through a forward split, and the share
# ratio is before/after.
# ---------------------------------------------------------------------------
PRE = {"close": 50.0, "closeunadj": 100.0}      # factor 2
POST = {"close": 50.0, "closeunadj": 50.0}      # factor 1  => ratio 2.0


def sep(ticker, date, domain, open_=49.0, volume=1_000_000):
    return {"ticker": ticker, "date": date, "open": open_, "volume": volume,
            **domain}


def normalise(rows, **kw):
    rep = kw.pop("report", None) or domains.NormalisationReport()
    bars = list(domains.normalise_sep_rows(rows, report=rep, **kw))
    return {(b.vendor.ticker, b.vendor.session): b for b in bars}, rep


class TestTheDefect:
    """Reproduce it before fixing it, or the fix is unverified."""

    def test_a_split_on_the_FIRST_bar_of_a_window_derives_NO_SPLIT(self):
        bars, rep = normalise([sep("AAA", "2021-01-11", POST)])
        assert bars[("AAA", "2021-01-11")].vendor.split_ratio == 1.0
        assert rep.splits_detected == 0

    def test_the_SAME_split_is_seen_when_the_predecessor_is_in_the_stream(self):
        """Identical data, one extra bar in front of it. The only difference is
        whether the comparison had something to compare against."""
        bars, rep = normalise([sep("AAA", "2021-01-08", PRE),
                               sep("AAA", "2021-01-11", POST)])
        assert bars[("AAA", "2021-01-11")].vendor.split_ratio == 2.0
        assert rep.splits_detected == 1


class TestPriorObservationsCloseTheGap:
    def test_a_SEEDED_predecessor_recovers_the_split_when_ACTIONS_confirms(self):
        bars, rep = normalise(
            [sep("AAA", "2021-01-11", POST)],
            prior_observations={"AAA": (PRE["close"], PRE["closeunadj"])},
            authoritative_splits={("AAA", "2021-01-11"): 2.0})
        assert bars[("AAA", "2021-01-11")].vendor.split_ratio == 2.0
        assert rep.splits_detected == 1
        assert not rep.seam_splits_uncorroborated

    def test_the_seed_is_keyed_on_SECURITY_not_ticker(self):
        """A reused symbol must not hand one company's close to another.

        The seed map is keyed on the resolved `security_id`, so a resolver that
        maps the same ticker to a different security finds no predecessor rather
        than the wrong one — and derives no split instead of a fabricated one.
        """
        bars, _ = normalise(
            [sep("AAA", "2021-01-11", POST)],
            resolve_identity=lambda t, s: "SEC-NEW",
            prior_observations={"SEC-OLD": (PRE["close"], PRE["closeunadj"])},
            authoritative_splits={("AAA", "2021-01-11"): 2.0})
        # ACTIONS still supplies the truth; what matters is that the DERIVED
        # path found nothing, rather than deriving against a foreign security.
        assert bars[("AAA", "2021-01-11")].vendor.security_id == "SEC-NEW"
        assert ("AAA", "2021-01-11") not in _.derived_splits


class TestSeamCaution:
    def test_an_UNCORROBORATED_seam_split_is_RECORDED_and_NOT_applied(self):
        bars, rep = normalise(
            [sep("AAA", "2021-01-11", POST)],
            prior_observations={"AAA": (PRE["close"], PRE["closeunadj"])})
        assert bars[("AAA", "2021-01-11")].vendor.split_ratio == 1.0, (
            "not applied — the seeded close may belong to an older adjustment "
            "vintage, and a stale one derives a SPURIOUS split")
        assert rep.seam_splits_uncorroborated == {("AAA", "2021-01-11"): 2.0}, (
            "but recorded: this is the population an operator must adjudicate, "
            "and a silent 1.0 is what the old code already did")

    def test_caution_applies_to_the_SEAM_ONLY_not_the_rest_of_the_window(self):
        """The second bar's predecessor came from the stream, so it is trusted.

        Without this the rule would suppress every derived split in the corpus
        and the fallback would stop existing.
        """
        bars, rep = normalise(
            [sep("AAA", "2021-01-11", PRE), sep("AAA", "2021-01-12", POST)],
            prior_observations={"AAA": (PRE["close"], PRE["closeunadj"])})
        assert bars[("AAA", "2021-01-12")].vendor.split_ratio == 2.0
        assert not rep.seam_splits_uncorroborated

    def test_a_spurious_reverse_split_from_a_stale_vintage_is_NOT_written(self):
        """The failure rule 3 exists to prevent, stated as data.

        A seeded close from BEFORE a vendor re-basing sits in the old adjustment
        while the fetched bar sits in the new one. Their domain ratio inverts and
        derives a reverse split that never happened — which, applied, would HALVE
        a share count.
        """
        bars, rep = normalise(
            [sep("AAA", "2021-01-11", PRE)],                  # factor 2, fresh
            prior_observations={"AAA": (POST["close"], POST["closeunadj"])})
        assert rep.seam_splits_uncorroborated[("AAA", "2021-01-11")] == 0.5
        assert bars[("AAA", "2021-01-11")].vendor.split_ratio == 1.0


# ---------------------------------------------------------------------------
# Database-backed: the store rules and the end-to-end regression.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for t in ("sentinel_bar_split_repairs", "sentinel_corpus_publications",
                  "sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "sentinel_corpus_anomalies", "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def put_bar(conn, sid, session, ticker, close, raw, ratio=1.0):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id, session, ticker,"
            " close_signal, close_unadjusted, split_ratio)"
            " VALUES (%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (security_id, session) DO UPDATE SET"
            " split_ratio = EXCLUDED.split_ratio",
            (sid, session, ticker, close, raw, ratio))
    conn.commit()


def ratio_of(conn, sid, session) -> float:
    with conn.cursor() as cur:
        cur.execute("SELECT split_ratio FROM sentinel_bars"
                    " WHERE security_id=%s AND session=%s", (sid, session))
        return float(cur.fetchone()[0])


def effective_ratio_of(conn, sid, session) -> float:
    from sentinel.feed import publication
    with conn.cursor() as cur:
        cur.execute(
            "SELECT " + publication.effective_split_ratio("b") +
            " FROM sentinel_bars b WHERE security_id=%s AND session=%s",
            (sid, session))
        return float(cur.fetchone()[0])


class TestPreviousObservations:
    def test_it_returns_the_last_bar_STRICTLY_BEFORE_the_session(self, conn):
        put_bar(conn, "P-AAA", "2021-01-05", "AAA", 10.0, 20.0)
        put_bar(conn, "P-AAA", "2021-01-08", "AAA", 50.0, 100.0)
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 99.0, 99.0)

        assert S.previous_observations(conn, "2021-01-11") == {
            "P-AAA": (50.0, 100.0)}

    def test_a_SPARSE_security_is_found_however_far_back_it_printed(self, conn):
        """The reason this is a query and not a lookback window.

        A fixed margin cannot bound how long a security has been quiet, which is
        why chunking the canonical LOADER was withdrawn rather than widened. The
        ingest escapes that only because it has a corpus to ask.
        """
        put_bar(conn, "P-SPARSE", "2020-03-02", "SPARSE", 50.0, 100.0)
        put_bar(conn, "P-LIQUID", "2021-01-08", "LIQUID", 7.0, 7.0)

        prev = S.previous_observations(conn, "2021-01-11")
        assert prev["P-SPARSE"] == (50.0, 100.0), "315 days is not too far"
        assert prev["P-LIQUID"] == (7.0, 7.0)


class TestTheUpsertNeverDowngrades:
    def test_an_incoming_1_0_does_NOT_overwrite_a_stored_split(self, conn):
        """The corruption, at the level of one statement."""
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=2.0)
        S.write_bars(conn, [domains.NormalisedBar(
            close_signal=50.0, vendor=_vendor("P-AAA", "2021-01-11", "AAA", 1.0))])
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 2.0

    def test_a_ratio_may_still_be_RAISED_from_1_0(self, conn):
        """Non-downgrade must not become non-correction: a later run that DOES
        have the predecessor has to be able to fix a missed split."""
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        S.write_bars(conn, [domains.NormalisedBar(
            close_signal=50.0, vendor=_vendor("P-AAA", "2021-01-11", "AAA", 2.0))])
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 2.0

    def test_ACTIONS_may_still_RESTATE_one_split_as_another(self, conn):
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=2.0)
        S.write_bars(conn, [domains.NormalisedBar(
            close_signal=50.0, vendor=_vendor("P-AAA", "2021-01-11", "AAA", 1.5))])
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 1.5


def _vendor(sid, session, ticker, ratio):
    from stock_strategy_shared.wealth_core.feed import VendorBar
    return VendorBar(session=session, security_id=sid, ticker=ticker,
                     raw_close=50.0, raw_open=49.0, volume=1_000_000,
                     split_ratio=ratio, dividend_per_share=0.0, tradeable=True)


class TestTheDailyOverlapNoLongerCorrupts:
    """End to end, through `ingest.daily`, which is what actually runs nightly."""

    def test_a_stored_split_SURVIVES_a_daily_run_that_reopens_its_session(self, conn):
        # A corpus in which 2021-01-11 correctly carries a 2:1, established when
        # that session sat mid-window.
        put_bar(conn, "P-AAA", "2021-01-08", "AAA", 50.0, 100.0)
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=2.0)
        put_bar(conn, "P-AAA", "2021-01-20", "AAA", 50.0, 50.0)

        # A daily run whose 14-day overlap reopens 2021-01-11 as its FIRST
        # session — the exact configuration that used to write 1.0 over the 2.0.
        rows = [sep("AAA", "2021-01-11", POST), sep("AAA", "2021-01-20", POST)]
        ingest.daily(conn, fetch=_fetch(rows), today="2021-01-20",
                     overlap_days=14)

        assert ratio_of(conn, "P-AAA", "2021-01-11") == 2.0, (
            "the daily overlap exists to REPAIR restated bars; it must never be "
            "the thing that breaks them")


def _fetch(sep_rows, action_rows=()):
    ticker_rows = [{"ticker": t, "permaticker": f"P-{t}"}
                   for t in sorted({r["ticker"] for r in sep_rows})]

    def fetch(table, params=None, **kw):
        if table == sharadar.TICKERS:
            return list(ticker_rows)
        lo = (params or {}).get("date.gte", "0000-00-00")
        hi = (params or {}).get("date.lte", "9999-99-99")
        if table == sharadar.ACTIONS:
            return [r for r in action_rows if lo <= r["date"] <= hi]
        return [r for r in sep_rows if lo <= r["date"] <= hi]
    return fetch


class TestRepair:
    def test_the_audit_finds_a_bar_that_CONTRADICTS_actions(self, conn):
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        S.write_actions(conn, [{"ticker": "AAA", "date": "2021-01-11",
                                "action": "split", "value": 2.0}])

        result = repair.audit(conn, start="2021-01-04", end="2021-01-15")
        assert not result.clean
        assert len(result.confirmed) == 1
        d = result.confirmed[0]
        assert (d.ticker, d.stored, d.authoritative) == ("AAA", 1.0, 2.0)
        assert d.is_missing_split

    def test_a_split_ACTIONS_never_recorded_is_INVISIBLE_to_the_audit(self, conn):
        """The audit is a LOWER BOUND and must be documented as one.

        This is the population most at risk — the derived fallback existed to
        catch exactly the splits ACTIONS omits — and there is no local witness
        for it. Reporting `clean` here is correct behaviour, which is why
        `clean` is not named `certifiable`.
        """
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        result = repair.audit(conn, start="2021-01-04", end="2021-01-15")
        assert result.clean
        assert "LOWER" in result.to_dict()["bound"]

    def test_repair_is_DRY_by_default(self, conn):
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        S.write_actions(conn, [{"ticker": "AAA", "date": "2021-01-11",
                                "action": "split", "value": 2.0}])

        out = repair.repair(conn, start="2021-01-04", end="2021-01-15")
        assert out["dry_run"] is True and out["rows_updated"] == 0
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 1.0

    def test_repair_applies_the_authoritative_value_and_leaves_a_TRACE(self, conn):
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        S.write_actions(conn, [{"ticker": "AAA", "date": "2021-01-11",
                                "action": "split", "value": 2.0}])

        out = repair.repair(conn, start="2021-01-04", end="2021-01-15",
                            dry_run=False)
        assert out["rows_updated"] == 1
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 1.0, (
            "the visible base generation must never be edited in place")
        assert effective_ratio_of(conn, "P-AAA", "2021-01-11") == 2.0
        assert out["published_version"] is not None
        assert repair.audit(conn, start="2021-01-04", end="2021-01-15").clean

        with conn.cursor() as cur:
            cur.execute("SELECT detail FROM sentinel_corpus_anomalies"
                        " WHERE kind = 'SPLIT_RATIO_REPAIRED'")
            assert "1 -> ACTIONS=2" in cur.fetchone()[0]

    def test_repair_is_the_ONLY_path_allowed_to_lower_a_ratio(self, conn):
        """The asymmetry between the two writers, asserted rather than described.

        The nightly upsert refuses to downgrade because absence of evidence must
        not overwrite evidence. A repair is evidence, applied deliberately by a
        human — so it must be able to do what the unattended path cannot.
        """
        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=4.0)
        S.write_actions(conn, [{"ticker": "AAA", "date": "2021-01-11",
                                "action": "split", "value": 1.0}])

        S.write_bars(conn, [domains.NormalisedBar(
            close_signal=50.0, vendor=_vendor("P-AAA", "2021-01-11", "AAA", 1.0))])
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 4.0, "upsert cannot"

        repair.repair(conn, start="2021-01-04", end="2021-01-15", dry_run=False)
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 4.0, "base is immutable"
        assert effective_ratio_of(conn, "P-AAA", "2021-01-11") == 1.0, \
            "published repair can lower the effective ratio"

    def test_an_unpublished_repair_candidate_is_invisible(self, conn):
        from sentinel.feed import publication

        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        run = S.IngestRun(conn, "repair").progress.run_id
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_bar_split_repairs"
                " (security_id,session,split_ratio,prior_split_ratio,"
                "  last_written_run_id) VALUES (%s,%s,2,1,%s)",
                ("P-AAA", "2021-01-11", run))
        conn.commit()

        assert effective_ratio_of(conn, "P-AAA", "2021-01-11") == 1.0
        assert not publication.coherence(conn).coherent

    def test_a_publication_failure_rolls_back_the_repair_generation(
            self, conn, monkeypatch):
        from sentinel.feed import publication

        put_bar(conn, "P-AAA", "2021-01-11", "AAA", 50.0, 50.0, ratio=1.0)
        S.write_actions(conn, [{"ticker": "AAA", "date": "2021-01-11",
                                "action": "split", "value": 2.0}])
        prior = publication.publish(conn, window_start="2021-01-04",
                                    window_end="2021-01-15")

        def fail_publish(*_args, **_kwargs):
            raise RuntimeError("injected publication crash")

        monkeypatch.setattr(publication, "publish", fail_publish)
        with pytest.raises(RuntimeError, match="injected publication crash"):
            repair.repair(conn, start="2021-01-04", end="2021-01-15",
                          dry_run=False)

        assert publication.current(conn).version == prior.version
        assert ratio_of(conn, "P-AAA", "2021-01-11") == 1.0
        assert effective_ratio_of(conn, "P-AAA", "2021-01-11") == 1.0
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_bar_split_repairs")
            assert cur.fetchone()[0] == 0
