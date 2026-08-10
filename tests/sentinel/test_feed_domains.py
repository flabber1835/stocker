"""The SEP -> domain mapping, which is silent when wrong.

Every test here is a documented failure mode from the backtester's loader, moved
to the code that will run in production. The mapping is a deliberate
re-implementation — Sentinel may not import a retired Stocker service — so the
duplication is pinned against the canonical version rather than trusted.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get('SENTINEL_REPO_ROOT') or ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.feed import domains as D  # noqa: E402

CANONICAL = ROOT / "services" / "backtester" / "app" / "wealth_core_replay.py"


def row(ticker, date, close, closeunadj, open_=None, volume=1_000_000):
    return {"ticker": ticker, "date": date, "close": close,
            "closeunadj": closeunadj, "open": open_, "volume": volume}


class TestTheForbiddenColumn:
    def test_closeadj_is_never_read(self):
        """A total-return series in the signal domain changes momentum on every
        dividend payer; in the mark it sizes every 4% admission off the wrong
        equity. Not reading it AT ALL is the only reliable way not to read it by
        accident."""
        import io
        import tokenize

        # TOKENIZED, not line-prefixed. The first version scanned raw lines and
        # flagged its own docstring — the module explaining why the column is
        # forbidden cannot be what fails the check. Strings and comments are
        # excluded, which also exempts SEP_FORBIDDEN_COLUMNS = ("closeadj",):
        # naming the prohibition is not violating it. What remains is executable
        # code, where the name could only appear as a real column access.
        offenders = []
        for py in (REPO / "sentinel").rglob("*.py"):
            src = py.read_text()
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type in (tokenize.STRING, tokenize.COMMENT):
                    continue
                if "closeadj" in tok.string:
                    offenders.append(f"{py.relative_to(ROOT)}:{tok.start[0]}: {tok.string}")
        assert not offenders, "closeadj is read in sentinel/ CODE:\n" + "\n".join(offenders)


class TestSplitRatio:
    def test_a_2_for_1_gives_ratio_2_not_one_half(self):
        """before/after, NOT after/before. The reversed form points the share
        count the wrong way and HALVES a position on a 2:1."""
        # pre-split rows carry closeunadj/close == 2; post-split rows carry 1
        assert D.split_ratio_from_domains(50.0, 100.0, 50.0, 50.0) == 2.0

    def test_a_reverse_split_gives_the_reciprocal(self):
        assert D.split_ratio_from_domains(100.0, 10.0, 100.0, 100.0) == pytest.approx(0.1)

    def test_vendor_rounding_is_NOT_a_split(self):
        """A spurious 1.003 would corrupt a share count silently and forever."""
        assert D.split_ratio_from_domains(100.0, 100.3, 100.0, 100.0) == 1.0

    def test_a_near_integral_ratio_is_SNAPPED(self):
        """1.9997 must not become a share count nobody can reconcile."""
        assert D.split_ratio_from_domains(50.0, 99.985, 50.0, 50.0) == 2.0

    def test_missing_or_nonpositive_inputs_mean_no_split(self):
        assert D.split_ratio_from_domains(None, 100.0, 50.0, 50.0) == 1.0
        assert D.split_ratio_from_domains(0.0, 100.0, 50.0, 50.0) == 1.0

    def test_it_matches_the_CANONICAL_implementation(self):
        """Pinned against the backtester's loader on the same inputs. The two are
        separate code by necessity; they must not become separate behaviour."""
        import importlib.util
        src = CANONICAL.read_text()
        start = src.index("def split_ratio_from_domains")
        end = src.index("# ── SHARADAR/ACTIONS", start)
        ns: dict = {}
        exec(compile(src[start:end], str(CANONICAL), "exec"), ns)
        canonical = ns["split_ratio_from_domains"]
        cases = [
            (50.0, 100.0, 50.0, 50.0), (100.0, 10.0, 100.0, 100.0),
            (100.0, 100.3, 100.0, 100.0), (50.0, 99.985, 50.0, 50.0),
            (None, 100.0, 50.0, 50.0), (12.5, 25.0, 12.5, 12.5),
            (33.0, 33.0, 33.0, 33.0), (10.0, 70.0, 10.0, 10.0),
        ]
        for c in cases:
            assert D.split_ratio_from_domains(*c) == canonical(*c), f"drift at {c}"


class TestNormalisation:
    def test_the_open_is_SCALED_into_the_as_traded_domain(self):
        """SEP.open is split-adjusted like close. Passing it through fills orders
        in one domain and marks the position in another."""
        rep = D.NormalisationReport()
        bars = list(D.normalise_sep_rows(
            [row("AAA", "2024-01-02", close=50.0, closeunadj=100.0, open_=49.0)],
            report=rep))
        assert bars[0].vendor.raw_open == pytest.approx(98.0)   # 49 * (100/50)
        assert bars[0].vendor.raw_close == 100.0         # as-traded, untouched
        assert bars[0].close_signal == 50.0              # SEP.close, CARRIED

    def test_a_bar_with_no_as_traded_close_is_DROPPED_not_substituted(self):
        rep = D.NormalisationReport()
        bars = list(D.normalise_sep_rows(
            [row("AAA", "2024-01-02", close=50.0, closeunadj=None)], report=rep))
        assert bars == []
        assert rep.dropped_no_raw_close == 1

    def test_an_unresolvable_identity_is_DROPPED_not_keyed_on_the_ticker(self):
        """A ticker fallback re-introduces the reuse splice on exactly the
        securities whose identity is doubtful."""
        rep = D.NormalisationReport()
        bars = list(D.normalise_sep_rows(
            [row("AAA", "2024-01-02", 50.0, 100.0)],
            resolve_identity=lambda t, s: None, report=rep))
        assert bars == []
        assert rep.dropped_no_identity == 1

    def test_the_split_ratio_follows_the_SECURITY_not_the_symbol(self):
        """Keying the previous observation on the ticker resets it at a rename
        and manufactures a spurious ratio on that session."""
        rows = [row("OLD", "2024-01-02", 50.0, 100.0),
                row("NEW", "2024-01-03", 50.0, 100.0)]
        bars = list(D.normalise_sep_rows(rows, resolve_identity=lambda t, s: "SEC1"))
        assert [b.vendor.split_ratio for b in bars] == [1.0, 1.0]

    def test_dividends_are_attached_per_ticker_session(self):
        bars = list(D.normalise_sep_rows(
            [row("AAA", "2024-01-02", 50.0, 50.0)],
            dividends={("AAA", "2024-01-02"): 0.75}))
        assert bars[0].vendor.dividend_per_share == 0.75

    def test_both_column_spellings_are_accepted(self):
        """Sharadar's raw export says `closeunadj`; bt_prices stores it as
        `close_unadjusted`. Reading one spelling would silently drop every row
        from the other source."""
        for key in ("closeunadj", "close_unadjusted"):
            r = {"ticker": "AAA", "date": "2024-01-02", "close": 50.0,
                 "open": 50.0, "volume": 1, key: 100.0}
            assert list(D.normalise_sep_rows([r]))[0].vendor.raw_close == 100.0


class TestTheCoverageRefusal:
    def test_a_mostly_empty_raw_domain_REFUSES(self):
        rep = D.NormalisationReport(rows=1000, dropped_no_raw_close=500)
        with pytest.raises(D.RawPriceDomainUnavailable, match="closeunadj"):
            D.assert_raw_price_domain(rep)

    def test_ordinary_gaps_do_NOT_refuse(self):
        rep = D.NormalisationReport(rows=1000, dropped_no_raw_close=20)
        assert D.assert_raw_price_domain(rep) == pytest.approx(0.98)

    def test_an_empty_feed_does_not_divide_by_zero(self):
        assert D.assert_raw_price_domain(D.NormalisationReport()) == 0.0
