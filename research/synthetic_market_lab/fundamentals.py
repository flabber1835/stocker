from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .companies import CompanyUniverse
from .config import DisclosureConfig


@dataclass
class FundamentalState:
    revenue: np.ndarray
    expenses: np.ndarray
    net_income: np.ndarray
    assets: np.ndarray
    liabilities: np.ndarray
    equity: np.ndarray
    cash: np.ndarray
    debt: np.ndarray
    margin: np.ndarray
    growth: np.ndarray
    quality: np.ndarray
    latent_value: np.ndarray


def initialize_fundamentals(companies: CompanyUniverse) -> FundamentalState:
    revenue = companies.initial_revenue.astype(float).copy()
    margin = companies.base_margin.astype(float).copy()
    net_income = revenue * margin
    expenses = revenue - net_income
    assets = companies.initial_assets.astype(float).copy()
    debt = companies.initial_debt.astype(float).copy()
    cash = companies.initial_cash.astype(float).copy()
    other_liabilities = assets * np.clip(0.20 - 0.025 * companies.base_quality, 0.05, 0.38)
    liabilities = debt + other_liabilities
    equity = assets - liabilities
    growth = companies.base_growth.astype(float).copy()
    quality = companies.base_quality.astype(float).copy()
    latent_value = np.maximum(0.05 * assets, equity + np.maximum(net_income, 0.0) * 9.0 + cash * 0.5)
    return FundamentalState(
        revenue=revenue,
        expenses=expenses,
        net_income=net_income,
        assets=assets,
        liabilities=liabilities,
        equity=equity,
        cash=cash,
        debt=debt,
        margin=margin,
        growth=growth,
        quality=quality,
        latent_value=latent_value,
    )


