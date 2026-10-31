"""Exact private source compilation and finite Core proposal pool; no replay."""
import ast
import hashlib
import json
from pathlib import Path

CORE='shared/stock_strategy_shared/wealth_core/'
BASELINE={'stop':.70,'review':119,'cooldown':21,'leadership':.10,'rank_memory':5,'freshness':0.}
LEVELS={'stop':[.60,.70,.80],'review':[63,119,189],'cooldown':[10,21,42],
        'leadership':[.05,.10,.20],'rank_memory':[1,5,10],'freshness':[-.02,0.,.02]}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def proposals():
    result=[{'id':'CORE_BASELINE','parameters':BASELINE}]
    # Three balanced joint proposals, ordered before any performance is read.
    for row in range(3):
        values={}
        for key,levels in LEVELS.items():
            seed=int.from_bytes(hashlib.sha256(('core-space-filling-001/'+key).encode()).digest()[:4],'big')
            values[key]=levels[((1+seed%2)*row+(seed//2)%3)%3]
        result.append({'id':'CORE_'+digest(values)[:16],'parameters':values})
    assert len({r['id'] for r in result})==4
    return result


def replace(text,old,new,count=1):
    if text.count(old)!=count:raise ValueError('REFUSED_FULL_SOURCE_SITE:'+old[:80])
    return text.replace(old,new)


def render(files,parameters):
    if set(parameters)!=set(BASELINE) or any(parameters[k] not in LEVELS[k] for k in parameters):
        raise ValueError('REFUSED_FULL_SOURCE_PARAMETERS')
    out=dict(files)
    def edit(name,fn):
        raw=fn(out[name].decode());ast.parse(raw,name);out[name]=raw.encode()
    def session(t):
        t=replace(t,'    digest = hashlib.sha256()\n    for chunk in _canonical_chunks(value):\n        digest.update(chunk.encode())\n    return digest.hexdigest()',
            '    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)\n'
            '    return hashlib.sha256(raw.encode()).hexdigest()')
        return replace(t,'    for _ in _canonical_chunks(value):\n        pass',
            '    json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)')
    edit('sentinel/core/session.py',session)
    def storage(t):
        t=replace(t,'        transitions = 0\n','        transitions = 0\n'
            '        import os\n        if os.environ.get("FULL_SYSTEM_WARMUP_ONLY")=="1":\n'
            '            status("FEATURE_WARMUP_CHECKPOINTED",session=cursor,completed_sessions=completed)\n            return 0\n')
        t=replace(t,"                status('PAUSED', session=cursor, completed_sessions=completed)",
            "                save()\n                status('PAUSED', session=cursor, completed_sessions=completed)")
        return replace(t,'            transitions += 1\n            save()\n',
            '            transitions += 1\n'
            '            if packet.day==START or packet.day==END or measurement[min(completed,len(measurement)-1)][:7]!=packet.day[:7]:\n                save()\n')
    edit('research/pooled_vacancy_funding/backtest.py',storage)
    if parameters!=BASELINE:
        edit(CORE+'state.py',lambda t: replace(replace(replace(replace(t,'REVIEW_AGE_SESSIONS = 119',f'REVIEW_AGE_SESSIONS = {parameters["review"]}'),
            'COOLDOWN_SESSIONS = 21',f'COOLDOWN_SESSIONS = {parameters["cooldown"]}'),
            'STOP_RETENTION = 0.70',f'STOP_RETENTION = {parameters["stop"]}'),
            'Fraction("0.70")',f'Fraction("{parameters["stop"]}")'))
        def engine(t):
            t=replace(t,'top_fraction: float = 0.10',f'top_fraction: float = {parameters["leadership"]}')
            return replace(t,'self.top_fraction != 0.10',f'self.top_fraction != {parameters["leadership"]}')
        edit(CORE+'engine.py',engine)
        def median(t):
            t=replace(t,'len(value["rank_history"]) > 5',f'len(value["rank_history"]) > {parameters["rank_memory"]}')
            t=replace(t,'history = (state["rank_history"] + [order])[-5:]',f'history = (state["rank_history"] + [order])[-{parameters["rank_memory"]}:]')
            return replace(t,'s.recent >= 0]',f's.recent >= {parameters["freshness"]}]')
        edit(CORE+'median5.py',median)
        edit(CORE+'signals.py',lambda t:replace(t,'return recent is not None and recent >= 0.0',
            f'return recent is not None and recent >= {parameters["freshness"]}'))
    profile=digest(parameters)
    edit('research/pooled_vacancy_funding/runtime.py',lambda t:replace(t,
        'identity = {**identity,',f'identity = {{**identity, "research_full_system_core_sha256": "{profile}",'))
    return out


def build(source,destination,parameters):
    source,destination=Path(source),Path(destination)
    if destination.exists() or source.resolve()==destination.resolve():raise ValueError('REFUSED_FULL_SOURCE_OVERWRITE')
    files={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    if len(files)!=514:raise ValueError('REFUSED_FULL_SOURCE_COUNT')
    from build_core_variants import render as observed_basis
    import re
    basis=observed_basis(files,risk=False)
    name='research/pooled_vacancy_funding/backtest.py';text=basis[name].decode()
    text,count=re.subn(r"_CORE_WINDOWS=.*\nSTART, END, MEASURED_CLOSES = _CORE_WINDOWS\[os.environ\['CAPITAL_RISK_WINDOW'\]\]",
        "START, END = '2018-01-02', '2026-07-31'\nMEASURED_CLOSES = 2156",text)
    if count!=1:raise ValueError('REFUSED_FULL_SOURCE_DATE_SITE')
    basis[name]=text.encode()
    snap='shared/stock_strategy_shared/wealth_core/accounting_snapshot.py'
    basis[snap]=replace(basis[snap].decode(),'ledger=ledger.to_dict(),',
        'ledger={"event_count":len(ledger.events),"receivables":ledger.to_dict()["receivables"]},').encode()
    result=render(basis,parameters);destination.mkdir(parents=True,exist_ok=False)
    for name,raw in result.items():
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    return {'schema':'research.full-system-private-source/1','parameters':parameters,'profile_sha256':digest(parameters),
        'original_files':514,'files':len(result),'changed':{n:{'before':hashlib.sha256(files[n]).hexdigest() if n in files else None,
        'after':hashlib.sha256(v).hexdigest()} for n,v in result.items() if v!=files.get(n)},
        'all_sources':{n:hashlib.sha256(v).hexdigest() for n,v in result.items()}}
