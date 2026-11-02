"""Three primary-confirmed mandatory cash completions, no account-state edits."""
from dataclasses import asdict
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_sprint_facts import published_packet, qualify_packet_schema

CATALOG='research:system-optimization-002/spring2020-cash-terminal-catalog/1'
COMPILER='research:system-optimization-002/spring2020-cash-terminal-compiler/1'
HYDRATED='research:system-optimization-002/spring2020-cash-private-terminal-catalog/1'
EXPECTED=(('CY','66103160004367746','2020-04-16','2020-04-16',23.85,'2020-04-15'),
          ('MLNX','597162481941536532','2020-04-24','2020-04-27',125.,'2020-04-24'),
          ('WBC','384188467071429790','2020-05-28','2020-05-29',136.5,'2020-05-28'))


def require_witness(row,witness):
    need(digest(row)==witness['source_observation_sha256']
         and all(row[k]==v for k,v in witness.items() if k!='source_observation_sha256'),
         'SPRING2020_CASH_EXACT_FROZEN_IDENTITY_WITNESS')


def preserve_sprint(cp,old,out):
    from system_campaign_sprint_facts import CATALOG as SC,COMPILER as SP,HYDRATED as SH
    name='hydrated-sprint-terminal-catalog.json'
    expected={SC:sha(Path('/driver/system-campaign-sprint-terminal-facts.json').read_bytes()),
        SP:sha(Path('/driver/system_campaign_sprint_facts.py').read_bytes()),SH:sha((old/name).read_bytes())}
    found=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'SPRING2020_CASH_ALL_RETAINED_REPAIR_BYTES')
        found.extend(v for v in json.loads(raw)['source_evidence'] if v['reference'] in expected)
    need(len(found)==3 and {v['reference']:v['sha256'] for v in found}==expected,
         'SPRING2020_CASH_EXACT_COMMITTED_SPRINT_FACTS')
    with (out/name).open('xb') as target:target.write((old/name).read_bytes())
    save(out/'retained-sprint-facts-proof.json',dict(source_evidence=expected,
        original_bytes_unchanged=True,old_overlay_reapplied_as_new=False,financial_sessions_advanced=0))


