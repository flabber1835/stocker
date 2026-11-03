"""Compile named parameterized canonical private trees; no engine execution."""
import ast,hashlib,json,re
from pathlib import Path
from system_campaign_space import DEFAULT,canonical,digest
from full_system_source import BASELINE,render as campaign_basis,replace
from build_core_variants import render as observed_basis

CORE='shared/stock_strategy_shared/wealth_core/'
def basis(files,risk):
    out=observed_basis(files,risk=risk)
    n='research/pooled_vacancy_funding/backtest.py';t=out[n].decode()
    t,count=re.subn(r"_CORE_WINDOWS=.*\nSTART, END, MEASURED_CLOSES = _CORE_WINDOWS\[os.environ\['CAPITAL_RISK_WINDOW'\]\]",
        "START, END = '2018-01-02', '2026-07-31'\nMEASURED_CLOSES = 2156",t)
    if count!=1:raise ValueError('REFUSED_CAMPAIGN_VARIANT_DATE_SITE')
    out[n]=t.encode();n=CORE+'accounting_snapshot.py'
    out[n]=replace(out[n].decode(),'ledger=ledger.to_dict(),','ledger={"event_count":len(ledger.events),"receivables":ledger.to_dict()["receivables"]},').encode()
    out=campaign_basis(out,BASELINE);n='research/pooled_vacancy_funding/backtest.py'
    out[n]=replace(out[n].decode(),
        '            if packet.day==START or packet.day==END or measurement[min(completed,len(measurement)-1)][:7]!=packet.day[:7]:\n                save()',
        '            if (packet.day==START or packet.day==END or axis[buffer.index+1][:7]!=packet.day[:7]\n'
        '                    or axis[buffer.index+1]==START):\n                save()').encode()
    return out

