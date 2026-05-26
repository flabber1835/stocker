"""
1-year simulation: bull→bear→bull with 5 named stocks + 59 small caps.

Named holdings (initial positions totalling ~$90k):
  AAPL  Apple Inc                $15,000
  SNDK  Sandisk Corp             $10,000
  MU    Micron Technology Inc    $20,000
  KEYS  Keysight Technologies    $15,000
  V     Visa Inc                 $30,000
  ─────────────────────────────────────
  Cash                           $10,000
  Total                         $100,000

Small caps: 20 sibling pairs (A/B share classes, same company name) = 40 tickers,
plus 19 individual small-cap tickers = 59 small caps total.

Sibling pairs let us observe whether the vetter's sibling-dedup logic excludes
both share classes when one is flagged.

Universe size: 110 (64 extra + 46 generated random tickers to meet the ≥100 guard).
"""

from datetime import date

from tests.harness.harness.scenario import InitialPosition, RegimeChange, Scenario

# ─── Named tickers ─────────────────────────────────────────────────────────

_NAMED = [
    {"ticker": "AAPL", "name": "Apple Inc",                   "sector": "Information Technology", "exchange": "NASDAQ"},
    {"ticker": "SNDK", "name": "Sandisk Corp",                "sector": "Information Technology", "exchange": "NASDAQ"},
    {"ticker": "MU",   "name": "Micron Technology Inc",       "sector": "Information Technology", "exchange": "NASDAQ"},
    {"ticker": "KEYS", "name": "Keysight Technologies Inc",   "sector": "Information Technology", "exchange": "NYSE"},
    {"ticker": "V",    "name": "Visa Inc",                    "sector": "Financials",             "exchange": "NYSE"},
]

# ─── Sibling pairs (A/B share classes, same company name) ─────────────────
# Format: (tickerA, tickerB, company_name, sector)

_SIBLING_PAIRS = [
    # Technology
    ("PIXLA", "PIXLB", "Pixel Systems Inc",       "Information Technology"),
    ("NXDA",  "NXDB",  "NexData Corp",            "Information Technology"),
    ("VLXA",  "VLXB",  "Velix Technologies Inc",  "Information Technology"),
    ("DSTRA", "DSTRB", "DataStream Inc",           "Information Technology"),
    ("RTXA",  "RTXB",  "RetailTech Corp",          "Consumer Discretionary"),
    # Health Care
    ("BCHA",  "BCHB",  "BioCharm Pharma Inc",     "Health Care"),
    ("MEBA",  "MEBB",  "MedBridge Inc",            "Health Care"),
    ("GNXA",  "GNXB",  "GenX Pharma Corp",         "Health Care"),
    ("VXRA",  "VXRB",  "VaxR Biologics Inc",       "Health Care"),
    ("PTCA",  "PTCB",  "ProTechClin Corp",          "Health Care"),
    # Financials
    ("FNXA",  "FNXB",  "FinEx Capital Corp",       "Financials"),
    ("CVBA",  "CVBB",  "CapVault Holdings Inc",    "Financials"),
    ("BRXA",  "BRXB",  "BrixFin Holdings Inc",     "Financials"),
    ("LNDA",  "LNDB",  "LendCo Corp",              "Financials"),
    ("WLSA",  "WLSB",  "WealthLS Inc",             "Financials"),
    # Energy
    ("GLXA",  "GLXB",  "GlobalX Energy Corp",      "Energy"),
    ("PENA",  "PENB",  "PennEnergy Corp",           "Energy"),
    ("FRXA",  "FRXB",  "ForexR Energy Inc",         "Energy"),
    # Materials / Industrials
    ("ZNTA",  "ZNTB",  "Zenith Materials Corp",    "Materials"),
    ("TRXA",  "TRXB",  "TrexIndustrials Inc",      "Industrials"),
]

# ─── Individual small caps (no sibling) ───────────────────────────────────

