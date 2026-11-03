"""Exact mandatory MDCO cash completion; no strategy or account-state edits."""
import json
import os
from dataclasses import asdict
from pathlib import Path
import zipfile

from full_system_benchmark import need, save
from system_campaign_facts import digest, sha

CATALOG='research:system-optimization-002/medicines-terminal-catalog/1'
COMPILER='research:system-optimization-002/medicines-terminal-compiler/1'
HYDRATED='research:system-optimization-002/medicines-private-terminal-catalog/1'


class MedicinesFacts:
    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw)
        need(self.catalog['schema']=='research.system-campaign-medicines-terminal-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted'],
             'MEDICINES_EXACT_CATALOG_SCOPE')
        need(len(self.catalog['terms'])==1,'MEDICINES_ONE_PRIMARY_REVIEWED_EVENT')
        t=self.catalog['terms'][0];a=t['added']
        need(t['ticker']=='MDCO' and t['security_id']==a['security_id']=='1000604417782241778'
             and t['native_session']=='2020-01-03' and a['session']=='2020-01-06'
             and a['kind']=='CASH_MERGER' and a['cash_per_share']==85.
             and a['entitlement_aggregation']=='HOLDER'
             and all(a[k] is None for k in ('delivered_security_id','delivered_ticker','delivered_issuer_id',
                 'exchange_ratio','cash_in_lieu_price_per_delivered_share')),
             'MEDICINES_EXACT_MANDATORY_CASH_AND_CORRECT_DATE')
        w=self.catalog['identity_witness']
        need((w['session'],w['security_id'],w['ticker'],w['issuer_id'],w['listing_first_session'],w['security_type_eligible'])==
             ('2020-01-02','1000604417782241778','MDCO','SEC_CIK:1113481','2000-08-08','1'),
             'MEDICINES_FROZEN_IDENTITY_AND_ELIGIBILITY_UNCHANGED')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_MEDICINES_FACTS_ONLY')
        from research.pooled_input_support import inputs
        t=self.catalog['terms'][0];actions=inputs.load_actions(Path('/frozen/bundle'))
        native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
        need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None
             and not native.completeness(0)[0],'MEDICINES_EXACT_ACTUAL_UNRESOLVED_NATIVE')
        need(not any(v.security_id==t['security_id'] for v in actions.terminal.get(t['added']['session'],())),
             'MEDICINES_NO_ALREADY_COMPLETE_CONFLICTING_TERM')
        w=self.catalog['identity_witness'];found=[]
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for row in inputs._archive_rows(archive,'observations-2020.csv.gz'):
                if (row['session'],row['security_id'])==(w['session'],w['security_id']):found.append(row)
        need(len(found)==1 and digest(found[0])==w['source_observation_sha256']
             and all(found[0][k]==v for k,v in w.items() if k!='source_observation_sha256'),
             'MEDICINES_EXACT_FROZEN_PRIVATE_IDENTITY_WITNESS')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def evidence(self):
        return [dict(reference=r,description=d,sha256=v) for r,d,v in (
            (CATALOG,'Exact issuer mandatory85USD and January6preopen/January3lasttrade facts.',self.catalog_sha),
            (COMPILER,'Exact ordinary sparse input compiler; no financial source or state change.',self.compiler_sha),
            (HYDRATED,'Exact private frozen identity witness and native-action binding.',self.hydrated_sha))]

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,
             'MEDICINES_HYDRATION_IMMUTABLE')
        need(cp['source_cursor']<'2020-01-03','MEDICINES_BOTH_EVENT_DATES_UNCONSUMED')
        t=self.catalog['terms'][0]
        save(out,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
            source_evidence=[*self.evidence(),dict(reference=t['primary_source'],description=t['description'],sha256=None),
                dict(reference=t['exchange_source'],description='Exchange confirms Jan6beforeopen and preserves Jan3trading.',sha256=None)],
            suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256'])],
            add=[t['added']]))
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        t=self.catalog['terms'][0];actions=inputs.load_actions(Path('/frozen/bundle'))
        for day in (t['native_session'],t['added']['session']):
            packet=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),());before=digest(asdict(packet))
            fixed=backtest.apply_repair(packet,loaded)
            need(digest(asdict(packet))==before,'MEDICINES_ORIGINAL_PACKET_UNCHANGED')
            terms=[v for v in fixed.terminal if v.security_id==t['security_id']]
            if day==t['native_session']:need(not terms,'MEDICINES_PRESERVE_JANUARY3_TRADING')
            else:need(len(terms)==1 and asdict(terms[0])==t['added'] and terms[0].completeness(1)[0],
                      'MEDICINES_COMPLETE_MANDATORY_JANUARY6_CONSIDERATION')
        save(out,dict(actual_native_and_added_packet_checks=2,original_packets_unchanged=True,
            preserved_last_trading_session='2020-01-03',effective_preopen_session='2020-01-06',
            exact_cash_per_eligible_common_share='85.00',mandatory_remaining_share_terms=True,
            catalog_sha256=self.catalog_sha,compiler_sha256=self.compiler_sha,private_hydrated_sha256=self.hydrated_sha,
            financial_sessions_advanced=0))
