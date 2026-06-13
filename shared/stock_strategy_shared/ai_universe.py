"""Hardcoded AI-buildout ("picks-and-shovels") ticker universe.

This is the CURRENT, STATIC theme universe — the physical/enabling supply chain of
the AI data-center buildout (compute, memory, networking/optical, servers, REITs,
cooling, power & electrical, generation/utilities, nuclear/SMR/uranium, and
construction/EPC). It deliberately EXCLUDES the demand-side hyperscaler sleeve
(MSFT/AMZN/GOOGL/META/ORCL) and pure AI-software/application names.

Provenance: compiled 2026-06-13 from current ETF holdings (SMH, SOXX, SRVR, DTCR,
GRID, XLU/VPU, NLR, NUKZ, URNM, URA) cross-referenced with recent analyst notes and
data-center supply-chain maps. US-listed only (the equity universe is built from AV
LISTING_STATUS = US exchanges, so foreign/ADR-only names — TSM, ASML, SK Hynix,
Samsung, the Taipei ODMs, Schneider/ABB/Siemens, etc. — are intentionally omitted;
they are tracked in the research notes, not here).

DESIGN NOTE: this list is hardcoded ON PURPOSE for now. It is the single source of
truth consumed by the api's /rankings/theme endpoint (which powers the Screener's
"Theme" filter). It will be replaced LATER by a dynamic, Anthropic-API-generated
universe; keeping it here behind one import means that swap touches one module.
"""
from __future__ import annotations

# As-of date the universe was researched/compiled. Surfaced in the API response so
# the dashboard can show when the (static) universe was last refreshed.
AI_BUILDOUT_AS_OF = "2026-06-13"

# 108 US-listed names, grouped by buildout layer (grouping is documentation only;
# the consumer treats this as one flat set). Each ticker appears exactly once,
# assigned to its best-fit primary layer.
AI_BUILDOUT_UNIVERSE: tuple[str, ...] = (
    # 1. Compute & accelerators + semicap
    "NVDA", "AMD", "AVGO", "MRVL", "AMAT", "LRCX", "KLAC", "TER", "NVMI", "ENTG",
    "MPWR", "CDNS", "SNPS", "INTC", "QCOM",
    # 2. Memory & storage
    "MU", "SNDK", "WDC", "STX",
    # 3. Networking & optical / interconnect
    "ANET", "ALAB", "CRDO", "COHR", "LITE", "AAOI", "FN", "CIEN", "APH", "CLS",
    "MTSI", "GLW", "TEL", "SMTC", "CSCO", "JNPR", "POET",
    # 4. Servers / ODMs
    "SMCI", "DELL", "HPE",
    # 5. Data-center REITs & colocation / neoclouds
    "EQIX", "DLR", "APLD", "CRWV", "IREN", "GDS", "IRM", "AMT", "SBAC", "CCI", "DBRG",
    # 6. Cooling & thermal
    "MOD", "TT", "JCI", "CARR",
    # 7. Power & electrical equipment
    "VRT", "ETN", "GEV", "POWL", "NVT", "HUBB", "NVTS", "POWI", "WOLF", "ON",
    "TXN", "AYI",
    # 8. Power generation & utilities
    "CEG", "VST", "TLN", "NRG", "NEE", "D", "AEP", "SO", "SRE", "EXC", "ETR",
    "XEL", "PCG", "DUK", "PEG",
    # 9. Nuclear / SMR / uranium
    "OKLO", "SMR", "NNE", "NKLR", "LEU", "BWXT", "CCJ", "UEC", "UUUU", "NXE",
    "DNN", "URG", "EU", "UROY", "CW",
    # 10. Construction / engineering / EPC
    "PWR", "EME", "FIX", "STRL", "FLR", "J", "ACM", "IESC", "MTZ", "MYRG", "LMB",
    "PRIM",
)

# Frozenset for O(1) membership tests by consumers.
AI_BUILDOUT_SET = frozenset(AI_BUILDOUT_UNIVERSE)
