"""Six exact following common-share completions; unchanged canonical finance."""
import csv
from dataclasses import asdict
import io,json,math,os,zipfile
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import need,save
from system_campaign_facts import digest,sha
from system_campaign_sprint_facts import published_packet,qualify_packet_schema
from system_campaign_2021_completions_facts import CIL,require_witness,require_alias_archive,notional

CATALOG='research:system-optimization-002/following-completions-terminal-catalog/1'
COMPILER='research:system-optimization-002/following-completions-terminal-compiler/1'
HYDRATED='research:system-optimization-002/following-completions-private-terminal-catalog/1'
EXPECTED=(
    ('ACIA','43443874000076334','2021-02-26','2021-03-01','CASH_MERGER',115.,None,None),
    ('APHA','1056418588994492299','2021-04-30','2021-05-03','CONVERSION',None,.8381,
     ('653423826172679659','TLRY','SEC_CIK:1731348')),
    ('CATM','1127660475946542495','2021-06-18','2021-06-21','CASH_MERGER',39.,None,None),
    ('AZPN1','223345417151181882','2022-05-16','2022-05-17','CASH_PLUS_STOCK',87.69,.42,
     ('556944515102158299','AZPN','SEC_CIK:929940')),
    ('REGI','1012599037173653936','2022-06-10','2022-06-13','CASH_MERGER',61.5,None,None),
    ('PLAN','621163045039428157','2022-06-21','2022-06-22','CASH_MERGER',63.75,None,None))


def require_aspen_rows(rows,term):
    p=term['provider_alias_proof']
    need(digest(rows)==p['rows_sha256'] and [digest(v) for v in rows]==p['selected_row_sha256']
         and len(rows)==5 and all(v['date']=='2022-05-16' for v in rows)
         and all(v['name']=='ASPEN TECHNOLOGY INC' for v in rows)
         and any(v['action']=='tickerchangefrom' and v['ticker']=='AZPN1' and v['contraticker']=='AZPN' for v in rows)
         and any(v['action']=='mergerto' and v['ticker']=='AZPN1' and v['contraticker']=='AZPN'
                 and v['contraname']=='ASPEN TECHNOLOGY INC' for v in rows)
         and any(v['action']=='mergerfrom' and v['ticker']=='AZPN' and v['contraticker']=='AZPN1'
                 and v['contraname']=='ASPEN TECHNOLOGY INC' for v in rows),
         'FOLLOWING_EXACT_ASPEN_ALIAS_AND_RECIPROCAL_MERGER_ROWS')


def qualify_aspen_alias(path,term):
    raw=path.read_bytes();require_alias_archive(raw);rows=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            with z.open(name) as source:
                for row in csv.DictReader(io.TextIOWrapper(source,encoding='utf8',newline='')):
                    if row['date']=='2022-05-16' and 'AZPN1' in (row['ticker'],row['contraticker']):rows.append(row)
    require_aspen_rows(rows,term)
    return len(rows)


def preserve_completions2021(cp,old,out):
    from system_campaign_2021_completions_facts import CATALOG as OC,COMPILER as OP,HYDRATED as OH
    name='hydrated-2021-completions-terminal-catalog.json'
    expected={OC:sha(Path('/driver/system-campaign-2021-completions-terminal-facts.json').read_bytes()),
        OP:sha(Path('/driver/system_campaign_2021_completions_facts.py').read_bytes()),OH:sha((old/name).read_bytes())}
    found=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'FOLLOWING_ALL_RETAINED_REPAIR_BYTES')
        found.extend(v for v in json.loads(raw)['source_evidence'] if v['reference'] in expected)
    need(len(found)==3 and {v['reference']:v['sha256'] for v in found}==expected,
         'FOLLOWING_EXACT_COMMITTED_COMPLETIONS2021_FACTS')
    with (out/name).open('xb') as target:target.write((old/name).read_bytes())
    save(out/'retained-2021-completions-facts-proof.json',dict(source_evidence=expected,
        original_bytes_unchanged=True,old_overlay_reapplied_as_new=False,financial_sessions_advanced=0))