_INDIVIDUAL = [
    ("MLCO", "Melco Holdings Corp",       "Consumer Discretionary", "NASDAQ"),
    ("OVHD", "Overhead Systems Inc",      "Industrials",            "NYSE"),
    ("PDCO", "PedaCo Healthcare Inc",     "Health Care",            "NASDAQ"),
    ("QBIX", "QBix Systems Corp",         "Information Technology", "NASDAQ"),
    ("RFNA", "Rafna Materials Corp",      "Materials",              "NYSE"),
    ("SGDX", "Sagadex Energy Inc",        "Energy",                 "NYSE"),
    ("THGV", "Thagive Staples Corp",      "Consumer Staples",       "NYSE"),
    ("UFBA", "Ufba Financial Holdings",   "Financials",             "NYSE"),
    ("VJPT", "Vajit Technologies Corp",   "Information Technology", "NASDAQ"),
    ("WKSC", "Weksco Industries Corp",    "Industrials",            "NYSE"),
    ("XLTA", "Xleta Utilities Corp",      "Utilities",              "NYSE"),
    ("YMBP", "Yemba Pharma Inc",          "Health Care",            "NASDAQ"),
    ("ZCOL", "Zcola Consumer Corp",       "Consumer Discretionary", "NASDAQ"),
    ("ADXT", "Adext Technologies Inc",    "Information Technology", "NASDAQ"),
    ("BFPA", "Bfpa Financial Corp",       "Financials",             "NYSE"),
    ("CGWL", "Cogwell Industrials Corp",  "Industrials",            "NYSE"),
    ("DHVX", "Dhvex Real Estate Inc",     "Real Estate",            "NYSE"),
    ("EJBT", "Ejbit Materials Corp",      "Materials",              "NYSE"),
    ("FKWM", "Fkwm Consumer Holdings",   "Consumer Staples",       "NASDAQ"),
]


def _build_extra_tickers() -> list:
    """Build the full list of extra ticker dicts for the av-sim."""
    rows = []

    # 5 named tickers first
    rows.extend(_NAMED)

    # 20 sibling pairs: each pair shares the same company name
    for (ta, tb, company, sector) in _SIBLING_PAIRS:
        rows.append({
            "ticker": ta,
            "name": f"{company} Class A",
            "sector": sector,
            "exchange": "NYSE",
        })
        rows.append({
            "ticker": tb,
            "name": f"{company} Class B",
            "sector": sector,
            "exchange": "NYSE",
        })

    # 19 individual small caps
    for (ticker, name, sector, exchange) in _INDIVIDUAL:
        rows.append({"ticker": ticker, "name": name, "sector": sector, "exchange": exchange})

    return rows


YEAR_INITIAL_POSITIONS = Scenario(
    name="year_initial_positions",
    seed=20240101,
    # 64 extra + 46 generated = 110 total (satisfies ≥100 universe guard)
    universe_size=110,
    start_date=date(2024, 1, 2),
    end_date=date(2025, 1, 2),
    regimes=[
        RegimeChange(date(2024, 1, 2),  "bull_calm"),
        RegimeChange(date(2024, 6, 1),  "bear_stress"),
        RegimeChange(date(2024, 10, 1), "bull_calm"),
    ],
    run_vetter=True,
    vetter_every_n_days=5,
    # Starting cash + positions totalling $100k
    initial_cash=10_000.0,
    initial_positions=[
        InitialPosition(ticker="AAPL", value_usd=15_000.0),
        InitialPosition(ticker="SNDK", value_usd=10_000.0),
        InitialPosition(ticker="MU",   value_usd=20_000.0),
        InitialPosition(ticker="KEYS", value_usd=15_000.0),
        InitialPosition(ticker="V",    value_usd=30_000.0),
    ],
    extra_tickers=_build_extra_tickers(),
    description=(
        "1-year bull→bear→bull: AAPL+SNDK+MU+KEYS+V initial positions, "
        "20 sibling pairs, 100k starting value, regime transitions Jun & Oct 2024"
    ),
)
