"""Wealth Core v1 — the two ordering conventions, NAMED. PURE.

Two places in the strategy compare candidates that the certified source does not
separate:

    leadership_boundary_tie_break        which of two EQUAL-momentum securities
                                        takes the last place in the leadership
                                        set, when the cutoff falls between them
    issuer_conflict_admission_tie_break  which of two securities of the SAME
                                        issuer is admitted, when both are
                                        candidates in the same session

The certified source fixes the SIZE of the leadership set and the LOCATION of
the issuer check — at admission, never before the cutoff. It does not fix either
ordering. Both were therefore decided here, and the point of this module is that
they are decided ONCE, in public, under a name, rather than implied by a `sort`
call three files apart.

WHY THIS IS NOT A COSMETIC REFACTOR. Both rules are silent when they are wrong.
A boundary tie resolved differently swaps one holding for another and then
compounds for years through the slot and cooldown machinery; an issuer conflict
resolved differently picks a different share class of the same company. Neither
produces an error, an outlier, or a visible discontinuity in any aggregate — the
run is simply a different run. The only way to notice is to have written the
tuple down and to persist it.

STABLE IDENTIFIERS BEFORE TICKERS, always. A ticker is reassigned after a
delisting and changes on a rebrand, so a tie broken on ticker is a tie broken on
a mutable label: the same two securities can order differently in two runs over
the same data because a vendor renamed one of them in between. `security_id`
comes first everywhere, and the ticker survives only as a last resort for the
case where two rows genuinely share an id — which should be impossible and is
therefore exactly where a silent collision would hide.

CHANGING EITHER RULE. If the recovered frozen prototype turns out to order
differently, the new behaviour goes in as a NAMED PROFILE beside the canonical
one and the fixture is re-pinned deliberately. It does not replace the canonical
rule quietly: a profile makes the difference greppable, hashable and selectable,
whereas an edited comparator makes every historical result silently
unreproducible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

CANONICAL_PROFILE = "canonical_2026_08"
"""The profile these rules describe. It is part of `WealthCoreConfig.config_hash`,
so a run scored under one profile can never be mistaken for a run scored under
another."""

KNOWN_PROFILES: tuple[str, ...] = (CANONICAL_PROFILE,)


@dataclass(frozen=True)
class OrderingRule:
    """A named comparison, its field list, and why it is ordered that way.

    `fields` is not documentation — `comparison_tuple` builds the sort key from
    it, so the description and the behaviour cannot drift apart.
    """
    name: str
    fields: tuple[str, ...]
    descending: frozenset[str]
    rationale: str

    def key(self, row: Any) -> tuple:
        out = []
        for f in self.fields:
            v = getattr(row, f, None)
            if f in self.descending:
                out.append(-v if isinstance(v, (int, float)) else v)
            else:
                out.append("" if v is None else v)
        return tuple(out)

    def comparison_tuple(self, row: Any) -> dict:
        """The full tuple, as data, for the audit row.

        Persisted rather than recomputed on demand: the reason one candidate
        beat another has to be recoverable from the record months later, and a
        reader who has to re-derive it from today's code will get today's
        answer, not the one that actually applied.
        """
        return {"rule": self.name,
                "fields": list(self.fields),
                "values": {f: getattr(row, f, None) for f in self.fields}}


LEADERSHIP_BOUNDARY_TIE_BREAK = OrderingRule(
    name="leadership_boundary_tie_break",
    fields=("momentum", "security_id", "ticker"),
    descending=frozenset({"momentum"}),
    rationale=(
        "The leadership set is the top max(25, ceil(N x 0.10)) by RAW MOMENTUM. "
        "When the cutoff falls between two securities with identical momentum, "
        "the permanent security identifier decides, then the ticker. Momentum "
        "ties are not exotic: a screen full of low-priced securities rounds to "
        "the same return often enough that input order alone would otherwise "
        "choose the book."),
)

ISSUER_CONFLICT_ADMISSION_TIE_BREAK = OrderingRule(
    name="issuer_conflict_admission_tie_break",
    fields=("score", "security_id", "ticker"),
    descending=frozenset({"score"}),
    rationale=(
        "Two securities of one issuer both reach admission; only one may be "
        "held. The higher DURABLE SCORE wins, then the permanent identifier, "
        "then the ticker. Deliberately the same ordering the admission queue "
        "already uses, so the winner is simply whichever the strategy would "
        "have admitted first had the other not existed — no separate notion of "
        "'the better listing' (ADV, primary-listing flags) is invented, since "
        "the certified source supplies none and each such signal would be a "
        "new unverified rule."),
)

RULES: dict[str, OrderingRule] = {
    r.name: r for r in (LEADERSHIP_BOUNDARY_TIE_BREAK,
                        ISSUER_CONFLICT_ADMISSION_TIE_BREAK)
}


def sort_for_leadership(rows: Sequence[Any]) -> list[Any]:
    """Rank the eligible population for the leadership cutoff."""
    return sorted(rows, key=LEADERSHIP_BOUNDARY_TIE_BREAK.key)


def sort_for_admission(rows: Sequence[Any]) -> list[Any]:
    """Order qualified candidates for admission, which is also the order that
    resolves an issuer conflict between two of them."""
    return sorted(rows, key=ISSUER_CONFLICT_ADMISSION_TIE_BREAK.key)


__all__ = ["CANONICAL_PROFILE", "KNOWN_PROFILES", "OrderingRule", "RULES",
           "LEADERSHIP_BOUNDARY_TIE_BREAK", "ISSUER_CONFLICT_ADMISSION_TIE_BREAK",
           "sort_for_leadership", "sort_for_admission"]