def render(files,parameters):
    p=canonical(parameters);risk=p['family']!='CORE';out=basis(files,risk)
    if p==DEFAULT:return out
    def edit(n,fn):
        text=fn(out[n].decode());ast.parse(text,n);out[n]=text.encode()
    def scalar(n,old,new):
        if old!=new:edit(n,lambda t:replace(t,old,new))
    def signals(t):
        t=replace(t,'SKIP_RECENT_SESSIONS = 21',f'SKIP_RECENT_SESSIONS = {p["skip"]}')
        t=replace(t,'LONG_LOOKBACK_SESSIONS = 126',f'LONG_LOOKBACK_SESSIONS = {p["lookback"]}')
        if p['volatility']=='simple_returns_v1':t=replace(t,'DEFAULT_VOLATILITY_PROFILE = LOG_RETURNS_CERTIFIED_V1','DEFAULT_VOLATILITY_PROFILE = SIMPLE_RETURNS_V1')
        return replace(t,'return recent is not None and recent >= 0.0',f'return recent is not None and recent >= {p["freshness"]!r}')
    edit(CORE+'signals.py',signals)
    length=p['lookback']+1;liquidity=p['liquidity'];nslots=p['slots'];weight=1/nslots
    def feature(t):
        t=replace(t,'series.signal_window(127)',f'series.signal_window({length})')
        t=replace(t,'len(series.session_indices) >= 127',f'len(series.session_indices) >= {length}')
        t=replace(t,'series.session_indices[-127:] == list(range(index-126, index+1))',f'series.session_indices[-{length}:] == list(range(index-{p["lookback"]}, index+1))')
        t=replace(t,'series.raw_closes[-20:], series.volumes[-20:]',f'series.raw_closes[-{liquidity}:], series.volumes[-{liquidity}:]')
        t=replace(t,'len(dollars)==20',f'len(dollars)=={liquidity}')
        return replace(t,'raw >= 1 and sum(dollars)/20 >= 20_000_000 and dollars[-1] >= 5_000_000',
            f'raw >= {p["minimum_price"]!r} and sum(dollars)/{liquidity} >= {p["average_dollars"]} and dollars[-1] >= {p["current_dollars"]}')
    edit(CORE+'window_signals.py',feature)
    def adapter(t):
        t=replace(t,'ring.indices[-127:]',f'ring.indices[-{length}:]')
        t=replace(t,"ring.values['signal_close'][-127:]",f"ring.values['signal_close'][-{length}:]")
        t=replace(t,"ring.values['raw_close'][-20:]",f"ring.values['raw_close'][-{liquidity}:]")
        return replace(t,"ring.values['volume'][-20:]",f"ring.values['volume'][-{liquidity}:]")
    edit('research/pooled_input_support/adapter.py',adapter)
    def median(t):
        t=replace(t,'n_slots=20, entry_weight=0.05',f'n_slots={nslots}, entry_weight={weight!r}')
        t=replace(t,'len(value["rank_history"]) > 5',f'len(value["rank_history"]) > {p["rank_memory"]}')
        t=replace(t,'history = (state["rank_history"] + [order])[-5:]',f'history = (state["rank_history"] + [order])[-{p["rank_memory"]}:]')
        t=replace(t,'durable[:3]',f'durable[:{p["front"]}]');t=replace(t,'durable[3:]',f'durable[{p["front"]}:]')
        return replace(t,'s.recent >= 0]',f's.recent >= {p["freshness"]!r}]')
    edit(CORE+'median5.py',median)
    def engine(t):
        for old,new in (
            ('top_fraction: float = 0.10',f'top_fraction: float = {p["leadership"]!r}'),
            ('max_admissions_per_session: int = 1',f'max_admissions_per_session: int = {p["admissions"]}'),
            ('minimum_leadership_population: int = 25',f'minimum_leadership_population: int = {p["minimum_leaders"]}'),
            ('self.n_slots != 20 or self.entry_weight != 0.05',f'self.n_slots != {nslots} or self.entry_weight != {weight!r}'),
            ('self.minimum_leadership_population != 25',f'self.minimum_leadership_population != {p["minimum_leaders"]}'),
            ('self.top_fraction != 0.10',f'self.top_fraction != {p["leadership"]!r}'),
            ('self.max_admissions_per_session != 1',f'self.max_admissions_per_session != {p["admissions"]}')):t=replace(t,old,new)
        return t
    edit(CORE+'engine.py',engine)
    def funding(t):
        t=replace(t,'n_slots=20, entry_weight=0.05',f'n_slots={nslots}, entry_weight={weight!r}')
        return replace(t,'intended = float(Fraction(str(equity)) / 20)',f'intended = float(Fraction(str(equity)) / {nslots})')
    edit(CORE+'v5.py',funding)
    edit('sentinel/core/session.py',lambda t:replace(t,'20 if median5 else DEFAULT_SLOTS',f'{nslots} if median5 else DEFAULT_SLOTS',count=2))
    def state(t):
        t=replace(t,'COOLDOWN_SESSIONS = 21',f'COOLDOWN_SESSIONS = {p["slot_cooldown"]}\nSECURITY_COOLDOWN_SESSIONS = {p["security_cooldown"]}')
        t=replace(t,'return n is not None and n < COOLDOWN_SESSIONS','return n is not None and n < SECURITY_COOLDOWN_SESSIONS')
        t=replace(t,'self.security_cooldowns[sid] >= COOLDOWN_SESSIONS','self.security_cooldowns[sid] >= SECURITY_COOLDOWN_SESSIONS')
        t=replace(t,'d, cooldown_sessions=COOLDOWN_SESSIONS)', 'd, cooldown_sessions=COOLDOWN_SESSIONS, security_cooldown_sessions=SECURITY_COOLDOWN_SESSIONS)')
        t=replace(t,'REVIEW_AGE_SESSIONS = 119',f'REVIEW_AGE_SESSIONS = {p["review"]}')
        t=replace(t,'STOP_RETENTION = 0.70',f'STOP_RETENTION = {p["stop"]!r}')
        return replace(t,'Fraction("0.70")',f'Fraction("{p["stop"]}")')
    edit(CORE+'state.py',state)
    def validation(t):
        t=replace(t,'def validate_payload(d, *, cooldown_sessions):','def validate_payload(d, *, cooldown_sessions, security_cooldown_sessions=None):')
        t=replace(t,'d.get("security_cooldowns"), "security_cooldowns",\n        maximum_exclusive=cooldown_sessions)',
            'd.get("security_cooldowns"), "security_cooldowns",\n        maximum_exclusive=(cooldown_sessions if security_cooldown_sessions is None else security_cooldown_sessions))')
        return t
    edit(CORE+'state_restore_validation.py',validation)
    if risk:
        if p['family']=='C':
            marker='C_'+digest(p)[:16]
            edit(CORE+'capital_risk.py',lambda t:replace(replace(replace(t,"Fraction('.10')",f"Fraction('{p['c_trigger']}')"),
                "Fraction('.08')",f"Fraction('{p['c_target']}')"),'C_10_8_V1',marker))
            edit(CORE+'adapter.py',lambda t:replace(t,'C_10_8_V1',marker))
        else:
            h=p['v_horizon']
            def policy(t):
                t=replace(t,'previous_sessions(session,21)',f'previous_sessions(session,{h})')
                t=replace(t,'len(bar.closes)<21',f'len(bar.closes)<{h}');t=replace(t,'bar.closes[-21:]',f'bar.closes[-{h}:]')
                return replace(t,'min(.30,max(.15,2*stdev([math.log(b/a) for a,b in zip(values,values[1:])])*math.sqrt(21)))',
                    f'min({p["v_maximum"]!r},max({p["v_minimum"]!r},{p["v_multiplier"]!r}*stdev([math.log(b/a) for a,b in zip(values,values[1:])])*math.sqrt({h})))')
            edit(CORE+'capital_risk.py',policy)
            def risk_axis(t):
                t=replace(t,'previous_sessions(session,21)',f'previous_sessions(session,{h})')
                return replace(t,'len(series.session_indices)>=21 and series.session_indices[-21:]==list(range(index-20,index+1))',
                    f'len(series.session_indices)>={h} and series.session_indices[-{h}:]==list(range(index-{h-1},index+1))')
            edit(CORE+'window_signals.py',risk_axis)
            edit('sentinel/core/window_material.py',lambda t:replace(t,"value['closes'] = value['closes'][-21:]",f"value['closes'] = value['closes'][-{h}:]"))
        out=bind_manifest(out)
    edit('research/pooled_vacancy_funding/runtime.py',lambda t:replace(t,
        'identity = {**identity,',f'identity = {{**identity, "research_system_campaign_sha256": "{digest(p)}",'))
    return out

