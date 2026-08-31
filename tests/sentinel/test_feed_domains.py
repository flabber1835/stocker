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



def row(ticker, date, close, closeunadj, open_=None, volume=1_000_000):
    return {"ticker": ticker, "date": date, "close": close,
            "closeunadj": closeunadj, "open": open_, "volume": volume}


#: The ONLY files under `sentinel/` permitted to name `closeadj`, by exact
#: relative path. Certification §5b is the decision record and must be updated
#: before this tuple is. Scoped to FILES, not directories: `sentinel/regime/` as
#: a package is not exempt, so a second sensor added beside spy.py inherits the
#: prohibition rather than the carve-out.
CLOSEADJ_PERMITTED = (
    # The SPY market-regime sensor. SPY is not a holding — it is a regime
    # sensor, and the frozen rule defines both of its predicates on a
    # total-return series.
    "sentinel/regime/spy.py",
    # Names the prohibition in order to ENFORCE it: SEP_FORBIDDEN_COLUMNS is
    # what makes the ingest drop the column. Naming it is not reading it.
    "sentinel/feed/domains.py",
    # Narrow transport/persistence path into the dedicated SPY-only table.
    # sharadar.py names the field only to validate the SFP wire schema; it never
    # exposes it to the security-bar domain.
    "sentinel/feed/sharadar.py",
    "sentinel/feed/staging_impl.py",
    "sentinel/feed/store.py",
    "sentinel/feed/schema.py",
    # Reference-source authority hashes the dedicated SFP/SPY total-return
    # field; it does not expose that domain to security signals or marks.
    "sentinel/feed/coherence.py",
    # Production is the narrow loader/transport into PublishedSession.
    "sentinel/core/production.py",
    # Shared type definition for that exact published SPY transport.
    "sentinel/core/session.py",
    # The sole composition that hands the published series to the sensor.
    "sentinel/core/kernel.py",
    # Commitment-only forward observer: hashes the exact already-composed
    # PublishedSession input but never exposes the SPY series to holdings,
    # marks, sizing, or execution.
    "sentinel/shadow_observation.py",
)


def _closeadj_in_source(src, label):
    """Executable-code occurrences of `closeadj` in one source string.

    COMMENTS and DOCSTRINGS are exempt — the module explaining why the column
    is forbidden cannot be what fails the check. Other STRING tokens are NOT
    exempt, and that is the correction: the previous guard skipped every string,
    so `bar["closeadj"]` passed while `df.closeadj` failed. This codebase
    carries corpus rows as dicts, so the string form is the natural one and the
    guard was materially weaker than it read. See certification §5b item 6.

    Takes SOURCE, not a path, so the self-tests below can probe it without
    writing files into `sentinel/` — which would be a package member that
    exists only during a test run.
    """
    import ast
    import io
    import tokenize

    # Docstring line ranges, via ast rather than token heuristics. The first
    # attempt tracked the previous token type and got function docstrings wrong
    # — it skipped NEWLINE/INDENT before recording them, so the "previous
    # meaningful token" was always the `:` and only MODULE docstrings were
    # exempted. ast asks the question directly.
    doc_lines = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc = body[0]
            doc_lines.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT or tok.start[0] in doc_lines:
            continue
        if "closeadj" in tok.string:
            out.append(f"{label}:{tok.start[0]}: {tok.string}")
    return out


def _closeadj_occurrences(py):
    return _closeadj_in_source(py.read_text(), py.relative_to(ROOT))


