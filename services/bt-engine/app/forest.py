"""The forest map — a run's SHAPE, not its score. PURE (no DB, no I/O).

A backtest currently answers "what did this config return?". That is an exit code.
It cannot answer "why", and the difference is expensive: the 35-names-drifting-to-26
exposure defect was invisible in every summary number while being obvious in the
book's own composition, and the CAGR it produced was measuring a de-risking artifact
rather than the rule under test.

The organising idea (docs/architecture.md "forest map"): the strategy is a moving
FOOTPRINT over the opportunity set. It has an area — how many names, and how much
capital in each — a shape, and both change every session. Wealth lost then decomposes
into distinct, separately-fixable reasons the footprint failed to cover growth:

    footprint too SMALL    → cash drag, position count under the cap
    footprint MOVES a lot  → churn; in the name, but not while it grew
    footprint LEFT early   → the exit fired before the move finished
    footprint WRONG place  → the ordering does not identify growth

This module computes the first three, which need only the run's own trace. The
fourth needs the ranked universe per date (what we DIDN'T hold and how it did) and
is deliberately NOT half-implemented here — see `missing` in the returned dict.

Every number is descriptive. Nothing here decides anything, and a diagnosis drawn
from ONE run is one sample: these are the numbers that tell you where to look, not
findings. Reasons are classified by MECHANISM so a future review can aggregate by
class of intervention rather than re-deriving intent from prose.
"""
from __future__ import annotations

from typing import Mapping, Sequence

# Reason-prefix → mechanism. Matched case-insensitively against the leading text of
# a fill's `reason`, which the sim writes verbatim from the decision that caused it.
# Unmatched reasons land in 'other' rather than being silently dropped — an exit
# route nobody classified is exactly the thing worth noticing.
_MECHANISMS: tuple[tuple[str, str], ...] = (
    ("trailing stop", "trailing_stop"),
    ("delisted", "delist_sweep"),
    ("orphan", "orphan_exit"),
    ("at_risk", "orphan_exit"),
    ("below floor", "floor_exit"),
    ("entry", "entry"),
    ("buy_add", "drift_add"),
    ("sell_trim", "drift_trim"),
    ("drift", "drift_trim"),
)


def classify_reason(reason: str | None, action: str | None = None) -> str:
    """Mechanism that produced a fill. Falls back to the ACTION, then 'other'."""
    text = (reason or "").strip().lower()
    for prefix, mech in _MECHANISMS:
        if text.startswith(prefix) or prefix in text[:40]:
            return mech
    if action in ("entry", "buy_add", "sell_trim", "exit"):
        return {"entry": "entry", "buy_add": "drift_add",
                "sell_trim": "drift_trim", "exit": "other_exit"}[action]
    return "other"


def _chapter_bounds(n_rows: int, n_chapters: int) -> list[tuple[int, int]]:
    """Contiguous, near-equal index ranges. A single average over three years
    destroys exactly the signal worth seeing — 'breadth collapsed in chapter 4 and
    our deployment collapsed with it' is a sentence about a mechanism failing at a
    moment, which no run-level mean can express."""
    if n_rows <= 0 or n_chapters <= 0:
        return []
    n = min(n_chapters, n_rows)
    step, out, start = n_rows / n, [], 0
    for i in range(n):
        end = n_rows if i == n - 1 else int(round(step * (i + 1)))
        if end > start:
            out.append((start, end))
        start = end
    return out


