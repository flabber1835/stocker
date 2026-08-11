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

from dataclasses import dataclass
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


#: EXCLUSIONS — deterministic reasons a discovered row is not an economically
#: relevant termination. Every one is a positive statement about WHY, never a
#: generic "not relevant": a catch-all bucket is where a mapping failure hides,
#: and the whole point of this accounting is that nothing disappears quietly.
EXCLUDED_ACQUIRER_SIDE = "ACQUIRER_SIDE_NOT_TERMINAL"
"""`acquisitionof` / `mergerfrom` — the ACQUIRER's row. This security continues."""

EXCLUDED_NON_TERMINAL = "NON_TERMINAL_ACTION_TYPE"
"""A known action that ends nothing: split, dividend, ticker change."""

EXCLUDED_UNSUPPORTED = "UNSUPPORTED_ACTION_TYPE"
"""An action name the mapping does not know. Treated as non-terminal, which is
the safe direction — a missed termination BLOCKS and is visible, a false one
destroys a live holding — but it is COUNTED, because a vendor introducing a new
terminal action name would otherwise be silent."""

EXCLUDED_OUTSIDE_WINDOW = "OUTSIDE_OPERATIONAL_WINDOW"
"""Dated outside the window being loaded."""

EXCLUDED_DUPLICATE = "DUPLICATE_VENDOR_ROW"
"""A second row with the same (ticker, session, action). Applying a termination
twice is not idempotent — the first releases the episode and the second finds
NOT_HELD — so duplicates are collapsed rather than replayed."""

EXCLUDED_ABSENT_FROM_CORPUS = "SECURITY_ABSENT_FROM_CORPUS"
"""No bar carries this ticker anywhere in the window, so no book could have held
it and no termination of it can change one.

DELIBERATELY KEYED ON THE RAW VENDOR TICKER, not on a resolved security. Keying
on resolution would make this bucket swallow exactly the failures it must not
hide: a security whose identity never resolves has its bars dropped too, so it
would look "absent from the corpus" and its unresolved termination would vanish
into a legitimate-sounding exclusion. Keyed on the ticker, a security that was
PRICED but cannot be NAMED stays unresolved and stays loud."""

#: FAILURES — an economically relevant termination that cannot be attributed.
#: Any of these inside the window makes Sentinel NOT READY.
UNRESOLVED_REASONS = frozenset({
    "NO_PERMANENT_ID", "AMBIGUOUS_IDENTITY", "TICKER_REUSE_UNRESOLVED",
    "IDENTITY_INTERVAL_GAP", "MULTIPLE_EFFECTIVE_MAPPINGS",
    "TERMS_NOT_EXPRESSIBLE"})


@dataclass(frozen=True)
class TerminalRow:
    """One discovered ACTIONS row and what became of it."""
    ticker: str
    session: str
    action: str
    disposition: str            # resolved | excluded | unresolved
    reason: str = ""
    security_id: Optional[str] = None

    def describe(self) -> str:
        return (f"{self.session} {self.ticker} {self.action.upper()}"
                f" reason={self.reason}" if self.reason
                else f"{self.session} {self.ticker} {self.action.upper()}")


@dataclass(frozen=True)
class TerminalLoadResult:
    """Terminal events, WITH the accounting that proves none went missing.

    The previous loader returned a bare list and dropped unresolvable rows on
    the floor — its own docstring said they were "SKIPPED and counted", and
    nothing counted them. Readiness could then be green on `COUNT(*) FROM
    sentinel_actions` while an individual termination had disappeared, so the
    book could hold a security that had been acquired and nothing would say so.

    CONSERVATION IS THE POINT:

        discovered == excluded + resolved + unresolved
        relevant   == resolved + unresolved

    Two equations rather than one, because they fail differently: the first
    catches a row that was neither used nor accounted for, the second catches a
    row miscounted as irrelevant.
    """
    events: list
    rows: list

    @property
    def discovered(self) -> int:
        return len(self.rows)

    @property
    def excluded(self) -> list:
        return [r for r in self.rows if r.disposition == "excluded"]

    @property
    def resolved(self) -> list:
        return [r for r in self.rows if r.disposition == "resolved"]

    @property
    def unresolved(self) -> list:
        return [r for r in self.rows if r.disposition == "unresolved"]

    @property
    def relevant(self) -> int:
        return len(self.resolved) + len(self.unresolved)

    def conservation_holds(self) -> bool:
        return (self.discovered
                == len(self.excluded) + len(self.resolved) + len(self.unresolved)
                and self.relevant == len(self.resolved) + len(self.unresolved))

    def exclusion_counts(self) -> dict:
        out: dict = {}
        for r in self.excluded:
            out[r.reason] = out.get(r.reason, 0) + 1
        return dict(sorted(out.items()))

    def to_dict(self) -> dict:
        return {
            "discovered": self.discovered,
            "relevant": self.relevant,
            "resolved": len(self.resolved),
            "excluded": len(self.excluded),
            "unresolved": len(self.unresolved),
            "conservation_holds": self.conservation_holds(),
            "exclusions": self.exclusion_counts(),
            # The offending rows THEMSELVES. An operator needs the date, the
            # ticker, the action and the reason — "unresolved: 1" is a number
            # nobody can act on.
            "unresolved_rows": [
                {"session": r.session, "ticker": r.ticker, "action": r.action,
                 "reason": r.reason} for r in self.unresolved],
        }


