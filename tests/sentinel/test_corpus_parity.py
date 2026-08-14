"""The real-window corpus comparison, and the fact that it can FAIL.

`test_loader_parity` proves the two MAPPINGS agree on rows both were handed.
That is not the same claim as "the bars actually seeded for 2021-2023 equal the
canonical ones", and the difference is everything a synthetic fixture cannot
contain: real splits on real securities, ticker reuse, delistings mid-window,
restatements that landed in one store and not the other.

The comparison itself needs both databases and a seeded corpus, so it runs from
the certification harness. What is tested HERE is the part that decides the
verdict — the rule, and above all what it does when it could not run.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: The REPOSITORY under inspection. Inside the certified image ROOT is /work
#: (tests, an importable backtester copy, tools) while the repo SOURCES live at
#: /work/repo — so a repo file read through ROOT resolves in a checkout and
#: raises FileNotFoundError in the image.
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

from tools import corpus_parity as CP  # noqa: E402

# The CANONICAL loader, imported directly: the hazard tests below assert
# properties of ITS date handling, and asserting them anywhere else would be
# asserting a paraphrase.
CP._add_backtester_to_path()
from app import wealth_core_replay as BT  # noqa: E402

W = ("2024-01-01", "2024-12-31")


def bar(session="2024-06-03", sid="P:AAA", **kw):
    base = dict(session=session, security_id=sid, ticker="AAA",
                raw_close=100.0, raw_open=99.0, volume=1e6,
                split_ratio=1.0, dividend_per_share=0.0, tradeable=True)
    base.update(kw)
    return VendorBar(**base)


def side(*bars):
    out = {}
    for b in bars:
        out.setdefault(b.session, []).append(b)
    return out


class TestItAgreesOnlyWhenItShould:

    def test_identical_corpora_agree(self):
        a = side(bar(), bar(sid="P:BBB"))
        assert CP.compare(a, side(bar(), bar(sid="P:BBB")), window=W).agrees

    def test_a_MISSING_bar_is_reported_as_membership_not_as_a_field(self):
        rep = CP.compare(side(bar()), side(bar(), bar(sid="P:BBB")), window=W)
        assert rep.missing_from_sentinel == [("2024-06-03", "P:BBB")]
        assert rep.field_divergences == {} and not rep.agrees

    def test_an_EXTRA_bar_is_reported_separately(self):
        rep = CP.compare(side(bar(), bar(sid="P:BBB")), side(bar()), window=W)
        assert rep.extra_in_sentinel == [("2024-06-03", "P:BBB")]

    def test_each_FIELD_divergence_is_counted_by_name(self):
        rep = CP.compare(side(bar(split_ratio=2.0, dividend_per_share=0.3)),
                         side(bar()), window=W)
        assert rep.field_divergences == {"split_ratio": 1,
                                         "dividend_per_share": 1}
        assert not rep.agrees

    def test_the_examples_NAME_the_security_and_the_two_values(self):
        rep = CP.compare(side(bar(split_ratio=2.0)), side(bar()), window=W)
        e = rep.examples[0]
        assert (e["security_id"], e["field"], e["sentinel"], e["canonical"]) \
            == ("P:AAA", "split_ratio", 2.0, 1.0)

    def test_tradeable_is_compared(self):
        """The field with no visible consequence until an order fills. It was
        defaulted on Sentinel's side until this batch."""
        rep = CP.compare(side(bar(tradeable=False)), side(bar()), window=W)
        assert rep.field_divergences == {"tradeable": 1}

    def test_None_and_zero_are_NOT_the_same(self):
        rep = CP.compare(side(bar(volume=None)), side(bar(volume=0.0)), window=W)
        assert rep.field_divergences == {"volume": 1}

    def test_representation_noise_does_NOT_count_as_divergence(self):
        """Both sides scale and round the as-traded open, so an exact equality
        test would fail on float representation rather than on data."""
        assert CP.compare(side(bar(raw_open=99.0)),
                          side(bar(raw_open=99.0 + 1e-13)), window=W).agrees


