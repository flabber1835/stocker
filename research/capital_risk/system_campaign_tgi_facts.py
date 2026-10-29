"""Exact TGI ordinary cash input; no financial source or state conversion."""
import json,os
from dataclasses import asdict
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/tgi-cash-catalog/1'
COMPILER='research:system-optimization-002/tgi-cash-compiler/1'
HYDRATED='research:system-optimization-002/tgi-private-cash-catalog/1'


class TgiCash:
    def __init__(self,path):
        self.catalog=json.loads(Path(path).read_bytes());self.catalog_sha=sha(Path(path).read_bytes())
        self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None
        need(self.catalog['schema']=='research.system-campaign-tgi-cash-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted'],
             'TGI_CATALOG_SCOPE')
        need([(t['ticker'],t['security_id'],t['native_session'],t['added']['session'],t['added']['cash_per_share'])
              for t in self.catalog['terms']]==[('TGI','498918945550351909','2025-07-24','2025-07-25',26.)],
             'TGI_EXACT_PRIMARY_TERMS')
        t,=self.catalog['terms'];a=t['added']
        need(a['security_id']==t['security_id'] and a['kind']=='CASH_MERGER'
             and a['exchange_ratio'] is None and a['cash_in_lieu_price_per_delivered_share'] is None
             and a['delivered_security_id'] is None and a['delivered_ticker'] is None and a['delivered_issuer_id'] is None
             and t['primary_source']=='https://www.sec.gov/Archives/edgar/data/1021162/000095017025098396/tgi-20250724.htm',
             'TGI_NO_STOCK_PROXY_OR_SOURCE_SUBSTITUTION')

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_TGI_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'));t,=self.catalog['terms']
        native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
        need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None,'TGI_ACTUAL_FROZEN_NATIVE_TERM')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'TGI_IMMUTABLE')
        cursor=cp['source_cursor'];need(cursor<'2025-07-24','TGI_OWN_PRE_EVENT')
        t,=self.catalog['terms']
        doc={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
            'source_evidence':[{'reference':CATALOG,'description':'Issuer completion, cash terms and next-session boundary.',
                                'sha256':self.catalog_sha},
                               {'reference':COMPILER,'description':'Ordinary input compiler; financial sources unchanged.',
                                'sha256':self.compiler_sha},
                               {'reference':HYDRATED,'description':'Exact native input qualification; no quote proxy.',
                                'sha256':self.hydrated_sha},
                               {'reference':t['primary_source'],'description':t['description'],'sha256':None}],
            'suppress':[{'session':t['native_session'],'security_id':t['security_id'],'term_sha256':t['native_term_sha256']}],
            'add':[t['added']]}
        save(out,doc)
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cursor,predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        actions=inputs.load_actions(Path('/frozen/bundle'));t,=self.catalog['terms']
        for day in (t['native_session'],t['added']['session']):
            packet=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
            before=digest(asdict(packet));fixed=backtest.apply_repair(packet,loaded)
            need(digest(asdict(packet))==before,'TGI_NATIVE_PACKET_UNCHANGED')
            own=[v for v in fixed.terminal if v.security_id==t['security_id']]
            if day==t['added']['session']:
                need(len(own)==1 and asdict(own[0])==t['added'] and own[0].completeness(1)[0],
                     'TGI_COMPLETE_CANONICAL_REPLACEMENT')
            else:need(not own,'TGI_PRESERVE_JULY24_TRADING')
        save(out,{'actual_native_and_added_packet_checks':2,'canonical_replacement_complete':True,
             'original_packets_unchanged':True,'financial_sessions_advanced':0,
             'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,'hydrated_sha256':self.hydrated_sha})
