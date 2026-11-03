"""Source-backed date correction; contingent consideration stays unresolved."""
import json,os
from dataclasses import asdict,replace
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/alder-terminal-catalog/1'
COMPILER='research:system-optimization-002/alder-terminal-compiler/1'
HYDRATED='research:system-optimization-002/alder-private-terminal-catalog/1'


class AlderFacts:
    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw);c=self.catalog
        need(c['schema']=='research.system-campaign-alder-unresolved-date/1'
             and (c['security_id'],c['ticker'],c['native_session'],c['effective_session'])==
                 ('941065113449292610','ALDR','2019-10-21','2019-10-22')
             and c['known_cash_leg']=='18.00' and c['contingent_rights_per_share']=='1'
             and c['maximum_conditional_later_cash']=='2.00'
             and c['preserve_unresolved_consideration'] is True
             and not c['canonical_financial_source_changed'] and not c['production_contacted'],
             'ALDER_EXACT_DATE_UNRESOLVED_RIGHT')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.native=None
        self.hydrated_sha=None;self.original=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_ALDER_FACTS_ONLY')
        from research.pooled_input_support import inputs
        c=self.catalog;actions=inputs.load_actions(Path('/frozen/bundle'))
        term,=[v for v in actions.terminal.get(c['native_session'],()) if v.security_id==c['security_id']]
        need(digest(asdict(term))==c['native_term_sha256'] and term.cash_per_share is None
             and not term.completeness(0)[0],'ALDER_EXACT_UNRESOLVED_NATIVE')
        need(not any(v.security_id==c['security_id'] for v in actions.terminal.get(c['effective_session'],())),
             'ALDER_NO_CONFLICTING_EFFECTIVE_TERM')
        self.native=term;save(out,{'catalog':c,'actual_native':asdict(term)})
        self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'ALDER_HYDRATION_UNCHANGED')
        c=self.catalog;need(cp['source_cursor']<c['native_session'],'ALDER_UNCONSUMED_EVENT')
        save(out,{'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
            'source_evidence':[
                {'reference':CATALOG,'description':'Exact completion date and explicit unresolved contingent consideration.','sha256':self.catalog_sha},
                {'reference':COMPILER,'description':'Date-only input wrapper; never complete or value the contingent right.','sha256':self.compiler_sha},
                {'reference':HYDRATED,'description':'Exact original unresolved term and immutable source catalog.','sha256':self.hydrated_sha},
                *({'reference':u,'description':'Completed merger or exchange timing;18USD plus contingent right, not20USD upfront.','sha256':None}
                  for u in c['primary_sources'])],
            'suppress':[{'session':c['native_session'],'security_id':c['security_id'],'term_sha256':c['native_term_sha256']}],
            'add':[]})
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def __enter__(self):
        need(self.native is not None and self.hydrated_sha is not None,'ALDER_HYDRATED_BEFORE_WRAPPER')
        from research.pooled_vacancy_funding import backtest
        self.original=backtest.apply_repair
        def corrected(packet,loaded):
            changed=self.original(packet,loaded)
            if packet.session!=self.catalog['effective_session']:return changed
            need(digest(asdict(self.native))==self.catalog['native_term_sha256'] and self.native.cash_per_share is None
                 and not self.native.completeness(0)[0],'ALDER_UNRESOLVED_TERM_NOT_COMPLETED')
            need(not any(v.security_id==self.catalog['security_id'] for v in changed.terminal),'ALDER_NO_DUPLICATE_TERMINAL')
            return replace(changed,terminal=(*changed.terminal,replace(self.native,session=packet.session)))
        backtest.apply_repair=corrected;return self

    def __exit__(self,*args):
        from research.pooled_vacancy_funding import backtest
        backtest.apply_repair=self.original

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        c=self.catalog;actions=inputs.load_actions(Path('/frozen/bundle'))
        for day in (c['native_session'],c['effective_session']):
            p=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),());before=digest(asdict(p))
            changed=backtest.apply_repair(p,loaded);terms=[t for t in changed.terminal if t.security_id==c['security_id']]
            need(digest(asdict(p))==before,'ALDER_ORIGINAL_PACKET_UNCHANGED')
            if day==c['native_session']:need(not terms,'ALDER_PRESERVE_LAST_TRADING_SESSION')
            else:
                need(len(terms)==1 and asdict(terms[0])==asdict(replace(self.native,session=day))
                     and terms[0].cash_per_share is None and not terms[0].completeness(0)[0],
                     'ALDER_REQUIRED_INCOMPLETE_CONSIDERATION_PRESERVED')
        save(out,{'actual_native_and_rescheduled_packet_checks':2,'original_packets_unchanged':True,
            'preserved_last_trading_session':c['native_session'],'unresolved_effective_session':c['effective_session'],
            'contingent_consideration_deliberately_unresolved':True,'all_replacements_complete':False,
            'no_cash_or_right_valuation_invented':True,'financial_sessions_advanced':0,
            'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,'private_hydrated_sha256':self.hydrated_sha})
