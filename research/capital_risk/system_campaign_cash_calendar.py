"""Data-driven cash recognition calendar; all arithmetic stays canonical."""
import csv
from dataclasses import asdict
import io,json,math,os,zipfile
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import need,save
from system_campaign_action_preflight import analyze_new_catalog,require_disjoint
from system_campaign_facts import digest,sha
from system_campaign_2021_completions_facts import require_witness,require_alias_archive,require_alias_rows
from system_campaign_sprint_facts import published_packet,qualify_packet_schema

PREOPEN='CONFIRMED_PREOPEN_COMPLETION'
NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY'


def validate_term(t):
    a=t['added'];w=t['identity_witness'];sid=t['security_id']
    need(a['kind']=='CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share']>0
         and a['security_id']==sid==w['security_id'] and w['ticker']==t['ticker']
         and w['session']<=t['last_trading_session']<a['session']
         and t['native_session'] in (t['last_trading_session'],a['session'])
         and a['entitlement_aggregation']=='HOLDER'
         and all(a[k] is None for k in ('delivered_security_id','delivered_ticker',
             'delivered_issuer_id','exchange_ratio','cash_in_lieu_price_per_delivered_share'))
         and a['reference']==t['primary_source']+' | '+t['description']
         and t['mandatory_common_share_completion_confirmed'] is True,
         'CASH_CALENDAR_CONFIRMED_MANDATORY_CASH_ONLY_SCOPE')
    if t['recognition_rule']==PREOPEN:
        need(t['preopen_completion_confirmed'] is True
             and t['actual_completion_date']==a['session'],'CASH_CALENDAR_ACTUAL_PREOPEN_DATE')
    else:
        need(t['recognition_rule']==NEXT and t['preopen_completion_confirmed'] is False
             and t['actual_completion_date']==t['last_trading_session']==t['native_session'],
             'CASH_CALENDAR_EXPLICIT_RETAINED_NEXT_SESSION_CONVENTION')
    if 'provider_alias_proof' in t:
        p=t['provider_alias_proof']
        need(p['ticker']==t['ticker'] and p['session']==t['native_session']
             and len(p['selected_row_sha256'])==5 and p['original_ticker']!=t['ticker'],
             'CASH_CALENDAR_EXPLICIT_FROZEN_PROVIDER_ALIAS')