class TestTheReportIsBOUNDED:

    def test_examples_are_capped_and_the_overflow_is_counted(self):
        mine = side(*[bar(sid=f"P:{i}", split_ratio=2.0) for i in range(40)])
        theirs = side(*[bar(sid=f"P:{i}") for i in range(40)])
        rep = CP.compare(mine, theirs, window=W, max_report=5)
        assert len(rep.examples) == 5 and rep.examples_truncated == 35

    def test_the_COUNT_stays_exact_regardless(self):
        mine = side(*[bar(sid=f"P:{i}", split_ratio=2.0) for i in range(40)])
        theirs = side(*[bar(sid=f"P:{i}") for i in range(40)])
        rep = CP.compare(mine, theirs, window=W, max_report=5)
        assert rep.field_divergences["split_ratio"] == 40


class TestNotHavingRunIsNotAPass:
    """The failure mode a certification tool must not have. An unreadable
    canonical corpus produces no divergences, and a report that treated 'no
    divergences found' as agreement would return its cleanest verdict for
    having done nothing at all."""

    def test_an_UNAVAILABLE_report_does_not_agree(self):
        rep = CP.ParityReport(window=W, unavailable="BT_DATABASE_URL is unset")
        assert rep.agrees is False
        assert rep.to_dict()["unavailable"]

    def test_a_missing_BT_URL_returns_UNAVAILABLE_rather_than_raising(self,
                                                                     monkeypatch):
        monkeypatch.delenv("BT_DATABASE_URL", raising=False)
        rep = CP.run(object(), start=W[0], end=W[1])
        assert rep.unavailable and "BT_DATABASE_URL" in rep.unavailable
        assert rep.agrees is False

    def test_an_EMPTY_comparison_with_no_reason_DOES_agree(self):
        """The control: emptiness is only a pass when both sides were actually
        read and both were empty."""
        assert CP.compare({}, {}, window=W).agrees

    def test_a_reversed_window_is_refused_before_database_access(self):
        rep = CP.run(object(), start="2024-12-31", end="2024-01-01",
                     bt_database_url="postgresql+psycopg://unused")
        assert rep.unavailable and "reversed" in rep.unavailable


