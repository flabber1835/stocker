"""Source-bound typed distributions and stock terms; no financial state edits."""
import ast,copy,json,os,zipfile
from dataclasses import asdict,replace
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha,REPAIR_SHA

CATALOG='research:system-optimization-002/distribution-catalog/1'
COMPILER='research:system-optimization-002/distribution-compiler/1'
HYDRATED='research:system-optimization-002/distribution-private-catalog/1'
FIRST='2019-04-09'


def compile_spin_function(raw,globals_,identities):
    """Only the five existing identity literals vary in the frozen pure codec."""
    need(sha(raw)==REPAIR_SHA,'DISTRIBUTION_FROZEN_PACKET_FUNCTION')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_apply_spinoff_repair']
    need(set(identities)=={'224580439420294771','37439132904117100','GE','GEV'},'DISTRIBUTION_IDENTITY_MAP')
    counts={k:0 for k in identities}
    for n in ast.walk(node):
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value in identities:
            counts[n.value]+=1;n.value=identities[n.value]
    need(counts=={'224580439420294771':2,'37439132904117100':1,'GE':1,'GEV':1},'DISTRIBUTION_EXACT_LITERAL_SITES')
    scope=dict(globals_)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<source-bound-distribution-packet-codec>','exec'),scope)
    return scope['_apply_spinoff_repair']


