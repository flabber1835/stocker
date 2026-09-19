from __future__ import annotations

import pytest

from research.synthetic_market_lab.config import ActionConfig, CompanyConfig, DisclosureConfig, WorldConfig
from research.synthetic_market_lab.generator import generate_world


@pytest.fixture(scope="session")
def adversarial_world(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-world") / "world"
    cfg = WorldConfig(
        seed=884422,
        years=1,
        companies=CompanyConfig(company_count=32, initially_listed_fraction=0.65),
        actions=ActionConfig(
            annual_bankruptcy_base_probability=0.35,
            annual_acquisition_probability=0.22,
            annual_ticker_change_probability=0.12,
            annual_identifier_change_probability=0.12,
            annual_issuance_probability=0.20,
            annual_buyback_probability=0.20,
            dividend_quarterly_probability=0.8,
        ),
        disclosures=DisclosureConfig(restatement_probability=0.50, missing_report_probability=0.0),
    )
    manifest = generate_world(cfg, path)
    return path, cfg, manifest
