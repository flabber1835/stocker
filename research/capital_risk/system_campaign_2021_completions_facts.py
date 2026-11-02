"""Eight exact2021 ordinary common-share completions; no financial source edit."""
import csv
from dataclasses import asdict
from fractions import Fraction
import io
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_benchmark import need,save
from system_campaign_facts import digest,sha
from system_campaign_sprint_facts import published_packet,qualify_packet_schema

CATALOG='research:system-optimization-002/2021-completions-terminal-catalog/1'
COMPILER='research:system-optimization-002/2021-completions-terminal-compiler/1'
HYDRATED='research:system-optimization-002/2021-completions-private-terminal-catalog/1'
ALIAS_SHA='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
CIL='RETAINED_FROZEN_RAW_OPEN_PROXY_NOT_ACTUAL_ISSUER_SETTLEMENT'
EXPECTED=(
    ('WPX','993356691887576902','2021-01-06','2021-01-07','CONVERSION',None,0.5165,
     ('603027491965685418','DVN','SEC_CIK:1090012')),
    ('BEAT1','67573316626643986','2021-02-08','2021-02-09','CASH_MERGER',72.,None,None),
    ('MIK','350829412574453923','2021-04-14','2021-04-15','CASH_MERGER',22.,None,None),
    ('VAR','258412215698403601','2021-04-14','2021-04-15','CASH_MERGER',177.5,None,None),
    ('NAV','515332170991709358','2021-06-30','2021-07-01','CASH_MERGER',44.5,None,None),
    ('WORK','753795210944150814','2021-07-20','2021-07-21','CASH_PLUS_STOCK',26.79,0.0776,
     ('344177561147922007','CRM','SEC_CIK:1108524')),
    ('HOME','914962085458002202','2021-07-22','2021-07-23','CASH_MERGER',37.,None,None),
    ('TRIL1','1119755750402433659','2021-11-16','2021-11-17','CASH_MERGER',18.5,None,None))
ALIASES={'BEAT1':('BEAT','BIOTELEMETRY INC','PHG','KONINKLIJKE PHILIPS NV'),
         'TRIL1':('TRIL','TRILLIUM THERAPEUTICS INC','PFE','PFIZER INC')}


def notional(added,bar):
    # Canonical stock-only terms use null for unused cash, never numeric zero.
    cash=added['cash_per_share']
    value=Fraction(0) if cash is None else Fraction(str(cash))
    if bar is not None:value+=Fraction(str(added['exchange_ratio']))*Fraction(str(bar.raw_close))
    return value


def require_witness(row,w):
    need(digest(row)==w['source_observation_sha256']
         and all(row[k]==v for k,v in w.items() if k!='source_observation_sha256'),
         'COMPLETIONS2021_EXACT_FROZEN_SOURCE_OR_DELIVERY_WITNESS')


def require_alias_archive(raw):
    need(len(raw)==9855560 and sha(raw)==ALIAS_SHA,'COMPLETIONS2021_EXACT_ORIGINAL_ALIAS_ARCHIVE')


def require_alias_rows(rows,term):
    p=term['provider_alias_proof'];ticker=term['ticker']
    need(digest(rows)==p['rows_sha256'] and [digest(r) for r in rows]==p['selected_row_sha256'] and len(rows)==5
         and all(r['date']==term['native_session'] for r in rows)
         and any(r['action']=='tickerchangefrom' and r['ticker']==ticker and r['contraticker']==p['original_ticker'] for r in rows)
         and any(r['action']=='acquisitionby' and r['ticker']==ticker and r['name']==p['company']
                 and r['contraticker']==p['counterparty_ticker'] and r['contraname']==p['counterparty_name'] for r in rows)
         and any(r['action']=='acquisitionof' and r['ticker']==p['counterparty_ticker']
                 and r['contraticker']==ticker and r['contraname']==p['company'] for r in rows),
         'COMPLETIONS2021_EXACT_ALIAS_AND_COUNTERPARTY_ROWS')


