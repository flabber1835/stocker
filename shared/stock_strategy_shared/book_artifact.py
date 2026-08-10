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

## Why it lives in `shared/` and NOT under `wealth_core/`

The producer is bt-engine's `rehearse_chain`, on the retired Stocker side. The
consumer is `sentinel rejection-audit`. Neither may import the other — a
Sentinel that needs a retired service is not a retirement, and bt-engine has no
`sentinel/` in its image — so one implementation has to sit where both can
reach it. `sentinel/core/book_artifact.py` is a re-export shim preserving module
IDENTITY, the same pattern `strategy_engine` and `core/terminal` already use.

It is deliberately NOT inside `stock_strategy_shared/wealth_core/`, even though
it reads a `RunResult`. That package's source tree is hashed as
`wealth_core_source` in every certification record, and it has been byte-identical
across three reviews — a property worth more than the tidier import path. This
module executes during no run and changes no economics; putting it where it
would move the engine's source hash would spend that invariant on a reporting
helper.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

#: Bumped when the fields a consumer depends on change shape. A reader that
#: parses an unknown schema hopefully is how a fail-closed gate acquires a
#: silent failure mode.
SCHEMA = "stock_strategy_shared.book_artifact/1"


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
    # STILL-OPEN HOLDINGS, from `episodes` — which is where they actually live.
    #
    # This read `state.holdings`, an attribute `PortfolioState` does not have.
    # The unit of holding state is the EPISODE (that is what makes the trailing
    # stop's "does not reset except when a new holding episode begins"
    # meaningful), and the episode is also where the CURRENT ticker is stored.
    # A local test fake that defined `.holdings` hid the mismatch completely:
    # against the real classes, a security bought as OLD and relabelled to NEW
    # returned {OLD} alone.
    #
    # That gap matters more than an ordinary missing source, because
    # `apply_ticker_changes` posts NO LEDGER EVENT by design — a relabelling
    # moves no money — so the ledger cannot recover the new label at all.
    state = getattr(result, "state", None)
    if state is not None:
        _tickers_from(getattr(state, "episodes", None), out)
        # `holdings` kept as a tolerated alias: some result shapes carry one,
        # and an extra name is the safe direction.
        _tickers_from(getattr(state, "holdings", None), out)
        # AND a structural sweep of the whole serialised state. Reading named
        # attributes is exactly what failed here — an assumption about a field
        # name, invisible until checked against the real object. The serialised
        # form finds a ticker wherever it moves to next.
        to_dict = getattr(state, "to_dict", None)
        if callable(to_dict):
            try:
                _tickers_from(to_dict(), out)
            except Exception:                               # noqa: BLE001
                pass
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
        "schema": SCHEMA,
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


def load(path: str | Path, *, start: Optional[str] = None,
         end: Optional[str] = None) -> tuple[list[str], list[str]]:
    """Read an artifact, REFUSING a partial one or one for the wrong window.

    Both keys are required. `dict.get(key, [])` would turn a file that names
    only `held` into the claim "nothing was pending terminal settlement" —
    silently, and specifically for the field most likely to be forgotten. Half
    a book is UNKNOWN, and the audit already says so; it can only say it if
    this refuses to invent the missing half.

    THE WINDOW MUST MATCH EXACTLY when the caller supplies one. A valid 2022
    book handed to a 2021-2023 audit is the same class of defect one layer up:
    every name held only in 2021 or 2023 is absent, so a refused row on one of
    them is judged by the ADMISSION floors — which do not govern an open
    position — and can be cleared. A well-formed file for the wrong period is
    more dangerous than a malformed one, because nothing about it looks wrong.
    """
    data = json.loads(Path(path).read_text())
    schema = data.get("schema")
    if schema != SCHEMA:
        raise ValueError(
            f"the book artifact declares schema {schema!r}, not {SCHEMA!r}. "
            f"Refused rather than parsed hopefully: the fields this reads are "
            f"the fields a fail-closed gate depends on.")
    missing = [k for k in ("held", "pending_terminal") if k not in data]
    if missing:
        raise ValueError(
            f"the book artifact is missing {missing}. Both keys are required: "
            f"an absent key is not an empty list, and treating it as one would "
            f"assert that nothing was held or nothing was pending — the exact "
            f"vacuous claim the audit's fail-closed rule exists to prevent. "
            f"Emit it with stock_strategy_shared.book_artifact.write().")
    for k in ("held", "pending_terminal"):
        if not isinstance(data[k], list):
            raise ValueError(f"the book artifact's {k!r} is not a list")

    if start is not None or end is not None:
        window = data.get("window") or {}
        got = (window.get("start"), window.get("end"))
        if got != (start, end):
            raise ValueError(
                f"the book artifact covers {got[0]}..{got[1]} and the audit is "
                f"for {start}..{end}. Refused: a book for a NARROWER or SHIFTED "
                f"window omits every security held outside it, and a refused "
                f"row on one of those would then be judged by admission floors "
                f"that do not govern a position the run actually held. Emit a "
                f"book for the interval being certified.")
    return ([str(t).upper() for t in data["held"]],
            [str(t).upper() for t in data["pending_terminal"]])


__all__ = ["SCHEMA", "from_run_result", "held_tickers", "load",
           "pending_terminal_tickers", "write"]
