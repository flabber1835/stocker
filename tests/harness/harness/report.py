"""
Report generation for harness simulation runs.

Produces:
  - A human-readable text report (.txt)
  - A machine-readable observations dump (_obs.json)

Both files are written to *report_dir* with a YYYYMMDD_HHMMSS prefix.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import List

from .scenario import DayObservation, Scenario


def generate_report(
    scenario: Scenario,
    observations: List[DayObservation],
    report_dir: str = "tests/harness/reports",
) -> str:
    """
    Build the text report and JSON observations file.

    Returns the full text report string.
    """
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    txt_path  = os.path.join(report_dir, f"{timestamp}_{scenario.name}.txt")
    json_path = os.path.join(report_dir, f"{timestamp}_{scenario.name}_obs.json")

    report_text = _build_text_report(scenario, observations)
    obs_json    = _build_obs_json(observations)

    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(report_text)

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(obs_json, fh, indent=2, default=str)

    return report_text


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_text_report(
    scenario: Scenario,
    observations: List[DayObservation],
) -> str:
    lines: List[str] = []

    # ── Header ─────────────────────────────────────────────────────────────
    lines.append(f"=== SIMULATION REPORT: {scenario.name} ===")
    if scenario.description:
        lines.append(scenario.description)
    lines.append(
        f"Period: {scenario.start_date} → {scenario.end_date} "
        f"({len(observations)} trading days)"
    )
    lines.append(f"Universe: {scenario.universe_size} tickers")
    lines.append(f"Seed: {scenario.seed}")
    lines.append("")

    # ── Day-by-day summary (every 10th day) ────────────────────────────────
    lines.append("DAY-BY-DAY SUMMARY (every 10th day):")
    for i, obs in enumerate(observations):
        if i % 10 != 0:
            continue
        lines.append(
            f"  {obs.date}: {obs.position_count} positions "
            f"| ${obs.account_value:,.0f} account value "
            f"| {obs.regime}"
            + (f" [{obs.label}]" if obs.label else "")
        )
    lines.append("")

    # ── Regime transitions ──────────────────────────────────────────────────
    lines.append("REGIME TRANSITIONS:")
    prev_regime = ""
    for obs in observations:
        if obs.regime != prev_regime:
            if prev_regime:
                lines.append(f"  {obs.date}: {prev_regime} → {obs.regime}")
            else:
                lines.append(f"  {obs.date}: (start) {obs.regime}")
            prev_regime = obs.regime
    lines.append("")

    # ── Final metrics ───────────────────────────────────────────────────────
    initial_value  = observations[0].account_value  if observations else 0.0
    final_value    = observations[-1].account_value if observations else 0.0
    pct_change     = (
        ((final_value - initial_value) / initial_value * 100)
        if initial_value else 0.0
    )
    peak_positions = max((o.position_count for o in observations), default=0)
    peak_date      = next(
        (o.date for o in observations if o.position_count == peak_positions),
        None,
    )
    avg_positions  = (
        sum(o.position_count for o in observations) / len(observations)
        if observations else 0.0
    )
    total_submitted = sum(o.intents_submitted for o in observations)
    total_accepted  = sum(o.intents_accepted  for o in observations)
    total_rejected  = total_submitted - total_accepted

    sign = "+" if pct_change >= 0 else ""
    lines.append("FINAL METRICS:")
    lines.append(f"  Initial account value:  ${initial_value:,.0f}")
    lines.append(
        f"  Final account value:    ${final_value:,.0f} "
        f"({sign}{pct_change:.1f}%)"
    )
    lines.append(
        f"  Peak positions:         {peak_positions}"
        + (f" (on {peak_date})" if peak_date else "")
    )
    lines.append(f"  Average positions:      {avg_positions:.1f}")
    lines.append(f"  Total trades submitted: {total_submitted}")
    lines.append(f"  Total trades accepted:  {total_accepted}")
    lines.append(f"  Total trades rejected:  {total_rejected}")
    lines.append("")

    # ── Restart recovery summary (only if any restarts were performed) ─────
    restart_obs = [o for o in observations if "recovered_in_" in o.label or "missed_window" in o.label]
    if restart_obs:
        lines.append("RESTART RECOVERY SUMMARY:")
        for obs in restart_obs:
            lines.append(f"  {obs.date}: {obs.label}")
        lines.append("")

    # ── Full observations log ───────────────────────────────────────────────
    lines.append("OBSERVATIONS LOG:")
    header = (
        f"  {'Date':<12} {'Positions':>10} {'Acct Value':>14} {'Cash':>12} "
        f"{'Regime':<14} {'Pipeline':<12} {'Submitted':>10} {'Accepted':>9}  Label"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for obs in observations:
        lines.append(
            f"  {str(obs.date):<12} {obs.position_count:>10} "
            f"${obs.account_value:>13,.0f} ${obs.cash:>11,.0f} "
            f"{obs.regime:<14} {obs.pipeline_status:<12} "
            f"{obs.intents_submitted:>10} {obs.intents_accepted:>9}  "
            f"{obs.label}"
        )

    return "\n".join(lines) + "\n"


def _build_obs_json(observations: List[DayObservation]) -> List[dict]:
    return [
        {
            "date":              obs.date.isoformat(),
            "position_count":   obs.position_count,
            "account_value":    obs.account_value,
            "cash":             obs.cash,
            "regime":           obs.regime,
            "label":            obs.label,
            "pipeline_status":  obs.pipeline_status,
            "intents_submitted": obs.intents_submitted,
            "intents_accepted":  obs.intents_accepted,
        }
        for obs in observations
    ]
