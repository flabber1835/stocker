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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

from tools import corpus_parity as CP  # noqa: E402

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
        assert len(rep.examples) == 5 and rep.truncated == 35

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


class TestItStaysOutOfTheRUNTIMEImage:

    def test_it_does_not_live_in_the_sentinel_package(self):
        """The canonical module imports SQLAlchemy at module scope, and that is
        a retired-stack dependency. Putting this under `sentinel/` would place
        the retired platform's ORM in the image that liquidates a brokerage
        account — `test_image_layout` caught it when this file briefly did."""
        assert not (ROOT / "sentinel" / "corpus_parity.py").exists()
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
        text = (ROOT / "Dockerfile.sentinel-test").read_text().replace("\\\n", " ")
        assert "/work/services/backtester" in text
