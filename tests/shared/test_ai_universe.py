"""Integrity tests for the hardcoded AI-buildout theme universe.

This is the static theme set powering the Screener's "Theme" filter (via api
/rankings/theme). It will be replaced by a dynamic Anthropic-API-generated universe
later; until then these tests guard the shape the api endpoint and dashboard assume.
"""
import re

from stock_strategy_shared.ai_universe import (
    AI_BUILDOUT_AS_OF,
    AI_BUILDOUT_SET,
    AI_BUILDOUT_UNIVERSE,
    AI_THEME_NAMES,
    ai_theme_members,
)

# Demand-side hyperscalers are deliberately NOT part of the picks-and-shovels set.
_EXCLUDED_DEMAND_SIDE = {"MSFT", "AMZN", "GOOGL", "GOOG", "META", "ORCL"}


def test_universe_has_108_names():
    assert len(AI_BUILDOUT_UNIVERSE) == 108


def test_universe_is_deduplicated():
    assert len(set(AI_BUILDOUT_UNIVERSE)) == len(AI_BUILDOUT_UNIVERSE)
    assert len(AI_BUILDOUT_SET) == len(AI_BUILDOUT_UNIVERSE)


def test_tickers_are_uppercase_us_symbols():
    # US-listed equity symbols: 1-5 uppercase letters, optional single dot class.
    pat = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
    bad = [t for t in AI_BUILDOUT_UNIVERSE if not pat.match(t)]
    assert not bad, f"non-US-symbol-looking tickers: {bad}"


def test_excludes_demand_side_hyperscalers():
    overlap = _EXCLUDED_DEMAND_SIDE & AI_BUILDOUT_SET
    assert not overlap, f"hyperscaler/demand-side names must be excluded: {overlap}"


def test_contains_known_core_picks_and_shovels():
    # Spot-check a few canonical names across layers so an accidental gutting fails.
    for t in ("NVDA", "AVGO", "MU", "ANET", "VRT", "ETN", "CEG", "OKLO", "EQIX", "PWR"):
        assert t in AI_BUILDOUT_SET, t


def test_as_of_is_iso_date():
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", AI_BUILDOUT_AS_OF)


def test_ai_theme_names_resolve_to_buildout_set():
    for name in AI_THEME_NAMES:
        assert ai_theme_members(name) is AI_BUILDOUT_SET


def test_non_ai_theme_returns_none():
    # A legacy/other theme name is NOT the buildout set → callers fall back.
    for name in ("value", "", "ai", "infra", "quality_core_v1"):
        assert ai_theme_members(name) is None


def test_ai_theme_names_is_the_documented_set():
    # Single source of truth consumed by BOTH the portfolio-builder (overlay
    # membership) and the llm-vetter (theme coverage). Both bind this shared
    # frozenset directly, so they cannot drift; this pins its contents.
    assert AI_THEME_NAMES == frozenset({"ai_infra", "ai_buildout"})
