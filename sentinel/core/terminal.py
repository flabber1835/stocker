"""SHARADAR/ACTIONS -> terminal events, carried across INTACT.

Every rule here was a defect found the hard way, so this is a faithful port of
`services/backtester/app/wealth_core_replay.py terminal_from_action` rather than
a fresh reading of the vendor's schema. `tests/sentinel/test_terminal.py` pins
the two against each other across a matrix of rows; separate code by necessity —
Sentinel may not import a retired Stocker service — must not become separate
behaviour.

> **This belongs in `shared/` eventually.** Promoting it, and leaving the
> backtester with a re-export shim, is the correct end state — one mapping, one
> module, the treatment `strategy_engine` already got. It is NOT done today
> because a Wealth Core certification rehearsal is in flight and that refactor
> touches the code being certified. Do it when the run lands.

## The four rules, and what each one cost

```text
A TERMINAL ACTION WITHOUT TERMS IS INCOMPLETE, NOT A WRITE-OFF
    Mapping `delisted` to a write-off is the obvious implementation and it
    fabricates a total loss. Every admission is 4% of EQUITY, so an invented
    zero permanently shrinks every position opened afterwards — and the run
    stays complete and plausible throughout. Zero is a TERM: it must be stated,
    never inferred from silence.

`value` IS A DEAL SIZE IN MILLIONS, NEVER A RATIO OR A PRICE   (defect D2)
    Identical on the `delisted` and `acquisitionby` rows of one event, and its
    magnitudes are company sizes. Read as an exchange ratio, a TMHC holder would
    have been delivered 6,768.8 shares per share. Provenance only.

'N/A' IS A SENTINEL, NOT A COUNTERPARTY                        (defect D1)
    `row.get("contraticker") or None` normalises None and '' and looks total —
    and passes 'N/A' straight through as truthy. Every terminal row then took
    the security-for-security branch and blocked. All 19,216 of them: the
    permanent block that froze a three-year rehearsal. **Any `or None` over a
    vendor string is suspect for this reason.**

IDENTITY IS RESOLVED BY THE CALLER
    `row["ticker"]` is an observation label. The episode this terminates is
    keyed on the PERMANENT id, so terms carrying a ticker match no holding and
    every action silently returns NOT_HELD. An unattributable action is NOT
    emitted — applying a terminal event to a security nobody can name is worse
    than missing one.
```

`acquisitionof` and `mergerfrom` are the ACQUIRER's side and are deliberately
not terminal for this security. An unknown action is treated as non-terminal,
which is the safe direction: a missed termination blocks and is visible, a false
one destroys a live holding.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping, Optional, Sequence

from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


class ActionSide(Enum):
    TARGET = "target"        # this security ENDS
    ACQUIRER = "acquirer"    # this security continues


TERMINAL_ACTION_SIDES: dict[str, ActionSide] = {
    "delisted": ActionSide.TARGET,
    "acquisitionby": ActionSide.TARGET,          # acquired BY someone
    "mergerto": ActionSide.TARGET,               # merged INTO something
    "bankruptcyliquidation": ActionSide.TARGET,
    "regulatorydelisting": ActionSide.TARGET,
    "voluntarydelisting": ActionSide.TARGET,
    "acquisitionof": ActionSide.ACQUIRER,        # NOT terminal for this security
    "mergerfrom": ActionSide.ACQUIRER,           # NOT terminal for this security
}

#: The names that END this security's holding.
TERMINAL_ACTIONS = frozenset(
    k for k, v in TERMINAL_ACTION_SIDES.items() if v is ActionSide.TARGET)

SPLIT_ACTIONS = frozenset({"split", "adrratiosplit"})
DIVIDEND_ACTIONS = frozenset({"dividend", "specialdividend", "spinoffdividend"})

#: Vendor placeholders that mean ABSENCE. `contraticker` carries the literal
#: string 'N/A' whenever an acquirer is PRIVATE.
VENDOR_SENTINELS = frozenset({"N/A", "NA", "NONE", "NULL", "-", "--"})


def vendor_symbol(v) -> Optional[str]:
    """A vendor symbol field, or None when it states absence. See defect D1."""
    if v is None:
        return None
    t = str(v).strip()
    if not t or t.upper() in VENDOR_SENTINELS:
        return None
    return t


def terminal_from_action(row: Mapping, session: str, *,
                         security_id: Optional[str] = None,
                         delivered_security_id: Optional[str] = None,
                         delivered_issuer_id: Optional[str] = None
                         ) -> Optional[TerminalTerms]:
    """One ACTIONS row -> the terminal terms it actually supports, or None."""
    action = (row.get("action") or "").lower()
    if action not in TERMINAL_ACTIONS:
        return None
    sid = security_id
    if not sid:
        return None

    # `value` is the TRANSACTION VALUE IN MILLIONS. Provenance, never a share or
    # price input — see the module docstring, defect D2.
    deal_value_musd = row.get("value")
    deal_value_musd = (float(deal_value_musd)
                       if deal_value_musd is not None else None)
    contra = vendor_symbol(row.get("contraticker"))
    # The acquirer's NAME is populated even when its ticker is 'N/A' (a PRIVATE
    # buyer), so it is the only counterparty identity available for those deals.
    contra_name = vendor_symbol(row.get("contraname"))

    ref = f"actions/{action}"
    if deal_value_musd is not None:
        ref += f" deal_value_musd={deal_value_musd:g}"
    if contra_name:
        ref += f" counterparty={contra_name}"

    if contra:
        # A PUBLIC acquirer: the delivered security is nameable, the ratio that
        # would size the delivery is not in the table. `exchange_ratio` stays
        # None rather than being filled with the deal value, so `completeness()`
        # refuses with MISSING_EXCHANGE_RATIO — the honest reason.
        return TerminalTerms(
            session=session, security_id=sid,
            kind=TerminalKind.CONVERSION,
            delivered_security_id=delivered_security_id,
            delivered_ticker=contra,
            delivered_issuer_id=delivered_issuer_id,
            exchange_ratio=None,
            # A fractional entitlement needs a settlement price and ACTIONS does
            # not carry one. Left None so `completeness()` blocks the deal that
            # actually produces a fraction, rather than silently dropping the
            # stub — real money leaving the book with no record.
            cash_in_lieu_price_per_delivered_share=None,
            reference=ref)

    # No stated-zero write-off route. `value == 0.0` is a statement about DEAL
    # SIZE and says nothing about consideration, so reading it as "holders
    # received nothing" wrote positions off on evidence that never existed.
    #
    # Everything else is a terminal event with no terms: a CASH_MERGER with
    # `cash_per_share=None`, which `completeness()` rejects and `apply_terminal`
    # records as BLOCKED. The chosen kind is immaterial — it never applies — and
    # the ORIGINAL action name rides in `reference` so the audit says what
    # happened rather than what shape was used to block it.
    return TerminalTerms(session=session, security_id=sid,
                         kind=TerminalKind.CASH_MERGER,
                         cash_per_share=None, reference=ref)


def load_terminal_events(conn, *, start: str, end: str,
                         resolve_identity=None) -> list:
    """Read `sentinel_actions` and map the terminal ones.

    `resolve_identity(ticker, session) -> security_id | None`. An unresolvable
    row is SKIPPED and counted rather than keyed on its ticker: terms carrying a
    ticker match no holding, so every such action would silently return NOT_HELD
    and the termination would be invisible rather than refused.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, session, action, value, contraticker"
            " FROM sentinel_actions WHERE session BETWEEN %s AND %s"
            " ORDER BY session, ticker, action", (start, end))
        rows = cur.fetchall()

    out = []
    for ticker, session, action, value, contraticker in rows:
        s = str(session)
        sid = resolve_identity(str(ticker), s) if resolve_identity else None
        terms = terminal_from_action(
            {"ticker": ticker, "action": action, "value": value,
             "contraticker": contraticker}, s, security_id=sid)
        if terms is not None:
            # `TerminalTerms` directly. `run.TerminalEvent` READS like a wrapper
            # type and is a back-compat FACTORY over TerminalTerms for the two
            # original kinds — it cannot express CONVERSION at all, which is
            # exactly what a public acquirer produces.
            out.append(terms)
    return out
