#!/usr/bin/env python3
"""Zero-budget Stage 7 observed-options validation for a Stage 6 winner.

Runs only after the preregistered conservative Stage 6 modeled gate passes.
Contract selection uses only the modeled entry geometry: underlying, target
expiration, and target strike. Subsequent option returns are never used to pick a
contract. Historical Alpaca daily option bars are available only from February
2024 onward, so this validation is limited to the preregistered 2024 Jul/Aug and
2025 target episodes.

This does not spend E8 and does not alter Wealth Core or Sentinel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

LABEL = "WC_TARGETED_HEDGE_STAGE7_ALPACA_OBSERVED_ZERO_BUDGET"
CONTRACT_URL = "https://paper-api.alpaca.markets/v2/options/contracts"
BARS_URL = "https://data.alpaca.markets/v1beta1/options/bars"
REQUIRED_TARGETS = {
    "2024_JULAUG": (pd.Timestamp("2024-07-15"), pd.Timestamp("2024-08-05")),
    "2025": (pd.Timestamp("2025-02-14"), pd.Timestamp("2025-04-08")),
}
MIN_PREMIUM_COVERAGE = 0.80
MAX_ENTRY_COST_RATIO = 1.15
MIN_EXIT_PROCEEDS_RATIO = 0.85


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_json(url: str, params: dict, key: str, secret: str, attempts: int = 4) -> dict:
    full = url + "?" + urlencode({k: v for k, v in params.items() if v is not None})
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "User-Agent": "stocker-targeted-hedge-stage7/1",
    }
    last = None
    for n in range(attempts):
        try:
            with urlopen(Request(full, headers=headers), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last = RuntimeError(f"HTTP {exc.code} from {url}: {body[:500]}")
            if exc.code not in (429, 500, 502, 503, 504):
                raise last
        except (URLError, TimeoutError) as exc:
            last = RuntimeError(f"request failed {url}: {exc}")
        if n + 1 < attempts:
            time.sleep(2 ** n)
    raise last or RuntimeError(f"request failed {url}")


def contract_pages(underlying: str, target_expiry: pd.Timestamp, target_strike: float, key: str, secret: str) -> list[dict]:
    # Search a deterministic neighborhood. Selection is lexicographic by absolute
    # expiration-day error and then relative strike error; returns never enter it.
    lo_exp = (target_expiry - pd.Timedelta(days=35)).date().isoformat()
    hi_exp = (target_expiry + pd.Timedelta(days=35)).date().isoformat()
    lo_strike = max(target_strike * 0.85, 0.01)
    hi_strike = target_strike * 1.15
    rows: list[dict] = []
    token = None
    for _ in range(20):
        data = request_json(
            CONTRACT_URL,
            {
                "underlying_symbols": underlying,
                "status": "inactive",
                "type": "put",
                "expiration_date_gte": lo_exp,
                "expiration_date_lte": hi_exp,
                "strike_price_gte": f"{lo_strike:.6f}",
                "strike_price_lte": f"{hi_strike:.6f}",
                "limit": 10000,
                "page_token": token,
            },
            key,
            secret,
        )
        batch = data.get("option_contracts", data.get("contracts", []))
        if not isinstance(batch, list):
            raise RuntimeError(f"unexpected option-contract response keys: {sorted(data)}")
        rows.extend(batch)
        token = data.get("next_page_token")
        if not token:
            break
    return rows


def choose_contract(underlying: str, target_expiry: pd.Timestamp, target_strike: float, key: str, secret: str) -> dict:
    rows = contract_pages(underlying, target_expiry, target_strike, key, secret)
    candidates = []
    for r in rows:
        try:
            expiry = pd.Timestamp(r["expiration_date"])
            strike = float(r["strike_price"])
            symbol = str(r["symbol"])
        except Exception:
            continue
        if str(r.get("type", "put")).lower() != "put":
            continue
        exp_err = abs((expiry - target_expiry).days)
        strike_err = abs(strike / target_strike - 1.0) if target_strike > 0 else float("inf")
        candidates.append((exp_err, strike_err, symbol, expiry, strike, r))
    if not candidates:
        raise RuntimeError(f"no historical put contract candidates for {underlying} target_expiry={target_expiry.date()} strike={target_strike}")
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    exp_err, strike_err, symbol, expiry, strike, raw = candidates[0]
    return {
        "symbol": symbol,
        "expiration_date": str(expiry.date()),
        "strike_price": strike,
        "expiration_error_days": int(exp_err),
        "relative_strike_error": float(strike_err),
        "raw_status": raw.get("status"),
        "root_symbol": raw.get("root_symbol"),
    }


def get_daily_bars(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp, key: str, secret: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {s: [] for s in symbols}
    token = None
    for _ in range(100):
        data = request_json(
            BARS_URL,
            {
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
                "limit": 10000,
                "sort": "asc",
                "page_token": token,
            },
            key,
            secret,
        )
        bars = data.get("bars", {})
        if not isinstance(bars, dict):
            raise RuntimeError(f"unexpected option-bars response keys: {sorted(data)}")
        for symbol, items in bars.items():
            if symbol in out and isinstance(items, list):
                out[symbol].extend(items)
        token = data.get("next_page_token")
        if not token:
            break
    return out


def bar_open_on(items: list[dict], date: pd.Timestamp) -> float | None:
    target = date.date()
    for b in items:
        ts = b.get("t")
        if ts is None:
            continue
        try:
            if pd.Timestamp(ts).date() == target:
                value = float(b["o"])
                if math.isfinite(value) and value >= 0:
                    return value
        except Exception:
            continue
    return None


def target_episode_number(stage5: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> int:
    x = stage5.copy()
    x["trigger_date"] = pd.to_datetime(x.trigger_date)
    q = x[(x.trigger_date >= start) & (x.trigger_date <= end)]
    if q.empty:
        raise RuntimeError(f"required Stage5 episode missing in {start.date()}..{end.date()}")
    return int(q.sort_values("trigger_date").iloc[0].episode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage6-root", type=Path, required=True)
    ap.add_argument("--stage5-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--api-secret", required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    stage6 = json.loads((args.stage6_root / "stage6_summary.json").read_text())
    if stage6.get("e8_gate") != "CLOSED_PENDING_OBSERVED_2024_2026_VALIDATION":
        raise RuntimeError(f"Stage6 did not open observed validation gate: {stage6.get('e8_gate')}")
    if not stage6.get("strict_dual_horizon_gate_applied"):
        raise RuntimeError("Stage6 strict dual-horizon gate missing")
    winner = stage6.get("best_conservative_candidate")
    if not winner or not str(winner).endswith("__CONSERVATIVE"):
        raise RuntimeError(f"invalid Stage6 conservative winner: {winner}")

    stage5 = pd.read_csv(args.stage5_root / "systemic_concordance_episodes.csv")
    trades = pd.read_csv(args.stage6_root / "modeled_put_trade_ledger.csv")
    trades = trades[trades.variant.astype(str).eq(str(winner))].copy()

    selected_rows = []
    episode_results = []
    for target, (start, trough) in REQUIRED_TARGETS.items():
        episode = target_episode_number(stage5, start, trough)
        buys = trades[(trades.episode.astype(int) == episode) & trades.action.astype(str).eq("BUY")].copy()
        sells = trades[(trades.episode.astype(int) == episode) & trades.action.astype(str).eq("SELL_RECOVERY")].copy()
        if buys.empty:
            raise RuntimeError(f"{target}: Stage6 winning variant had no initial BUY rows")
        if sells.empty:
            raise RuntimeError(f"{target}: Stage6 winning variant had no SELL_RECOVERY rows")

        selections = {}
        all_symbols = []
        min_date = pd.to_datetime(buys.date).min()
        max_date = pd.to_datetime(sells.date).max()
        for b in buys.itertuples(index=False):
            entry = pd.Timestamp(b.date)
            target_expiry = entry + pd.Timedelta(days=int(b.dte_calendar))
            c = choose_contract(str(b.ticker), target_expiry, float(b.strike), args.api_key, args.api_secret)
            selections[str(b.ticker)] = c
            all_symbols.append(c["symbol"])

        bars = get_daily_bars(sorted(set(all_symbols)), min_date, max_date, args.api_key, args.api_secret)
        model_entry_total = 0.0
        model_entry_covered = 0.0
        observed_entry = 0.0
        model_exit_covered = 0.0
        observed_exit = 0.0

        for b in buys.itertuples(index=False):
            ticker = str(b.ticker)
            c = selections[ticker]
            symbol = c["symbol"]
            contracts = int(b.contracts)
            model_entry = -float(b.cash_flow)
            model_entry_total += model_entry
            obs_entry_px = bar_open_on(bars.get(symbol, []), pd.Timestamp(b.date))

            sell_q = sells[sells.ticker.astype(str).eq(ticker)]
            model_exit = float(sell_q.iloc[0].cash_flow) if not sell_q.empty else np.nan
            sell_date = pd.Timestamp(sell_q.iloc[0].date) if not sell_q.empty else pd.NaT
            obs_exit_px = bar_open_on(bars.get(symbol, []), sell_date) if pd.notna(sell_date) else None

            covered = obs_entry_px is not None and obs_exit_px is not None and math.isfinite(model_exit)
            if covered:
                model_entry_covered += model_entry
                observed_entry += contracts * float(obs_entry_px) * 100.0
                model_exit_covered += model_exit
                observed_exit += contracts * float(obs_exit_px) * 100.0

            selected_rows.append({
                "target": target,
                "episode": episode,
                "winner": winner,
                "ticker": ticker,
                "modeled_contracts": contracts,
                "modeled_entry_date": str(pd.Timestamp(b.date).date()),
                "modeled_target_strike": float(b.strike),
                "modeled_target_dte_calendar": int(b.dte_calendar),
                "modeled_executable_entry_cost": model_entry,
                "modeled_exit_date": "" if pd.isna(sell_date) else str(sell_date.date()),
                "modeled_executable_exit_proceeds": model_exit,
                "selected_option_symbol": symbol,
                "selected_expiration_date": c["expiration_date"],
                "selected_strike_price": c["strike_price"],
                "expiration_error_days": c["expiration_error_days"],
                "relative_strike_error": c["relative_strike_error"],
                "observed_entry_bar_open": obs_entry_px,
                "observed_exit_bar_open": obs_exit_px,
                "observed_roundtrip_complete": bool(covered),
            })

        coverage = model_entry_covered / model_entry_total if model_entry_total > 0 else 0.0
        entry_ratio = observed_entry / model_entry_covered if model_entry_covered > 0 else float("nan")
        exit_ratio = observed_exit / model_exit_covered if model_exit_covered > 0 else float("nan")
        coverage_pass = coverage >= MIN_PREMIUM_COVERAGE
        entry_pass = math.isfinite(entry_ratio) and entry_ratio <= MAX_ENTRY_COST_RATIO
        exit_pass = math.isfinite(exit_ratio) and exit_ratio >= MIN_EXIT_PROCEEDS_RATIO
        gate_pass = bool(coverage_pass and entry_pass and exit_pass)
        episode_results.append({
            "target": target,
            "episode": episode,
            "winner": winner,
            "modeled_entry_total": model_entry_total,
            "modeled_entry_covered": model_entry_covered,
            "observed_entry_total_for_covered_legs": observed_entry,
            "modeled_exit_covered": model_exit_covered,
            "observed_exit_total_for_covered_legs": observed_exit,
            "premium_notional_coverage": coverage,
            "observed_to_modeled_entry_cost_ratio": entry_ratio,
            "observed_to_modeled_exit_proceeds_ratio": exit_ratio,
            "coverage_pass": bool(coverage_pass),
            "entry_cost_pass": bool(entry_pass),
            "exit_value_pass": bool(exit_pass),
            "gate_pass": gate_pass,
        })

    detail = pd.DataFrame(selected_rows)
    result = pd.DataFrame(episode_results)
    detail.to_csv(args.output / "observed_contract_validation.csv", index=False)
    result.to_csv(args.output / "observed_episode_validation.csv", index=False)
    all_pass = bool(len(result) == len(REQUIRED_TARGETS) and result.gate_pass.all())
    report = {
        "status": "PASS",
        "label": LABEL,
        "zero_budget_diagnostic": True,
        "experiment_budget_consumed": False,
        "e8_spent": False,
        "stage6_winner": winner,
        "required_targets": list(REQUIRED_TARGETS),
        "observed_gate": {
            "minimum_premium_notional_coverage": MIN_PREMIUM_COVERAGE,
            "maximum_observed_to_modeled_entry_cost_ratio": MAX_ENTRY_COST_RATIO,
            "minimum_observed_to_modeled_exit_proceeds_ratio": MIN_EXIT_PROCEEDS_RATIO,
            "both_required_target_episodes_must_pass": True,
        },
        "contract_selection": "closest expiration to modeled target DTE, then closest strike to modeled target strike; no future option returns used",
        "data_source": {
            "contracts_endpoint": CONTRACT_URL,
            "historical_bars_endpoint": BARS_URL,
            "history_availability_boundary": "February 2024 onward",
            "historical_bars_feed_field": "not exposed as a request parameter by the documented historical-bars endpoint; evidence grade must record account entitlement separately if known",
        },
        "required_episode_results": episode_results,
        "observed_stage7_gate_passed": all_pass,
        "e8_gate": "OPEN_FOR_ONE_PREREGISTERED_EXPERIMENT" if all_pass else "CLOSED_OBSERVED_OPTIONS_VALIDATION_NO_GO",
        "production_change_authorized": False,
    }
    (args.output / "stage7_summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    files = [args.output / "observed_contract_validation.csv", args.output / "observed_episode_validation.csv", args.output / "stage7_summary.json"]
    (args.output / "STAGE7_SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print(json.dumps(report, indent=2, sort_keys=True))
    print(result.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
