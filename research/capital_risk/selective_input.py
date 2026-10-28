"""Causal read-only views of the unchanged original book and qualified prices."""
from collections import defaultdict
from fractions import Fraction as Q
from pathlib import Path
import gzip,hashlib,json,math
from holding_identity import bind_book,encoded

def need(v,c):
    if not v:raise ValueError(c)
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def lines(path):
    with Path(path).open('rb') as stream:
        for raw in stream:yield json.loads(raw)

class Source:
    def __init__(self,root,bundle,qualified,output):
        self.root=Path(root);self.bundle=Path(bundle);self.qualified=Path(qualified)
        cp=json.loads(gzip.decompress((self.root/'checkpoint.json.gz').read_bytes()))
        self.frozen_sources=cp['base']['sources'];self.events=cp['run']['state']['ledger']['events']
        self.base=cp['base'];self.input_sha256=cp['run']['input_sha256'];self.byday=defaultdict(list)
        for e in self.events:self.byday[e['session']].append(e)
        del cp
        self.identity=Path(output)/'identity';self.binding=bind_book(self.root,self.identity)
        need(self.binding['records']==4765 and self.binding['duplicate_security_closes']==8,'REFUSED_P2_IDENTITY_BASIS')
        prices=self.qualified/'qualification/prices/price-bindings.jsonl'
        need(sha(prices)=='b0e995879173b418685a154ef3c5264a97d64fcf6d2a2e39070745296e5a6f62','REFUSED_P2_QUALIFIED_PRICE_FILE')
        prior=json.loads((self.qualified/'qualification/summary.json').read_bytes())
        need(prior['status']=='ACTION_PRICE_QUALIFICATION_COMPLETE' and prior['prices']['equity_raw_domain_covered'],'REFUSED_P2_PRICE_QUALIFICATION')
        self.prices=prices
        import csv
        with gzip.open(self.bundle/'cash.csv.gz','rt') as f:self.cash={r['session']:r for r in csv.DictReader(f)}
        schedule=json.loads((self.bundle/'terminal-schedule.json').read_bytes());self.terms={}
        for e in self.events:
            if e['event_type']!='CONVERSION':continue
            found=[t for t in schedule if t['effective_session']==e['session'] and t['security_id']==e['security_id']]
            need(len(found)==1,'REFUSED_P2_CONVERSION_TERMS')
            t=found[0];d=e['detail'];ratio=d['exchange_ratio_exact']
            need(abs(Q(ratio)-Q(t['exchange_ratio']))<=Q('1e-15') and t['delivered_security_id']==d['delivered_security_id'],'REFUSED_P2_CONVERSION_BASIS')
            need(Q(str(e['price'] or 0))==Q(t['cash_per_share'] or 0),'REFUSED_P2_CONVERSION_CASH')
            self.terms[(e['session'],e['security_id'])]=dict(ratio=ratio,cash_per_share=t['cash_per_share'] or '0',
                cil_price=t['cash_in_lieu_price_per_delivered_share'] or None,delivered_security_id=t['delivered_security_id'],
                delivered_ticker=t['delivered_ticker'],reference=t['reference'],original_terms=t,
                source_event_sha256=hashlib.sha256(encoded(e)).hexdigest())
        self.spins={}
        for t in json.loads((self.bundle/'supplements.json').read_bytes()):
            if t['kind']=='SPINOFF':self.spins[(t['effective_session'],t['security_id'])]=t
        days=[r['session'] for r in self.rows()];need(len(days)==4765 and days==sorted(set(days)),'REFUSED_SOURCE_CALENDAR')
        self.next_session={day:(days[i+1] if i+1<len(days) else None) for i,day in enumerate(days)}

    def rows(self):
        for name in ('formation','daily'):yield from lines(self.root/(name+'.jsonl'))

    def frames(self):
        count=0
        for row,binding,price in zip(self.rows(),lines(self.identity/'identity-bindings.jsonl'),lines(self.prices),strict=True):
            day=row['session'];need(day==binding['session']==price['session'],'REFUSED_P2_SOURCE_AXIS')
            for key in ('state_sha256','input_sha256','chain_sha256'):
                need(row[key]==binding['source_'+key]==price['source_'+key],'REFUSED_P2_SOURCE_ROW_BINDING')
            need(not price['issues'],'REFUSED_P2_PRICE_ISSUE');count+=1
            yield dict(row=row,holdings=binding['holdings'],prices=price['prices'],source_events=self.byday[day],cash=self.cash[day],
                price_chain_sha256=price['price_chain_sha256'],identity_chain_sha256=binding['identity_chain_sha256'])
        need(count==4765,'REFUSED_P2_SOURCE_COMPLETE')

def observations(frame,classifier):
    r=frame['row'];core=Q(r['economics']['parent_core_close_equity']);need(core>0,'REFUSED_P2_CORE_NAV')
    exits={op['slot_id'] for op in r['evidence']['research_entry_audit']['operations'] if op['operation']=='CLOSE_POSITION'}
    result=[]
    for b in frame['holdings']:
        o=b['source_observation'];h=classifier.Holding(o['ticker'],None,o['own_dd'],o['r21'],o['r63'],o['age_sessions'])
        required=[o['own_dd'],o['r21']]+([o['r63']] if o['age_sessions']>=63 else [])
        unknown=any(x is None or not math.isfinite(x) for x in required)
        dd='0' if o['own_dd'] is None or not math.isfinite(o['own_dd']) else str(max(0,-o['own_dd']))
        sid=b['security_id'];price=frame['prices'][sid]['raw_close'];weight=Q(b['shares'])*Q(price)/core
        result.append(dict(episode=b['episode'],security_id=sid,slot_id=b['slot_id'],ticker=o['ticker'],
            weight=str(weight),drawdown=dd,red=bool(classifier.is_red(h)),green=bool(classifier.is_green(h)),
            unknown=unknown,core_exit=b['slot_id'] in exits,source_state_sha256=r['state_sha256']))
    return result
