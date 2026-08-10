"""What the run HELD, emitted by the run. No human in the evidentiary chain.

The rejection audit's two strongest materiality checks ask whether a refused
price row intersects a security the run held or was waiting on a terminal
settlement for. Those inputs used to arrive as a comma-separated list on a
command line, which puts human transcription between the machine that knows the
answer and the verdict that depends on it. A mistyped ticker there does not
produce an error; it produces a CLEAN certification.

So the run emits the answer itself:

```text
RunResult  ->  book_artifact.from_run_result()  ->  book.json
                                                        |
                             sentinel rejection-audit --book book.json
```

## The union is deliberately OVER-inclusive

Every source that can name a security the run touched is unioned, and anything
ambiguous is INCLUDED rather than excluded. That asymmetry is the whole design:

```text
a ticker wrongly PRESENT    an irrelevant rejection is called MATERIAL.
                            The interval refuses, a human looks, and says so.
                            Costly, visible, safe
a ticker wrongly ABSENT     a rejection on a security the run actually held is
                            judged by the ADMISSION floors — which do not govern
                            an open position at all — and can be cleared.
                            Free, invisible, wrong
```

There is no symmetry to preserve here. The audit is a fail-closed gate, so its
inputs bias toward blocking.

## Raw vendor tickers, not security ids

The audit keys on the RAW VENDOR TICKER, because that is the only thing a
refused row has: a bar dropped for unresolvable identity has no security id by
definition — that is why it was dropped. So this collects tickers, and collects
them from every label a security carried during the interval rather than only
its last one. A rename mid-interval means two tickers named the same company,
and the refusal could be filed under either.

## It reads the run, it does not re-run anything

Every source here is already retained on `RunResult` and already hashed, or is
audit-only state. Nothing is recomputed, no engine call is made, and no parity
hash can move as a result — the artifact is a projection of what the run
already produced.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def _tickers_from(obj: Any, out: set[str], *, depth: int = 0) -> None:
    """Collect every `ticker`-ish string reachable in a nested structure.

    Structural rather than schema-specific ON PURPOSE. The alternative is a
    list of known key paths, which silently stops finding things the day a
    field is added or renamed — and "silently stops finding things" is the
    exact failure this artifact exists to prevent. A field that is not a ticker
    but is named one would over-include, which is the safe direction.
    """
    if depth > 12 or obj is None:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v and (
                    k == "ticker" or k.endswith("_ticker")):
                out.add(v.upper())
            else:
                _tickers_from(v, out, depth=depth + 1)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            _tickers_from(v, out, depth=depth + 1)
    else:
        t = getattr(obj, "ticker", None)
        if isinstance(t, str) and t:
            out.add(t.upper())
        d = getattr(obj, "to_dict", None)
        if callable(d):
            try:
                _tickers_from(d(), out, depth=depth + 1)
            except Exception:                               # noqa: BLE001
                pass


def held_tickers(result) -> set[str]:
    """Every raw ticker the book held at ANY point in the run.

    The LEDGER is the primary source and is the right one: it is append-only,
    always retained, and a security cannot be held without a fill naming it.
    `sessions` is not — it is elided above 400 sessions, so a three-year run
    would answer this question from a truncated record and under-report exactly
    where the interval is longest.
    """
    out: set[str] = set()
    ledger = getattr(result, "ledger", None)
    if ledger is not None:
        _tickers_from(getattr(ledger, "events", []) or [], out)
        _tickers_from(getattr(ledger, "receivables", []) or [], out)
    # Still-open holdings at the end, plus the per-session facts that survive
    # elision. Belt and braces: each of these alone should be a subset of the
    # ledger's names, and a disagreement means the ledger is not the complete
    # record this assumes it is — over-including is how that stays safe.
    state = getattr(result, "state", None)
    if state is not None:
        _tickers_from(getattr(state, "holdings", None), out)
    _tickers_from(getattr(result, "session_facts", []) or [], out)
    return out


def pending_terminal_tickers(result) -> set[str]:
    """Every raw ticker with a terminal event the run was carrying or resolved.

    Both, not just the still-pending ones. A terminal event that RESOLVED
    mid-interval was pending before it did, and a refused price row on one of
    those sessions is exactly as material — the grace window is when a missing
    print changes the settlement price.
    """
    out: set[str] = set()
    _tickers_from(getattr(result, "terminal_results", []) or [], out)
    state = getattr(result, "state", None)
    if state is not None:
        for attr in ("terminal_pending_terms", "terminal_carry_audit"):
            _tickers_from(getattr(state, attr, None), out)
        # `terminal_pending_sessions` is keyed on SECURITY ID with an int
        # value, so the structural walk finds nothing in it. The ids are still
        # worth recording — they name securities the audit may be able to match
        # by other means, and an empty field here would misrepresent the run as
        # having carried nothing.
        pending = getattr(state, "terminal_pending_sessions", None) or {}
        out.update(str(k).upper() for k in pending)
    return out


def from_run_result(result, *, start: str, end: str,
                    extra_held: Iterable[str] = ()) -> dict:
    """The artifact. Both keys ALWAYS present, even when empty.

    An empty list here is a positive claim — "the run held nothing" — and it is
    only ever made by this function, which knows. A caller that supplies
    nothing gets UNKNOWN from the audit instead, which is a different and much
    weaker statement.
    """
    held = held_tickers(result) | {str(t).upper() for t in extra_held}
    pending = pending_terminal_tickers(result)
    return {
        "schema": "sentinel.book_artifact/1",
        "window": {"start": start, "end": end},
        "held": sorted(held),
        "pending_terminal": sorted(pending),
        "counts": {"held": len(held), "pending_terminal": len(pending)},
        "note": ("Union over the WHOLE interval, not an end-of-run snapshot, "
                 "and deliberately over-inclusive: a ticker wrongly present "
                 "makes a rejection MATERIAL (visible, safe), one wrongly "
                 "absent lets a rejection on a held security be cleared by "
                 "admission floors that do not govern it."),
    }


def write(result, path: str | Path, *, start: str, end: str) -> dict:
    """Emit beside the run's other evidence. Returns what was written."""
    rec = from_run_result(result, start=start, end=end)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2, sort_keys=True))
    return rec


def load(path: str | Path) -> tuple[list[str], list[str]]:
    """Read an artifact, REFUSING a partial one.

    Both keys are required. `dict.get(key, [])` would turn a file that names
    only `held` into the claim "nothing was pending terminal settlement" —
    silently, and specifically for the field most likely to be forgotten. Half
    a book is UNKNOWN, and the audit already says so; it can only say it if
    this refuses to invent the missing half.
    """
    data = json.loads(Path(path).read_text())
    missing = [k for k in ("held", "pending_terminal") if k not in data]
    if missing:
        raise ValueError(
            f"the book artifact is missing {missing}. Both keys are required: "
            f"an absent key is not an empty list, and treating it as one would "
            f"assert that nothing was held or nothing was pending — the exact "
            f"vacuous claim the audit's fail-closed rule exists to prevent. "
            f"Emit it with sentinel.core.book_artifact.write().")
    for k in ("held", "pending_terminal"):
        if not isinstance(data[k], list):
            raise ValueError(f"the book artifact's {k!r} is not a list")
    return ([str(t).upper() for t in data["held"]],
            [str(t).upper() for t in data["pending_terminal"]])


__all__ = ["from_run_result", "held_tickers", "load",
           "pending_terminal_tickers", "write"]
