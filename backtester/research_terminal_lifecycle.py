"""Causal terminal lifecycle for the retained research leadership witness.

Canonical terminal records retire a security from the event-session close
selection. The prior selection still earns its event-session economic return.
All ordinary observed returns retain the frozen signal-price calculation.
"""
from __future__ import annotations

import csv
import gzip
import math
from pathlib import Path
from typing import Mapping


class LeadershipReturnUnresolved(RuntimeError):
    """An existing leadership member lacks a provable economic return."""


def _number(value, *, positive=False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LeadershipReturnUnresolved("unresolved recent-leadership return: missing price/terms") from exc
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise LeadershipReturnUnresolved("unresolved recent-leadership return: invalid price/terms")
    return result


def terminal_index(root: Path) -> dict[str, dict[str, dict[str, str]]]:
    """Read the terminal ledger of an already validated canonical package."""
    by_session: dict[str, dict[str, dict[str, str]]] = {}
    with gzip.open(Path(root) / "terminal-events.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            session = str(row.get("effective_session") or "")
            sid = str(row.get("security_id") or "")
            if len(session) != 10 or not sid:
                raise LeadershipReturnUnresolved("terminal ledger lacks session/security identity")
            records = by_session.setdefault(session, {})
            if sid in records and records[sid] != row:
                raise LeadershipReturnUnresolved(f"conflicting terminal evidence: {session} {sid}")
            records[sid] = dict(row)
    return by_session


def leadership_return(*, security_id: str, session: str, prior_signal,
                      current_signal, prior_raw, terminal: Mapping | None,
                      delivered_raw=None, split_ratio=1.0) -> tuple[float, str]:
    """Value one member, including its authenticated terminal consideration."""
    try:
        _number(prior_signal, positive=True)
        if terminal is not None:
            if (str(terminal.get("security_id")) != str(security_id)
                    or str(terminal.get("effective_session")) != str(session)):
                raise LeadershipReturnUnresolved("terminal evidence is outside this identity/session")
            if terminal.get("disposition") == "EXACT_EVIDENCE":
                if not terminal.get("authority") or not terminal.get("evidence_hash"):
                    raise LeadershipReturnUnresolved("terminal evidence lacks authenticated provenance")
                kind = terminal.get("kind")
                if kind == "CASH_MERGER":
                    value = _number(terminal.get("cash_per_share"))
                elif kind == "WRITE_OFF":
                    value = 0.0
                elif kind in {"CONVERSION", "CASH_PLUS_STOCK"}:
                    if not terminal.get("delivered_security_id"):
                        raise LeadershipReturnUnresolved("terminal delivery identity missing")
                    ratio = _number(terminal.get("exchange_ratio"), positive=True)
                    # The witness is a fractional, equal-weight return index.
                    # Real portfolio whole-share settlement remains in Book.
                    value = ratio * _number(delivered_raw, positive=True)
                    if kind == "CASH_PLUS_STOCK":
                        value += _number(terminal.get("cash_per_share"))
                else:
                    raise LeadershipReturnUnresolved(f"unsupported exact terminal kind: {kind}")
                result = value * _number(split_ratio, positive=True) / _number(prior_raw, positive=True) - 1.0
                if not math.isfinite(result):
                    raise LeadershipReturnUnresolved("non-finite terminal return")
                return result, "EXACT_TERMINAL_CONSIDERATION"
        # A recorded close is observable evidence for the frozen price witness.
        # A missing close still requires complete authenticated terminal terms.
        return _number(current_signal, positive=True) / float(prior_signal) - 1.0, "OBSERVED_SIGNAL_CLOSE"
    except LeadershipReturnUnresolved as exc:
        raise LeadershipReturnUnresolved(
            f"unresolved recent-leadership return: {session} {security_id}: {exc}"
        ) from exc


def _once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def install(text: str) -> str:
    """Attach the terminal lifecycle to fully assembled canonical research."""
    text = _once(text, "from collections import defaultdict\n",
                 "from collections import defaultdict\nfrom backtester.research_terminal_lifecycle import terminal_index as _lead_terminal_index, leadership_return as _lead_return\n",
                 "terminal leadership imports")
    text = _once(text, "    recent_nav=1.; recent_nav_hist=[1.]; prior_recent_sel=tuple(); prior_close_map={}\n",
                 "    recent_nav=1.; recent_nav_hist=[1.]; prior_recent_sel=tuple(); prior_close_map={}\n"
                 "    _lead_prior_raw={}; _retired_tids=set(); _lead_terminal_counts={'EXACT_TERMINAL_CONSIDERATION':0,'OBSERVED_SIGNAL_CLOSE':0}\n"
                 "    _lead_terminal_by_session=_lead_terminal_index(_CANONICAL.root)\n",
                 "terminal leadership state")
    # Canonical retirement is applied only when the event session is observed.
    text = _once(text, "            et=tids[elig]\n",
                 "            _lead_events=_lead_terminal_by_session.get(ds,{})\n"
                 "            _retired_tids.update(_SID_TO_TID[_s] for _s in _lead_events if _s in _SID_TO_TID)\n"
                 "            if _retired_tids: elig=elig & np.asarray([int(_t) not in _retired_tids for _t in tids],dtype=bool)\n"
                 "            et=tids[elig]\n", "terminal-aware close eligibility")
    original = """                    if not(finite(p0) and p0>0 and finite(p1) and p1>0):
                        raise RuntimeError(f'unresolved recent-leadership return: {ds} {tick[int(tid0)]}')
                    vals.append(float(p1)/float(p0)-1)"""
    replacement = """                    _lead_sid=str(sid[int(tid0)]); _lead_event=_lead_events.get(_lead_sid)
                    _delivered_tid=None if _lead_event is None else _SID_TO_TID.get(str(_lead_event.get('delivered_security_id','')))
                    _delivered_px=None if _delivered_tid is None else clraw[int(_delivered_tid)]
                    _lead_ret,_lead_source=_lead_return(security_id=_lead_sid,session=ds,prior_signal=p0,current_signal=p1,prior_raw=_lead_prior_raw.get(int(tid0)),terminal=_lead_event,delivered_raw=_delivered_px,split_ratio=canonicalsplit[int(tid0)])
                    _lead_terminal_counts[_lead_source]+=1
                    vals.append(_lead_ret)"""
    text = _once(text, original, replacement, "terminal leadership economic return")
    previous = "            prior_recent_sel=tuple(map(int,recsel)); prior_close_map={int(t):float(clsig[int(t)]) for t in recsel if finite(clsig[int(t)])}\n"
    text = _once(text, previous,
                 previous + "            _lead_prior_raw={int(t):float(clraw[int(t)]) for t in recsel if finite(clraw[int(t)])}\n",
                 "terminal leadership raw basis")
    # Daily close eligibility blocks fresh admissions. Outstanding reservations
    # also expire on retirement, including reservations created on prior days.
    pending = "                tid=s.pending_tid; px=opraw[tid]\n"
    text = _once(text, pending,
                 "                tid=s.pending_tid\n"
                 "                if tid in _retired_tids:\n"
                 "                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; continue\n"
                 "                px=opraw[tid]\n", "retired pending admission")
    summary = "'financial_grade_missing_leadership_return_policy':'FAIL_CLOSED',"
    text = _once(text, summary,
                 summary + "\n        'terminal_leadership_return_sources':_lead_terminal_counts,\n        'terminal_retired_security_count':len(_retired_tids),",
                 "terminal leadership evidence")
    compile(text, "<terminal-aware-research-champion>", "exec")
    return text
