"""Prospective data-only stock/mixed calendar; canonical finance stays unchanged."""
from copy import deepcopy
from dataclasses import asdict
import csv,io,json,math,os,zipfile
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need,save
from system_campaign_action_preflight import analyze_new_catalog,require_disjoint
from system_campaign_facts import digest,sha
from system_campaign_2021_completions_facts import CIL,require_witness,require_alias_archive,notional
from system_campaign_sprint_facts import published_packet,qualify_packet_schema


def validate_term(t):
    a=t['added'];w=t['identity_witness'];d=t['delivered_identity_witness'];cash=a['cash_per_share']
    need(t['security_id']==a['security_id']==w['security_id'] and t['ticker']==w['ticker']
         and w['session']<=t['last_trading_session']<a['session']
         and t['native_session'] in (t['last_trading_session'],a['session'])
         and t['mandatory_common_share_completion_confirmed'] is True
         and t['preopen_completion_confirmed'] is True and t['actual_completion_date']==a['session']
         and a['entitlement_aggregation']=='HOLDER' and a['cash_in_lieu_price_per_delivered_share'] is None
         and a['kind']==('CONVERSION' if cash is None else 'CASH_PLUS_STOCK')
         and (cash is None or type(cash) is float and math.isfinite(cash) and cash>0)
         and type(a['exchange_ratio']) is float and math.isfinite(a['exchange_ratio']) and a['exchange_ratio']>0
         and a['reference']==t['primary_source']+' | '+t['description'],
         'STOCK_CALENDAR_CONFIRMED_COMMON_TERMS_AND_PREOPEN_BOUNDARY')
    need((a['delivered_security_id'],a['delivered_ticker'],a['delivered_issuer_id'])==
         (d['security_id'],d['ticker'],d['issuer_id']) and d['session']==a['session']
         and d['security_type_eligible']=='1' and d['security_id']!=w['security_id'],
         'STOCK_CALENDAR_EXACT_FROZEN_DELIVERED_IDENTITY')
    if 'frozen_provider_issuer_limitation' in t:
        lim=t['frozen_provider_issuer_limitation']
        need(set(lim)=={'delivered_frozen_issuer','actual_new_issuer','provider_metadata_upgraded'}
             and lim['provider_metadata_upgraded'] is False and lim['delivered_frozen_issuer']==d['issuer_id']
             and lim['actual_new_issuer']!=d['issuer_id'],
             'STOCK_CALENDAR_DECLARED_FROZEN_ISSUER_LIMITATION')
    p=t['provider_rows_proof']
    need(p['ticker']==t['ticker'] and p['session']==t['native_session']
         and p['archive_bytes']==9855560
         and p['archive_sha256']=='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
         and 1<=len(p['selected_row_sha256'])<=16,'STOCK_CALENDAR_BOUNDED_EXACT_PROVIDER_PREIMAGES')


def require_provider_rows(rows,t):
    p=t['provider_rows_proof']
    need(digest(rows)==p['rows_sha256'] and [digest(r) for r in rows]==p['selected_row_sha256']
         and all(r['date']==t['native_session'] and t['ticker'] in (r['ticker'],r['contraticker']) for r in rows),
         'STOCK_CALENDAR_EVERY_ORIGINAL_PROVIDER_ROW')


