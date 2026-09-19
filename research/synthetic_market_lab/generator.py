from __future__ import annotations

import math
import platform
from collections import defaultdict
from pathlib import Path

import numpy as np
import pydantic

from .actions import ActionEvent, security_id_for, ticker_for
from .calendar import business_sessions
from .companies import EXPOSURE_NAMES, CompanyUniverse, generate_companies
from .config import WorldConfig
from .factors import FACTOR_NAMES, generate_factors
from .fundamentals import (
    FundamentalState,
    initialize_fundamentals,
    make_disclosure_events,
    quarterly_update,
    truth_rows,
)
from .io import DeterministicCSVGzipWriter, file_record, write_canonical_json, write_csv_gz
from .macro import REGIMES, SHOCK_TYPES, generate_macro
from .pricing import generate_bars
from .rng import SeedLedger
from .sectors import generate_sectors

PRICE_COLUMNS = (
    "date", "session", "company_id", "security_id", "ticker", "open", "high", "low", "close", "adj_close",
    "volume", "dollar_volume", "spread_bps",
)
UNIVERSE_COLUMNS = ("snapshot_date", "session", "company_id", "security_id", "ticker", "sector", "industry")
BENCHMARK_COLUMNS = ("date", "session", "ticker", "open", "high", "low", "close", "adj_close", "volume")
MACRO_COLUMNS = (
    "date", "session", "regime", "growth", "inflation", "policy_rate", "yield_slope", "credit_spread", "liquidity",
    "commodity_impulse", "volatility", "productivity", "risk_appetite", "shock_credit", "shock_energy", "shock_supply",
    "shock_geopolitical", "shock_liquidity", "shock_productivity", "shock_bubble",
)
FACTOR_COLUMNS = ("date", "session", *FACTOR_NAMES)
SECTOR_COLUMNS = ("date", "session", "sector", "sector_return")
TRUTH_COLUMNS = (
    "company_id", "period_end", "session", "age_days", "health", "distress_probability", "true_revenue", "true_expenses",
    "true_net_income", "true_assets", "true_liabilities", "true_equity", "true_cash", "true_debt", "true_shares", "true_growth",
    "true_margin", "true_quality", "latent_value",
)
DISCLOSURE_COLUMNS = (
    "company_id", "security_id", "ticker", "period_end", "filed_at", "version", "report_type", "revenue", "expenses",
    "net_income", "assets", "liabilities", "equity", "cash", "debt", "shares_outstanding", "revenue_growth", "margin",
    "leverage", "quality", "is_restatement",
)
ACTION_COLUMNS = (
    "company_id", "security_id", "ticker", "announced_at", "effective_date", "action_type", "ratio", "cash_amount",
    "new_ticker", "new_security_id", "reason", "pre_price", "post_mechanical_price", "pre_shares", "post_shares",
    "pre_cash", "post_cash",
)
SECURITY_MASTER_COLUMNS = (
    "company_id", "security_id", "ticker", "valid_from", "valid_to", "listing_date", "delist_date", "delist_reason", "sector", "industry",
)
SHOCK_COLUMNS = ("date", "session", "shock_id", "shock_type", "intensity", "source", "affected_scope")

STREAM_NAMES = ["macro", "factors", "sectors", "companies", "fundamentals", "disclosures", "prices", "actions", "benchmark"]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-x))


def _identity_at(identity_rows: list[dict[str, object]], company_index: int, session: int) -> tuple[str, str]:
    candidates = [r for r in identity_rows if r["company_index"] == company_index and int(r["valid_from_session"]) <= session and (r["valid_to_session"] is None or session <= int(r["valid_to_session"]))]
    if candidates:
        row = max(candidates, key=lambda r: int(r["valid_from_session"]))
        return str(row["security_id"]), str(row["ticker"])
    historical = [r for r in identity_rows if r["company_index"] == company_index and int(r["valid_from_session"]) <= session]
    if historical:
        row = max(historical, key=lambda r: int(r["valid_from_session"]))
        return str(row["security_id"]), str(row["ticker"])
    return security_id_for(company_index, 0), ticker_for(company_index, 0)


