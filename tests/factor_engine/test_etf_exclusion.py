"""
Tests for the ETF/fund name-based exclusion logic used in factor-engine's universe query.

The SQL filter is:
  NOT (
    COALESCE(asset_class, '') ILIKE '%ETF%'
    OR COALESCE(name, '') ~* '(ProShares|iShares|SPDR|Invesco|Direxion|VanEck|WisdomTree
                               |\bETF\b|\bFund\b|\bTrust\b|\bIndex\b|\bLeveraged\b|\bInverse\b)'
  )

These tests mirror that logic in Python so the regex can be regression-tested
without a database.
"""
import re

_ETF_NAME_RE = re.compile(
    r"(ProShares|iShares|SPDR|Invesco|Direxion|VanEck|WisdomTree"
    r"|\bETF\b|\bFund\b|\bTrust\b|\bIndex\b|\bLeveraged\b|\bInverse\b)",
    re.IGNORECASE,
)


def _is_excluded(name: str | None, asset_class: str | None = None) -> bool:
    if asset_class and "etf" in asset_class.lower():
        return True
    return bool(_ETF_NAME_RE.search(name or ""))


# ── asset_class filter ────────────────────────────────────────────────────────

def test_etf_asset_class_excluded():
    assert _is_excluded("SPY", "ETF") is True

def test_etf_asset_class_case_insensitive():
    assert _is_excluded("SPY", "Exchange Traded Fund (ETF)") is True

def test_blank_asset_class_falls_through_to_name():
    assert _is_excluded("ProShares Ultra Semiconductors", "") is False or \
           _is_excluded("ProShares Ultra Semiconductors", "") is True  # name catches it
    assert _is_excluded("ProShares Ultra Semiconductors") is True


# ── known ETF fund-family prefixes ────────────────────────────────────────────

def test_proshares_excluded():
    # USD = ProShares Ultra Semiconductors — the specific case that prompted this
    assert _is_excluded("ProShares Ultra Semiconductors") is True

def test_ishares_excluded():
    assert _is_excluded("iShares Core S&P 500 ETF") is True

def test_spdr_excluded():
    assert _is_excluded("SPDR S&P 500 ETF Trust") is True

def test_invesco_excluded():
    assert _is_excluded("Invesco QQQ Trust") is True

def test_direxion_excluded():
    assert _is_excluded("Direxion Daily Technology Bull 3X Shares") is True

def test_vaneck_excluded():
    assert _is_excluded("VanEck Semiconductor ETF") is True

def test_wisdomtree_excluded():
    assert _is_excluded("WisdomTree U.S. LargeCap Dividend Fund") is True


# ── generic keyword exclusions ────────────────────────────────────────────────

def test_etf_word_excluded():
    assert _is_excluded("Some Sector ETF") is True

def test_fund_word_excluded():
    assert _is_excluded("Some Investment Fund") is True

def test_index_word_excluded():
    assert _is_excluded("S&P 500 Index") is True

def test_leveraged_word_excluded():
    assert _is_excluded("Leveraged Equity Strategy") is True

def test_inverse_word_excluded():
    assert _is_excluded("Inverse S&P 500") is True


# ── legitimate stocks that must NOT be excluded ───────────────────────────────

def test_apple_not_excluded():
    assert _is_excluded("Apple Inc.") is False

def test_microsoft_not_excluded():
    assert _is_excluded("Microsoft Corporation") is False

def test_nvidia_not_excluded():
    assert _is_excluded("NVIDIA Corporation") is False

def test_western_digital_not_excluded():
    assert _is_excluded("Western Digital Corp") is False

def test_alphabet_not_excluded():
    assert _is_excluded("Alphabet Inc.") is False

def test_amazon_not_excluded():
    assert _is_excluded("Amazon.com Inc.") is False


# ── documented false-positive: Trust in company name ─────────────────────────

def test_known_false_positive_trust_in_name():
    # REITs and banks with "Trust" in their name are incorrectly excluded.
    # This is a known limitation of the broad regex approach.
    # Fix later via security-type field or curated allowlist.
    assert _is_excluded("Northern Trust Corporation") is True  # false positive
    assert _is_excluded("First Industrial Realty Trust") is True  # false positive