class StockCalendar:
    def __init__(self,catalog):
        self.catalog=catalog;self.rows={};self.added=[];self.alias_rows=0
        need(catalog['schema']=='research.factual-stock-calendar-catalog/1' and 1<=len(catalog['terms'])<=128
             and catalog['cil_convention']==CIL and catalog['loader_sha256']==sha(Path(__file__).read_bytes())
             and not any(catalog[k] for k in ('canonical_financial_source_changed','provider_metadata_upgraded',
                                            'new_tax_or_settlement_model','production_contacted')),
             'STOCK_CALENDAR_DATA_ONLY_INHERITED_MODEL_AND_EXACT_LOADER')
        for term in catalog['terms']:validate_term(term)
        need(len({t['security_id'] for t in catalog['terms']})==len(catalog['terms']),
             'STOCK_CALENDAR_UNIQUE_SOURCE_SECURITIES')

    def hydrate(self,cp,old,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_STOCK_CALENDAR_HYDRATION_ONLY')
        from system_campaign_ordinary_registry import registrations
        need(self.catalog['commitment_group'] in registrations()
             and self.catalog['commitment_group']['loader_file']==Path(__file__).name,
             'STOCK_CALENDAR_EXPLICIT_NEW_REGISTRY_GROUP')
        check=analyze_new_catalog(cp,old,self.catalog);save(out/'stock-calendar-collision-preflight.json',check);require_disjoint(check)
        from research.pooled_input_support import inputs
        from research.pooled_input_support.bundle import axis
        dates=axis();actions=inputs.load_actions(Path('/frozen/bundle'));wanted={}
        for t in self.catalog['terms']:
            native_day=t['native_session'];day=t['added']['session'];sid=t['security_id']
            need(dates[dates.index(t['last_trading_session'])+1]==day,'STOCK_CALENDAR_EXACT_ADJACENT_SESSION')
            native,=[v for v in actions.terminal.get(native_day,()) if v.security_id==sid]
            need(digest(asdict(native))==t['native_term_sha256'] and not native.completeness(0)[0],
                 'STOCK_CALENDAR_ACTUAL_INCOMPLETE_NATIVE_BYTES')
            other=[v for v in actions.terminal.get(day,()) if v.security_id==sid]
            need(other==([native] if day==native_day else []),'STOCK_CALENDAR_NO_UNDECLARED_BASE_INPUT_COLLISION')
            for w in (t['identity_witness'],t['delivered_identity_witness']):
                key=w['session'],w['security_id']
                if key in wanted:need(wanted[key]==w,'STOCK_CALENDAR_CONSISTENT_SHARED_DELIVERY')
                wanted[key]=w
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as z:
            for year in sorted({k[0][:4] for k in wanted}):
                for row in inputs._archive_rows(z,'observations-'+year+'.csv.gz'):
                    key=row['session'],row['security_id']
                    if key not in wanted:continue
                    need(key not in self.rows,'STOCK_CALENDAR_UNIQUE_FULL_SOURCE_ROW')
                    require_witness(row,wanted[key]);self.rows[key]=row
        need(set(self.rows)==set(wanted),'STOCK_CALENDAR_ALL_SOURCE_AND_DELIVERY_WITNESSES')
        provider=(old/'provider-source/SHARADAR_ACTIONS.zip').read_bytes();require_alias_archive(provider)
        found={t['ticker']:[] for t in self.catalog['terms']}
        with zipfile.ZipFile(io.BytesIO(provider)) as z:
            for name in z.namelist():
                with z.open(name) as src:
                    for row in csv.DictReader(io.TextIOWrapper(src,encoding='utf8',newline='')):
                        for t in self.catalog['terms']:
                            if row['date']==t['native_session'] and t['ticker'] in (row['ticker'],row['contraticker']):found[t['ticker']].append(row)
        for t in self.catalog['terms']:
            require_provider_rows(found[t['ticker']],t);self.alias_rows+=len(found[t['ticker']])
            d=t['delivered_identity_witness'];row=self.rows[d['session'],d['security_id']]
            price=float(row['raw_open']);need(math.isfinite(price) and price>0,'STOCK_CALENDAR_POSITIVE_FROZEN_CIL_RAW_OPEN')
            added=deepcopy(t['added']);added['cash_in_lieu_price_per_delivered_share']=price;self.added.append(added)
        return dict(schema='research.factual-stock-calendar-private-payload/1',catalog=self.catalog,
            source_witnesses=[self.rows[k] for k in sorted(self.rows)],effective_terms=self.added,
            provider_rows=found,actual_alias_rows=self.alias_rows,source_metadata_unchanged=True,
            cil_convention=CIL,not_actual_issuer_settlement=True)

    def patch(self):
        need(len(self.added)==len(self.catalog['terms']),'STOCK_CALENDAR_HYDRATION_REQUIRED')
        return dict(suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256'])
                              for t in self.catalog['terms']],add=deepcopy(self.added))

    def qualify(self,loaded,old_objects,out,*,packet_source_sha256):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.inputs import Packet
        from research.bounded_20y.run import vendor
        from research.pooled_vacancy_funding import backtest
        from sentinel.controller import terminal_returns
        qualify_packet_schema(Packet,packet_source_sha256);actions=inputs.load_actions(Path('/frozen/bundle'))
        checks=guards=deliveries=0
        for t,a in zip(self.catalog['terms'],self.added):
            sid=t['security_id'];d=t['delivered_identity_witness'];bar=vendor(self.rows[d['session'],d['security_id']])
            prior=SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(t['last_trading_session'],1.,1.)}}},last_processed_session=t['last_trading_session'])
            for day in sorted({t['native_session'],a['session']}):
                original=Packet(day,(bar,) if day==a['session'] else (),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(original));fixed=original
                for obj in [*old_objects,loaded]:fixed=backtest.apply_repair(fixed,obj)
                need(digest(asdict(original))==before,'STOCK_CALENDAR_ORIGINAL_PACKET_UNCHANGED');checks+=1
                matches=[v for v in fixed.terminal if v.security_id==sid]
                if day==a['session']:
                    need(len(matches)==1 and asdict(matches[0])==a and matches[0].completeness(1)[0],
                         'STOCK_CALENDAR_EXACT_COMPLETE_HOLDER_CONSIDERATION')
                    values=terminal_returns.values(prior=prior,published=published_packet(fixed))
                    need(values[sid]==float(notional(a,bar)),'STOCK_CALENDAR_CANONICAL_NOTIONAL_CONSIDERATION');deliveries+=1
                    bad=SimpleNamespace(session=day,bars=(),terminal_events=fixed.terminal)
                    try:terminal_returns.values(prior=prior,published=bad)
                    except ValueError as error:need('lacks delivered close' in str(error),'STOCK_CALENDAR_MISSING_DELIVERY_QUOTE_REASON')
                    else:raise ValueError('REFUSED_STOCK_CALENDAR_MISSING_DELIVERY_QUOTE_GUARD')
                    try:require_witness({**self.rows[d['session'],d['security_id']],'issuer_id':'WRONG'},d)
                    except ValueError:pass
                    else:raise ValueError('REFUSED_STOCK_CALENDAR_CHANGED_DELIVERED_IDENTITY')
                else:need(not matches,'STOCK_CALENDAR_LAST_TRADING_SESSION_PRESERVED')
                if day==t['native_session']:
                    try:terminal_returns.values(prior=prior,published=published_packet(original))
                    except ValueError as error:need('incomplete leadership cash terminal' in str(error),'STOCK_CALENDAR_ORIGINAL_REFUSAL_REASON');guards+=1
                    else:raise ValueError('REFUSED_STOCK_CALENDAR_ORIGINAL_REFUSAL_GUARD')
        save(out,dict(schema='research.factual-stock-calendar-qualification/1',actual_packet_checks=checks,
            actual_stock_or_mixed_terms=deliveries,original_incomplete_guards=guards,actual_full_witnesses=len(self.rows),
            actual_alias_rows=self.alias_rows,cumulative_retained_inputs_applied=True,original_packets_unchanged=True,
            missing_delivery_quote_refused=True,wrong_delivered_identity_refused=True,cil_convention=CIL,
            financial_sessions_advanced=0,production_contacted=False))