class CashCalendar:
    def __init__(self,catalog):
        self.catalog=catalog;terms=catalog['terms']
        need(catalog['schema']=='research.factual-cash-calendar-catalog/1'
             and 1<=len(terms)<=128 and catalog['loader_sha256']==sha(Path(__file__).read_bytes())
             and catalog['canonical_financial_source_changed'] is False
             and catalog['provider_metadata_upgraded'] is False and catalog['production_contacted'] is False,
             'CASH_CALENDAR_DATA_ONLY_DECLARED_LOADER')
        from system_campaign_ordinary_registry import registrations
        need(catalog['commitment_group'] in registrations()
             and catalog['commitment_group']['loader_file']==Path(__file__).name,
             'CASH_CALENDAR_EXPLICIT_REGISTERED_GROUP')
        for t in terms:validate_term(t)
        need(len({t['security_id'] for t in terms})==len(terms),'CASH_CALENDAR_UNIQUE_SECURITIES')
        self.rows={};self.alias_rows=0

    def hydrate(self,cp,root,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_CASH_CALENDAR_HYDRATION_ONLY')
        proof=analyze_new_catalog(cp,root,self.catalog)
        save(out/'cash-calendar-collision-preflight.json',proof);require_disjoint(proof)
        from research.pooled_input_support import inputs
        from research.pooled_input_support.bundle import axis
        dates=axis();actions=inputs.load_actions(Path('/frozen/bundle'));wanted={}
        for t in self.catalog['terms']:
            day=t['added']['session'];native_day=t['native_session'];sid=t['security_id']
            need(dates[dates.index(t['last_trading_session'])+1]==day,
                 'CASH_CALENDAR_EXACT_FROZEN_NEXT_SESSION_AFTER_LAST_TRADE')
            native,=[v for v in actions.terminal.get(native_day,()) if v.security_id==sid]
            need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None
                 and not native.completeness(0)[0],'CASH_CALENDAR_ACTUAL_INCOMPLETE_NATIVE')
            other=[v for v in actions.terminal.get(day,()) if v.security_id==sid]
            need((other==[native] if day==native_day else not other),
                 'CASH_CALENDAR_NO_UNDECLARED_BASE_INPUT_COLLISION')
            w=t['identity_witness'];key=w['session'],sid
            need(key not in wanted,'CASH_CALENDAR_UNIQUE_WITNESS');wanted[key]=w
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for year in sorted({k[0][:4] for k in wanted}):
                for row in inputs._archive_rows(archive,'observations-'+year+'.csv.gz'):
                    key=row['session'],row['security_id']
                    if key not in wanted:continue
                    need(key not in self.rows,'CASH_CALENDAR_UNIQUE_ACTUAL_SOURCE_ROW')
                    require_witness(row,wanted[key]);self.rows[key]=row
        need(set(self.rows)==set(wanted),'CASH_CALENDAR_ALL_FULL_SOURCE_WITNESSES')
        aliases=[t for t in self.catalog['terms'] if 'provider_alias_proof' in t]
        if aliases:
            raw=(root/'provider-source/SHARADAR_ACTIONS.zip').read_bytes();require_alias_archive(raw)
            found={t['ticker']:[] for t in aliases}
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                for name in z.namelist():
                    with z.open(name) as source:
                        for row in csv.DictReader(io.TextIOWrapper(source,encoding='utf8',newline='')):
                            for t in aliases:
                                if row['date']==t['native_session'] and t['ticker'] in (row['ticker'],row['contraticker']):found[t['ticker']].append(row)
            for t in aliases:require_alias_rows(found[t['ticker']],t)
            self.alias_rows=sum(map(len,found.values()))
        return dict(schema='research.factual-cash-calendar-private-payload/1',catalog=self.catalog,
            source_witnesses=[self.rows[k] for k in sorted(self.rows)],actual_alias_rows=self.alias_rows,
            source_metadata_unchanged=True,annual_scans=len({k[0][:4] for k in wanted}))

    def patch(self):
        return dict(suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in self.catalog['terms']],
            add=[t['added'] for t in self.catalog['terms']])

    def qualify(self,loaded,old_objects,out,*,packet_source_sha256):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.inputs import Packet
        from research.pooled_vacancy_funding import backtest
        from sentinel.controller import terminal_returns
        qualify_packet_schema(Packet,packet_source_sha256)
        actions=inputs.load_actions(Path('/frozen/bundle'));checks=0;guards=0
        for t in self.catalog['terms']:
            sid=t['security_id'];native_day=t['native_session'];day=t['added']['session']
            for session in sorted({native_day,day}):
                original=Packet(session,(),{},{},1.,{},tuple(actions.terminal.get(session,())),())
                before=digest(asdict(original));fixed=original
                for obj in [*old_objects,loaded]:fixed=backtest.apply_repair(fixed,obj)
                need(digest(asdict(original))==before,'CASH_CALENDAR_ORIGINAL_PACKET_UNCHANGED');checks+=1
                matches=[v for v in fixed.terminal if v.security_id==sid]
                prior=SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(t['last_trading_session'],1.,1.)}}},last_processed_session=t['last_trading_session'])
                if session==day:
                    need(len(matches)==1 and asdict(matches[0])==t['added'] and matches[0].completeness(1)[0],
                         'CASH_CALENDAR_CUMULATIVE_EXACT_RECOGNITION_TERM')
                    actual=terminal_returns.values(prior=prior,published=published_packet(fixed))
                    need(actual[sid]==t['added']['cash_per_share'],'CASH_CALENDAR_CANONICAL_CASH_NOTIONAL')
                else:need(not matches,'CASH_CALENDAR_PRESERVED_NATIVE_LAST_TRADING_DAY')
                if session==native_day:
                    try:terminal_returns.values(prior=prior,published=published_packet(original))
                    except ValueError as e:need('incomplete leadership cash terminal' in str(e),'CASH_CALENDAR_ORIGINAL_GUARD_REASON');guards+=1
                    else:raise ValueError('REFUSED_CASH_CALENDAR_ORIGINAL_INCOMPLETE_GUARD_MISSING')
        save(out,dict(schema='research.factual-cash-calendar-qualification/1',actual_packet_checks=checks,
            actual_cash_mergers=len(self.catalog['terms']),actual_full_witnesses=len(self.rows),actual_alias_rows=self.alias_rows,
            original_incomplete_guards=guards,cumulative_retained_inputs_applied=True,
            canonical_notional_cash_verified=True,original_packets_unchanged=True,financial_sessions_advanced=0))


def build(cp,old,out,catalog_path):
    raw=catalog_path.read_bytes();catalog=CashCalendar(json.loads(raw))
    group=catalog.catalog['commitment_group']
    need(catalog_path.name==group['catalog_file'],'CASH_CALENDAR_EXACT_REGISTERED_PUBLIC_CATALOG')
    payload=catalog.hydrate(cp,old,out);private=out/group['private_file'];save(private,payload)
    refs={'catalog':sha(raw),'loader':sha(Path(__file__).read_bytes()),'private':sha(private.read_bytes())}
    stem=group['reference_stem']
    evidence=[dict(reference=stem+k,sha256=v,description='Exact data-driven primary cash recognition calendar and frozen source witnesses.') for k,v in refs.items()]
    for t in catalog.catalog['terms']:
        evidence.extend(dict(reference=t[k],sha256=None,description=t['description']) for k in ('primary_source','timing_source'))
    overlay=out/group['overlay_file']
    save(overlay,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],source_evidence=evidence,**catalog.patch()))
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(overlay,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,pred in ((cp['source_cursor'],'0'*64),(min(t['native_session'] for t in catalog.catalog['terms']),cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=pred)
        except ValueError:pass
        else:raise ValueError('REFUSED_CASH_CALENDAR_PREDECESSOR_OR_CONSUMED_FALSIFIER')
    return catalog,loaded,overlay
