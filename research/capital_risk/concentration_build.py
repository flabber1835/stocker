"""Add only the new dated quarter to the already qualified private compiler."""
import ast
import hashlib
from pathlib import Path
from build_core_variants import render,replace

ENV='concentration-q1-2025'
START,END,CLOSES='2025-01-02','2025-03-31',60
BACKTEST='research/pooled_vacancy_funding/backtest.py'

def render_quarter(files,*,risk):
    original=render(files,risk=risk);out=dict(original)
    text=replace(out[BACKTEST].decode(),
        "START, END, MEASURED_CLOSES = _CORE_WINDOWS[os.environ['CAPITAL_RISK_WINDOW']]",
        f"_CORE_WINDOWS[{ENV!r}]=({START!r},{END!r},{CLOSES})\n"
        "START, END, MEASURED_CLOSES = _CORE_WINDOWS[os.environ['CAPITAL_RISK_WINDOW']]")
    ast.parse(text);out[BACKTEST]=text.encode()
    if {k for k in out if out[k]!=original[k]}!={BACKTEST}:
        raise ValueError('REFUSED_QUARTER_NONDATE_SOURCE_CHANGE')
    return out

def build_quarter(source,destination,*,risk):
    if destination.exists() or source.resolve()==destination.resolve():raise ValueError('REFUSED_QUARTER_OVERWRITE')
    files={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    if len(files)!=514:raise ValueError('REFUSED_QUARTER_FROZEN_SOURCE_COUNT')
    out=render_quarter(files,risk=risk);destination.mkdir(parents=True,exist_ok=False)
    for name,raw in out.items():
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    digest=lambda raw:hashlib.sha256(raw).hexdigest()
    return dict(original_files=514,files=len(out),risk_hooks=risk,
        only_change_after_qualified_compiler=BACKTEST,window=[START,END,CLOSES],
        source_files={k:digest(v) for k,v in sorted(out.items())},
        changed={k:dict(before=digest(files[k]) if k in files else None,after=digest(v)) for k,v in out.items() if files.get(k)!=v})
