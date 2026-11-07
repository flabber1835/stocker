"""Exact mandatory Array BioPharma cash completion; no financial state edits."""
import json,os,zipfile
from dataclasses import asdict
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/array-terminal-catalog/1'
COMPILER='research:system-optimization-002/array-terminal-compiler/1'
HYDRATED='research:system-optimization-002/array-private-terminal-catalog/1'


class ArrayFacts:
    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw)
        need(self.catalog['schema']=='research.system-campaign-array-terminal-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted'],
             'ARRAY_CATALOG_SCOPE')
        need(len(self.catalog['terms'])==1,'ARRAY_ONE_REVIEWED_EVENT')
        t=self.catalog['terms'][0];a=t['added']
        need(t['ticker']=='ARRY1' and t['security_id']==a['security_id']=='331866698645518730'
             and t['native_session']==a['session']=='2019-07-30' and a['kind']=='CASH_MERGER'
             and a['cash_per_share']==48. and a['entitlement_aggregation']=='HOLDER'
             and all(a[k] is None for k in ('delivered_security_id','delivered_ticker','delivered_issuer_id',
                 'exchange_ratio','cash_in_lieu_price_per_delivered_share')),
             'ARRAY_EXACT_PRIMARY_SAME_DAY_CASH_TERMS')
        w=self.catalog['identity_witness']
        need((w['session'],w['security_id'],w['ticker'],w['issuer_id'],w['listing_first_session'],w['security_type_eligible'])==
             ('2019-07-29','331866698645518730','ARRY1','SEC_UNKNOWN:331866698645518730','2000-11-30','0'),
             'ARRAY_NO_IDENTITY_OR_ELIGIBILITY_UPGRADE')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_ARRAY_FACTS_ONLY')
        from research.pooled_input_support import inputs
        t=self.catalog['terms'][0];actions=inputs.load_actions(Path('/frozen/bundle'))
        native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
        need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None,
             'ARRAY_ACTUAL_FROZEN_NATIVE_TERM')
        w=self.catalog['identity_witness'];found=[]
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as z:
            for r in inputs._archive_rows(z,'observations-2019.csv.gz'):
                if (r['session'],r['security_id'])==(w['session'],w['security_id']):found.append(r)
        need(len(found)==1 and digest(found[0])==w['source_observation_sha256']
             and all(found[0][k]==v for k,v in w.items() if k!='source_observation_sha256'),
             'ARRAY_EXACT_PRIVATE_IDENTITY_WITNESS')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'ARRAY_HYDRATION_UNCHANGED')
        need(cp['source_cursor']<'2019-07-30','ARRAY_UNCONSUMED_EVENT')
        t=self.catalog['terms'][0]
        doc={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
             'source_evidence':[
                 {'reference':CATALOG,'description':'Exact issuer completed mandatory48USD July30,2019 entitlement.', 'sha256':self.catalog_sha},
                 {'reference':COMPILER,'description':'Exact ordinary input compiler; financial sources unchanged.', 'sha256':self.compiler_sha},
                 {'reference':HYDRATED,'description':'Exact private frozen identity witness admission.', 'sha256':self.hydrated_sha},
                 {'reference':t['primary_source'],'description':t['description'],'sha256':None}],
             'suppress':[{'session':t['native_session'],'security_id':t['security_id'],'term_sha256':t['native_term_sha256']}],
             'add':[t['added']]}
        save(out,doc)
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        t=self.catalog['terms'][0];day=t['native_session'];actions=inputs.load_actions(Path('/frozen/bundle'))
        p=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),());before=digest(asdict(p))
        changed=backtest.apply_repair(p,loaded);matches=[v for v in changed.terminal if v.security_id==t['security_id']]
        need(digest(asdict(p))==before and len(matches)==1 and asdict(matches[0])==t['added']
             and matches[0].completeness(1)[0],'ARRAY_ACTUAL_COMPLETE_REPLACEMENT_ORIGINAL_UNCHANGED')
        save(out,{'actual_native_and_added_packet_checks':1,'all_replacements_complete':True,'original_packets_unchanged':True,
            'financial_sessions_advanced':0,'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,
            'private_hydrated_sha256':self.hydrated_sha,'mandatory_remaining_share_terms_not_voluntary_tender':True})