def build(cp,old,out,catalog_path):
    raw=catalog_path.read_bytes();obj=StockCalendar(json.loads(raw));group=obj.catalog['commitment_group']
    need(catalog_path.name==group['catalog_file'],'STOCK_CALENDAR_EXACT_REGISTERED_CATALOG')
    payload=obj.hydrate(cp,old,out);private=out/group['private_file'];save(private,payload)
    refs={'catalog':sha(raw),'loader':sha(Path(__file__).read_bytes()),'private':sha(private.read_bytes())}
    evidence=[dict(reference=group['reference_stem']+k,sha256=v,description='Primary stock/mixed consideration, unchanged compiler and full frozen private witnesses; raw-open CIL proxy.') for k,v in refs.items()]
    for t in obj.catalog['terms']:
        evidence.extend(dict(reference=t[k],sha256=None,description=t['description']) for k in ('primary_source','timing_source'))
    overlay=out/group['overlay_file']
    save(overlay,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],source_evidence=evidence,**obj.patch()))
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(overlay,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,pred in ((cp['source_cursor'],'0'*64),(min(t['native_session'] for t in obj.catalog['terms']),cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=pred)
        except ValueError:pass
        else:raise ValueError('REFUSED_STOCK_CALENDAR_WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    return obj,loaded,overlay