def quarterly_update(
    state: FundamentalState,
    companies: CompanyUniverse,
    shares: np.ndarray,
    health: np.ndarray,
    distress_probability: np.ndarray,
    macro_state: np.ndarray,
    rng: np.random.Generator,
    indices: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    idx = np.arange(len(shares), dtype=int) if indices is None else np.asarray(indices, dtype=int)
    signal = np.zeros(len(shares), dtype=float)
    margin_change_all = np.zeros(len(shares), dtype=float)
    if len(idx) == 0:
        return signal, margin_change_all

    growth_macro, inflation, policy_rate, _slope, credit_spread, _liquidity, commodity, _vol, productivity, _risk = macro_state
    prior_revenue = state.revenue[idx].copy()
    prior_margin = state.margin[idx].copy()

    annual_growth = (
        companies.base_growth[idx]
        + companies.cyclicality[idx] * growth_macro
        + 0.35 * productivity
        - 0.55 * distress_probability[idx]
        + 0.025 * companies.exposures[idx, 10] * commodity
        + rng.normal(0.0, 0.055, len(idx))
    )
    q_growth = np.clip(annual_growth / 4.0, -0.45, 0.55)
    state.revenue[idx] = np.maximum(50_000.0, state.revenue[idx] * np.exp(q_growth))

    target_margin = (
        companies.base_margin[idx]
        + 0.025 * companies.base_quality[idx]
        + 0.020 * growth_macro
        - 0.035 * credit_spread
        - 0.055 * distress_probability[idx]
        + rng.normal(0.0, 0.012, len(idx))
    )
    state.margin[idx] = np.clip(0.68 * state.margin[idx] + 0.32 * target_margin, -0.55, 0.55)
    state.net_income[idx] = state.revenue[idx] * state.margin[idx]
    state.expenses[idx] = state.revenue[idx] - state.net_income[idx]

    asset_growth = np.clip(0.45 * q_growth + 0.012 * inflation + rng.normal(0.0, 0.015, len(idx)), -0.25, 0.35)
    state.assets[idx] = np.maximum(100_000.0, state.assets[idx] * (1.0 + asset_growth))

    desired_debt_ratio = np.clip(
        0.28 - 0.045 * companies.base_quality[idx] + 0.35 * distress_probability[idx] + 0.8 * credit_spread + 0.25 * policy_rate,
        0.01,
        0.92,
    )
    desired_debt = state.assets[idx] * desired_debt_ratio
    state.debt[idx] = np.maximum(0.0, 0.75 * state.debt[idx] + 0.25 * desired_debt)

    desired_cash_ratio = np.clip(0.10 + 0.025 * companies.base_quality[idx] + 0.06 * health[idx] - 0.05 * distress_probability[idx], 0.005, 0.45)
    state.cash[idx] = np.clip(
        0.75 * state.cash[idx] + 0.25 * state.assets[idx] * desired_cash_ratio + 0.15 * np.maximum(state.net_income[idx], 0.0),
        0.0,
        state.assets[idx] * 0.75,
    )

    other_liabilities = state.assets[idx] * np.clip(0.18 + 0.06 * distress_probability[idx] + rng.normal(0.0, 0.012, len(idx)), 0.03, 0.45)
    state.liabilities[idx] = state.debt[idx] + other_liabilities
    state.equity[idx] = state.assets[idx] - state.liabilities[idx]
    state.growth[idx] = np.log(np.maximum(state.revenue[idx], 1.0) / np.maximum(prior_revenue, 1.0)) * 4.0
    state.quality[idx] = np.clip(companies.base_quality[idx] + 1.8 * state.margin[idx] + 0.7 * health[idx] - 0.8 * distress_probability[idx], -4.0, 4.0)
    state.latent_value[idx] = np.maximum(
        state.assets[idx] * 0.03,
        state.equity[idx] + 9.0 * np.maximum(state.net_income[idx], 0.0) + 0.45 * state.cash[idx] - 0.15 * state.debt[idx],
    )

    signal[idx] = np.clip(1.2 * q_growth + 0.8 * (state.margin[idx] - prior_margin), -0.35, 0.35)
    margin_change_all[idx] = state.margin[idx] - prior_margin
    return signal, margin_change_all


def truth_rows(
    company_ids: np.ndarray,
    period_end: str,
    session: int,
    age_days: np.ndarray,
    health: np.ndarray,
    distress_probability: np.ndarray,
    state: FundamentalState,
    shares: np.ndarray,
    indices: np.ndarray | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    idx = np.arange(len(company_ids), dtype=int) if indices is None else np.asarray(indices, dtype=int)
    for i in idx:
        cid = company_ids[i]
        rows.append(
            {
                "company_id": cid,
                "period_end": period_end,
                "session": session,
                "age_days": int(age_days[i]),
                "health": float(health[i]),
                "distress_probability": float(distress_probability[i]),
                "true_revenue": float(state.revenue[i]),
                "true_expenses": float(state.expenses[i]),
                "true_net_income": float(state.net_income[i]),
                "true_assets": float(state.assets[i]),
                "true_liabilities": float(state.liabilities[i]),
                "true_equity": float(state.equity[i]),
                "true_cash": float(state.cash[i]),
                "true_debt": float(state.debt[i]),
                "true_shares": float(shares[i]),
                "true_growth": float(state.growth[i]),
                "true_margin": float(state.margin[i]),
                "true_quality": float(state.quality[i]),
                "latent_value": float(state.latent_value[i]),
            }
        )
    return rows


def _noise_value(value: float, sigma: float, rng: np.random.Generator) -> float:
    return float(value * (1.0 + rng.normal(0.0, sigma)))


def make_disclosure_events(
    session: int,
    period_end: str,
    listed_mask: np.ndarray,
    active_mask: np.ndarray,
    state: FundamentalState,
    shares: np.ndarray,
    company_ids: np.ndarray,
    cfg: DisclosureConfig,
    session_count: int,
    rng: np.random.Generator,
    report_type: str = "quarterly",
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for i in np.flatnonzero(listed_mask & active_mask):
        if rng.random() < cfg.missing_report_probability:
            continue
        delay = int(rng.integers(cfg.filing_delay_min_sessions, cfg.filing_delay_max_sessions + 1))
        filed_session = session + delay
        if filed_session >= session_count:
            continue

        def build(version: int, filed: int, sigma: float, is_restatement: bool) -> dict[str, object]:
            revenue = _noise_value(float(state.revenue[i]), sigma, rng)
            net_income = _noise_value(float(state.net_income[i]), sigma * 1.4, rng)
            assets = max(1.0, _noise_value(float(state.assets[i]), sigma, rng))
            liabilities = _noise_value(float(state.liabilities[i]), sigma, rng)
            equity = assets - liabilities
            cash = max(0.0, min(assets, _noise_value(float(state.cash[i]), sigma, rng)))
            debt = max(0.0, _noise_value(float(state.debt[i]), sigma, rng))
            margin = net_income / revenue if abs(revenue) > 1e-9 else 0.0
            return {
                "company_index": int(i),
                "company_id": str(company_ids[i]),
                "period_end": period_end,
                "filed_session": int(filed),
                "version": version,
                "report_type": report_type,
                "revenue": revenue,
                "expenses": revenue - net_income,
                "net_income": net_income,
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "cash": cash,
                "debt": debt,
                "shares_outstanding": float(shares[i]),
                "revenue_growth": float(state.growth[i]),
                "margin": float(margin),
                "leverage": float(debt / assets),
                "quality": float(state.quality[i] + rng.normal(0.0, sigma)),
                "is_restatement": is_restatement,
            }

        events.append(build(1, filed_session, cfg.reporting_noise_std, False))
        if rng.random() < cfg.restatement_probability:
            extra = int(rng.integers(cfg.restatement_delay_min_sessions, cfg.restatement_delay_max_sessions + 1))
            restated_session = filed_session + extra
            if restated_session < session_count:
                events.append(build(2, restated_session, cfg.reporting_noise_std * 0.35, True))
    return events