def growth_capture(rankings: Sequence[dict], forward: Mapping[tuple, float],
                   *, top_k: int = 25) -> dict | None:
    """Did the names we PASSED OVER do better than the ones we took?

    The one question a run's own trace cannot answer, and the reason
    bt_sweep_rankings exists. For each date it compares the forward return of the
    SELECTED book against the best-ranked names that were not selected, and splits
    the passed-over group by WHY:

      out_ranked   — the model ranked it below the book. A FACTOR-MODEL miss.
      cap_blocked  — the model ranked it inside the book but the builder refused
                     it (sector, cluster, capacity). A CONSTRUCTION miss.

    That split is the whole point. The two have different fixes, and a single
    "we missed winners" number cannot tell them apart — which is how a
    construction problem gets mistaken for a ranking problem and answered with a
    factor change that could not possibly have helped.

    `forward` maps (date, ticker) -> forward return. Dates with no forward data
    are SKIPPED rather than treated as zero: a horizon that has not elapsed is
    not a flat outcome, and averaging it in would drag every number toward zero
    exactly at the end of a run.
    """
    by_date: dict = {}
    for r in rankings or []:
        d, t = r.get("date"), r.get("ticker")
        if d is None or t is None:
            continue
        by_date.setdefault(d, []).append(r)
    if not by_date:
        return None

    sel_r, out_r, cap_r, n_dates = [], [], [], 0
    for d, rows in by_date.items():
        rows.sort(key=lambda r: r.get("rank") or 10**9)
        got = [forward.get((d, r["ticker"])) for r in rows]
        if not any(v is not None for v in got):
            continue
        n_dates += 1
        for r, fwd in zip(rows, got):
            if fwd is None:
                continue
            if r.get("selected"):
                sel_r.append(fwd)
            elif r.get("reject_reason"):
                cap_r.append(fwd)
            elif (r.get("rank") or 10**9) <= top_k:
                cap_r.append(fwd)      # inside the head but unselected
            else:
                out_r.append(fwd)

    def _avg(xs):
        return round(sum(xs) / len(xs), 6) if xs else None

    sel, out_ranked, cap = _avg(sel_r), _avg(out_r), _avg(cap_r)
    notes = []
    # The interpretation, stated rather than left to the reader — the same
    # reasoning the selection audit uses on the live side.
    if sel is not None and cap is not None and cap > sel:
        notes.append("cap_blocked beat selected — implicates CONSTRUCTION "
                     "(sector/cluster/capacity caps), not the factor model")
    if sel is not None and out_ranked is not None and out_ranked > sel:
        notes.append("out_ranked beat selected — implicates the FACTOR MODEL: "
                     "names it scored below the book did better than the book")
    return {
        "n_dates": n_dates,
        "top_k": top_k,
        "selected_avg_fwd": sel,
        "out_ranked_avg_fwd": out_ranked,
        "cap_blocked_avg_fwd": cap,
        "n_selected": len(sel_r), "n_out_ranked": len(out_r),
        "n_cap_blocked": len(cap_r),
        "notes": notes,
    }