class CashCompletionFacts:
    first_native='2020-04-16'

    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw);c=self.catalog
        need(c['schema']=='research.system-campaign-spring2020-cash-facts/1'
             and not any(c[k] for k in ('canonical_financial_source_changed','provider_metadata_upgraded',
                 'new_tax_or_settlement_model','production_contacted')),
             'SPRING2020_CASH_FACTUAL_ONLY_SCOPE')
        need(len(c['terms'])==3,'SPRING2020_CASH_EXACT_THREE_COMPLETIONS')
        for t,(ticker,sid,native,effective,cash,last_trade) in zip(c['terms'],EXPECTED):
            a=t['added'];w=t['identity_witness']
            need((t['ticker'],t['security_id'],t['native_session'],a['session'],a['cash_per_share'])==
                 (ticker,sid,native,effective,cash) and a['security_id']==sid and a['kind']=='CASH_MERGER'
                 and a['entitlement_aggregation']=='HOLDER' and t['last_trading_session']==last_trade
                 and all(a[k] is None for k in ('delivered_security_id','delivered_ticker','delivered_issuer_id',
                     'exchange_ratio','cash_in_lieu_price_per_delivered_share')),
                 'SPRING2020_CASH_EXACT_MANDATORY_COMMON_SHARE_TERMS')
            need(w['security_id']==sid and w['ticker']==ticker and w['session']<native
                 and a['reference'].startswith(t['primary_source']+' | '),
                 'SPRING2020_CASH_SOURCE_BOUND_IDENTITY_AND_PRIMARY_REFERENCE')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_SPRING2020_CASH_FACTS_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={}
        for t in self.catalog['terms']:
            native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
            need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None
                 and not native.completeness(0)[0],'SPRING2020_CASH_ACTUAL_INCOMPLETE_NATIVE_BINDING')
            if t['added']['session']!=t['native_session']:
                need(not any(v.security_id==t['security_id'] for v in actions.terminal.get(t['added']['session'],())),
                     'SPRING2020_CASH_NO_CONFLICTING_COMPLETE_TERM')
            w=t['identity_witness'];wanted[(w['session'],w['security_id'])]=w
        seen=set()
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for row in inputs._archive_rows(archive,'observations-2020.csv.gz'):
                key=row['session'],row['security_id']
                if key not in wanted:continue
                need(key not in seen,'SPRING2020_CASH_UNIQUE_WITNESS_ROW');require_witness(row,wanted[key]);seen.add(key)
        need(seen==set(wanted),'SPRING2020_CASH_ALL_ACTUAL_SOURCE_WITNESSES')
        save(out,self.catalog);self.hydrated_sha=sha(out.read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,
             'SPRING2020_CASH_HYDRATION_IMMUTABLE')
        need(all(cp['source_cursor']<min(t['native_session'],t['added']['session']) for t in self.catalog['terms']),
             'SPRING2020_CASH_ALL_DATES_UNCONSUMED')
        evidence=[dict(reference=r,description=d,sha256=h) for r,d,h in (
            (CATALOG,'Primary-confirmed gross common-share cash and actual preopen completion dates.',self.catalog_sha),
            (COMPILER,'Exact factual input compiler; no financial source or state conversion.',self.compiler_sha),
            (HYDRATED,'Actual frozen native terms and unchanged identity witnesses.',self.hydrated_sha))]
        for t in self.catalog['terms']:
            evidence.extend((dict(reference=t['primary_source'],description=t['description'],sha256=None),
                dict(reference=t['timing_source'],description='Actual preopen completion; preserve last trading session '+t['last_trading_session'],sha256=None)))
        save(out,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],source_evidence=evidence,
            suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in self.catalog['terms']],
            add=[t['added'] for t in self.catalog['terms']]))
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out,*,packet_source_sha256):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        from sentinel.controller import terminal_returns
        qualify_packet_schema(Packet,packet_source_sha256)
        actions=inputs.load_actions(Path('/frozen/bundle'));checks=0
        def prior(sid,day):return SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(day,1.,1.)}}},last_processed_session=day)
        for t in self.catalog['terms']:
            for day in sorted({t['native_session'],t['added']['session']}):
                original=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),());before=digest(asdict(original))
                fixed=backtest.apply_repair(original,loaded);checks+=1
                need(digest(asdict(original))==before,'SPRING2020_CASH_ORIGINAL_PACKET_UNCHANGED')
                matches=[v for v in fixed.terminal if v.security_id==t['security_id']]
                if day==t['added']['session']:
                    need(len(matches)==1 and asdict(matches[0])==t['added'] and matches[0].completeness(1)[0],
                         'SPRING2020_CASH_ACTUAL_COMPLETE_COMMON_SHARE_TERM')
                    values=terminal_returns.values(prior=prior(t['security_id'],t['last_trading_session']),published=published_packet(fixed))
                    need(values[t['security_id']]==t['added']['cash_per_share'],'SPRING2020_CASH_CANONICAL_NOTIONAL_CONSIDERATION')
                else:need(not matches,'SPRING2020_CASH_PRESERVE_LAST_TRADING_SESSION')
                if day==t['native_session']:
                    try:terminal_returns.values(prior=prior(t['security_id'],t['identity_witness']['session']),published=published_packet(original))
                    except ValueError as error:need('incomplete leadership cash terminal' in str(error),'SPRING2020_CASH_ORIGINAL_GUARD_REASON')
                    else:raise ValueError('REFUSED_SPRING2020_CASH_ORIGINAL_INCOMPLETE_GUARD_MISSING')
        save(out,dict(actual_packet_checks=checks,actual_native_terms=3,actual_identity_witnesses=3,
            same_date_CY_replacement_verified=True,original_packets_unchanged=True,
            actual_canonical_notional_cash_verified=True,all_original_incomplete_guards_retained=True,
            actual_packet_source_sha256=packet_source_sha256,financial_sessions_advanced=0,
            catalog_sha256=self.catalog_sha,compiler_sha256=self.compiler_sha,private_hydrated_sha256=self.hydrated_sha))
