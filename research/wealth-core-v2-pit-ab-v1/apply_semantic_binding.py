#!/usr/bin/env python3
"""Bind the corrected entry-funding semantics to WealthCoreConfig identity.

The branch deliberately changes economics.  A result produced after this change
must not carry the same config hash as the legacy cash-clipped admission rule.
There is exactly one accepted profile here; this is versioning, not a tunable
strategy choice.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "shared/stock_strategy_shared/wealth_core/engine.py"
TEST = ROOT / "tests/wealth_core/test_slot_funding.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if new in text:
        return
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{path}: expected exactly one anchor, found {n}")
    path.write_text(text.replace(old, new, 1))


replace_once(
    ENGINE,
    "@dataclass(frozen=True)\nclass WealthCoreConfig:\n",
    'ENTRY_FUNDING_PROFILE = "full_whole_share_target_v1"\n\n\n'
    "@dataclass(frozen=True)\nclass WealthCoreConfig:\n",
)
replace_once(
    ENGINE,
    "    minimum_leadership_population: int = 25\n"
    "    # The ORDERING PROFILE, in the config hash. A run scored under one profile\n",
    "    minimum_leadership_population: int = 25\n"
    "    # Foundational admission economics.  This is intentionally a single\n"
    "    # accepted value, not a strategy knob: it prevents a corrected run from\n"
    "    # carrying the same config identity as the superseded cash-clipped rule.\n"
    "    entry_funding_profile: str = ENTRY_FUNDING_PROFILE\n"
    "    # The ORDERING PROFILE, in the config hash. A run scored under one profile\n",
)
replace_once(
    ENGINE,
    "    def __post_init__(self) -> None:\n"
    "        if self.dividend_settlement_lag_sessions < 0:\n",
    "    def __post_init__(self) -> None:\n"
    "        if self.entry_funding_profile != ENTRY_FUNDING_PROFILE:\n"
    "            raise ValueError(\n"
    "                f\"unknown entry_funding_profile {self.entry_funding_profile!r}; \"\n"
    "                f\"the corrected kernel accepts only {ENTRY_FUNDING_PROFILE!r}. \"\n"
    "                f\"Legacy cash-clipped slot funding is deliberately not a \"\n"
    "                f\"compatibility mode.\")\n"
    "        if self.dividend_settlement_lag_sessions < 0:\n",
)
replace_once(
    ENGINE,
    '            "minimum_leadership_population": self.minimum_leadership_population,\n'
    '            "ordering_profile": self.ordering_profile,\n',
    '            "minimum_leadership_population": self.minimum_leadership_population,\n'
    '            "entry_funding_profile": self.entry_funding_profile,\n'
    '            "ordering_profile": self.ordering_profile,\n',
)

text = TEST.read_text()
marker = "def test_whole_shares_is_full_target_or_zero_never_cash_clipped():\n"
if "test_corrected_funding_semantics_are_bound_to_config_identity" not in text:
    addition = '''def test_corrected_funding_semantics_are_bound_to_config_identity():\n    cfg = WealthCoreConfig()\n    assert cfg.entry_funding_profile == "full_whole_share_target_v1"\n    with pytest.raises(ValueError, match="Legacy cash-clipped slot funding"):\n        WealthCoreConfig(entry_funding_profile="legacy_cash_clipped_v0")\n\n    # The profile is identity-bearing: altering the frozen object only for this\n    # hash falsifier must move the config hash.  Production construction cannot\n    # do this because the dataclass is frozen and __post_init__ refuses it.\n    before = cfg.config_hash()\n    object.__setattr__(cfg, "entry_funding_profile", "falsifier-only")\n    assert cfg.config_hash() != before\n\n\n'''
    if marker not in text:
        raise RuntimeError("test_slot_funding.py: insertion marker missing")
    TEST.write_text(text.replace(marker, addition + marker, 1))

print("bound corrected slot-funding semantics to config identity")