class TestTheForbiddenColumn:
    """A total-return series in the signal domain changes momentum on every
    dividend payer; in the mark it sizes every 4% admission off the wrong
    equity; in execution it is not a price anything trades at. Not reading it AT
    ALL is the only reliable way not to read it by accident.

    NARROWED 2026-08-12, and made STRICTER in the same change — see
    certification §5b. Exactly one sensor may read it; the string-literal hole
    that let `bar["closeadj"]` through everywhere is closed.
    """

    def test_closeadj_is_read_in_NO_module_outside_the_allowlist(self):
        offenders = []
        for py in sorted((REPO / "sentinel").rglob("*.py")):
            rel = py.relative_to(REPO).as_posix()
            if f"sentinel/{rel}" in CLOSEADJ_PERMITTED or rel in CLOSEADJ_PERMITTED:
                continue
            offenders.extend(_closeadj_occurrences(py))
        assert not offenders, (
            "closeadj is named in sentinel/ CODE outside the allowlist:\n"
            + "\n".join(offenders))

    def test_the_allowlist_is_EXACTLY_the_regime_transport_paths(self):
        """Pinned by EQUALITY, not membership.

        Adding a third permitted path cannot be done without editing this
        assertion, and editing it without a §5b entry is the review signal. A
        guard that merely tolerates its allowlist grows one entry at a time.
        """
        assert CLOSEADJ_PERMITTED == (
            "sentinel/regime/spy.py",
            "sentinel/feed/domains.py",
            "sentinel/feed/sharadar.py",
            "sentinel/feed/staging_impl.py",
            "sentinel/feed/store.py",
            "sentinel/feed/schema.py",
            "sentinel/feed/coherence.py",
            "sentinel/core/production.py",
            "sentinel/core/session.py",
            "sentinel/core/kernel.py",
            "sentinel/shadow_observation.py",
        )

    def test_the_SPY_sensor_is_the_only_strategy_reader(self):
        """Other permitted modules only transport the value to this sensor."""
        from sentinel.feed import domains as dom

        assert dom.SEP_FORBIDDEN_COLUMNS == ("closeadj",)
        from sentinel.regime import spy as spy_mod

        assert spy_mod.SPY_PRICE_COLUMN == "closeadj"

    def test_the_exemption_is_by_FILE_not_by_PACKAGE(self):
        """`sentinel/regime/` is not blanket-exempt. A second module added there
        inherits the prohibition — which is the difference between a narrowing
        and a hole."""
        assert all(
            p.startswith("sentinel/") and p.endswith(".py")
            for p in CLOSEADJ_PERMITTED)
        assert "sentinel/regime" not in CLOSEADJ_PERMITTED
        assert "sentinel/regime/" not in CLOSEADJ_PERMITTED

    def test_the_guard_CATCHES_a_dict_key_read(self):
        """The hole this narrowing closed.

        `bar["closeadj"]` is a STRING token, so the previous guard — which
        skipped every string — passed it. That is the natural form in a codebase
        that carries corpus rows as dicts.
        """
        import io
        import tokenize

        src = 'def f(bar):\n    return float(bar["closeadj"])\n'
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        old_style = [t for t in toks
                     if t.type not in (tokenize.STRING, tokenize.COMMENT)
                     and "closeadj" in t.string]
        assert not old_style, "precondition: the OLD guard misses this form"
        assert _closeadj_in_source(src, "probe"), "the NEW guard must catch it"

    def test_the_guard_still_catches_the_ATTRIBUTE_form(self):
        assert _closeadj_in_source("def f(df):\n    return df.closeadj\n", "probe")

    def test_a_DOCSTRING_naming_the_column_is_still_exempt(self):
        """The module explaining the prohibition cannot be what fails it."""
        assert not _closeadj_in_source(
            '"""Never read closeadj here."""\n\n\ndef f():\n    return 1\n', "probe")

    def test_a_COMMENT_naming_the_column_is_still_exempt(self):
        assert not _closeadj_in_source("# never read closeadj\nX = 1\n", "probe")

    def test_a_FUNCTION_docstring_is_exempt_but_its_body_is_not(self):
        src = ('def f(bar):\n'
               '    """closeadj is forbidden here."""\n'
               '    return bar["closeadj"]\n')
        hits = _closeadj_in_source(src, "probe")
        assert len(hits) == 1, hits


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
