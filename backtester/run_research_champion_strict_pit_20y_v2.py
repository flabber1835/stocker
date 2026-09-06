#!/usr/bin/env python3
"""Formal Research Champion replay with causal terminal accounting repairs."""
from __future__ import annotations

from backtester import run_research_champion_strict_pit_20y as champion
from backtester.research_champion_terminal_leadership_overlay import (
    install as _install_terminal_leadership,
)


_OLD_NAV_GATE = """            eq,unresolved=book.equity(clraw)
            if unresolved and date>=START:
                raise RuntimeError(f'financial-grade NAV unresolved on {ds}')
"""

_BOUNDED_TERMINAL_NAV_GATE = """            eq,unresolved=book.equity(clraw)
            if unresolved and date>=START:
                _unresolved_tids=[int(s.tid) for s in book.slots if s.held() and not(finite(clraw[int(s.tid)]) and clraw[int(s.tid)]>0)]
                _unapproved=[_tid for _tid in _unresolved_tids if _tid not in book.terminal_pending]
                _uncarryable=[_tid for _tid in _unresolved_tids if _tid in book.terminal_pending and not(finite(book.last_raw.get(_tid,np.nan)) and book.last_raw.get(_tid,np.nan)>0)]
                if _unapproved or _uncarryable:
                    _detail=[{'ticker':str(tick[_tid]),'security_id':str(sid[_tid]),'terminal_pending':_tid in book.terminal_pending,'last_raw':book.last_raw.get(_tid)} for _tid in _unresolved_tids]
                    raise RuntimeError(f'financial-grade NAV unresolved on {ds}: {_detail}')
"""


def _patch_bounded_terminal_nav(text: str) -> str:
    """Permit only the already-certified C1 carried terminal claim in NAV.

    The 20-year financial gate and the Production-equivalent C1 terminal overlay
    were installed together, but the unconditional stale-mark gate rejected the
    first missing print of every valid C1 claim before its ten-session bounded
    settlement could run. Preserve fail-closed NAV semantics for every ordinary
    holding and require a trustworthy prior raw mark for the sole carried-claim
    exception.
    """
    count = text.count(_OLD_NAV_GATE)
    if count != 1:
        raise RuntimeError(
            f"Research Champion bounded terminal NAV gate: expected one seam, found {count}"
        )
    out = text.replace(_OLD_NAV_GATE, _BOUNDED_TERMINAL_NAV_GATE, 1)
    required = (
        "_unresolved_tids",
        "_tid not in book.terminal_pending",
        "book.last_raw.get(_tid,np.nan)",
        "financial-grade NAV unresolved",
    )
    missing = [needle for needle in required if needle not in out]
    if missing:
        raise RuntimeError(f"Research Champion bounded terminal NAV gate missing: {missing}")
    return out


def install(text: str) -> str:
    return _patch_bounded_terminal_nav(_install_terminal_leadership(text))


# strict20._twenty_year_transform resolves this module global at generation time.
# Binding the corrected installer here leaves Champion parameters and promotion
# assertions untouched while closing known terminal accounting seams.
champion.strict20.install_terminal_grace = install


def main() -> int:
    return int(champion.main())


if __name__ == "__main__":
    raise SystemExit(main())