def _corpus_tickers(conn, start: str, end: str) -> set:
    """Every ticker the VENDOR PRICED in the window, by raw symbol.

    STORED BARS *UNION* INGEST REJECTIONS, and the union is the whole point.

    Raw symbol rather than resolved security was necessary but not sufficient:
    `sentinel_bars` only ever contains rows that RESOLVED, because
    `domains.normalise_sep_rows` drops an unresolvable bar before storage — so
    reading raw tickers out of it still cannot see a security the vendor priced
    and the ingest could not name. The failure chain was:

        SEP prices XYZ -> identity fails -> bar dropped -> no XYZ in
        sentinel_bars -> terminal action for XYZ filed
        SECURITY_ABSENT_FROM_CORPUS

    which is precisely the hiding this exclusion was designed to prevent,
    arriving one layer upstream of where it was defended. The rejection table
    restores the missing half of the evidence.

    A test that writes a bar and then withholds its identity CANNOT catch this,
    because ordinary ingestion can never produce that state — it is a valid unit
    test of an impossible production condition. The falsifier has to run through
    `ingest.seed`/`ingest.daily`.
    """
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        # THE SAME VISIBILITY RULE THE LOADER APPLIES. If a bar is hidden
        # because its ingest never published, the security was not priced as far
        # as any decision is concerned — and reading the two tables under
        # different rules is how "absent from the corpus" would start excluding
        # terminations of securities the book can actually see.
        cur.execute("SELECT DISTINCT ticker FROM sentinel_bars b"
                    " WHERE session BETWEEN %s AND %s"
                    f"   AND {visible_predicate('b')}", (start, end))
        priced = {str(t[0]).upper() for t in cur.fetchall() if t[0]}
    try:
        from sentinel.feed import store as feed_store
        priced |= feed_store.rejected_tickers(conn, start, end)
    except Exception:                                # noqa: BLE001
        # An older corpus with no rejection table. Deliberately tolerated on
        # READ — but readiness carries its own check for the same condition, so
        # a missing table cannot make an identity outage invisible.
        pass
    return priced


def load_terminal_events(conn, *, start: str, end: str,
                         resolve_identity=None,
                         resolve_with_reason=None) -> TerminalLoadResult:
    """Read `sentinel_actions`, map the terminal ones, and ACCOUNT for the rest.

    `resolve_with_reason(ticker, session) -> (security_id, reason)` is preferred;
    `resolve_identity` is accepted for callers that predate it and yields
    NO_PERMANENT_ID for every failure, which is the least informative honest
    answer rather than a guess.

    An unresolvable row is never keyed on its ticker: terms carrying a ticker
    match no holding, so the action would silently return NOT_HELD and the
    termination would be invisible rather than refused.
    """
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        # PUBLISHED ONLY, exactly as the bars are. A corpus that hides the
        # prices of an unpublished ingest while exposing its TERMINATIONS is
        # worse than one that hides neither: a terminal event would be applied
        # to a book marked from a different generation of the data.
        cur.execute(
            "SELECT ticker, session, action, value, contraticker"
            " FROM sentinel_actions a WHERE session BETWEEN %s AND %s"
            f"   AND {visible_predicate('a')}"
            " ORDER BY session, ticker, action", (start, end))
        rows = cur.fetchall()

    priced = _corpus_tickers(conn, start, end)
    out: list = []
    seen: set = set()
    audit: list = []

    for ticker, session, action, value, contraticker in rows:
        s, tk = str(session), str(ticker)
        act = (action or "").lower()
        key = (tk.upper(), s, act)

        def _row(disposition, reason="", sid=None):
            return TerminalRow(ticker=tk, session=s, action=act,
                               disposition=disposition, reason=reason,
                               security_id=sid)

        if key in seen:
            audit.append(_row("excluded", EXCLUDED_DUPLICATE))
            continue
        seen.add(key)

        if not (start <= s <= end):          # defensive; the SQL already bounds it
            audit.append(_row("excluded", EXCLUDED_OUTSIDE_WINDOW))
            continue

        side = TERMINAL_ACTION_SIDES.get(act)
        if side is ActionSide.ACQUIRER:
            audit.append(_row("excluded", EXCLUDED_ACQUIRER_SIDE))
            continue
        if side is None:
            audit.append(_row(
                "excluded",
                EXCLUDED_NON_TERMINAL
                if act in SPLIT_ACTIONS | DIVIDEND_ACTIONS
                else EXCLUDED_UNSUPPORTED))
            continue

        # RELEVANCE, decided before identity so a mapping failure cannot be
        # reclassified as irrelevant by its own consequences.
        if priced and tk.upper() not in priced:
            audit.append(_row("excluded", EXCLUDED_ABSENT_FROM_CORPUS))
            continue

        if resolve_with_reason is not None:
            sid, why = resolve_with_reason(tk, s)
        elif resolve_identity is not None:
            sid, why = resolve_identity(tk, s), "NO_PERMANENT_ID"
        else:
            sid, why = None, "NO_PERMANENT_ID"

        if not sid:
            audit.append(_row("unresolved", why))
            continue

        terms = terminal_from_action(
            {"ticker": ticker, "action": action, "value": value,
             "contraticker": contraticker}, s, security_id=sid)
        if terms is None:
            # The identity resolved and the mapping still produced nothing. That
            # is a mapping gap, not an identity one, and it must not be filed as
            # an exclusion — it is a termination we cannot express.
            audit.append(_row("unresolved", "TERMS_NOT_EXPRESSIBLE", sid))
            continue

        # `TerminalTerms` directly. `run.TerminalEvent` READS like a wrapper
        # type and is a back-compat FACTORY over TerminalTerms for the two
        # original kinds — it cannot express CONVERSION at all, which is
        # exactly what a public acquirer produces.
        out.append(terms)
        audit.append(_row("resolved", sid=sid))

    return TerminalLoadResult(events=out, rows=audit)