def bind_manifest(files):
    # Existing classifications and operational ports are retained. Only newly
    # parameterized Wealth Core modules have their expected bytes updated.
    n='sentinel/economic-implementation-v2.json';reader='sentinel/economic_manifest.py';v=json.loads(files[n]);out=dict(files)
    for group in ('pure_contracts','input_compilers'):
        for module in v[group]:
            if module.startswith('stock_strategy_shared.wealth_core.'):
                path='shared/'+module.replace('.','/')+'.py'
                if path not in files:raise ValueError('REFUSED_CAMPAIGN_CLASSIFIED_MODULE')
                v[group][module]=hashlib.sha256(files[path]).hexdigest()
    raw=(json.dumps(v,indent=2,sort_keys=True)+'\n').encode();old=hashlib.sha256(files[n]).hexdigest()
    out[n]=raw;out[reader]=replace(files[reader].decode(),f"MANIFEST_SHA256 = '{old}'",f"MANIFEST_SHA256 = '{hashlib.sha256(raw).hexdigest()}'").encode()
    from core_manifest import extend
    return extend(out)

def build(source,destination,parameters):
    source,destination=Path(source),Path(destination)
    if destination.exists() or source.resolve()==destination.resolve():raise ValueError('REFUSED_CAMPAIGN_VARIANT_OVERWRITE')
    files={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    if len(files)!=514:raise ValueError('REFUSED_CAMPAIGN_FROZEN_SOURCE_COUNT')
    p=canonical(parameters);result=render(files,p);destination.mkdir(parents=True,exist_ok=False)
    for n,raw in result.items():
        ast.parse(raw,n) if n.endswith('.py') else None
        target=destination/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    return {'schema':'research.system-campaign-variant-source/1','parameters':p,'profile_sha256':digest(p),'original_files':514,'files':len(result),
        'all_sources':{n:hashlib.sha256(raw).hexdigest() for n,raw in result.items()},
        'changed':{n:{'before':hashlib.sha256(files[n]).hexdigest() if n in files else None,'after':hashlib.sha256(raw).hexdigest()} for n,raw in result.items() if raw!=files.get(n)}}
