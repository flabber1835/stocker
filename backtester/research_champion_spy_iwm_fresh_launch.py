#!/usr/bin/env python3
"""Independent launch with input-derived pre-warmup security lifecycle state."""
from __future__ import annotations
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backtester import research_champion_spy_iwm_observers as observer


def prior_retired(by_session: dict, sid_to_tid: dict, before: str) -> set[int]:
    """Retain already effective retirements; no portfolio or future-event state."""
    cutoff = date.fromisoformat(before)
    result = set()
    for session, records in by_session.items():
        effective = date.fromisoformat(session)
        if effective >= cutoff:
            continue
        for sid in records:
            if sid in sid_to_tid:
                result.add(int(sid_to_tid[sid]))
    return result


def install_lifecycle(text: str) -> str:
    if 'import prior_retired as _prior_retired' in text:
        raise RuntimeError('Prior lifecycle initialization is already installed')
    text = observer.once(text,
        'from backtester import research_champion_spy_iwm_observers as _observer\n',
        'from backtester import research_champion_spy_iwm_observers as _observer\n'
        'from backtester.research_champion_spy_iwm_fresh_launch import prior_retired as _prior_retired\n',
        'prior-lifecycle helper import')
    anchor = '    _lead_terminal_by_session=_lead_terminal_index(_CANONICAL.root)\n'
    addition = '''    _retired_tids.update(_prior_retired(_lead_terminal_by_session,_SID_TO_TID,str(_observers.warmup_start.date())))
    _prewarm_retired_ids=sorted(str(sid[_tid]) for _tid in _retired_tids)
    _observer.write_json(OUT/'prewarm-lifecycle-state.json',{
        'status':'RECONSTRUCTED_FROM_FROZEN_INPUT_EVENTS',
        'before_session':str(_observers.warmup_start.date()),
        'retired_security_count':len(_prewarm_retired_ids),
        'retired_security_ids_sha256':hashlib.sha256(json.dumps(_prewarm_retired_ids,separators=(',',':')).encode()).hexdigest(),
        'inherited_portfolio_state':False,'future_events_used':False})
'''
    text = observer.once(text, anchor, anchor+addition, 'prior input-derived retirements')
    compile(text, '<fresh-launch-lifecycle>', 'exec')
    return text


def main() -> int:
    if '--mode' not in sys.argv or sys.argv[sys.argv.index('--mode')+1] != 'fresh5':
        raise RuntimeError('Lifecycle launch wrapper is restricted to fresh5')
    original = observer.install
    observer.install = lambda text,mode: install_lifecycle(original(text,mode))
    try:
        return observer.main()
    finally:
        observer.install = original


if __name__ == '__main__':
    raise SystemExit(main())