def qualify_aliases(path,terms):
    wanted={t['ticker']:t for t in terms if 'provider_alias_proof' in t}
    need(set(wanted)==set(ALIASES),'COMPLETIONS2021_BOTH_PROVIDER_ALIASES_REQUIRED')
    raw=path.read_bytes();require_alias_archive(raw);found={k:[] for k in wanted}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            with archive.open(name) as source:
                for row in csv.DictReader(io.TextIOWrapper(source,encoding='utf8',newline='')):
                    for ticker,t in wanted.items():
                        if row['date']==t['native_session'] and ticker in (row['ticker'],row['contraticker']):found[ticker].append(row)
    for ticker,t in wanted.items():require_alias_rows(found[ticker],t)
    return sum(map(len,found.values()))


def preserve_autumn_cash(cp,old,out):
    from system_campaign_autumn2020_cash_facts import CATALOG as AC,COMPILER as AP,HYDRATED as AH
    name='hydrated-autumn2020-cash-terminal-catalog.json'
    expected={AC:sha(Path('/driver/system-campaign-autumn2020-cash-terminal-facts.json').read_bytes()),
        AP:sha(Path('/driver/system_campaign_autumn2020_cash_facts.py').read_bytes()),AH:sha((old/name).read_bytes())}
    found=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'COMPLETIONS2021_ALL_RETAINED_REPAIR_BYTES')
        found.extend(v for v in json.loads(raw)['source_evidence'] if v['reference'] in expected)
    need(len(found)==3 and {v['reference']:v['sha256'] for v in found}==expected,
         'COMPLETIONS2021_EXACT_COMMITTED_AUTUMN_FACTS')
    with (out/name).open('xb') as target:target.write((old/name).read_bytes())
    save(out/'retained-autumn2020-cash-facts-proof.json',dict(source_evidence=expected,
        original_bytes_unchanged=True,old_overlay_reapplied_as_new=False,financial_sessions_advanced=0))


