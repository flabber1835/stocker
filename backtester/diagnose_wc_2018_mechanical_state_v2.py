#!/usr/bin/env python3
"""Compatibility runner for the zero-budget 2018 Wealth Core mechanical diagnostic.

The original diagnostic was written against pre-correction retained-replay source
seams. Strategy 9 now preserves two corrected semantics before this diagnostic
instruments the generated replay:

1. age-119 review basis is the split-adjusted execution-session OPEN (``opsig``),
   not the fill-session signal CLOSE (``clsig``);
2. the broad independent-security replay expresses issuer identity through
   ``issuer_key(..., ds)`` rather than the older direct ``issuer[...]`` lookup.

This wrapper adapts ONLY the diagnostic's exact source-matching templates to those
current seams. The replacement text is adapted in the same way, so the generated
replay retains the current Strategy 9 economics byte-for-byte at those seams.
The diagnostic also uses a horizon-scoped output normalizer because its replay
stops after 2019-03-31 and therefore cannot satisfy Strategy 9's ordinary
2021-2026 reporting windows. No strategy decision, threshold, timing rule, or
portfolio state is changed.
"""
from __future__ import annotations

from pathlib import Path

from backtester import diagnose_wc_2018_mechanical_state as diag


_ORIGINAL_REPLACE_ONCE = diag.replace_once


def _current_seam_replace(text: str, old: str, new: str, label: str) -> str:
    if label == "fill diagnostic":
        legacy = "s.entry_sig=float(clsig[tid]) if finite(clsig[tid]) else np.nan"
        current = (
            "s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) "
            "and opsig[tid]>0 else np.nan"
        )
        if legacy not in old or legacy not in new:
            raise RuntimeError("fill diagnostic compatibility template drifted")
        old = old.replace(legacy, current)
        new = new.replace(legacy, current)

    elif label == "admission pressure diagnostic":
        # The broad Strategy 9 lineage deliberately made every security its own
        # issuer by defining issuer_key() to SID:<security>. Keep that exact
        # current semantic while adapting the old diagnostic template.
        substitutions = (
            ("issuer[s.tid]", "issuer_key(s.tid,ds)"),
            ("issuer[s.pending_tid]", "issuer_key(s.pending_tid,ds)"),
            ("issuer[tid]", "issuer_key(tid,ds)"),
        )
        for legacy, current in substitutions:
            old = old.replace(legacy, current)
            new = new.replace(legacy, current)

    return _ORIGINAL_REPLACE_ONCE(text, old, new, label)


def _finalize_diagnostic_horizon(output: Path) -> None:
    """Normalize raw replay output for the diagnostic's bounded horizon only.

    The generated Strategy 9 replay already emits the complete chronological
    daily path and raw summary. The ordinary Strategy 9 finalizer additionally
    computes fixed 5/10/15/20-year windows ending in 2026; those windows are
    intentionally unavailable after this diagnostic truncates at 2019-03-31.
    The mechanical diagnostic consumes only the normalized daily evidence.
    """
    daily_path = output / "daily.csv"
    summary_path = output / "summary.json"
    if not daily_path.exists() or not summary_path.exists():
        raise RuntimeError("diagnostic replay did not emit required raw outputs")

    daily = diag.pd.read_csv(daily_path, parse_dates=["date"])
    daily = daily[daily["date"] <= diag.pd.Timestamp("2019-03-31")].copy()
    daily.rename(
        columns={
            "shadow_equity": "research_wealth_core_equity",
            "open_equity": "research_wealth_core_open_equity",
            "control_nav": "research_nav",
            "control_allocation": "research_allocation",
        },
        inplace=True,
    )
    required = {
        "date",
        "research_wealth_core_equity",
        "research_nav",
        "research_allocation",
        "spy_nav",
    }
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"diagnostic daily evidence missing: {sorted(missing)}")
    if daily.empty or daily["date"].max() < diag.pd.Timestamp("2018-12-31"):
        raise RuntimeError("diagnostic replay did not reach the complete 2018 evidence window")

    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
    daily.to_csv(
        output / "daily.csv.gz",
        index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
    daily_path.unlink()


def main() -> int:
    diag.replace_once = _current_seam_replace
    diag.strategy9.finalize = _finalize_diagnostic_horizon
    return diag.main()


if __name__ == "__main__":
    raise SystemExit(main())