class TestBothCorporaArePinnedAndIdentified:
    SRC = (ROOT / "tools" / "corpus_parity.py").read_text()

    def test_the_sentinel_side_uses_its_publication_pin(self):
        assert "with publication.pinned(sentinel_conn)" in self.SRC
        assert "publication.assert_coherent(sentinel_conn)" in self.SRC

    def test_the_canonical_side_is_one_locked_repeatable_read_snapshot(self):
        start = self.SRC.index("with bt_conn.begin()")
        end = self.SRC.index("except Exception as exc", start)
        body = self.SRC[start:end]
        tx = body.index(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        lock = body.index("pg_try_advisory_xact_lock_shared")
        identity = body.index("FROM bt_data_version WHERE id = 1")
        bars = body.index("bt.load_bars")
        assert tx < lock < identity < bars

    def test_the_tool_and_engine_use_the_same_advisory_key(self):
        engine_gate = (REPO / "services" / "bt-engine" / "app" /
                       "jobs_busy.py").read_text()
        literal = "0x4254_434F_5250_5553"
        assert literal in self.SRC and literal in engine_gate

    def test_the_report_names_both_generations(self):
        rep = CP.ParityReport(
            window=W, sentinel_data_version=12,
            canonical_data_version="generation-7",
            canonical_source_mode="sharadar")
        out = rep.to_dict()
        assert out["sentinel_data_version"] == 12
        assert out["canonical_data_version"] == "generation-7"
        assert out["canonical_source_mode"] == "sharadar"

    def test_the_real_run_resolves_identity_as_of_the_window_end(self,
                                                                 monkeypatch):
        """The canonical resolver is point-in-time and requires ``as_of``.

        Exercise ``run`` rather than inspecting its source: omitting the
        keyword makes the fake resolver raise ``TypeError`` and the parity
        report fail closed as unavailable.
        """
        from contextlib import contextmanager, nullcontext
        from types import SimpleNamespace

        import sqlalchemy as sa
        from sentinel.core import loader
        from sentinel.feed import publication

        observed = {}
        identity = object()

        @contextmanager
        def pinned(_conn):
            yield SimpleNamespace(version=12)

        class Result:
            def __init__(self, *, scalar=None, row=None):
                self._scalar = scalar
                self._row = row

            def scalar_one(self):
                return self._scalar

            def first(self):
                return self._row

        class Connection:
            def begin(self):
                return nullcontext()

            def execute(self, statement, _params=None):
                sql = str(statement)
                if "pg_try_advisory_xact_lock_shared" in sql:
                    return Result(scalar=True)
                if "FROM bt_data_version" in sql:
                    return Result(row=("generation-7", "READY", "sharadar"))
                return Result()

        class Engine:
            def connect(self):
                return nullcontext(Connection())

        def load_identity(_conn, *, as_of):
            observed["as_of"] = as_of
            return identity

        monkeypatch.setattr(publication, "pinned", pinned)
        monkeypatch.setattr(publication, "assert_coherent", lambda _conn: None)
        monkeypatch.setattr(
            loader, "load_window",
            lambda _conn, *, start, end: SimpleNamespace(bars_by_session={}))
        monkeypatch.setattr(sa, "create_engine", lambda _url: Engine())
        monkeypatch.setattr(BT, "load_identity", load_identity)
        monkeypatch.setattr(BT, "load_actions", lambda _conn, _start, _end: [])
        monkeypatch.setattr(BT, "load_sessions", lambda _conn, _start, _end: [])
        monkeypatch.setattr(
            BT, "split_ratios_from_actions",
            lambda _actions, _sessions: {})
        monkeypatch.setattr(
            BT, "dividends_from_actions",
            lambda _actions, _sessions: {})
        monkeypatch.setattr(
            BT, "load_bars",
            lambda _conn, _start, _end, **kwargs: (
                {} if kwargs["identity"] is identity else None))

        rep = CP.run(object(), start=W[0], end=W[1],
                     bt_database_url="postgresql+psycopg://unused")

        assert rep.agrees, rep.unavailable
        assert observed == {"as_of": W[1]}


class TestItStaysOutOfTheRUNTIMEImage:

    def test_it_does_not_live_in_the_sentinel_package(self):
        """The canonical module imports SQLAlchemy at module scope, and that is
        a retired-stack dependency. Putting this under `sentinel/` would place
        the retired platform's ORM in the image that liquidates a brokerage
        account — `test_image_layout` caught it when this file briefly did."""
        assert not (REPO / "sentinel" / "corpus_parity.py").exists()
        assert (ROOT / "tools" / "corpus_parity.py").exists()


class TestTheCanonicalPathIsIMPORTABLE:
    """The tool did `from app import wealth_core_replay`, and `app` is a
    top-level package INSIDE services/backtester — so being under /work was not
    enough and the real-window parity step would have died on
    ModuleNotFoundError the first time anyone ran it. Fail-closed rather than
    false-green, and still a stop at the last gate before the reseed."""

    def test_the_tool_puts_the_backtester_ON_the_path_itself(self):
        import sys
        CP._add_backtester_to_path()
        assert any(p.endswith("services/backtester") for p in sys.path), (
            "the tool relies entirely on an environment variable set by one "
            "specific image, so it fails anywhere else")

    def test_the_canonical_module_then_imports(self):
        CP._add_backtester_to_path()
        try:
            from app import wealth_core_replay  # noqa: F401
        except ModuleNotFoundError as exc:
            if "sqlalchemy" in str(exc):
                pytest.skip("sqlalchemy absent in this checkout (it is pinned "
                            "in the certification image, not the runtime one)")
            raise

    def test_the_TEST_image_also_sets_it_on_PYTHONPATH(self):
        """Belt and braces, and the belt is the one that matters at 8b: the
        tool is invoked as `python -m tools.corpus_parity` inside that image."""
        text = (REPO / "Dockerfile.sentinel-test").read_text().replace("\\\n", " ")
        assert "/work/services/backtester" in text


class TestTheCanonicalDSNIsExplicitAndUsesAnInstalledDriver:
    """`sa.create_engine("postgresql://...")` selects psycopg2.

    The certified closure carries psycopg 3 and nothing else, so a bare
    `postgresql://` fails with `No module named 'psycopg2'` — surfaced as "the
    canonical corpus could not be read", one indirection from the cause. The
    scheme has to name the driver the image actually has."""

    SCRIPT = REPO / "scripts" / "sentinel-certify.sh"

    def test_no_repository_known_dsn_or_password_is_a_fallback(self):
        body = self.SCRIPT.read_text()
        assert '[ -n "${BT_DATABASE_URL:-}" ] || fail' in body
        assert '-e BT_DATABASE_URL="${BT_DATABASE_URL}"' in body
        assert "postgresql+psycopg://btuser:btpass@" not in body
        assert "postgresql://sentinel:sentinel@" not in body

    def test_the_operator_is_told_to_name_psycopg3(self):
        body = self.SCRIPT.read_text()
        assert "`+psycopg` in an operator-supplied canonical DSN" in body

    def test_psycopg2_is_NOT_in_the_closure(self):
        """The premise. If it ever is, the bare scheme starts working and this
        class should be revisited rather than deleted — the failure it prevents
        would just move."""
        lock = REPO / "sentinel" / "requirements.lock"
        if not lock.exists():
            assert "psycopg[binary]" in \
                (REPO / "sentinel" / "requirements.txt").read_text()
            return
        names = [l.split("==")[0].lower() for l in lock.read_text().splitlines()
                 if "==" in l and not l.startswith("#")]
        assert "psycopg2" not in names and "psycopg2-binary" not in names
        assert "psycopg" in names

    def test_the_explicit_authority_is_passed_over_the_host_network(self):
        body = self.SCRIPT.read_text()
        i = body.index('-e BT_DATABASE_URL="${BT_DATABASE_URL}"')
        assert "--network host" in body[:i]


class TestTheStreamedCompareIsTheSameCOMPARISON:
    """Session-streamed rather than whole-window, for memory — and the verdict
    must not move an inch. Asserted on fixtures carrying every kind of finding
    at once: a field divergence, a bar only Sentinel has, and a bar only the
    canonical side has."""

    @staticmethod
    def bar(sid, **over):
        from types import SimpleNamespace
        d = dict(security_id=sid, ticker="AAA", raw_close=10.0, raw_open=9.0,
                 volume=100.0, split_ratio=1.0, dividend_per_share=0.0,
                 tradeable=True)
        d.update(over)
        return SimpleNamespace(**d)

    def frames(self):
        mine, theirs = {}, {}
        for s in ("2021-01-04", "2021-02-04", "2021-03-04"):
            mine[s] = [self.bar("S1"), self.bar("S2", raw_close=11.0),
                       self.bar("EXTRA")]
            theirs[s] = [self.bar("S1"), self.bar("S2"), self.bar("MISSING")]
        return mine, theirs

    def test_the_counts_are_exact(self):
        mine, theirs = self.frames()
        rep = CP.compare(mine, theirs, window=("2021-01-01", "2021-03-31"))
        assert rep.missing_count == 3          # one per session
        assert rep.extra_count == 3
        assert rep.field_divergences == {"raw_close": 3}
        assert rep.sentinel_bars == 9 and rep.canonical_bars == 9
        assert rep.agrees is False

    def test_a_bar_matches_only_WITHIN_its_session(self):
        """The property that makes streaming legitimate. If a security appears
        on different sessions on the two sides, that is two membership
        differences, not a match."""
        mine = {"2021-01-04": [self.bar("S1")]}
        theirs = {"2021-01-05": [self.bar("S1")]}
        rep = CP.compare(mine, theirs, window=("2021-01-01", "2021-01-31"))
        assert rep.missing_count == 1 and rep.extra_count == 1
        assert rep.field_divergences == {}

    def test_agreement_is_still_agreement(self):
        mine, _ = self.frames()
        rep = CP.compare(mine, mine, window=("2021-01-01", "2021-03-31"))
        assert rep.agrees is True
        assert rep.missing_count == rep.extra_count == 0


class TestTheREPORTIsBoundedWhenParityFailsCATASTROPHICALLY:
    """The failure case is the one that must stay bounded — it is the one that
    runs out of memory. A corpus seeded against the wrong universe puts every
    key in the membership lists, in a report whose JSON only ever prints their
    LENGTH."""

    @staticmethod
    def bar(sid):
        from types import SimpleNamespace
        return SimpleNamespace(security_id=sid, ticker="AAA", raw_close=1.0,
                               raw_open=1.0, volume=1.0, split_ratio=1.0,
                               dividend_per_share=0.0, tradeable=True)

    def total_disagreement(self, n=500):
        mine = {"2021-01-04": [self.bar(f"MINE{i}") for i in range(n)]}
        theirs = {"2021-01-04": [self.bar(f"THEIRS{i}") for i in range(n)]}
        return CP.compare(mine, theirs, window=("2021-01-01", "2021-01-31"),
                          max_report=25)

    def test_the_samples_are_capped(self):
        rep = self.total_disagreement()
        assert len(rep.missing_from_sentinel) == 25
        assert len(rep.extra_in_sentinel) == 25

    def test_but_the_counts_are_NOT(self):
        rep = self.total_disagreement()
        assert rep.missing_count == 500 and rep.extra_count == 500

    def test_the_json_reports_counts_and_labels_the_samples_as_samples(self):
        d = self.total_disagreement().to_dict()
        assert d["missing_from_sentinel"] == 500
        assert len(d["missing_sample"]) == 25
        assert d["agrees"] is False

    def test_the_cap_does_not_decide_the_VERDICT(self):
        """`agrees` reads the counts. Deciding it from a capped list would make
        a report that named nothing look like agreement."""
        rep = self.total_disagreement()
        rep.missing_from_sentinel.clear()
        rep.extra_in_sentinel.clear()
        assert rep.agrees is False


class TestWhyTheLOADERSAreNotChunked:
    """A REGRESSION TEST FOR A REJECTED DESIGN.

    An earlier fix for the OOM ran the whole canonical loader once per 92-day
    chunk. It is unsound, and the tests written for it could not see that
    because they compared already-normalised bars and never invoked a loader.
    Two pieces of loader state cross a date boundary:

    ```text
    snap_to_session   an ex-date is a CALENDAR date snapped forward to the next
                      SESSION. Given the chunk's own session list, an action in
                      the tail of a chunk snaps past its end and is DROPPED —
                      and the next chunk never loads that action, because its
                      date is before that chunk's start. The action vanishes
                      from both.

    load_bars `prev`  the derived split ratio reads the PREVIOUS observation
                      per security. The first bar of a chunk has none, so it
                      derives a different ratio than the same bar mid-window —
                      and `prev` is keyed on security with NO recency bound, so
                      a name that last printed weeks ago still carries its
                      previous close. No finite overlap can reconstruct it.
    ```

    These assertions pin the HAZARD, not the abandoned code: if either
    behaviour ever changes, the reasoning here has to be revisited before
    anyone reaches for chunking again."""

    def test_an_action_in_a_chunks_TAIL_is_dropped_by_that_chunk(self):
        """Friday-ending chunk, Saturday ex-date, Monday session."""
        whole = ["2021-01-08", "2021-01-11"]          # Fri, Mon
        chunk1 = ["2021-01-08"]                        # Fri only
        assert BT.snap_to_session("2021-01-09", whole) == "2021-01-11"
        assert BT.snap_to_session("2021-01-09", chunk1) is None, (
            "if this ever returns a session, re-derive the argument before "
            "reintroducing chunked loading")

    def test_and_the_NEXT_chunk_never_sees_that_action(self):
        """It filters actions by ITS OWN start date, which is after the
        ex-date. So neither chunk carries it — the action is lost, not
        double-counted, which is the harder failure to notice."""
        actions = [{"ticker": "AAA", "date": "2021-01-09", "action": "split",
                    "value": 2.0}]
        chunk2_sessions = ["2021-01-11", "2021-01-12"]
        chunk2_actions = [r for r in actions if r["date"] >= "2021-01-10"]
        assert chunk2_actions == []
        assert BT.split_ratios_from_actions(chunk2_actions,
                                            chunk2_sessions) == {}
        # Whole-window loading catches it.
        assert BT.split_ratios_from_actions(
            actions, ["2021-01-08"] + chunk2_sessions) == {
                ("AAA", "2021-01-11"): 2.0}

    def test_the_derived_split_ratio_depends_on_the_PREVIOUS_bar(self):
        """So the first bar of any chunk derives a different ratio."""
        mid_window = BT.split_ratio_from_domains(50.0, 100.0, 50.0, 50.0)
        chunk_start = BT.split_ratio_from_domains(None, None, 50.0, 50.0)
        assert mid_window != chunk_start, (
            "the derived ratio no longer reads previous state — the second "
            "reason chunked loading was rejected would no longer apply")

    def test_the_tool_exposes_no_chunking_entry_point(self):
        assert not hasattr(CP, "run_chunked")
        assert not hasattr(CP, "_chunks")

    def test_the_harness_does_not_pass_a_chunk_flag(self):
        body = (REPO / "scripts" / "sentinel-certify.sh").read_text()
        assert "--chunk-days" not in body