class DistributionFacts:
    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw)
        need(self.catalog['schema']=='research.system-campaign-distributions-2019-facts/1'
             and not self.catalog['canonical_financial_source_changed'] and not self.catalog['production_contacted'],
             'DISTRIBUTION_CATALOG_SCOPE')
        need([(s['added']['session'],s['added']['parent_ticker'],s['added']['parent_security_id'],
               s['added']['child_ticker'],s['added']['child_security_id'],s['added']['child_shares_per_parent']) for s in self.catalog['spins']]==[
            ('2019-04-09','NVS','35236694394768611','ALC','495423651304945316','0.2'),
            ('2019-06-28','OPLN','380320910009786790','IAA','196896286149315402','1')],
             'DISTRIBUTION_EXACT_SPIN_IDENTITIES_RATIOS')
        need(all(len(s['native'])==2 and len({n['term_sha256'] for n in s['native']})==2
             and s['added']['policy']=='LIQUIDATE_CHILD_AT_OPEN' and s['added']['child_price'] is None
             and s['added']['cash_in_lieu_price'] is None
             and s['cash_proxy_semantics']=='IN_KIND_CHILD_DISTRIBUTION_NOT_ADDITIONAL_CASH' for s in self.catalog['spins']),
             'DISTRIBUTION_EXACT_NO_DUPLICATE_CASH_POLICY')
        need([(t['ticker'],t['security_id'],t['native_session'],t['added']['session'],t['added']['kind'],
               t['added']['security_id'],t['added']['cash_per_share'],t['added']['exchange_ratio'],
               t['added']['delivered_security_id'],t['added']['delivered_ticker'],t['added']['delivered_issuer_id'],
               t['added']['cash_in_lieu_price_per_delivered_share'],t['proxy']['convention']) for t in self.catalog['terms']]==[
            ('LLL1','149209101404250271','2019-06-28','2019-07-01','CONVERSION','149209101404250271',None,1.3,
             '821698168806940222','LHX','SEC_UNKNOWN:821698168806940222',None,'RETAINED_RAW_OPEN_RESEARCH_PROXY'),
            ('APHA','1056418588994492299','2021-04-30','2021-05-03','CONVERSION','1056418588994492299',None,.8381,
             '653423826172679659','TLRY','SEC_CIK:1731348',0.,'CONTRACTUAL_ZERO_FRACTIONAL_CONSIDERATION')],
             'DISTRIBUTION_EXACT_STOCK_TERMS_NO_INVENTED_CASH')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_DISTRIBUTION_INPUT_ONLY')
        from research.pooled_input_support import inputs
        from research.bounded_20y.run import vendor,distributions
        actions=inputs.load_actions(Path('/frozen/bundle'));wanted={}
        for s in self.catalog['spins']:
            for name in ('parent','child'):
                wanted[s['added']['session'],s['added'][name+'_security_id']]=(s,name+'_observation_sha256')
        for t in self.catalog['terms']:
            n,=[v for v in actions.terminal.get(t['native_session'],()) if v.security_id==t['security_id']]
            need(digest(asdict(n))==t['native_term_sha256'] and n.cash_per_share is None,'DISTRIBUTION_ACTUAL_NATIVE_TERMINAL')
            p=t['proxy'];need((p['session'],p['security_id']) not in wanted,'DISTRIBUTION_UNIQUE_PRIVATE_QUOTE')
            wanted[p['session'],p['security_id']]=(p,'source_observation_sha256')
        rows={}
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            native=distributions(inputs._archive_rows(archive,'actions.csv.gz'))
            for year in sorted({day[:4] for day,sid in wanted}):
                for r in inputs._archive_rows(archive,'observations-'+year+'.csv.gz'):
                    k=r['session'],r['security_id']
                    if k not in wanted:continue
                    target,field=wanted[k]
                    need(k not in rows and digest(r)==target[field],'DISTRIBUTION_EXACT_PRIVATE_OBSERVATION');rows[k]=r
        need(set(rows)==set(wanted),'DISTRIBUTION_ALL_PRIVATE_QUOTES')
        for s in self.catalog['spins']:
            fields=s['added'];day=fields['session'];sid=fields['parent_security_id']
            actual=[v for v in native.get(day,()) if v.parent_security_id==sid]
            need(sorted((digest(asdict(v)),v.source_row_id) for v in actual)==sorted((v['term_sha256'],v['source_row_id']) for v in s['native']),
                 'DISTRIBUTION_BOTH_NATIVE_SPIN_ROWS')
            for name in ('parent','child'):
                value=asdict(vendor(rows[day,fields[name+'_security_id']]))
                need(digest(value)==s[name+'_bar_sha256'],'DISTRIBUTION_EXACT_PRIVATE_BAR');s[name+'_bar']=value
            s['cash_proxy_per_parent']=str(s['parent_bar']['dividend_per_share'])
            need(float(s['cash_proxy_per_parent'])>0 and s['child_bar']['tradeable'] and s['child_bar']['raw_open']>0,
                 'DISTRIBUTION_SOURCE_CASH_AND_TRADEABLE_CHILD')
            fields['cash_in_lieu_price']=str(s['child_bar']['raw_open'])
        for t in self.catalog['terms']:
            p=t['proxy'];row=rows[p['session'],p['security_id']]
            need(row['ticker']==t['added']['delivered_ticker'] and row['issuer_id']==t['added']['delivered_issuer_id'],
                 'DISTRIBUTION_FROZEN_DELIVERED_IDENTITY')
            if p['convention']=='RETAINED_RAW_OPEN_RESEARCH_PROXY':
                price=float(row['raw_open']);need(price>0,'DISTRIBUTION_POSITIVE_DECLARED_PROXY')
                t['added']['cash_in_lieu_price_per_delivered_share']=price
            else:need(t['added']['cash_in_lieu_price_per_delivered_share']==0.,'DISTRIBUTION_APHA_ZERO_NOT_OPEN_PROXY')
        save(out,self.catalog);self.hydrated_sha=sha(Path(out).read_bytes());self.hydrated_digest=digest(self.catalog)

    def evidence(self):
        return [{'reference':r,'description':d,'sha256':v} for r,d,v in (
            (CATALOG,'Exact issuer distribution/stock conversion facts and retained metadata limitations.',self.catalog_sha),
            (COMPILER,'Exact scoped packet codec; canonical financial source unchanged.',self.compiler_sha),
            (HYDRATED,'Exact private frozen quote hydration, retained only in encrypted evidence.',self.hydrated_sha))]

    def _bound(self,loaded):
        expected={v['reference']:v['sha256'] for v in self.evidence()}
        found=[(v.reference,v.sha256) for v in loaded.source_evidence if v.reference in expected]
        if not found:return False
        need(len(found)==3 and dict(found)==expected and self.hydrated_sha is not None
             and digest(self.catalog)==self.hydrated_digest,'DISTRIBUTION_EXACT_IMMUTABLE_COMMITMENTS')
        need(loaded._resume_session<FIRST,'DISTRIBUTION_EARLIEST_SPIN_UNCONSUMED')
        return True

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'DISTRIBUTION_HYDRATION_IMMUTABLE')
        need(cp['source_cursor']<FIRST,'DISTRIBUTION_EARLIEST_SPIN_UNCONSUMED')
        doc={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':cp['run']['checkpoint_sha256'],
             'source_evidence':self.evidence(),'suppress':[],'add':[]}
        for t in self.catalog['terms']:
            doc['suppress'].append({'session':t['native_session'],'security_id':t['security_id'],'term_sha256':t['native_term_sha256']})
            doc['add'].append(t['added'])
            doc['source_evidence'].append({'reference':t['primary_source'],'description':t['description'],'sha256':None})
        save(out,doc)
        from research.pooled_vacancy_funding.repair import load_repair
        loaded=load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        need(self._bound(loaded),'DISTRIBUTION_OWN_BOUND_REPAIR');return loaded

    def __enter__(self):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'DISTRIBUTION_HYDRATED_CONTEXT_ONLY')
        from research.pooled_vacancy_funding import backtest,repair
        from sentinel.core.spinoffs import SpinoffDistribution
        self.backtest=backtest;self.original=backtest.apply_repair;compiled=[]
        for s in self.catalog['spins']:
            fields=s['added'];term=SpinoffDistribution(**fields)
            fn=compile_spin_function(Path(repair.__file__).read_bytes(),vars(repair),{
                '224580439420294771':fields['parent_security_id'],'37439132904117100':fields['child_security_id'],
                'GE':fields['parent_ticker'],'GEV':fields['child_ticker']})
            local=SimpleNamespace(suppress=tuple(SimpleNamespace(term_sha256=v['term_sha256']) for v in s['native']),
                add=(SimpleNamespace(cash_in_lieu_price=fields['cash_in_lieu_price'],terms=lambda t=term:t),),
                parent_bar_sha256=s['parent_bar_sha256'],child_bar_sha256=s['child_bar_sha256'],
                cash_proxy_per_parent=s['cash_proxy_per_parent'],earliest_affected_session=fields['session'])
            compiled.append((fields['session'],fn,local))
        def apply(packet,loaded):
            changed=self.original(packet,loaded)
            if not self._bound(loaded):return changed
            for day,fn,source in compiled:
                if packet.day==day:
                    local=copy.copy(source);local._resume_session=loaded._resume_session;changed=fn(changed,local)
            return changed
        backtest.apply_repair=apply;return self

    def __exit__(self,*args):self.backtest.apply_repair=self.original

    def qualify(self,loaded,out):
        """Actual frozen packets and canonical term primitives; no sessions."""
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.bounded_20y.run import distributions
        from research.pooled_vacancy_funding import backtest
        from stock_strategy_shared.wealth_core.terminal import TerminalTerms,TerminalKind,_split_entitlement,_cash_in_lieu
        from stock_strategy_shared.wealth_core.feed import VendorBar
        from fractions import Fraction
        actions=inputs.load_actions(Path('/frozen/bundle'))
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as z:native=distributions(inputs._archive_rows(z,'actions.csv.gz'))
        checked=0
        for s in self.catalog['spins']:
            day=s['added']['session'];bars=tuple(VendorBar(**s[name+'_bar']) for name in ('parent','child'))
            packet=Packet(day,bars,{},{},1.,{},tuple(actions.terminal.get(day,())),tuple(native.get(day,())))
            before=digest(asdict(packet));fixed=backtest.apply_repair(packet,loaded)
            need(digest(asdict(packet))==before,'DISTRIBUTION_ORIGINAL_PACKET_UNCHANGED')
            matches=[v for v in fixed.spins if v.parent_security_id==s['added']['parent_security_id']]
            need(len(matches)==1 and asdict(matches[0])==s['added'],'DISTRIBUTION_ACTUAL_TYPED_CHILD_ONCE')
            parent=s['added']['parent_security_id']
            need(all(asdict(a)==asdict(replace(b,dividend_per_share=0.)) if b.security_id==parent else asdict(a)==asdict(b)
                     for a,b in zip(fixed.bars,packet.bars)),'DISTRIBUTION_ONLY_PARENT_CASH_PROXY_CHANGED')
            for bad in (replace(packet,spins=tuple(v for v in packet.spins if v.source_row_id!=s['native'][0]['source_row_id'])),
                        replace(packet,bars=tuple(replace(b,raw_open=b.raw_open+.01) if b.security_id==parent else b for b in bars))):
                try:backtest.apply_repair(bad,loaded)
                except ValueError:pass
                else:raise ValueError('REFUSED_DISTRIBUTION_ACTUAL_SOURCE_FALSIFIER')
            checked+=1
        for t in self.catalog['terms']:
            for day in (t['native_session'],t['added']['session']):
                packet=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
                before=digest(asdict(packet));fixed=self.original(packet,loaded)
                need(digest(asdict(packet))==before,'DISTRIBUTION_ORIGINAL_TERMINALS_UNCHANGED')
                matches=[v for v in fixed.terminal if v.security_id==t['security_id']]
                if day==t['added']['session']:
                    need(len(matches)==1 and asdict(matches[0])==t['added'] and matches[0].completeness(1)[0],
                         'DISTRIBUTION_ACTUAL_COMPLETE_STOCK_TERM')
                else:need(not matches,'DISTRIBUTION_NATIVE_TERMINAL_SUPPRESSED')
                checked+=1
        ap=self.catalog['terms'][1]['added'];term=TerminalTerms(**{**ap,'kind':TerminalKind(ap['kind'])})
        need(_split_entitlement(1,term.exchange_ratio)==(0,Fraction(8381,10000))
             and _cash_in_lieu(Fraction(8381,10000),term)==0,'DISTRIBUTION_CANONICAL_APHA_ZERO_FRACTIONAL_PAYMENT')
        bad=SimpleNamespace(source_evidence=loaded.source_evidence,_resume_session=FIRST)
        try:self._bound(bad)
        except ValueError:pass
        else:raise ValueError('REFUSED_DISTRIBUTION_CONSUMED_SPIN_FALSIFIER')
        save(out,{'actual_native_and_added_packet_checks':checked,'all_replacements_complete':True,
            'original_packets_unchanged':True,'both_native_spin_rows_and_parent_cash_suppressed':True,
            'actual_source_row_quote_and_consumed_spin_falsifiers':True,'canonical_apha_zero_fractional_payment':True,
            'financial_sessions_advanced':0,'catalog_sha256':self.catalog_sha,'compiler_sha256':self.compiler_sha,
            'private_hydrated_sha256':self.hydrated_sha})