class CompletionFacts:
    first_native='2021-01-06'

    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw);c=self.catalog
        need(c['schema']=='research.system-campaign-2021-completions-facts/1' and c['cil_convention']==CIL
             and not any(c[k] for k in ('canonical_financial_source_changed','provider_metadata_upgraded',
                 'new_tax_or_settlement_model','production_contacted')),'COMPLETIONS2021_FACTUAL_ONLY_SCOPE')
        need(len(c['terms'])==8,'COMPLETIONS2021_EXACT_EIGHT_EVENTS')
        for t,(ticker,sid,native,effective,kind,cash,ratio,delivery) in zip(c['terms'],EXPECTED):
            a=t['added'];w=t['identity_witness']
            need((t['ticker'],t['security_id'],t['native_session'],a['session'],a['kind'],a['cash_per_share'],a['exchange_ratio'])==
                 (ticker,sid,native,effective,kind,cash,ratio) and a['security_id']==sid
                 and a['entitlement_aggregation']=='HOLDER' and t['last_trading_session']==native
                 and a['cash_in_lieu_price_per_delivered_share'] is None,
                 'COMPLETIONS2021_EXACT_COMMON_SHARE_CONSIDERATION_AND_DATES')
            need(w['security_id']==sid and w['ticker']==ticker and w['session']<native
                 and a['reference'].startswith(t['primary_source']+' | '),'COMPLETIONS2021_PRIMARY_SOURCE_BOUND_IDENTITY')
            got=tuple(a[k] for k in ('delivered_security_id','delivered_ticker','delivered_issuer_id'))
            if delivery is None:
                need(got==(None,None,None) and 'delivered_identity_witness' not in t,'COMPLETIONS2021_NO_INVENTED_CASH_DELIVERY')
            else:
                dw=t['delivered_identity_witness']
                need(got==delivery and (dw['security_id'],dw['ticker'],dw['issuer_id'])==delivery
                     and dw['session']==effective and dw['security_type_eligible']=='1','COMPLETIONS2021_EXACT_FROZEN_DELIVERY_IDENTITY')
            if ticker in ALIASES:
                p=t['provider_alias_proof'];expected=ALIASES[ticker]
                need((p['original_ticker'],p['company'],p['counterparty_ticker'],p['counterparty_name'])==expected
                     and p['ticker']==ticker and p['session']==native and p['archive_sha256']==ALIAS_SHA and p['archive_bytes']==9855560
                     and w['issuer_id']=='SEC_UNKNOWN:'+sid and w['security_type_eligible']=='0',
                     'COMPLETIONS2021_ALIAS_WITHOUT_PROVIDER_METADATA_UPGRADE')
            else:need('provider_alias_proof' not in t,'COMPLETIONS2021_ONLY_DECLARED_ALIASES')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes())
        self.hydrated_sha=None;self.delivered={};self.alias_rows=0

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_COMPLETIONS2021_FACTS_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={};seen={}
        for t in self.catalog['terms']:
            native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
            need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None
                 and not native.completeness(0)[0],'COMPLETIONS2021_ACTUAL_INCOMPLETE_NATIVE_BINDING')
            need(not any(v.security_id==t['security_id'] for v in actions.terminal.get(t['added']['session'],())),
                 'COMPLETIONS2021_NO_CONFLICTING_COMPLETE_TERM')
            for w in (t['identity_witness'],*([t['delivered_identity_witness']] if 'delivered_identity_witness' in t else [])):
                key=w['session'],w['security_id'];need(key not in wanted,'COMPLETIONS2021_UNIQUE_WITNESS_BINDING');wanted[key]=w
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for row in inputs._archive_rows(archive,'observations-2021.csv.gz'):
                key=row['session'],row['security_id']
                if key not in wanted:continue
                need(key not in seen,'COMPLETIONS2021_UNIQUE_SOURCE_WITNESS_ROW');require_witness(row,wanted[key]);seen[key]=row
        need(set(seen)==set(wanted),'COMPLETIONS2021_ALL_TEN_SOURCE_AND_DELIVERY_WITNESSES')
        self.alias_rows=qualify_aliases(out.parent/'provider-source/SHARADAR_ACTIONS.zip',self.catalog['terms'])
        for t in self.catalog['terms']:
            if 'delivered_identity_witness' not in t:continue
            w=t['delivered_identity_witness'];row=seen[w['session'],w['security_id']]
            price=float(row['raw_open']);need(math.isfinite(price) and price>0,'COMPLETIONS2021_POSITIVE_DECLARED_RAW_OPEN_CIL_PROXY')
            self.delivered[t['security_id']]=row;t['added']['cash_in_lieu_price_per_delivered_share']=price
        save(out,self.catalog);self.hydrated_sha=sha(out.read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'COMPLETIONS2021_HYDRATION_IMMUTABLE')
        need(all(cp['source_cursor']<min(t['native_session'],t['added']['session']) for t in self.catalog['terms']),
             'COMPLETIONS2021_ALL_DATES_UNCONSUMED')
        evidence=[dict(reference=r,description=d,sha256=h) for r,d,h in (
            (CATALOG,'Exact primary-confirmed ordinary common-share consideration and trading dates.',self.catalog_sha),
            (COMPILER,'Factual input compiler; financial source, classifications and account state unchanged.',self.compiler_sha),
            (HYDRATED,'Actual native terms/source aliases/frozen quote witnesses and declared raw-open CIL proxy.',self.hydrated_sha))]
        for t in self.catalog['terms']:
            evidence.extend((dict(reference=t['primary_source'],description=t['description'],sha256=None),
                dict(reference=t['timing_source'],description='Preserve last trading session '+t['last_trading_session'],sha256=None)))
        save(out,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],source_evidence=evidence,
            suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in self.catalog['terms']],
            add=[t['added'] for t in self.catalog['terms']]))
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out,*,packet_source_sha256):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.bounded_20y.run import vendor
        from research.pooled_vacancy_funding import backtest
        from sentinel.controller import terminal_returns
        need(self.alias_rows==10 and len(self.delivered)==2,'COMPLETIONS2021_ACTUAL_ALIASES_AND_DELIVERIES_BEFORE_CANONICAL_PROBE')
        qualify_packet_schema(Packet,packet_source_sha256);actions=inputs.load_actions(Path('/frozen/bundle'));checks=0;stock=0
        def prior(t,day):
            sid=t['security_id'];return SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(day,1.,1.)}}},last_processed_session=day)
        for t in self.catalog['terms']:
            sid=t['security_id'];bar=vendor(self.delivered[sid]) if sid in self.delivered else None
            for day in (t['native_session'],t['added']['session']):
                original=Packet(day,(bar,) if bar is not None and day==t['added']['session'] else (),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(original));fixed=backtest.apply_repair(original,loaded);checks+=1
                need(digest(asdict(original))==before,'COMPLETIONS2021_ORIGINAL_PACKET_UNCHANGED')
                matches=[v for v in fixed.terminal if v.security_id==sid]
                if day==t['added']['session']:
                    need(len(matches)==1 and asdict(matches[0])==t['added'] and matches[0].completeness(1)[0],
                         'COMPLETIONS2021_ACTUAL_COMPLETE_ORDINARY_HOLDER_TERM')
                    values=terminal_returns.values(prior=prior(t,t['last_trading_session']),published=published_packet(fixed))
                    expected=notional(t['added'],bar)
                    need(values[sid]==float(expected),'COMPLETIONS2021_ACTUAL_CANONICAL_NOTIONAL_CONSIDERATION')
                    if bar is not None:
                        stock+=1;bad=SimpleNamespace(session=day,bars=(),terminal_events=fixed.terminal)
                        try:terminal_returns.values(prior=prior(t,t['last_trading_session']),published=bad)
                        except ValueError as error:need('lacks delivered close' in str(error),'COMPLETIONS2021_MISSING_DELIVERY_QUOTE_GUARD_REASON')
                        else:raise ValueError('REFUSED_COMPLETIONS2021_MISSING_DELIVERY_QUOTE_GUARD')
                        try:require_witness({**self.delivered[sid],'issuer_id':'WRONG'},t['delivered_identity_witness'])
                        except ValueError:pass
                        else:raise ValueError('REFUSED_COMPLETIONS2021_WRONG_DELIVERY_METADATA_GUARD')
                else:
                    need(not matches,'COMPLETIONS2021_PRESERVE_LAST_TRADING_SESSION')
                    try:terminal_returns.values(prior=prior(t,t['identity_witness']['session']),published=published_packet(original))
                    except ValueError as error:need('incomplete leadership cash terminal' in str(error),'COMPLETIONS2021_ORIGINAL_INCOMPLETE_GUARD_REASON')
                    else:raise ValueError('REFUSED_COMPLETIONS2021_ORIGINAL_INCOMPLETE_GUARD')
        need(checks==16 and stock==2,'COMPLETIONS2021_ALL_ACTUAL_CANONICAL_PROBES')
        save(out,dict(actual_packet_checks=checks,actual_native_terms=8,actual_identity_witnesses=10,
            actual_stock_conversions=stock,actual_cash_mergers=6,actual_aliases=2,actual_original_alias_rows=self.alias_rows,
            all_last_trading_sessions_preserved=True,original_packets_unchanged=True,
            actual_canonical_notional_consideration_verified=True,all_original_incomplete_guards_retained=True,
            missing_delivery_quote_refused=True,wrong_delivery_metadata_refused=True,provider_metadata_unchanged=True,
            cil_convention=CIL,actual_packet_source_sha256=packet_source_sha256,financial_sessions_advanced=0,
            catalog_sha256=self.catalog_sha,compiler_sha256=self.compiler_sha,private_hydrated_sha256=self.hydrated_sha))
