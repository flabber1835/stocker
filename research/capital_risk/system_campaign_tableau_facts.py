"""Exact mandatory Tableau stock conversion; canonical financial source unchanged."""
import json,os,zipfile
from dataclasses import asdict
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/tableau-terminal-catalog/1'
COMPILER='research:system-optimization-002/tableau-terminal-compiler/1'
HYDRATED='research:system-optimization-002/tableau-private-terminal-catalog/1'


class TableauFacts:
    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw)
        need(self.catalog['schema']=='research.system-campaign-tableau-terminal-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted'],
             'TABLEAU_CATALOG_SCOPE')
        need([(t['ticker'],t['security_id'],t['native_session'],t['added']['session'],t['added']['kind'],
               t['added']['security_id'],t['added']['cash_per_share'],t['added']['exchange_ratio']) for t in self.catalog['terms']]==[
            ('DATA','1043452212170571060','2019-07-31','2019-08-01','CONVERSION','1043452212170571060',None,1.103),
            ('TCF1','216684274153477700','2019-07-31','2019-08-01','CONVERSION','216684274153477700',None,.5081),
            ('CTRL','261788311002817744','2019-07-31','2019-08-02','CASH_MERGER','261788311002817744',23.91,None),
            ('UQM','3393863893051950','2019-07-31','2019-08-01','CASH_MERGER','3393863893051950',1.71,None),
            ('BKS','268110096969655215','2019-08-06','2019-08-07','CASH_MERGER','268110096969655215',6.5,None)],
             'TABLEAU_BATCH_EXACT_PRIMARY_TERMS_AND_BOUNDARIES')
        for t,sid,ticker,issuer in zip(self.catalog['terms'][:2],('344177561147922007','707661213264749628'),
                                      ('CRM','TCF'),('SEC_CIK:1108524','SEC_CIK:814184')):
            a,p=t['added'],t['proxy']
            need(a['delivered_security_id']==p['security_id']==sid and a['delivered_ticker']==ticker
                 and a['delivered_issuer_id']==issuer and p['session']=='2019-08-01'
                 and a['cash_in_lieu_price_per_delivered_share'] is None,'TABLEAU_BATCH_EXACT_DELIVERED_IDENTITY_PROXY')
        need(all(t['proxy'] is None and all(t['added'][k] is None for k in ('delivered_security_id','delivered_ticker',
                 'delivered_issuer_id','cash_in_lieu_price_per_delivered_share')) for t in self.catalog['terms'][2:])
             and all(t['added']['entitlement_aggregation']=='HOLDER' for t in self.catalog['terms'])
             and self.catalog['unreviewed_preferred_security_untouched']=='884451527437425797','TABLEAU_NO_INVENTED_PREFERRED_OR_STOCK_LEGS')
        need([(w['session'],w['security_id'],w['ticker'],w['issuer_id'],w['listing_first_session'],w['security_type_eligible'])
              for w in self.catalog['identity_witnesses']]==[('2019-07-31','216684274153477700','TCF1','SEC_UNKNOWN:216684274153477700','1997-12-31','0')],
             'TABLEAU_TCF_ALIAS_NO_ELIGIBILITY_UPGRADE')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_TABLEAU_FACTS_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={};witnesses={}
        for t in self.catalog['terms']:
            native,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
            need(digest(asdict(native))==t['native_term_sha256'] and native.cash_per_share is None,'TABLEAU_ACTUAL_FROZEN_NATIVE_TERM')
            if t['proxy']:
                p=t['proxy'];need((p['session'],p['security_id']) not in wanted,'TABLEAU_UNIQUE_FROZEN_PROXY');wanted[p['session'],p['security_id']]=t
        for w in self.catalog['identity_witnesses']:witnesses[w['session'],w['security_id']]=w
        found={};seen=set()
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as z:
            for r in inputs._archive_rows(z,'observations-2019.csv.gz'):
                k=r['session'],r['security_id']
                if k in witnesses:
                    w=witnesses[k];need(k not in seen and digest(r)==w['source_observation_sha256']
                        and all(r[x]==v for x,v in w.items() if x!='source_observation_sha256'),'TABLEAU_EXACT_FROZEN_ALIAS_WITNESS');seen.add(k)
                if k not in wanted:continue
                t=wanted[k];need(k not in found and digest(r)==t['proxy']['source_observation_sha256']
                    and r['ticker']==t['added']['delivered_ticker'] and r['issuer_id']==t['added']['delivered_issuer_id'],
                    'TABLEAU_EXACT_FROZEN_DELIVERED_QUOTE');found[k]=r
                price=float(r['raw_open']);need(price>0,'TABLEAU_POSITIVE_DECLARED_PROXY');t['added']['cash_in_lieu_price_per_delivered_share']=price
        need(set(found)==set(wanted) and seen==set(witnesses),'TABLEAU_ALL_QUOTES_AND_WITNESSES')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'TABLEAU_HYDRATION_UNCHANGED')
        need(cp['source_cursor']<'2019-07-31','TABLEAU_UNCONSUMED_EVENT')
        doc={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
             'source_evidence':[
                 {'reference':CATALOG,'description':'Exact completed mandatory1.103CRM exchange terms and preopen boundary.', 'sha256':self.catalog_sha},
                 {'reference':COMPILER,'description':'Exact ordinary input compiler; financial sources unchanged.', 'sha256':self.compiler_sha},
                 {'reference':HYDRATED,'description':'Exact privately hydrated frozen raw-open fractional-CIL research proxy.', 'sha256':self.hydrated_sha}],
             'suppress':[],'add':[]}
        for t in self.catalog['terms']:
            doc['suppress'].append({'session':t['native_session'],'security_id':t['security_id'],'term_sha256':t['native_term_sha256']})
            doc['add'].append(t['added']);doc['source_evidence'].append({'reference':t['primary_source'],'description':t['description'],'sha256':None})
        save(out,doc)
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        actions=inputs.load_actions(Path('/frozen/bundle'));checked=0
        for t in self.catalog['terms']:
            for day in (t['native_session'],t['added']['session']):
                p=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),());before=digest(asdict(p))
                changed=backtest.apply_repair(p,loaded);matches=[v for v in changed.terminal if v.security_id==t['security_id']]
                need(digest(asdict(p))==before,'TABLEAU_ORIGINAL_PACKET_UNCHANGED')
                if day==t['added']['session']:
                    need(len(matches)==1 and asdict(matches[0])==t['added'] and matches[0].completeness(1)[0],
                         'TABLEAU_ACTUAL_COMPLETE_REPLACEMENT')
                else:need(not matches,'TABLEAU_NATIVE_CASH_SUPPRESSED_PRESERVE_TRADING')
                checked+=1
        save(out,{'actual_native_and_added_packet_checks':checked,'all_replacements_complete':True,'original_packets_unchanged':True,
            'financial_sessions_advanced':0,'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,
            'private_hydrated_sha256':self.hydrated_sha,'mandatory_remaining_share_terms_not_voluntary_exchange':True})
