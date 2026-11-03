"""Reusable data-driven mandatory cash completions; canonical finance unchanged."""
from dataclasses import asdict
import json,math,os,zipfile
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import need,save
from system_campaign_action_preflight import analyze_new_catalog,require_disjoint
from system_campaign_facts import digest,sha
from system_campaign_2021_completions_facts import require_witness
from system_campaign_sprint_facts import published_packet,qualify_packet_schema


class CashBatch:
    def __init__(self,catalog):
        self.catalog=catalog;terms=catalog['terms']
        need(catalog['schema']=='research.future-input-amendment-catalog/1' and 1<=len(terms)<=128
             and catalog['cash_loader_sha256']==sha(Path(__file__).read_bytes())
             and catalog['canonical_financial_source_changed'] is False
             and catalog['provider_metadata_upgraded'] is False,'CASH_BATCH_DECLARED_DATA_ONLY_LOADER')
        for t in terms:
            a=t['added'];w=t['identity_witness']
            need(a['kind']=='CASH_MERGER' and type(a['cash_per_share']) is float
                 and math.isfinite(a['cash_per_share']) and a['cash_per_share']>0
                 and a['security_id']==t['security_id']==w['security_id']
                 and w['ticker']==t['ticker'] and w['session']<t['native_session']<a['session']
                 and t['last_trading_session']==t['native_session']
                 and a['entitlement_aggregation']=='HOLDER'
                 and all(a[k] is None for k in ('delivered_security_id','delivered_ticker',
                     'delivered_issuer_id','exchange_ratio','cash_in_lieu_price_per_delivered_share'))
                 and a['reference'].startswith(t['primary_source']+' | ')
                 and t['mandatory_common_share_completion_confirmed'] is True
                 and t['preopen_completion_confirmed'] is True,'CASH_BATCH_EXACT_CONFIRMED_CASH_ONLY_SCOPE')
        self.rows={}

    def hydrate(self,cp,root,out,*,extra_witnesses=()):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_CASH_BATCH_HYDRATION_ONLY')
        check=analyze_new_catalog(cp,root,self.catalog);save(out/'new-action-collision-preflight.json',check);require_disjoint(check)
        from research.pooled_input_support import inputs
        from research.pooled_input_support.bundle import axis
        dates=axis()
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={}
        for t in self.catalog['terms']:
            need(dates[dates.index(t['native_session'])+1]==t['added']['session'],
                 'CASH_BATCH_EXACT_NEXT_FROZEN_TRADING_SESSION')
            native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
            need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None
                 and not native.completeness(0)[0],'CASH_BATCH_ACTUAL_INCOMPLETE_NATIVE_TERM')
            need(not any(v.security_id==t['security_id'] for v in actions.terminal.get(t['added']['session'],())),
                 'CASH_BATCH_NO_COMPLETE_BASE_INPUT_COLLISION')
            w=t['identity_witness'];key=w['session'],w['security_id']
            need(key not in wanted,'CASH_BATCH_UNIQUE_WITNESS');wanted[key]=w
        for w in extra_witnesses:
            key=w['session'],w['security_id'];need(key not in wanted,'CASH_BATCH_UNIQUE_EXTRA_WITNESS');wanted[key]=w
        # All requested witnesses in a year share one read, not one read/company.
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for year in sorted({k[0][:4] for k in wanted}):
                for row in inputs._archive_rows(archive,'observations-'+year+'.csv.gz'):
                    key=row['session'],row['security_id']
                    if key not in wanted:continue
                    need(key not in self.rows,'CASH_BATCH_UNIQUE_ACTUAL_SOURCE_ROW')
                    require_witness(row,wanted[key]);self.rows[key]=row
        need(set(self.rows)==set(wanted),'CASH_BATCH_ALL_FULL_SOURCE_WITNESSES_PRESENT')
        return dict(schema='research.factual-cash-batch-private-witnesses/1',
            witnesses=[self.rows[k] for k in sorted(self.rows)],source_metadata_unchanged=True,
            annual_scans=len({k[0][:4] for k in wanted}),requested_events=len(self.catalog['terms']),
            auxiliary_witnesses=len(extra_witnesses))

    def patch(self):
        return dict(suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in self.catalog['terms']],
            add=[t['added'] for t in self.catalog['terms']])

    def qualify(self,loaded,old_objects,out,*,packet_source_sha256):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.inputs import Packet
        from research.pooled_vacancy_funding import backtest
        from sentinel.controller import terminal_returns
        qualify_packet_schema(Packet,packet_source_sha256)
        actions=inputs.load_actions(Path('/frozen/bundle'));checks=0
        for t in self.catalog['terms']:
            sid=t['security_id']
            for day in (t['native_session'],t['added']['session']):
                original=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(original));fixed=original
                for obj in [*old_objects,loaded]:fixed=backtest.apply_repair(fixed,obj)
                need(digest(asdict(original))==before,'CASH_BATCH_ORIGINAL_PACKET_UNCHANGED');checks+=1
                matching=[v for v in fixed.terminal if v.security_id==sid]
                prior=SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(t['last_trading_session'],1.,1.)}}},last_processed_session=t['last_trading_session'])
                if day==t['added']['session']:
                    need(len(matching)==1 and asdict(matching[0])==t['added'] and matching[0].completeness(1)[0],
                         'CASH_BATCH_CUMULATIVE_EXACT_COMPLETE_CASH_TERM')
                    value=terminal_returns.values(prior=prior,published=published_packet(fixed))
                    need(value[sid]==t['added']['cash_per_share'],'CASH_BATCH_ACTUAL_CANONICAL_NOTIONAL_CASH')
                else:
                    need(not matching,'CASH_BATCH_PRESERVE_LAST_TRADING_SESSION')
                    try:terminal_returns.values(prior=prior,published=published_packet(original))
                    except ValueError as e:need('incomplete leadership cash terminal' in str(e),'CASH_BATCH_ORIGINAL_GUARD_REASON')
                    else:raise ValueError('REFUSED_CASH_BATCH_ORIGINAL_INCOMPLETE_GUARD_MISSING')
        save(out,dict(schema='research.factual-cash-batch-qualification/1',actual_packet_checks=checks,
            actual_cash_mergers=len(self.catalog['terms']),actual_full_witnesses=len(self.rows),
            cumulative_retained_inputs_applied=True,canonical_notional_cash_verified=True,
            original_packets_unchanged=True,original_incomplete_guards_preserved=True,
            provider_metadata_unchanged=True,financial_sessions_advanced=0,
            actual_packet_source_sha256=packet_source_sha256))