class FollowingFacts:
    first_native='2021-02-26'

    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw);c=self.catalog
        need(c['schema']=='research.system-campaign-following-completions-facts/1' and c['cil_convention']==CIL
             and not any(c[k] for k in ('canonical_financial_source_changed','provider_metadata_upgraded',
                 'new_tax_or_settlement_model','production_contacted')),'FOLLOWING_FACTUAL_ONLY_SCOPE')
        need(len(c['terms'])==6,'FOLLOWING_EXACT_SIX_EVENTS')
        for t,(ticker,sid,native,effective,kind,cash,ratio,delivery) in zip(c['terms'],EXPECTED):
            a=t['added'];w=t['identity_witness']
            need((t['ticker'],t['security_id'],t['native_session'],a['session'],a['kind'],a['cash_per_share'],a['exchange_ratio'])==
                 (ticker,sid,native,effective,kind,cash,ratio) and a['security_id']==sid
                 and a['entitlement_aggregation']=='HOLDER' and t['last_trading_session']==native
                 and a['cash_in_lieu_price_per_delivered_share'] is None,
                 'FOLLOWING_EXACT_COMMON_SHARE_CONSIDERATION_AND_DATES')
            need(w['security_id']==sid and w['ticker']==ticker and w['session']<native
                 and a['reference'].startswith(t['primary_source']+' | '),'FOLLOWING_PRIMARY_SOURCE_BOUND_IDENTITY')
            got=tuple(a[k] for k in ('delivered_security_id','delivered_ticker','delivered_issuer_id'))
            if delivery is None:
                need(got==(None,None,None) and 'delivered_identity_witness' not in t,'FOLLOWING_NO_INVENTED_CASH_DELIVERY')
            else:
                dw=t['delivered_identity_witness']
                need(got==delivery and (dw['security_id'],dw['ticker'],dw['issuer_id'])==delivery
                     and dw['session']==effective and dw['security_type_eligible']=='1','FOLLOWING_EXACT_FROZEN_DELIVERY_IDENTITY')
            if ticker=='AZPN1':
                p=t['provider_alias_proof'];lim=t['frozen_provider_issuer_limitation']
                need(p['ticker']=='AZPN1' and p['original_ticker']=='AZPN' and p['company']=='ASPEN TECHNOLOGY INC'
                     and p['session']==native and p['archive_sha256']=='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
                     and p['archive_bytes']==9855560 and w['issuer_id']=='SEC_UNKNOWN:'+sid and w['security_type_eligible']=='0'
                     and lim==dict(source_issuer=w['issuer_id'],delivered_frozen_issuer='SEC_CIK:929940',
                                   actual_new_issuer='SEC_CIK:1897982',provider_metadata_upgraded=False),
                     'FOLLOWING_ASPEN_FROZEN_ISSUER_LIMITATION_NOT_UPGRADED')
            else:need('provider_alias_proof' not in t,'FOLLOWING_ONLY_DECLARED_ALIAS')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes())
        self.hydrated_sha=None;self.delivered={};self.alias_rows=0

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_FOLLOWING_FACTS_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={};seen={}
        for t in self.catalog['terms']:
            native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
            need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None
                 and not native.completeness(0)[0],'FOLLOWING_ACTUAL_INCOMPLETE_NATIVE_BINDING')
            need(not any(v.security_id==t['security_id'] for v in actions.terminal.get(t['added']['session'],())),
                 'FOLLOWING_NO_CONFLICTING_COMPLETE_TERM')
            for w in (t['identity_witness'],*([t['delivered_identity_witness']] if 'delivered_identity_witness' in t else [])):
                key=w['session'],w['security_id'];need(key not in wanted,'FOLLOWING_UNIQUE_WITNESS_BINDING');wanted[key]=w
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for year in ('2021','2022'):
                for row in inputs._archive_rows(archive,'observations-'+year+'.csv.gz'):
                    key=row['session'],row['security_id']
                    if key not in wanted:continue
                    need(key not in seen,'FOLLOWING_UNIQUE_SOURCE_WITNESS_ROW');require_witness(row,wanted[key]);seen[key]=row
        need(set(seen)==set(wanted) and len(seen)==8,'FOLLOWING_ALL_EIGHT_SOURCE_AND_DELIVERY_WITNESSES')
        aspen,=[t for t in self.catalog['terms'] if t['ticker']=='AZPN1']
        self.alias_rows=qualify_aspen_alias(out.parent/'provider-source/SHARADAR_ACTIONS.zip',aspen)
        for t in self.catalog['terms']:
            if 'delivered_identity_witness' not in t:continue
            w=t['delivered_identity_witness'];row=seen[w['session'],w['security_id']]
            price=float(row['raw_open']);need(math.isfinite(price) and price>0,'FOLLOWING_POSITIVE_DECLARED_RAW_OPEN_CIL_PROXY')
            self.delivered[t['security_id']]=row;t['added']['cash_in_lieu_price_per_delivered_share']=price
        save(out,self.catalog);self.hydrated_sha=sha(out.read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'FOLLOWING_HYDRATION_IMMUTABLE')
        need(all(cp['source_cursor']<min(t['native_session'],t['added']['session']) for t in self.catalog['terms']),
             'FOLLOWING_ALL_DATES_UNCONSUMED')
        evidence=[dict(reference=r,description=d,sha256=h) for r,d,h in (
            (CATALOG,'Primary-confirmed mandatory ordinary common-share terms and trading dates.',self.catalog_sha),
            (COMPILER,'Factual input compiler; financial source, classifications and account state unchanged.',self.compiler_sha),
            (HYDRATED,'Actual native terms/full witnesses/original Aspen alias and retained raw-open CIL proxies.',self.hydrated_sha))]
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
        need(self.alias_rows==5 and len(self.delivered)==2,'FOLLOWING_ACTUAL_ALIAS_AND_DELIVERIES_BEFORE_CANONICAL_PROBE')
        qualify_packet_schema(Packet,packet_source_sha256);actions=inputs.load_actions(Path('/frozen/bundle'));checks=0;stock=0
        def prior(t,day):
            sid=t['security_id'];return SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(day,1.,1.)}}},last_processed_session=day)
        for t in self.catalog['terms']:
            sid=t['security_id'];bar=vendor(self.delivered[sid]) if sid in self.delivered else None
            for day in (t['native_session'],t['added']['session']):
                original=Packet(day,(bar,) if bar is not None and day==t['added']['session'] else (),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(original));fixed=backtest.apply_repair(original,loaded);checks+=1
                need(digest(asdict(original))==before,'FOLLOWING_ORIGINAL_PACKET_UNCHANGED')
                matches=[v for v in fixed.terminal if v.security_id==sid]
                if day==t['added']['session']:
                    need(len(matches)==1 and asdict(matches[0])==t['added'] and matches[0].completeness(1)[0],
                         'FOLLOWING_ACTUAL_COMPLETE_ORDINARY_HOLDER_TERM')
                    values=terminal_returns.values(prior=prior(t,t['last_trading_session']),published=published_packet(fixed))
                    need(values[sid]==float(notional(t['added'],bar)),'FOLLOWING_ACTUAL_CANONICAL_NOTIONAL_CONSIDERATION')
                    if bar is not None:
                        stock+=1;bad=SimpleNamespace(session=day,bars=(),terminal_events=fixed.terminal)
                        try:terminal_returns.values(prior=prior(t,t['last_trading_session']),published=bad)
                        except ValueError as error:need('lacks delivered close' in str(error),'FOLLOWING_MISSING_DELIVERY_QUOTE_GUARD_REASON')
                        else:raise ValueError('REFUSED_FOLLOWING_MISSING_DELIVERY_QUOTE_GUARD')
                        try:require_witness({**self.delivered[sid],'issuer_id':'WRONG'},t['delivered_identity_witness'])
                        except ValueError:pass
                        else:raise ValueError('REFUSED_FOLLOWING_WRONG_DELIVERY_METADATA_GUARD')
                else:
                    need(not matches,'FOLLOWING_PRESERVE_LAST_TRADING_SESSION')
                    try:terminal_returns.values(prior=prior(t,t['identity_witness']['session']),published=published_packet(original))
                    except ValueError as error:need('incomplete leadership cash terminal' in str(error),'FOLLOWING_ORIGINAL_INCOMPLETE_GUARD_REASON')
                    else:raise ValueError('REFUSED_FOLLOWING_ORIGINAL_INCOMPLETE_GUARD')
        need(checks==12 and stock==2,'FOLLOWING_ALL_ACTUAL_CANONICAL_PROBES')
        save(out,dict(actual_packet_checks=checks,actual_native_terms=6,actual_identity_witnesses=8,
            actual_stock_conversions=stock,actual_cash_mergers=4,actual_aliases=1,actual_original_alias_rows=self.alias_rows,
            all_last_trading_sessions_preserved=True,original_packets_unchanged=True,
            actual_canonical_notional_consideration_verified=True,all_original_incomplete_guards_retained=True,
            missing_delivery_quote_refused=True,wrong_delivery_metadata_refused=True,provider_metadata_unchanged=True,
            aspen_frozen_issuer_limitation_disclosed=True,cil_convention=CIL,
            actual_packet_source_sha256=packet_source_sha256,financial_sessions_advanced=0,
            catalog_sha256=self.catalog_sha,compiler_sha256=self.compiler_sha,private_hydrated_sha256=self.hydrated_sha))