def _write_static_paths(output: Path, cfg: WorldConfig, dates, macro, factors, sectors) -> None:
    macro_rows = []
    for t, d in enumerate(dates):
        s = macro.state[t]
        k = macro.shocks[t]
        macro_rows.append((d.isoformat(), t, REGIMES[int(macro.regime_index[t])], *map(float, s), *map(float, k)))
    write_csv_gz(output / "ground_truth/macro_daily.csv.gz", MACRO_COLUMNS, macro_rows)

    factor_rows = []
    for t, d in enumerate(dates):
        factor_rows.append((d.isoformat(), t, *map(float, factors.values[t])))
    write_csv_gz(output / "ground_truth/factor_daily.csv.gz", FACTOR_COLUMNS, factor_rows)

    sector_rows = []
    for t, d in enumerate(dates):
        for j, name in enumerate(sectors.names):
            sector_rows.append((d.isoformat(), t, name, float(sectors.returns[t, j])))
    write_csv_gz(output / "ground_truth/sector_daily.csv.gz", SECTOR_COLUMNS, sector_rows)

    shock_rows = []
    for event in macro.shock_events:
        t = int(event["session"])
        shock_rows.append((dates[t].isoformat(), t, event["shock_id"], event["shock_type"], event["intensity"], event["source"], event["affected_scope"]))
    write_csv_gz(output / "ground_truth/shocks.csv.gz", SHOCK_COLUMNS, shock_rows)

    causal = {
        "version": cfg.generator_version,
        "rules": {
            "public.prices[t]": {"parents": ["macro[t]", "factors[t]", "company_state[t]", "company_state[t-1]", "actions[effective<=t]", "rng.prices[t]"], "max_future_lag": 0},
            "public.disclosures[t]": {"parents": ["true_fundamentals[period_end<=t]", "filing_delay<=t", "rng.disclosures"], "max_future_lag": 0},
            "public.actions[t]": {"parents": ["company_state[<=t]", "prices[<=t]", "rng.actions"], "max_future_lag": 0},
            "public.universe[t]": {"parents": ["listing_events[<=t]", "delisting_events[<=t]", "identity_events[<=t]"], "max_future_lag": 0},
            "adapter": {"parents": ["public/* only"], "ground_truth_access": False, "max_future_lag": 0},
        },
    }
    write_canonical_json(output / "ground_truth/causal_dependencies.json", causal)


