"""Additional factual terminal inputs; no financial state or source conversion."""
import json,os,zipfile
from dataclasses import asdict
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha


class MidyearFacts:
    def __init__(self,path):
        self.path=Path(path);self.raw=self.path.read_bytes();self.catalog=json.loads(self.raw)
        need(self.catalog['schema']=='research.system-campaign-midyear-terminal-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted'],
             'MIDYEAR_TERMINAL_CATALOG_SCOPE')
        need([(t['ticker'],t['security_id'],t['native_session'],t['added']['session'],t['added']['cash_per_share'],
               t['added']['kind'],t['added']['exchange_ratio'],t['added']['delivered_security_id']) for t in self.catalog['terms']]==[
                  ('FMI','59735459814812516','2018-07-31','2018-07-31',137.,'CASH_MERGER',None,None),
                  ('COL','589557654748685297','2018-11-26','2018-11-27',93.33,'CASH_PLUS_STOCK',.37525,'148187321807650528')],
             'MIDYEAR_EXACT_PRIMARY_TERMS')
        fmi,col=self.catalog['terms']
        need(fmi['proxy'] is None and col['proxy']['session']=='2018-11-27'
             and col['proxy']['security_id']=='148187321807650528' and col['added']['delivered_ticker']=='RTX'
             and col['added']['delivered_issuer_id']=='SEC_UNKNOWN:148187321807650528'
             and col['added']['cash_in_lieu_price_per_delivered_share'] is None
             and col['proxy']['convention']=='RETAINED_FIRST_EFFECTIVE_SESSION_RAW_OPEN_PROXY_NOT_ACTUAL_EXCHANGE_AGENT_NET_RATE'
             and self.catalog['FMSA_exact_cash_unproven'] and self.catalog['AAAP_mandatory_payment_unproven'],
             'MIDYEAR_EXACT_PROXY_SCOPE')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_MIDYEAR_FACTS_ONLY')
        from research.pooled_input_support import inputs
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={}
        for term in self.catalog['terms']:
            original,=[v for v in actions.terminal.get(term['native_session'],()) if v.security_id==term['security_id']]
            need(digest(asdict(original))==term['native_term_sha256'] and original.cash_per_share is None,
                 'MIDYEAR_ACTUAL_FROZEN_NATIVE_TERM')
            if term['proxy']:
                proxy=term['proxy'];key=proxy['session'],proxy['security_id']
                need(key not in wanted,'MIDYEAR_UNIQUE_PROXY');wanted[key]=(term,proxy)
        seen=set()
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for year in sorted({day[:4] for day,sid in wanted}):
                for row in inputs._archive_rows(archive,'observations-'+year+'.csv.gz'):
                    key=row['session'],row['security_id']
                    if key not in wanted:continue
                    term,proxy=wanted[key];need(key not in seen and digest(row)==proxy['source_observation_sha256'],
                        'MIDYEAR_PRIVATE_PROXY_ROW');seen.add(key)
                    price=float(row['raw_open']);need(price>0,'MIDYEAR_POSITIVE_PROXY_PRICE')
                    term['added']['cash_in_lieu_price_per_delivered_share']=price
        need(seen==set(wanted),'MIDYEAR_ALL_PROXY_QUOTES')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,
             'MIDYEAR_HYDRATION_IMMUTABLE')
        cursor=cp['source_cursor'];need(cursor<'2018-07-31','MIDYEAR_ALL_TERMS_UNCONSUMED')
        document={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
            'source_evidence':[
                {'reference':'research:system-optimization-002/midyear-terminal-catalog/1',
                 'description':'Exact additional issuer completion terms and declared fractional proxy.',
                 'sha256':self.catalog_sha},
                {'reference':'research:system-optimization-002/midyear-terminal-compiler/1',
                 'description':'Exact ordinary terminal input compiler; financial sources unchanged.',
                 'sha256':self.compiler_sha},
                {'reference':'research:system-optimization-002/midyear-private-terminal-catalog/1',
                 'description':'Exact private quote hydration from the frozen archive.',
                 'sha256':self.hydrated_sha}], 'suppress':[],'add':[]}
        for term in self.catalog['terms']:
            need(term['native_session']>cursor and term['added']['session']>cursor,'MIDYEAR_NO_PAST_EVENT')
            document['suppress'].append({'session':term['native_session'],'security_id':term['security_id'],
                'term_sha256':term['native_term_sha256']})
            document['add'].append(term['added'])
            document['source_evidence'].append({'reference':term['primary_source'],
                'description':term['description'],'sha256':None})
        save(out,document)
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cursor,predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        """Actual native input and parser qualification; zero financial sessions."""
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding import backtest
        actions=inputs.load_actions(Path('/frozen/bundle'))
        checked=0
        for term in self.catalog['terms']:
            for day in sorted({term['native_session'],term['added']['session']}):
                packet=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(packet));result=backtest.apply_repair(packet,loaded)
                need(digest(asdict(packet))==before,'MIDYEAR_ORIGINAL_PACKET_UNCHANGED')
                matches=[v for v in result.terminal if v.security_id==term['security_id']]
                if day==term['added']['session']:
                    need(len(matches)==1 and asdict(matches[0])==term['added'] and matches[0].completeness(1)[0],
                         'MIDYEAR_CANONICAL_COMPLETE_REPLACEMENT')
                else:need(not matches,'MIDYEAR_EXACT_NATIVE_SUPPRESSION')
                checked+=1
        save(out,{'actual_native_and_added_packet_checks':checked,'all_replacements_complete':True,
            'original_packets_unchanged':True,'financial_sessions_advanced':0,
            'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,'private_hydrated_sha256':self.hydrated_sha,
            'AAAP_unresolved_and_no_payment_added':True})
