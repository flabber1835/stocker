"""
Tests for the LLM vetter rank prompt wording.

Root cause of the "B = Barrick Gold, rank 1" bug: the prompt said
"Rank: 2 of 50" which LLMs read as "position 2 in a 50-stock portfolio",
causing them to believe the stock was already held.

After the fix the prompt must:
  - Show universe rank as "Universe rank: #N (out of all ranked stocks ...)"
  - Show vetter batch as "Vetter batch: N top-ranked candidates reviewed today"
  - NEVER combine both numbers in the form "N of M" on the same line
  - Correctly set "ALREADY HELD" vs "CANDIDATE FOR ENTRY" based on in_portfolio
"""
from __future__ import annotations
import os as _os, sys as _sys

_VETTER_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "llm-vetter"))
_app = _sys.modules.get("app")
if _app is None or _VETTER_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _sys.path[:1] != [_VETTER_PATH]:
        _sys.path.insert(0, _VETTER_PATH)

import re
from app.vetter import _format_ticker_message


def _prompt(
    ticker: str = "AAPL",
    rank: int | None = None,
    total_candidates: int | None = None,
    in_portfolio: bool = False,
    composite_score: float | None = None,
    factor_scores: dict | None = None,
) -> str:
    return _format_ticker_message(
        ticker=ticker,
        news=[],
        earnings_date=None,
        tavily_articles=[],
        today="2026-05-25",
        entry_rank=25,
        exit_rank=40,
        confirmation_days=3,
        risk_horizon_days=90,
        rank=rank,
        total_candidates=total_candidates,
        in_portfolio=in_portfolio,
        composite_score=composite_score,
        factor_scores=factor_scores,
    )


class TestRankPromptWording:
    def test_universe_rank_label_present(self):
        prompt = _prompt(ticker="AAPL", rank=2, total_candidates=50)
        assert "Universe rank:" in prompt, (
            "Prompt must contain 'Universe rank:' label"
        )

    def test_universe_rank_number_shown(self):
        prompt = _prompt(ticker="AAPL", rank=2, total_candidates=50)
        assert "#2" in prompt or "rank: #2" in prompt.lower(), (
            f"Prompt must show the rank number with '#' prefix, got:\n{prompt}"
        )

    def test_vetter_batch_label_present_when_candidates_given(self):
        prompt = _prompt(ticker="AAPL", rank=2, total_candidates=50)
        assert "Vetter batch:" in prompt, (
            "Prompt must contain 'Vetter batch:' label when total_candidates is provided"
        )

    def test_vetter_batch_count_shown(self):
        prompt = _prompt(ticker="AAPL", rank=2, total_candidates=60)
        assert "60" in prompt, "Vetter batch count (60) must appear in prompt"

    def test_ambiguous_combined_form_absent(self):
        """The old 'Rank: 2 of 50' pattern must not appear."""
        prompt = _prompt(ticker="B", rank=1, total_candidates=50)
        # Match "Rank: N of M" on a single line (the old format)
        bad_pattern = re.compile(r"Rank:\s*\d+\s+of\s+\d+", re.IGNORECASE)
        assert not bad_pattern.search(prompt), (
            f"Prompt contains ambiguous 'Rank: N of M' form which LLMs misread as portfolio position:\n{prompt}"
        )

    def test_universe_rank_mentions_investable_universe(self):
        prompt = _prompt(ticker="AAPL", rank=5, total_candidates=50)
        # The universe rank line should clarify it's the full universe, not the vetter batch
        assert "universe" in prompt.lower(), (
            "Rank line must mention 'universe' to distinguish from portfolio position"
        )

    def test_no_rank_when_none(self):
        prompt = _prompt(ticker="AAPL", rank=None, total_candidates=None)
        assert "Universe rank:" not in prompt
        assert "Vetter batch:" not in prompt

    def test_no_vetter_batch_when_total_candidates_none(self):
        prompt = _prompt(ticker="AAPL", rank=3, total_candidates=None)
        assert "Vetter batch:" not in prompt
        # But universe rank should still show
        assert "Universe rank:" in prompt

    def test_rank_1_does_not_say_already_held(self):
        """Rank #1 non-held stock must show CANDIDATE, not ALREADY HELD."""
        prompt = _prompt(ticker="B", rank=1, total_candidates=50, in_portfolio=False)
        assert "CANDIDATE FOR ENTRY" in prompt
        assert "ALREADY HELD" not in prompt

    def test_held_stock_says_already_held(self):
        prompt = _prompt(ticker="AAPL", rank=3, total_candidates=50, in_portfolio=True)
        assert "ALREADY HELD" in prompt
        assert "CANDIDATE FOR ENTRY" not in prompt

    def test_rank_and_batch_on_separate_lines(self):
        """Universe rank and vetter batch must NOT be on the same line."""
        prompt = _prompt(ticker="AAPL", rank=2, total_candidates=50)
        for line in prompt.splitlines():
            has_universe_rank = "Universe rank:" in line
            has_vetter_batch = "Vetter batch:" in line
            assert not (has_universe_rank and has_vetter_batch), (
                f"Universe rank and Vetter batch appear on the same line — would confuse LLM:\n{line}"
            )

    def test_composite_score_shown_when_provided(self):
        prompt = _prompt(ticker="AAPL", rank=2, composite_score=0.8234)
        assert "0.8234" in prompt

    def test_factor_scores_shown_when_provided(self):
        prompt = _prompt(ticker="AAPL", rank=2, factor_scores={"quality": 0.75, "momentum": 0.60})
        assert "quality" in prompt
        assert "momentum" in prompt

    def test_ticker_always_present(self):
        prompt = _prompt(ticker="XYZ", rank=10)
        assert "XYZ" in prompt

    def test_entry_exit_rank_present(self):
        prompt = _prompt(ticker="AAPL")
        assert "25" in prompt   # entry_rank
        assert "40" in prompt   # exit_rank
