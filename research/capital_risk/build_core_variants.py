"""Deterministic private-source compiler. Never changes installed/PAPER sources."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
CORE='shared/stock_strategy_shared/wealth_core/'


def replace(text, old, new, *, count=1):
    if text.count(old)!=count:
        raise ValueError('REFUSED_PATCH_SITE_COUNT_'+str(text.count(old)))
    return text.replace(old,new)


def render(files, *, risk):
    basis=json.loads((HERE/'core-source-basis.json').read_bytes())
    for name,expected in basis.items():
        if hashlib.sha256(files[name]).hexdigest()!=expected:
            raise ValueError('REFUSED_FROZEN_PATCH_SOURCE_'+name)
    out=dict(files)
    def edit(name,fn):
        text=out[name].decode().replace('\r\n','\n');text=fn(text)
        ast.parse(text,filename=name);out[name]=text.encode()
    def dates(t):
        t=replace(t,"START, END = '2008-02-22', '2026-07-31'\nMEASURED_CLOSES = 4639",
            "import os\n_CORE_WINDOWS={'stress-2021':('2021-01-04','2022-12-30',503),"
            "'recent-2025':('2025-01-02','2026-07-31',395)}\n"
            "START, END, MEASURED_CLOSES = _CORE_WINDOWS[os.environ['CAPITAL_RISK_WINDOW']]")
        t=replace(t,'axis = full_axis[offset:]','axis = full_axis[offset:full_axis.index(END)+1]')
        t=replace(t,'iterator = (p for p in inputs.packets(args.bundle, args.archive) if p.day >= axis[0])',
            'iterator = inputs.packets(args.bundle, args.archive, first=axis[0], last=END)')
        return t
    edit('research/pooled_vacancy_funding/backtest.py',dates)
    def bounded(t):
        t=replace(t,'def packets(bundle, archive_path):','def packets(bundle, archive_path, *, first=None, last=None):')
        t=replace(t,'    expected = prepared_axis()','    expected = [d for d in prepared_axis() if (first is None or d>=first) and (last is None or d<=last)]')
        t=replace(t,"        for partition in manifest['observation_partitions']:\n",
            "        for partition in manifest['observation_partitions']:\n"
            "            if first is not None and partition['year']<int(first[:4]) or last is not None and partition['year']>int(last[:4]):\n                continue\n")
        t=replace(t,'                observed.append(day)','                if first is not None and day<first or last is not None and day>last:\n                    continue\n                observed.append(day)')
        t=replace(t,'    if applied != set(overlay):','    if applied != {k for k in overlay if (first is None or k[0]>=first) and (last is None or k[0]<=last)}:')
        return t
    edit('research/pooled_input_support/inputs.py',bounded)
    if not risk:
        return out
    out[CORE+'capital_risk.py']=(HERE/'core_policy.py').read_bytes()
    def funding(t):
        t=replace(t,'RESEARCH_PROFILES = frozenset((ORIGINAL_ADMISSION_PROFILE, BASELINE_PROFILE, *POOLED_PROFILES))',
            'from .capital_risk import PROFILES as CAPITAL_RISK_PROFILES\n'
            'RESEARCH_PROFILES = frozenset((ORIGINAL_ADMISSION_PROFILE, BASELINE_PROFILE, *POOLED_PROFILES, *CAPITAL_RISK_PROFILES))')
        return replace(t,'if profile == ORIGINAL_ADMISSION_PROFILE:',
            'if profile == ORIGINAL_ADMISSION_PROFILE or profile in CAPITAL_RISK_PROFILES:')
    edit(CORE+'v5.py',funding)
    def state(t):
        t=replace(t,'    episode_peak_split_adjusted_close: float | None = None',
            '    episode_peak_split_adjusted_close: float | None = None\n'
            '    research_stop_floor: float | None = None\n    research_stop_cursor: str | None = None')
        return replace(t,'    d = asdict(ep)','    d = asdict(ep)\n'
            "    for key in ('research_stop_floor','research_stop_cursor'):\n"
            '        if d[key] is None: d.pop(key)')
    edit(CORE+'state.py',state)
    def validation(t):
        return replace(t,'def validate_payload(d, *, cooldown_sessions):',
            'def validate_payload(d, *, cooldown_sessions):\n'
            '    from .capital_risk import validate_stop_profile\n    validate_stop_profile(d)')
    edit(CORE+'state_restore_validation.py',validation)
    def engine(t):
        t=replace(t,'import math\n','import math\nfrom . import capital_risk\n')
        t=replace(t,'    CLOSE_POSITION = "CLOSE_POSITION"','    CLOSE_POSITION = "CLOSE_POSITION"\n    REDUCE_POSITION = "REDUCE_POSITION"')
        t=replace(t,'    EXIT_TRAILING_STOP = "EXIT_TRAILING_STOP"',
            '    EXIT_TRAILING_STOP = "EXIT_TRAILING_STOP"\n    CONCENTRATION_BAND = "CONCENTRATION_BAND"')
        t=replace(t,'    certified_signals: tuple[float, float, float, float] | None = None',
            '    certified_signals: tuple[float, float, float, float] | None = None\n    signal_sessions: Sequence[str] | None = None')
        t=replace(t,'        if ep.stop_triggered(px):',
            '        if capital_risk.volatility_stop(ep,bars=bars,session=session,cfg=cfg):')
        return replace(t,'    ready = [i for i in state.ready_slots() if i not in exiting]',
            '    capital_risk.trim_decisions(state=state,bars=bars,marks=marks,cfg=cfg,\n'
            '        pending=pending or [],decision=d,noncash_assets=noncash_assets)\n'
            '    ready = [i for i in state.ready_slots() if i not in exiting]')
    edit(CORE+'engine.py',engine)
    def window(t):
        t=replace(t,'import math\n','import math\nfrom sentinel.feed.calendar import previous_sessions\n')
        t=replace(t,'        (mom, recent, vol, score) if eligible else None)',
            '        (mom, recent, vol, score) if eligible else None,\n'
            '        signal_sessions=(tuple(previous_sessions(session,21))\n'
            '            if len(series.session_indices)>=21 and series.session_indices[-21:]==list(range(index-20,index+1)) else None))')
        return t
    edit(CORE+'window_signals.py',window)
    def adapter(t):
        t=replace(t,'    intended_dollars: float | None = None','    intended_dollars: float | None = None\n    risk_detail: dict | None = None')
        t=replace(t,'    def validate_sizing(self, *, open_time: bool) -> None:\n',
            '    def validate_sizing(self, *, open_time: bool) -> None:\n'
            '        if self.operation is Operation.REDUCE_POSITION:\n'
            '            import math\n'
            '            if self.intended_dollars is not None or not isinstance(self.risk_detail,dict) or self.risk_detail.get("research_rule")!="C_10_8_V1" or not math.isfinite(self.shares) or self.shares<=0:\n'
            '                raise ValueError("REFUSED_REDUCTION_INTENT")\n'
            '            return\n'
            '        if self.risk_detail is not None: raise ValueError("REFUSED_MISLABELLED_RISK_INTENT")\n')
        t=replace(t,'        return out\n','        if self.risk_detail is not None: out["risk_detail"]=self.risk_detail\n        return out\n')
        t=replace(t,'                   intended_dollars=d.get("intended_dollars"))',
            '                   intended_dollars=d.get("intended_dollars"), risk_detail=d.get("risk_detail"))')
        t=replace(t,'        pending.sort(key=lambda p: (p.operation is not Operation.CLOSE_POSITION,',
            '        pending.sort(key=lambda p: (p.operation not in (Operation.CLOSE_POSITION,Operation.REDUCE_POSITION),')
        t=replace(t,'        if po.operation is Operation.CLOSE_POSITION:\n            ep = state.episodes.get(po.slot_id)',
            '        if po.operation is Operation.REDUCE_POSITION:\n'
            '            from .capital_risk import apply_reduction\n'
            '            ep=state.episodes.get(po.slot_id)\n'
            '            if ep is None or ep.security_id!=po.security_id:\n'
            '                res_cancelled.append(_cancelled_order(state,po,session=session,reason="STALE_REDUCTION_INTENT"))\n'
            '                continue\n'
            '            before=state.cash\n'
            '            audit=apply_reduction(state,slot_id=po.slot_id,shares=po.shares,raw_open=px,cfg=cfg,cash_before_exact=opening_cash_exact)\n'
            '            if opening_cash_exact is not None: opening_cash_exact+=Fraction(str(audit["cash_proceeds"]))\n'
            '            ledger.post(session=session,event_type=EventType.SELL,cash_before=before,cash_delta=state.cash-before,\n'
            '                security_id=po.security_id,ticker=po.ticker,shares_delta=-po.shares,price=px,\n'
            '                fees=po.shares*px*cfg.transaction_cost_bps/10000,reason=po.reason,\n'
            '                detail={"research_reduction":audit,"signal_detail":po.risk_detail,"pending_transformations":list(po.transformations)})\n'
            '        elif po.operation is Operation.CLOSE_POSITION:\n            ep = state.episodes.get(po.slot_id)')
        t=replace(t,'        if op.operation in (Operation.OPEN_SLOT_POSITION, Operation.CLOSE_POSITION):',
            '        if op.operation in (Operation.OPEN_SLOT_POSITION, Operation.CLOSE_POSITION, Operation.REDUCE_POSITION):')
        t=replace(t,'                intended_dollars=(op.detail or {}).get("intended_dollars")))',
            '                intended_dollars=(op.detail or {}).get("intended_dollars"),\n'
            '                risk_detail=(op.detail if op.operation is Operation.REDUCE_POSITION else None)))')
        t=replace(t,'    for op in d.operations:\n',
            '    closing_slots={op.slot_id for op in d.operations if op.operation is Operation.CLOSE_POSITION}\n'
            '    for po in list(pending):\n'
            '        if po.operation is Operation.REDUCE_POSITION and po.slot_id in closing_slots:\n'
            '            res_cancelled.append(_cancelled_order(state,po,session=session,reason="FULL_CLOSE_SUPERSEDES_TRIM"))\n'
            '            pending.remove(po)\n    for op in d.operations:\n')
        # Validate unsupported conversion before corporate actions or fills can
        # touch this session's copy. Ordinary cash exits may cancel the intent.
        t=replace(t,'    _preflight_splits(state, bars, pending)\n    by_sec =',
            '    for po in pending:\n'
            '        if po.operation is Operation.REDUCE_POSITION and any(\n'
            '            term.security_id==po.security_id and term.kind.value in ("CONVERSION","CASH_PLUS_STOCK") for term in terminal_terms):\n'
            '            raise ValueError("REFUSED_PENDING_TRIM_CONVERSION")\n'
            '    _preflight_splits(state, bars, pending)\n    by_sec =')
        return t
    edit(CORE+'adapter.py',adapter)
    def terminal(t):
        t=replace(t,'                     if ep.episode_peak_split_adjusted_close is not None else 1.0))]',
            '                     if ep.episode_peak_split_adjusted_close is not None else 1.0),\n'
            '                    (ep.research_stop_floor * signal_scale if ep.research_stop_floor is not None else 1.0))]')
        return replace(t,'        ep.episode_peak_split_adjusted_close *= signal_domain_scale',
            '        ep.episode_peak_split_adjusted_close *= signal_domain_scale\n'
            '    from .capital_risk import rebase_floor\n    rebase_floor(ep,signal_domain_scale)')
    edit(CORE+'terminal.py',terminal)
    def spins(t):
        t=replace(t,'        group["reference_scale"] = scale',
            '        for parent in group["parents"]:\n'
            '            if parent.research_stop_floor is not None and (not math.isfinite(parent.research_stop_floor*scale) or parent.research_stop_floor*scale<=0):\n'
            '                raise SpinoffTermsRequired("invalid research stop reference scale")\n'
            '        group["reference_scale"] = scale')
        return replace(t,'                parent.episode_peak_split_adjusted_close *= group["reference_scale"]',
            '                parent.episode_peak_split_adjusted_close *= group["reference_scale"]\n'
            '            from stock_strategy_shared.wealth_core.capital_risk import rebase_floor\n'
            '            rebase_floor(parent,group["reference_scale"])')
    edit('sentinel/core/spinoffs.py',spins)
    def live(t):
        return replace(t,'return "sell" if self.operation == Operation.CLOSE_POSITION.value else "buy"',
            'return "sell" if self.operation in (Operation.CLOSE_POSITION.value,Operation.REDUCE_POSITION.value) else "buy"')
    edit(CORE+'live.py',live)
    return out


def build(source,destination,*,risk):
    if destination.exists() or source.resolve()==destination.resolve():
        raise ValueError('REFUSED_VARIANT_OVERWRITE')
    files={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    if len(files)!=514:
        raise ValueError('REFUSED_FROZEN_SOURCE_COUNT')
    output=render(files,risk=risk)
    destination.mkdir(parents=True,exist_ok=False)
    for name,raw in output.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return dict(original_files=514,files=len(output),risk_hooks=risk,
        changed={k:dict(before=hashlib.sha256(files[k]).hexdigest() if k in files else None,
                       after=hashlib.sha256(v).hexdigest()) for k,v in output.items() if files.get(k)!=v})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True);p.add_argument('--risk',action='store_true')
    args=p.parse_args();print(json.dumps(build(args.source,args.destination,risk=args.risk)))