def forest_map(equity: Sequence[dict], trades: Sequence[dict],
               positions: Sequence[dict], *, max_positions: int,
               n_chapters: int = 8,
               rankings: Sequence[dict] | None = None,
               forward_returns: Mapping[tuple, float] | None = None) -> dict:
    """Descriptive shape of one run. See the module docstring for the frame.

    equity/trades/positions are the SimResult lists verbatim. `max_positions` is
    the configured cap, so breadth can be read as a FRACTION of what the config
    asked for — 26 names means nothing without knowing whether the cap was 30 or 50.
    """
    out: dict = {"n_chapters": 0, "missing": []}
    gc = (growth_capture(rankings, forward_returns)
          if rankings and forward_returns else None)
    if gc:
        out["growth_capture"] = gc
    else:
        # Still DECLARED when absent. Silently omitting it reads as "nothing else
        # was available", which is the more dangerous error — it is the difference
        # between "we checked and the book was the best of what we saw" and "we
        # never looked".
        out["missing"].append(
            "growth_capture: needs the ranked universe per date (bt_sweep_rankings) "
            "AND forward returns — pass rankings= and forward_returns=")

    # ── deployment: was the footprint the size the config asked for? ──────────
    by_date: dict = {}
    for p in positions or []:
        d = p.get("date")
        if d is None:
            continue
        slot = by_date.setdefault(d, {"n": 0, "w": 0.0})
        slot["n"] += 1
        slot["w"] += float(p.get("weight") or 0.0)
    dates = sorted(by_date)
    if dates:
        counts = [by_date[d]["n"] for d in dates]
        invested = [by_date[d]["w"] for d in dates]
        cap = max(1, int(max_positions))
        out["deployment"] = {
            "mean_positions": round(sum(counts) / len(counts), 2),
            "min_positions": min(counts),
            "max_positions_held": max(counts),
            "configured_cap": cap,
            "mean_fill_ratio": round(sum(counts) / len(counts) / cap, 4),
            "mean_invested_weight": round(sum(invested) / len(invested), 4),
            "min_invested_weight": round(min(invested), 4),
            # The defect this exists to make visible: a book persistently below
            # its cap with the difference sitting in cash is a de-risking overlay
            # nobody configured, and it silently changes what a run measures.
            "sessions_below_90pct_of_cap": sum(1 for c in counts if c < 0.9 * cap),
            "share_of_sessions_below_90pct": round(
                sum(1 for c in counts if c < 0.9 * cap) / len(counts), 4),
        }

    # ── exits and entries by MECHANISM ───────────────────────────────────────
    mech: dict[str, dict] = {}
    for t in trades or []:
        m = classify_reason(t.get("reason"), t.get("action"))
        row = mech.setdefault(m, {"n": 0, "notional": 0.0, "tx_cost": 0.0})
        row["n"] += 1
        row["notional"] += float(t.get("qty") or 0.0) * float(t.get("price") or 0.0)
        row["tx_cost"] += float(t.get("tx_cost") or 0.0)
    if mech:
        out["by_mechanism"] = {
            k: {"n": v["n"], "notional": round(v["notional"], 2),
                "tx_cost": round(v["tx_cost"], 2)}
            for k, v in sorted(mech.items(), key=lambda kv: -kv[1]["n"])
        }

    # ── churn: names the footprint kept stepping on and off ──────────────────
    entries: dict[str, int] = {}
    for t in trades or []:
        if (t.get("action") or "") == "entry":
            entries[t.get("ticker")] = entries.get(t.get("ticker"), 0) + 1
    repeats = {k: v for k, v in entries.items() if v > 1}
    if entries:
        out["churn"] = {
            "distinct_names_entered": len(entries),
            "names_entered_more_than_once": len(repeats),
            "max_entries_for_one_name": max(entries.values()),
            "repeat_entry_share": round(len(repeats) / len(entries), 4),
            "worst": sorted(repeats.items(), key=lambda kv: -kv[1])[:5],
        }

    # ── chapters: where in TIME the shape changed ────────────────────────────
    eq = [e for e in (equity or []) if e.get("date") is not None]
    eq.sort(key=lambda e: e["date"])
    bounds = _chapter_bounds(len(eq), n_chapters)
    if bounds:
        trades_by_date: dict = {}
        for t in trades or []:
            if t.get("date") is not None:
                trades_by_date.setdefault(t["date"], 0)
                trades_by_date[t["date"]] += 1
        chapters = []
        for lo, hi in bounds:
            span = eq[lo:hi]
            first, last = span[0], span[-1]
            pv0, pv1 = float(first.get("portfolio_value") or 0), float(last.get("portfolio_value") or 0)
            sv0 = float(first.get("spy_value") or 0)
            sv1 = float(last.get("spy_value") or 0)
            span_dates = {r["date"] for r in span}
            held = [by_date[d]["n"] for d in dates if d in span_dates] if dates else []
            chapters.append({
                "from": str(first["date"]), "to": str(last["date"]),
                "book_return": round(pv1 / pv0 - 1.0, 4) if pv0 else None,
                "spy_return": round(sv1 / sv0 - 1.0, 4) if sv0 else None,
                "excess": (round((pv1 / pv0) - (sv1 / sv0), 4)
                           if pv0 and sv0 else None),
                "worst_drawdown": round(min(
                    (float(r.get("drawdown") or 0.0) for r in span), default=0.0), 4),
                "mean_positions": (round(sum(held) / len(held), 2) if held else None),
                "n_fills": sum(trades_by_date.get(d, 0) for d in span_dates),
            })
        out["chapters"] = chapters
        out["n_chapters"] = len(chapters)
        # The single most useful pointer: which slice of time cost the most
        # RELATIVE to the benchmark. Where to look, not what is wrong.
        scored = [(c["excess"], i) for i, c in enumerate(chapters)
                  if c["excess"] is not None]
        if scored:
            out["worst_chapter_idx"] = min(scored)[1]
    return out
