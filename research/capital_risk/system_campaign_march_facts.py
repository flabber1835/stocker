"""Separately committed March cash facts; canonical parser/application unchanged."""
import json,os
from dataclasses import asdict
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/march-cash-catalog/1'
COMPILER='research:system-optimization-002/march-cash-compiler/1'
HYDRATED='research:system-optimization-002/march-private-cash-catalog/1'


class MarchCash:
    def __init__(self,path):
        self.catalog=json.loads(Path(path).read_bytes());self.catalog_sha=sha(Path(path).read_bytes())
        self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None
        need(self.catalog['schema']=='research.system-campaign-march-cash-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted']
             and self.catalog['AAAP_mandatory_payment_unproven'],'MARCH_CASH_SCOPE')
        need([(t['ticker'],t['native_session'],t['added']['session'],t['added']['cash_per_share'])
              for t in self.catalog['terms']]==[('CUDA','2018-02-09','2018-02-12',27.55),
                                               ('JUNO','2018-03-05','2018-03-07',87.),
                                               ('BIVV','2018-03-08','2018-03-08',105.)],
             'MARCH_CASH_EXACT_PRIMARY_TERMS')
        need(all(t['added']['security_id']==t['security_id'] and t['added']['kind']=='CASH_MERGER'
             and t['primary_source'].startswith('https://www.sec.gov/Archives/edgar/')
             and t['added']['exchange_ratio'] is None and t['added']['cash_in_lieu_price_per_delivered_share'] is None
             and t['added']['delivered_security_id'] is None for t in self.catalog['terms']),
             'MARCH_CASH_NO_STOCK_OR_PROXY')

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_MARCH_CASH_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'))
        for term in self.catalog['terms']:
            native,=[v for v in actions.terminal.get(term['native_session'],()) if v.security_id==term['security_id']]
            need(digest(asdict(native))==term['native_term_sha256'] and native.cash_per_share is None,
                 'MARCH_CASH_ACTUAL_FROZEN_NATIVE_TERM')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'MARCH_CASH_IMMUTABLE')
        cursor=cp['source_cursor'];need(cursor<'2018-02-09','MARCH_CASH_OWN_PRE_EVENT')
        doc={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
             'source_evidence':[{'reference':CATALOG,'description':'Issuer completion and trading-cessation facts.',
                                 'sha256':self.catalog_sha},
                                {'reference':COMPILER,'description':'Ordinary cash input compiler; no financial source changes.',
                                 'sha256':self.compiler_sha},
                                {'reference':HYDRATED,'description':'Exact native input qualification; no quote proxy.',
                                 'sha256':self.hydrated_sha}], 'suppress':[],'add':[]}
        for t in self.catalog['terms']:
            need(t['native_session']>cursor and t['added']['session']>cursor,'MARCH_CASH_NO_PAST_EVENT')
            doc['suppress'].append({'session':t['native_session'],'security_id':t['security_id'],
                                    'term_sha256':t['native_term_sha256']})
            doc['add'].append(t['added']);doc['source_evidence'].append({'reference':t['primary_source'],
                'description':t['description'],'sha256':None})
        save(out,doc)
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cursor,predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        actions=inputs.load_actions(Path('/frozen/bundle'));checked=0
        for t in self.catalog['terms']:
            # Include the intervening JUNO legal-completion session explicitly.
            days={t['native_session'],t['added']['session']}
            if t['ticker']=='JUNO':days.add('2018-03-06')
            for day in sorted(days):
                packet=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(packet));fixed=backtest.apply_repair(packet,loaded)
                need(before==digest(asdict(packet)),'MARCH_CASH_NATIVE_PACKET_UNCHANGED')
                own=[v for v in fixed.terminal if v.security_id==t['security_id']]
                if day==t['added']['session']:
                    need(len(own)==1 and asdict(own[0])==t['added'] and own[0].completeness(1)[0],
                         'MARCH_CASH_COMPLETE_CANONICAL_REPLACEMENT')
                else:need(not own,'MARCH_CASH_NO_EARLY_CANCELLATION')
                checked+=1
        save(out,{'actual_frozen_packet_checks':checked,'canonical_replacements_complete':True,
             'JUNO_native_March5_and_legal_March6_no_premature_cancellation':True,
             'original_packets_unchanged':True,'financial_sessions_advanced':0,
             'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,
             'hydrated_sha256':self.hydrated_sha,'AAAP_unresolved_no_payment':True})