def generate_world(cfg: WorldConfig, output_dir: str | Path) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "public").mkdir(exist_ok=True)
    (output / "ground_truth").mkdir(exist_ok=True)

    ledger = SeedLedger(cfg.generator_version, cfg.seed)
    rng_macro = ledger.generator("macro")
    rng_factors = ledger.generator("factors")
    rng_sectors = ledger.generator("sectors")
    rng_companies = ledger.generator("companies")
    rng_fund = ledger.generator("fundamentals")
    rng_disc = ledger.generator("disclosures")
    rng_price = ledger.generator("prices")
    rng_actions = ledger.generator("actions")
    rng_benchmark = ledger.generator("benchmark")

    dates = business_sessions(cfg.start_date, cfg.session_count)
    macro = generate_macro(cfg.session_count, cfg.macro, rng_macro)
    factors = generate_factors(macro, cfg.factors, rng_factors)
    sectors = generate_sectors(cfg.companies.sectors, factors.values, macro.state, rng_sectors)
    companies = generate_companies(cfg.companies, cfg.session_count, rng_companies)
    _write_static_paths(output, cfg, dates, macro, factors, sectors)

    n = cfg.companies.company_count
    fund: FundamentalState = initialize_fundamentals(companies)
    shares = companies.initial_shares.astype(float).copy()
    health = np.clip(0.30 * companies.base_quality + rng_fund.normal(0.0, 0.55, n), -2.5, 2.5)
    distress = _sigmoid(-4.2 - 0.9 * health + 0.55 * np.maximum(companies.initial_debt / companies.initial_assets - 0.45, 0.0) * 4.0)
    fundamental_signal = np.zeros(n, dtype=float)
    prior_economic_return = np.zeros(n, dtype=float)
    conditional_vol = companies.base_volatility.copy()
    prev_close = np.full(n, np.nan, dtype=float)
    adj_scale = np.ones(n, dtype=float)
    active = np.zeros(n, dtype=bool)
    listed = np.zeros(n, dtype=bool)
    bankrupt = np.zeros(n, dtype=bool)
    acquired = np.zeros(n, dtype=bool)
    pending_delist = np.zeros(n, dtype=bool)
    last_split_session = np.full(n, -10_000, dtype=int)
    ticker_version = np.zeros(n, dtype=int)
    security_version = np.zeros(n, dtype=int)
    current_ticker = np.array([ticker_for(i, 0) for i in range(n)], dtype=object)
    current_security = np.array([security_id_for(i, 0) for i in range(n)], dtype=object)
    listing_date_by_company: list[str | None] = [None] * n
    delist_session_by_company = np.full(n, -1, dtype=int)
    delist_reason_by_company: list[str] = [""] * n

    identity_rows: list[dict[str, object]] = []
    current_identity_row = np.full(n, -1, dtype=int)
    action_queue: dict[int, list[ActionEvent]] = defaultdict(list)
    actions_all: list[ActionEvent] = []
    disclosure_events: list[dict[str, object]] = []
    truth_all: list[dict[str, object]] = []

    stats = defaultdict(int)

    def schedule(event: ActionEvent) -> None:
        if event.effective_session >= cfg.session_count:
            return
        if event.announced_ticker is None:
            event.announced_ticker = str(current_ticker[event.company_index])
        if event.announced_security_id is None:
            event.announced_security_id = str(current_security[event.company_index])
        action_queue[event.effective_session].append(event)
        actions_all.append(event)

    # IPO announcements are causal public events and do not make a security a universe member before listing.
    for i in range(n):
        t = int(companies.listing_session[i])
        actions_all.append(
            ActionEvent(
                company_index=i,
                action_type="ipo",
                announced_session=max(0, t - 5),
                effective_session=t,
                announced_ticker=ticker_for(i, 0),
                announced_security_id=security_id_for(i, 0),
                reason="synthetic_listing",
            )
        )

    benchmark_prev = 100.0
    benchmark_scale = 1.0

    with DeterministicCSVGzipWriter(output / "public/prices.csv.gz", PRICE_COLUMNS) as price_writer, DeterministicCSVGzipWriter(
        output / "public/universe.csv.gz", UNIVERSE_COLUMNS
    ) as universe_writer, DeterministicCSVGzipWriter(output / "public/benchmark.csv.gz", BENCHMARK_COLUMNS) as benchmark_writer:
        for t, d in enumerate(dates):
            d_iso = d.isoformat()
            # Listings become active at the start of the listing session.
            for i in np.flatnonzero(companies.listing_session == t):
                listed[i] = True
                active[i] = True
                listing_date_by_company[i] = d_iso
                current_ticker[i] = ticker_for(int(i), int(ticker_version[i]))
                current_security[i] = security_id_for(int(i), int(security_version[i]))
                row = {
                    "company_index": int(i),
                    "company_id": str(companies.company_id[i]),
                    "security_id": str(current_security[i]),
                    "ticker": str(current_ticker[i]),
                    "valid_from_session": t,
                    "valid_to_session": None,
                    "listing_session": t,
                }
                identity_rows.append(row)
                current_identity_row[i] = len(identity_rows) - 1
                stats["ipos"] += 1

            raw_base = prev_close.copy()
            event_return_shock = np.zeros(n, dtype=float)

            # Apply effective actions mechanically before the daily return is generated.
            for event in sorted(action_queue.get(t, []), key=lambda e: (e.company_index, e.action_type)):
                i = event.company_index
                if not active[i] and event.action_type != "delisting":
                    event.reason = (event.reason + ";cancelled_inactive").strip(";")
                    continue
                pre_price = float(raw_base[i]) if math.isfinite(float(raw_base[i])) else float(companies.initial_price[i])
                pre_shares = float(shares[i])
                pre_cash = float(fund.cash[i])
                event.diagnostics.update({"pre_price": pre_price, "pre_shares": pre_shares, "pre_cash": pre_cash})

                if event.action_type in {"split", "reverse_split"}:
                    ratio = float(event.ratio or 1.0)
                    if ratio <= 0:
                        raise ValueError("split ratio must be positive")
                    if math.isfinite(float(raw_base[i])):
                        raw_base[i] = max(cfg.prices.min_price, raw_base[i] / ratio)
                    shares[i] *= ratio
                    adj_scale[i] *= ratio
                    last_split_session[i] = t
                elif event.action_type == "dividend":
                    amount = max(0.0, float(event.cash_amount or 0.0))
                    if math.isfinite(float(raw_base[i])) and raw_base[i] > amount + cfg.prices.min_price:
                        ex_price = raw_base[i] - amount
                        adj_scale[i] *= raw_base[i] / ex_price
                        raw_base[i] = ex_price
                    cash_out = min(fund.cash[i], amount * shares[i])
                    fund.cash[i] -= cash_out
                    fund.assets[i] = max(1.0, fund.assets[i] - cash_out)
                    fund.equity[i] = fund.assets[i] - fund.liabilities[i]
                elif event.action_type == "issuance":
                    ratio = max(1.0, float(event.ratio or 1.0))
                    new_shares = shares[i] * (ratio - 1.0)
                    proceeds = new_shares * pre_price * 0.98
                    shares[i] *= ratio
                    fund.cash[i] += proceeds
                    fund.assets[i] += proceeds
                    fund.equity[i] = fund.assets[i] - fund.liabilities[i]
                elif event.action_type == "buyback":
                    ratio = min(1.0, max(0.5, float(event.ratio or 1.0)))
                    retired = shares[i] * (1.0 - ratio)
                    spend = min(fund.cash[i] * 0.70, retired * pre_price)
                    shares[i] *= ratio
                    fund.cash[i] -= spend
                    fund.assets[i] = max(1.0, fund.assets[i] - spend)
                    fund.equity[i] = fund.assets[i] - fund.liabilities[i]
                elif event.action_type == "bankruptcy":
                    bankrupt[i] = True
                    event_return_shock[i] -= 0.85
                    health[i] = min(health[i], -2.5)
                    distress[i] = max(distress[i], 0.98)
                    if not pending_delist[i]:
                        pending_delist[i] = True
                        delist_t = min(cfg.session_count - 1, t + cfg.actions.delist_delay_sessions)
                        schedule(
                            ActionEvent(
                                company_index=i,
                                action_type="delisting",
                                announced_session=t,
                                effective_session=delist_t,
                                reason="bankruptcy",
                            )
                        )
                elif event.action_type == "acquisition":
                    acquired[i] = True
                    event_return_shock[i] += 0.18
                    if not pending_delist[i]:
                        pending_delist[i] = True
                        delist_t = min(cfg.session_count - 1, t + cfg.actions.delist_delay_sessions)
                        schedule(ActionEvent(company_index=i, action_type="delisting", announced_session=t, effective_session=delist_t, reason="acquisition"))
                elif event.action_type == "ticker_change":
                    prior_row = int(current_identity_row[i])
                    if prior_row >= 0:
                        identity_rows[prior_row]["valid_to_session"] = t - 1
                    ticker_version[i] += 1
                    current_ticker[i] = event.new_ticker or ticker_for(i, int(ticker_version[i]))
                    identity_rows.append(
                        {
                            "company_index": i,
                            "company_id": str(companies.company_id[i]),
                            "security_id": str(current_security[i]),
                            "ticker": str(current_ticker[i]),
                            "valid_from_session": t,
                            "valid_to_session": None,
                            "listing_session": int(companies.listing_session[i]),
                        }
                    )
                    current_identity_row[i] = len(identity_rows) - 1
                elif event.action_type == "identifier_change":
                    prior_row = int(current_identity_row[i])
                    if prior_row >= 0:
                        identity_rows[prior_row]["valid_to_session"] = t - 1
                    security_version[i] += 1
                    current_security[i] = event.new_security_id or security_id_for(i, int(security_version[i]))
                    identity_rows.append(
                        {
                            "company_index": i,
                            "company_id": str(companies.company_id[i]),
                            "security_id": str(current_security[i]),
                            "ticker": str(current_ticker[i]),
                            "valid_from_session": t,
                            "valid_to_session": None,
                            "listing_session": int(companies.listing_session[i]),
                        }
                    )
                    current_identity_row[i] = len(identity_rows) - 1
                elif event.action_type == "delisting":
                    if active[i]:
                        active[i] = False
                        delist_session_by_company[i] = t
                        delist_reason_by_company[i] = event.reason or "delisting"
                        row_ix = int(current_identity_row[i])
                        if row_ix >= 0:
                            identity_rows[row_ix]["valid_to_session"] = max(int(identity_rows[row_ix]["valid_from_session"]), t - 1)
                        stats["delistings"] += 1

                post_price = float(raw_base[i]) if math.isfinite(float(raw_base[i])) else pre_price
                event.diagnostics.update(
                    {
                        "post_mechanical_price": post_price,
                        "post_shares": float(shares[i]),
                        "post_cash": float(fund.cash[i]),
                    }
                )
                stats[event.action_type + "s"] += 1

            # Latent company health evolves before price formation using only current/past state.
            growth = float(macro.state[t, 0])
            credit_spread = float(macro.state[t, 4])
            liquidity_state = float(macro.state[t, 5])
            health_target = 0.35 * companies.base_quality + 3.0 * companies.cyclicality * growth - 2.8 * credit_spread + 0.20 * liquidity_state
            health = np.clip(0.992 * health + 0.008 * health_target + rng_fund.normal(0.0, 0.018, n), -3.5, 3.5)
            debt_ratio = np.divide(fund.debt, np.maximum(fund.assets, 1.0))
            distress = _sigmoid(-3.8 - 1.15 * health + 4.2 * np.maximum(debt_ratio - 0.42, 0.0) + 2.0 * credit_spread)
            fundamental_signal *= 0.985

            # New listings receive a causal opening base from current true company value.
            new_idx = np.flatnonzero(companies.listing_session == t)
            for i in new_idx:
                intrinsic = max(cfg.prices.min_price, float(fund.latent_value[i] / max(shares[i], 1.0)))
                raw_base[i] = max(cfg.prices.min_price, 0.55 * float(companies.initial_price[i]) + 0.45 * intrinsic)
                adj_scale[i] = 1.0
                prior_economic_return[i] = 0.0

            active_idx = np.flatnonzero(active)
            economic_base = np.where(np.isfinite(raw_base), raw_base * adj_scale, np.nan)
            bars = generate_bars(
                active_idx,
                economic_base,
                raw_base,
                adj_scale,
                prior_economic_return,
                conditional_vol,
                fundamental_signal,
                health,
                distress,
                companies,
                shares,
                factors.values[t],
                sectors.returns[t],
                macro.state[t],
                event_return_shock,
                cfg.prices,
                cfg.liquidity,
                rng_price,
            )

            for pos, i in enumerate(active_idx):
                prev_close[i] = float(bars["close"][pos])
                prior_economic_return[i] = float(bars["economic_return"][pos])
                conditional_vol[i] = float(bars["conditional_vol"][pos])
                price_writer.write(
                    (
                        d_iso,
                        t,
                        companies.company_id[i],
                        current_security[i],
                        current_ticker[i],
                        float(bars["open"][pos]),
                        float(bars["high"][pos]),
                        float(bars["low"][pos]),
                        float(bars["close"][pos]),
                        float(bars["adj_close"][pos]),
                        float(bars["volume"][pos]),
                        float(bars["dollar_volume"][pos]),
                        float(bars["spread_bps"][pos]),
                    )
                )
                universe_writer.write((d_iso, t, companies.company_id[i], current_security[i], current_ticker[i], companies.sector[i], companies.industry[i]))

            # Synthetic public market benchmark. It is an index, not a ground-truth macro variable.
            market_ret = float(factors.values[t, 0])
            bench_gap = float(rng_benchmark.normal(0.0, 0.002 + 0.004 * macro.state[t, 7]))
            bench_close = max(1.0, benchmark_prev * math.exp(market_ret))
            bench_open = max(1.0, benchmark_prev * math.exp(bench_gap))
            bench_range = abs(float(rng_benchmark.normal(0.0, 0.004 + 0.008 * macro.state[t, 7])))
            bench_high = max(bench_open, bench_close) * math.exp(bench_range)
            bench_low = min(bench_open, bench_close) * math.exp(-bench_range)
            bench_volume = 500_000_000.0 * (1.0 + 1.8 * macro.state[t, 7]) * float(rng_benchmark.lognormal(0.0, 0.12))
            benchmark_writer.write((d_iso, t, cfg.benchmark_public_ticker, bench_open, bench_high, bench_low, bench_close, bench_close * benchmark_scale, bench_volume))
            benchmark_prev = bench_close

            # Structural action arrivals use only state visible/true at or before this session.
            if t + 1 < cfg.session_count:
                eligible = np.flatnonzero(active & ~pending_delist)
                for i in eligible:
                    if t - last_split_session[i] >= cfg.actions.split_cooldown_sessions:
                        if prev_close[i] >= cfg.actions.split_price_threshold:
                            ratio = 2.0 if prev_close[i] < cfg.actions.split_price_threshold * 2.5 else 4.0
                            schedule(ActionEvent(i, "split", t, t + 1, ratio=ratio, reason="price_range_management"))
                            last_split_session[i] = t
                        elif prev_close[i] <= cfg.actions.reverse_split_price_threshold and distress[i] > 0.55:
                            ratio = 0.1
                            schedule(ActionEvent(i, "reverse_split", t, t + 1, ratio=ratio, reason="listing_price_support"))
                            last_split_session[i] = t

                    daily_bankruptcy = cfg.actions.annual_bankruptcy_base_probability / cfg.sessions_per_year
                    hazard = daily_bankruptcy * math.exp(4.0 * max(float(distress[i]) - 0.45, 0.0))
                    if not bankrupt[i] and rng_actions.random() < min(0.08, hazard):
                        bankruptcy_t = t + 1
                        delist_t = min(cfg.session_count - 1, bankruptcy_t + cfg.actions.delist_delay_sessions)
                        schedule(ActionEvent(i, "bankruptcy", t, bankruptcy_t, reason="distress_default"))
                        schedule(ActionEvent(i, "delisting", t, delist_t, reason="bankruptcy"))
                        pending_delist[i] = True
                        continue

                    age_years = (companies.initial_age_days[i] + t * 365.25 / cfg.sessions_per_year) / 365.25
                    acq_hazard = cfg.actions.annual_acquisition_probability / cfg.sessions_per_year
                    if age_years > 2.0 and health[i] > -0.3 and rng_actions.random() < acq_hazard:
                        acquisition_t = t + 1
                        delist_t = min(cfg.session_count - 1, acquisition_t + cfg.actions.delist_delay_sessions)
                        schedule(ActionEvent(i, "acquisition", t, acquisition_t, reason="strategic_acquisition"))
                        schedule(ActionEvent(i, "delisting", t, delist_t, reason="acquisition"))
                        pending_delist[i] = True
                        continue

                    if rng_actions.random() < cfg.actions.annual_ticker_change_probability / cfg.sessions_per_year:
                        new_ticker = ticker_for(i, int(ticker_version[i]) + 1)
                        schedule(ActionEvent(i, "ticker_change", t, t + 1, new_ticker=new_ticker, reason="corporate_rebranding"))
                    if rng_actions.random() < cfg.actions.annual_identifier_change_probability / cfg.sessions_per_year:
                        new_sec = security_id_for(i, int(security_version[i]) + 1)
                        schedule(ActionEvent(i, "identifier_change", t, t + 1, new_security_id=new_sec, reason="security_reorganization"))

            # Company-specific fiscal calendars: each company reports every 63 sessions from its own offset.
            due_mask = (t >= companies.fiscal_quarter_offset) & (((t - companies.fiscal_quarter_offset) % 63) == 0)
            due_idx = np.flatnonzero(due_mask)
            if len(due_idx):
                new_signal, _margin_change = quarterly_update(
                    fund, companies, shares, health, distress, macro.state[t], rng_fund, indices=due_idx
                )
                fundamental_signal[due_idx] = new_signal[due_idx]
                age_days = companies.initial_age_days + np.rint(t * 365.25 / cfg.sessions_per_year).astype(int)
                truth_all.extend(truth_rows(companies.company_id, d_iso, t, age_days, health, distress, fund, shares, indices=due_idx))
                quarter_number = t // 63 + 1
                report_type = "annual" if quarter_number % 4 == 0 else "quarterly"
                disclosure_events.extend(
                    make_disclosure_events(
                        t,
                        d_iso,
                        listed & due_mask,
                        active & due_mask,
                        fund,
                        shares,
                        companies.company_id,
                        cfg.disclosures,
                        cfg.session_count,
                        rng_disc,
                        report_type=report_type,
                    )
                )

                if t + 1 < cfg.session_count:
                    for i in np.flatnonzero(active & ~pending_delist & due_mask):
                        if fund.net_income[i] > 0 and health[i] > -0.8 and rng_actions.random() < cfg.actions.dividend_quarterly_probability:
                            per_share_income = fund.net_income[i] / max(shares[i], 1.0)
                            amount = max(0.0, min(float(prev_close[i]) * 0.04, per_share_income * cfg.actions.dividend_payout_ratio))
                            if amount > 0.0001:
                                eff = min(cfg.session_count - 1, t + 5)
                                schedule(ActionEvent(i, "dividend", t, eff, cash_amount=amount, reason="quarterly_distribution"))
                        if rng_actions.random() < cfg.actions.annual_issuance_probability / 4.0:
                            schedule(ActionEvent(i, "issuance", t, t + 1, ratio=float(rng_actions.uniform(1.01, 1.10)), reason="capital_raise"))
                        if fund.cash[i] > fund.assets[i] * 0.05 and rng_actions.random() < cfg.actions.annual_buyback_probability / 4.0:
                            schedule(ActionEvent(i, "buyback", t, t + 1, ratio=float(rng_actions.uniform(0.96, 0.995)), reason="share_repurchase"))

    # Close still-open identity intervals at the final generated date.
    for i in range(n):
        row_ix = int(current_identity_row[i])
        if row_ix >= 0 and identity_rows[row_ix]["valid_to_session"] is None:
            identity_rows[row_ix]["valid_to_session"] = cfg.session_count - 1 if active[i] else max(int(identity_rows[row_ix]["valid_from_session"]), int(delist_session_by_company[i]) - 1)

    # True quarterly state.
    write_csv_gz(output / "ground_truth/company_quarterly.csv.gz", TRUTH_COLUMNS, truth_all)

    # Public security master.
    security_master_rows = []
    for row in sorted(identity_rows, key=lambda r: (str(r["company_id"]), int(r["valid_from_session"]), str(r["security_id"]))):
        i = int(row["company_index"])
        vfrom = int(row["valid_from_session"])
        vto = int(row["valid_to_session"])
        delist_t = int(delist_session_by_company[i])
        security_master_rows.append(
            (
                row["company_id"], row["security_id"], row["ticker"], dates[vfrom].isoformat(), dates[vto].isoformat(),
                listing_date_by_company[i] or dates[int(companies.listing_session[i])].isoformat(),
                dates[delist_t].isoformat() if delist_t >= 0 else "",
                delist_reason_by_company[i], companies.sector[i], companies.industry[i],
            )
        )
    write_csv_gz(output / "public/security_master.csv.gz", SECURITY_MASTER_COLUMNS, security_master_rows)

    # Resolve disclosure identifiers at the filing session; later revisions remain separate rows.
    disclosure_rows = []
    for event in sorted(disclosure_events, key=lambda e: (int(e["filed_session"]), str(e["company_id"]), str(e["period_end"]), int(e["version"]))):
        i = int(event["company_index"])
        fs = int(event["filed_session"])
        sec, tick = _identity_at(identity_rows, i, fs)
        disclosure_rows.append(
            (
                event["company_id"], sec, tick, event["period_end"], dates[fs].isoformat(), event["version"], event["report_type"],
                event["revenue"], event["expenses"], event["net_income"], event["assets"], event["liabilities"], event["equity"],
                event["cash"], event["debt"], event["shares_outstanding"], event["revenue_growth"], event["margin"], event["leverage"],
                event["quality"], event["is_restatement"],
            )
        )
    write_csv_gz(output / "public/disclosures.csv.gz", DISCLOSURE_COLUMNS, disclosure_rows)

    # Public actions preserve announced identity and mechanical reconciliation diagnostics.
    action_rows = []
    for event in sorted(actions_all, key=lambda e: (e.announced_session, e.effective_session, e.company_index, e.action_type)):
        i = event.company_index
        diag = event.diagnostics
        action_rows.append(
            (
                companies.company_id[i], event.announced_security_id or security_id_for(i, 0), event.announced_ticker or ticker_for(i, 0),
                dates[event.announced_session].isoformat(), dates[event.effective_session].isoformat(), event.action_type,
                event.ratio, event.cash_amount, event.new_ticker, event.new_security_id, event.reason,
                diag.get("pre_price"), diag.get("post_mechanical_price"), diag.get("pre_shares"), diag.get("post_shares"),
                diag.get("pre_cash"), diag.get("post_cash"),
            )
        )
    write_csv_gz(output / "public/actions.csv.gz", ACTION_COLUMNS, action_rows)

    # Count final action outcomes from rows, including IPOs.
    action_type_counts: dict[str, int] = defaultdict(int)
    for event in actions_all:
        action_type_counts[event.action_type] += 1

    generated_files = [
        p for p in sorted(output.rglob("*")) if p.is_file() and p.name not in {"manifest.json", "validation.json"}
    ]
    files = {str(p.relative_to(output)): file_record(p) for p in generated_files}
    manifest = {
        "generator_version": cfg.generator_version,
        "world_id": cfg.world_id(),
        "seed": cfg.seed,
        "config": cfg.canonical_dict(),
        "config_sha256": cfg.config_sha256(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pydantic_version": pydantic.__version__,
        "rng_algorithm": "numpy.random.PCG64DXSM",
        "rng_streams": ledger.describe(STREAM_NAMES),
        "sessions": cfg.session_count,
        "companies": n,
        "files": files,
        "statistics": {
            "first_date": dates[0].isoformat(),
            "last_date": dates[-1].isoformat(),
            "price_rows": int(price_writer.rows),
            "universe_rows": int(universe_writer.rows),
            "benchmark_rows": int(benchmark_writer.rows),
            "identity_intervals": len(identity_rows),
            "disclosures": len(disclosure_rows),
            "restatements": sum(1 for e in disclosure_events if bool(e["is_restatement"])),
            "ground_truth_quarter_rows": len(truth_all),
            "end_active_securities": int(active.sum()),
            "ever_listed_companies": int(listed.sum()),
            "bankrupt_companies": int(bankrupt.sum()),
            "acquired_companies": int(acquired.sum()),
            "action_counts": dict(sorted(action_type_counts.items())),
            "macro_shock_events": len(macro.shock_events),
        },
    }
    write_canonical_json(output / "manifest.json", manifest)
    return manifest
