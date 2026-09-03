from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).parents[2] / "backtester" / "mine_historical_metadata_candidates_v4_ownership_strict.py"
    spec = importlib.util.spec_from_file_location("strict", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_form4_generic_ticker_label_cannot_prove_issuer_identity() -> None:
    strict = _load()
    raw = """
CONFORMED SUBMISSION TYPE: 4
FILED AS OF DATE: 20180920
<ownershipDocument>
<issuer><issuerCik>0001140411</issuerCik><issuerTradingSymbol>OTHER</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0000105598</rptOwnerCik></reportingOwnerId></reportingOwner>
</ownershipDocument>
Trading Symbol: WFC
"""
    visible = strict.safe.v3.visible_text(raw)
    assert strict.ownership_strict_ticker_proofs(raw, visible, "WFC") == []


def test_form4_exact_issuer_trading_symbol_is_authority_candidate() -> None:
    strict = _load()
    raw = """
CONFORMED SUBMISSION TYPE: 4
FILED AS OF DATE: 20150303
<ownershipDocument>
<issuer><issuerCik>0001623595</issuerCik><issuerTradingSymbol>ATLS</issuerTradingSymbol></issuer>
</ownershipDocument>
"""
    visible = strict.safe.v3.visible_text(raw)
    proofs = strict.ownership_strict_ticker_proofs(raw, visible, "ATLS")
    assert proofs and proofs[0][0] == "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML"


def test_non_ownership_explicit_trading_symbol_label_remains_candidate() -> None:
    strict = _load()
    raw = """
CONFORMED SUBMISSION TYPE: 10-K
FILED AS OF DATE: 20150303
Trading Symbol: ABC
"""
    visible = strict.safe.v3.visible_text(raw)
    proofs = strict.ownership_strict_ticker_proofs(raw, visible, "ABC")
    assert proofs and proofs[0][0] == "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
