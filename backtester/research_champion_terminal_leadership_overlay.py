#!/usr/bin/env python3
"""Causal terminal filter for the frozen Research Champion leadership witness.

A security that terminates on session T may contribute its valid T close to the
return selected on T-1. It cannot be selected at T as a source for a T+1 return,
because no continuing security exists on T+1. The frozen terminal ledger already
contains the causal disposition. This overlay removes such securities from the
next-session leadership witness while keeping the general missing-return policy
fail-closed.
"""
from __future__ import annotations

from backtester.research_terminal_grace_overlay import install as _install_financial_grade


_OLD = "prior_recent_sel=tuple(map(int,recsel)); prior_close_map={int(t):float(clsig[int(t)]) for t in recsel if finite(clsig[int(t)])}"
_NEW = """def _leadership_term_tid(_ticker):
                return strict_tid(_ticker,ds) if 'strict_tid' in globals() else tmap.get(str(_ticker))
            _leadership_terminal_tids={z for tk,rs in actions.get(date,{}).items() if (z:=_leadership_term_tid(tk)) is not None and any(a in TERMINAL for a,_,_ in rs)}
            _leadership_terminal_tids.update(_exact_terminal_by_session.get(ds,{}))
            prior_recent_sel=tuple(int(t) for t in recsel if int(t) not in _leadership_terminal_tids)
            prior_close_map={int(t):float(clsig[int(t)]) for t in prior_recent_sel if finite(clsig[int(t)])}"""


def install_terminal_leadership_filter(text: str) -> str:
    count = text.count(_OLD)
    if count != 1:
        raise RuntimeError(
            f"terminal leadership filter: expected one source seam, found {count}"
        )
    out = text.replace(_OLD, _NEW, 1)
    required = (
        "_leadership_terminal_tids",
        "_exact_terminal_by_session.get(ds,{})",
        "prior_recent_sel=tuple(int(t) for t in recsel if int(t) not in _leadership_terminal_tids)",
    )
    missing = [needle for needle in required if needle not in out]
    if missing:
        raise RuntimeError(f"terminal leadership filter missing seams: {missing}")
    return out


def install(text: str) -> str:
    return install_terminal_leadership_filter(_install_financial_grade(text))
