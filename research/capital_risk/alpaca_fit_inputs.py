"""Hosted immutable Alpaca input adapter. No broker, database or Core decisions.

Packed prices are storage only. Source domain conversions, admission, features
and the financial transition are the existing canonical implementations.
"""
from __future__ import annotations
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
import gzip
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace


def need(value,reason):
    if not value:raise ValueError('REFUSED_ALPACA_FIT_'+reason)


def hosted():need(os.environ.get('ALPACA_FIT_HOSTED')=='1','LOCAL_FINANCIAL_INPUT_EXECUTION')


def split_fact(kind,record,axis,splits):
    """Same supported-term/refused-term split boundary as AlpacaSource.

    Distinct provider IDs do not multiply the same dated split twice. A
    malformed/conflicting fact is returned for the caller's dated quarantine.
    """
    from sentinel.feed.alpaca_observation import stock_split
    from sentinel.feed.alpaca_transport import AlpacaTransportRefused
    try:
        fact=stock_split(kind,record,axis=axis);key=(fact['ticker'],fact['date']);ratio=Decimal(fact['ratio'])
        if key in splits and splits[key]!=ratio:raise AlpacaTransportRefused('conflicting split terms')
        splits[key]=ratio
        return fact,None
    except AlpacaTransportRefused as exc:return None,str(exc)


def cash_fact(record,axis):
    from sentinel.feed.alpaca_observation import cash_dividend
    from sentinel.feed.alpaca_transport import AlpacaTransportRefused
    from sentinel.feed import calendar
    try:return cash_dividend(record,axis=axis),None
    except AlpacaTransportRefused as exc:
        value=record.get('ex_date');trusted=False
        if isinstance(value,str):
            try:trusted=calendar.previous_sessions(value,1)==[value]
            except (ValueError,TypeError):pass
        return None,{'reason':str(exc),'record':record,'trusted_ex_session':value if trusted else None}


def cash_dependency_issues(prior,issues,session):
    held={e['security_id'] for e in prior.wealth_core.get('episodes',{}).values()}
    queued={o['security_id'] for o in prior.pending if o['operation']=='OPEN_SLOT_POSITION'}
    blocked=[]
    for issue in issues:
        ids=set(issue['security_ids']);ex=issue['trusted_ex_session']
        if ex is None and ids&(held|queued):blocked.append(issue['record']['id'])
        elif ex is not None and ids&held and prior.last_processed_session is not None and prior.last_processed_session<ex<=session:
            blocked.append(issue['record']['id'])
    return blocked


def responses(root):
    """Authenticated archive inventory is a precondition; recheck raw preimages."""
    manifest=json.loads((root/'manifest.json').read_bytes())
    proofs=[json.loads(line) for line in (root/'capture/request-receipts.jsonl').read_bytes().splitlines()]
    need(len(proofs)==len({p['file'] for p in proofs}),'DUPLICATE_RESPONSE')
    for proof in proofs:
        name='capture/'+proof['file'];spec=manifest['members'][name];payload=(root/name).read_bytes()
        need(len(payload)==spec['bytes']==proof['bytes'] and hashlib.sha256(payload).hexdigest()==spec['sha256']==proof['sha256'],'RESPONSE_CIPHER_INVENTORY')
        with gzip.GzipFile(fileobj=__import__('io').BytesIO(payload)) as stream:raw=stream.read(32*1024**2+1)
        need(len(raw)==proof['raw_bytes']<=32*1024**2 and hashlib.sha256(raw).hexdigest()==proof['raw_sha256'],'RESPONSE_RAW_PREIMAGE')
        yield proof,json.loads(raw)


class LazyBars(Mapping):
    def __init__(self,data,days,admitted):self.data,self.days,self.admitted=data,tuple(days),admitted
    def __len__(self):return len(self.days)
    def __iter__(self):return iter(self.days)
    def __getitem__(self,day):
        if day not in self.days:raise KeyError(day)
        from sentinel.core.input_domains import _vendor
        return [_vendor(self.data.bar(sid,day)) for sid,first in sorted(self.admitted.items())
                if first<=day and self.data.paired(sid,day)]


class Inputs:
    def __init__(self,root,bil_root,protocol,capture_sha,prefix_root=None,*,packed=False,factual_repair=None):
        hosted()
        import numpy as np
        from sentinel.feed import calendar
        from sentinel.feed.alpaca_observation import bar_page_rows,action_participants,structural_action_date
        self.root=Path(root);self.protocol=protocol;self.capture_sha=capture_sha;self.packed=packed
        capture=json.loads((self.root/'capture/capture.json').read_bytes())
        need(capture['status']=='COMPLETE' and capture['pagination_complete'] is True
             and capture['account_order_position_activity_calls']==0,'CAPTURE_NOT_COMPLETE')
        prefix_root=Path(prefix_root) if prefix_root is not None else None
        classified=json.loads(((prefix_root or self.root)/'capture/classification.json').read_bytes())
        self.assets={r['asset_id']:r for r in classified['selected']};self.by_ticker={r['ticker']:sid for sid,r in self.assets.items()}
        need(len(self.assets)==len(self.by_ticker),'ASSET_ALIAS')
        self.sids=sorted(self.assets);self.sid_index={s:i for i,s in enumerate(self.sids)}
        self.axis=calendar.sessions_in_range(protocol['data_start'],protocol['data_end']);self.index={d:i for i,d in enumerate(self.axis)}
        self.values=np.zeros((len(self.sids),len(self.axis),4),dtype='float64')
        self.present=np.zeros((len(self.sids),len(self.axis),2),dtype='bool')
        self.bench={symbol:{a:{} for a in ('raw','all','split')} for symbol in ('SPY','BIL')}
        self.actions={};self.action_proofs={};self.splits={};self.dividends={};self.resets={};self.undated={};self.cache=None;self.action_issues=[];self.pending_cash=[]
        page_groups={};actual_counts=Counter()
        from itertools import chain
        streams=[responses(r) for r in ([prefix_root,self.root] if prefix_root is not None else [self.root])]
        for proof,reply in chain.from_iterable(streams):
            endpoint=proof['endpoint'];params=proof.get('params') or {}
            if endpoint.endswith('/corporate-actions'):
                for kind,records in reply['corporate_actions'].items():
                    for record in records:
                        key=record['id'];need(key not in self.actions or self.actions[key]==(kind,record),'ACTION_IDENTITY')
                        self.actions[key]=(kind,record)
                        self.action_proofs.setdefault(key,[]).append({k:proof[k] for k in ('file','sha256','raw_sha256')})
            elif endpoint.endswith('/bars'):
                adjustment=params['adjustment'];symbols=set(params['symbols'].split(','))
                need(params['feed']=='sip' and params['timeframe']=='1Day' and params['asof']==protocol['data_end'],'BAR_QUERY')
                group=json.dumps({k:v for k,v in params.items() if k!='page_token'},sort_keys=True)
                expected=page_groups.get(group)
                need(params.get('page_token')==expected,'PAGINATION_PREDECESSOR')
                page_groups[group]=reply.get('next_page_token')
                rows=bar_page_rows(reply['bars'],symbols=symbols,sessions=set(self.axis))
                if symbols=={'BIL','SPY'}:
                    need(adjustment in ('raw','all'),'BENCHMARK_DOMAIN')
                    for (symbol,day),row in rows.items():
                        need(day not in self.bench[symbol][adjustment],'BENCHMARK_DUPLICATE');self.bench[symbol][adjustment][day]=row
                    actual_counts['benchmarks_'+adjustment]+=len(rows)
                else:
                    need(adjustment in ('raw','split') and symbols.issubset(self.by_ticker),'STOCK_DOMAIN')
                    domain=0 if adjustment=='raw' else 1
                    for (symbol,day),row in rows.items():
                        i,j=self.sid_index[self.by_ticker[symbol]],self.index[day]
                        need(not self.present[i,j,domain],'DUPLICATE_BAR');self.present[i,j,domain]=True
                        if domain==0:self.values[i,j,:3]=[row['open'],row['close'],row['volume']]
                        else:self.values[i,j,3]=row['close']
                    actual_counts[adjustment]+=len(rows)
        need(all(token is None for token in page_groups.values()),'UNFINISHED_PAGINATION')
        if prefix_root is None:need(dict(actual_counts)==capture['stock_and_benchmark_bar_counts'],'CAPTURE_COUNTS')
        else:
            from alpaca_fit_resume import price_plan
            expected={json.dumps(q,sort_keys=True) for q in price_plan(protocol,self.by_ticker)}
            need(set(page_groups)==expected and capture['schema']=='research.alpaca-fit-price-suffix/1'
                 and capture['remaining_query_plan_complete'] is True,'COMPOSITE_QUERY_PLAN_COVERAGE')
        for proof,reply in responses(Path(bil_root)):
            params=proof['params'];need(proof['endpoint'].endswith('/bars') and params['symbols']=='BIL'
                and params['adjustment']=='split' and params['feed']=='sip' and params['asof']==protocol['data_end'],'BIL_SUPPLEMENT_DOMAIN')
            need(reply.get('next_page_token') is None,'BIL_SUPPLEMENT_PAGINATION')
            for (symbol,day),row in bar_page_rows(reply['bars'],symbols={'BIL'},sessions=set(self.axis)).items():
                need(day not in self.bench[symbol]['split'],'BIL_SPLIT_DUPLICATE');self.bench[symbol]['split'][day]=row
        for symbol in ('SPY','BIL'):
            for adjustment in (('raw','all','split') if symbol=='BIL' else ('raw','all')):
                need(set(self.bench[symbol][adjustment])==set(self.axis),'BENCHMARK_AXIS')
        for key,(kind,record) in self.actions.items():
            from sentinel.feed.alpaca_identity import action_sources
            participants=action_participants(record) if kind=='cash_dividends' else action_sources(kind,record)
            symbols=participants&(set(self.by_ticker)|{'BIL','SPY'})
            if not symbols:continue
            if kind=='cash_dividends':
                fact,issue=cash_fact(record,set(self.axis))
                if issue is not None:
                    issue['security_ids']=sorted(self.by_ticker[s] for s in symbols if s in self.by_ticker)
                    self.pending_cash.append(issue);self.action_issues.append({'id':key,'kind':kind,**issue})
                elif fact:
                    identity=(fact['ticker'],fact['date']);self.dividends[identity]=self.dividends.get(identity,Decimal(0))+Decimal(fact['rate'])
            elif kind in ('forward_splits','reverse_splits'):
                day=structural_action_date(kind,record)
                if day is not None and self.axis[0]<=day<=self.axis[-1]:
                    fact,reason=split_fact(kind,record,set(self.axis),self.splits)
                    if reason is not None:
                        self.action_issues.append({'id':key,'kind':kind,'record':record,'reason':reason})
                        for symbol in symbols:self.resets.setdefault(symbol,[]).append((day,key,kind))
                elif day is None:
                    for symbol in symbols:self.undated.setdefault(symbol,[]).append(key)
            else:
                day=structural_action_date(kind,record)
                for symbol in symbols:
                    if day is None:self.undated.setdefault(symbol,[]).append(key)
                    elif day<=self.axis[-1]:self.resets.setdefault(symbol,[]).append((day,key,kind))
        self.factual_repair_receipt=None
        if factual_repair is not None:
            from alpaca_fit_identity_repair import apply,digest
            descriptor=json.loads(Path(factual_repair).read_bytes())
            need(descriptor['dataset_sha256']==capture_sha and descriptor['protocol_sha256']==hashlib.sha256(
                Path('/src/research/capital_risk/alpaca-fit-protocol.json').read_bytes()).hexdigest(),'FACTUAL_INPUT_BASIS')
            source_manifest_sha=hashlib.sha256(((prefix_root or self.root)/'manifest.json').read_bytes()).hexdigest()
            self.factual_repair_receipt=apply(self,descriptor,source_manifest_sha256=source_manifest_sha)
            self.capture_sha=digest({'dataset_sha256':capture_sha,'factual_interpretation_sha256':digest(descriptor)})
        need(not ({'BIL','SPY'}&set(self.undated)),'UNDATED_BENCHMARK_ACTION')
        need(not any(self.axis[0]<=day<=self.axis[-1] for day,_,_ in self.resets.get('BIL',[])),'UNSUPPORTED_BIL_ACTION')
        from sentinel.feed.alpaca_observation import admissible_history
        bil=[dict(ticker='BIL',date=d,open=self.bench['BIL']['raw'][d]['open'],close=self.bench['BIL']['raw'][d]['close'],
             closeunadj=self.bench['BIL']['raw'][d]['close'],volume=self.bench['BIL']['raw'][d]['volume'],
             adjusted_close=self.bench['BIL']['split'][d]['close']) for d in self.axis]
        admitted,_=admissible_history(bil,axis=self.axis,symbols={'BIL'},action_affected=frozenset(),pair_absent=set(),
            split_terms={k:str(v) for k,v in self.splits.items() if k[0]=='BIL'})
        need(admitted=={'BIL':self.axis[0]},'BIL_RAW_SPLIT_CORROBORATION')
        self.split_by_symbol={};self.dividend_by_symbol={}
        for (symbol,day),ratio in self.splits.items():self.split_by_symbol.setdefault(symbol,{})[(symbol,day)]=str(ratio)
        for symbol,day in self.dividends:self.dividend_by_symbol.setdefault(symbol,set()).add(day)
        self.summary={'schema':'research.alpaca-fit-normalization/1','dataset_sha256':capture_sha,
            'assets':len(self.assets),'sessions':len(self.axis),'counts':dict(actual_counts),'actions':len(self.actions),
            'unsupported_dated_split_records':sum(i['kind'] in ('forward_splits','reverse_splits') for i in self.action_issues),
            'unresolved_cash_records':len(self.pending_cash),
            'undated_selected_symbols':sorted(set(self.undated)&set(self.by_ticker)),
            'current_cohort_survivor_conditioned':True,'publication_time_archive':False}

    def paired(self,sid,day):return bool(self.present[self.sid_index[sid],self.index[day]].all())

    def row(self,sid,day):
        i,j=self.sid_index[sid],self.index[day];need(self.paired(sid,day),'UNPAIRED_BAR')
        o,c,v,s=map(float,self.values[i,j]);ticker=self.assets[sid]['ticker']
        return dict(ticker=ticker,date=day,open=o,close=c,closeunadj=c,volume=v,adjusted_close=s)

    def paired_rows(self,sid,days):
        """Storage-only vector extraction; dates/float values retain exact order."""
        i=self.sid_index[sid];indices=[self.index[d] for d in days];ticker=self.assets[sid]['ticker']
        observed=self.present[i,indices];paired=observed[:,0]&observed[:,1]
        values=self.values[i,indices].tolist()
        rows=[dict(ticker=ticker,date=day,open=v[0],close=v[1],closeunadj=v[1],volume=v[2],adjusted_close=v[3])
              for day,v,ok in zip(days,values,paired.tolist()) if ok]
        absent={(ticker,day) for day,any_,ok in zip(days,observed.any(axis=1).tolist(),paired.tolist()) if any_ and not ok}
        return rows,absent

    def bar(self,sid,day):
        from sentinel.feed.canonical_transforms import alpaca_bar
        ticker=self.assets[sid]['ticker']
        return alpaca_bar(self.row(sid,day),asset_id=sid,split_ratio=self.splits.get((ticker,day),Decimal(1)),
                         dividend_per_share=self.dividends.get((ticker,day),Decimal(0)))

    def admitted(self,days):
        from sentinel.feed.alpaca_observation import admissible_history
        result={};reasons=Counter()
        for sid in self.sids:
            ticker=self.assets[sid]['ticker']
            if ticker in self.undated:
                reasons['UNDATED_UNSUPPORTED_ACTION']+=1;continue
            resets=[d for d,_,_ in self.resets.get(ticker,()) if d<=days[-1]]
            if self.packed:rows,absent=self.paired_rows(sid,days)
            else:
                rows=[self.row(sid,d) for d in days if self.paired(sid,d)]
                absent={(ticker,d) for d in days if bool(self.present[self.sid_index[sid],self.index[d]].any()) and not self.paired(sid,d)}
            found,why=admissible_history(rows,axis=list(days),symbols={ticker},action_affected=frozenset(),pair_absent=absent,
                reset_after={ticker:max(resets)} if resets else {},
                split_terms={k:v for k,v in self.split_by_symbol.get(ticker,{}).items() if days[0]<=k[1]<=days[-1]},
                dividend_dates={ticker:{d for d in self.dividend_by_symbol.get(ticker,()) if days[0]<=d<=days[-1]}})
            if ticker in found:result[sid]=found[ticker]
            reasons.update(why)
        return result,dict(reasons)

    def metadata(self,admitted,day):
        from stock_strategy_shared.wealth_core.feed import SecurityMeta
        return {sid:SecurityMeta(security_id=sid,ticker=self.assets[sid]['ticker'],
            category='Nasdaq Non-ETF Common Stock Candidate',permaticker=sid,related_tickers=None,
            first_session=first,last_session=day,exchange=self.assets[sid]['exchange'],exchange_authoritative=True)
            for sid,first in admitted.items()}

    def warmup(self,days):
        from sentinel.core.loader import CorpusWindow
        admitted,reasons=self.admitted(days);need(len(admitted)>=200,'WARMUP_UNIVERSE')
        window=CorpusWindow(list(days),LazyBars(self,days,admitted),self.metadata(admitted,days[-1]))
        window.median5_spy_closes={d:self.bench['SPY']['all'][d]['close'] for d in days};window.median5_terminals={}
        return window,{'admitted':len(admitted),'reasons':reasons}

    def material(self,prior,day,version,*,qualify=False):
        from stock_strategy_shared.wealth_core.feed import SecuritySeries
        from stock_strategy_shared.wealth_core.window_signals import feature
        from sentinel.core.window_material import WindowFeatures,Signal,protected,compile_rows
        from sentinel.feed import calendar
        from sentinel.feed.rolling_contract import digest,PriceWindow
        days=calendar.previous_sessions(day,300);admitted,reasons=self.admitted(days);meta=self.metadata(admitted,day)
        live=protected(prior)
        need(live.issubset(admitted),'PROTECTED_SOURCE_UNAVAILABLE:'+','.join(sorted(live-set(admitted))))
        signals=[];histories={};global_indices=[self.index[d] for d in days]
        for sid,first in sorted(admitted.items()):
            indices=[i for i,d in enumerate(days) if d>=first]
            need(indices and days[indices[-1]]==day,'ADMITTED_TAIL_CURSOR')
            if self.packed:
                values=self.values[self.sid_index[sid],[global_indices[i] for i in indices]]
                closes=values[-127:,3].tolist();raw=values[-20:,1].tolist();volumes=values[-20:,2].tolist()
            else:
                closes=[self.row(sid,days[i])['adjusted_close'] for i in indices[-127:]]
                raw=[self.row(sid,days[i])['closeunadj'] for i in indices[-20:]]
                volumes=[self.row(sid,days[i])['volume'] for i in indices[-20:]]
            series=SecuritySeries(sid,self.assets[sid]['ticker'],f'SID:{sid}',session_indices=indices[-127:],
                signal_closes=closes,raw_closes=raw,volumes=volumes)
            signals.append(Signal.from_feature(feature(series,meta[sid],index=299,session=day)))
            if sid in live:histories[sid]=tuple(self.bar(sid,d) for d in days[-261:-1] if d>=first)
        snap=digest({'schema':'research.alpaca-frozen-publication/1','source':self.capture_sha,'session':day,
                     'version':version,'admitted':admitted})
        material=WindowFeatures(snapshot_sha256=snap,prior_state_sha256=prior.state_hash,publication_version=version,
            sessions=tuple(days),signals=tuple(signals),histories=histories)
        qualification=None
        if qualify:
            qualified_at=time.monotonic()
            manifest=SimpleNamespace(window=PriceWindow.through(day),snapshot_id=snap)
            def rows():
                for sid,first in sorted(admitted.items()):
                    for d in days:
                        if d>=first:yield self.bar(sid,d)
            slow=compile_rows(prior=prior,manifest=manifest,metadata=meta,
                resolve_identity=lambda ticker,d:self.by_ticker.get(ticker),publication_version=version,session=day,rows=rows())
            need(slow.model_dump(mode='json',by_alias=True)==material.model_dump(mode='json',by_alias=True),'CANONICAL_FEATURE_MISMATCH')
            qualification={'session':day,'canonical_features_sha256':slow.sha256,'packed_features_sha256':material.sha256,
                           'signals':len(signals),'protected':len(live),'complete_equality':True,
                           'canonical_comparison_seconds':time.monotonic()-qualified_at}
        return material,meta,{'admitted':len(admitted),'reasons':reasons},qualification

    def published(self,prior,day,version,*,formation,qualify=False):
        blocked=cash_dependency_issues(prior,self.pending_cash,day)
        need(not blocked,'UNRESOLVED_CASH_DEPENDENCY:'+','.join(blocked))
        from sentinel.feed import calendar
        from sentinel.core.session import PublishedSession,DefensiveBar
        from sentinel.core.history import FormationWindowProof,CurrentWindowProof
        from sentinel.core.input_domains import _vendor
        from sentinel.feed.rolling_contract import digest
        material,meta,admission,qualification=self.material(prior,day,version,qualify=qualify)
        days=list(material.sessions);anchors={}
        from sentinel.core.window_material import protected
        for sid in sorted(protected(prior)):
            series=prior.feed['series'].get(sid,{})
            anchor=series.get('signal_basis_anchor')
            if anchor is None:
                anchor=next(([d,r,s] for d,r,s in zip(reversed(series.get('sessions',[])),
                    reversed(series.get('raw_closes',[])),reversed(series.get('signal_closes',[]))) if r and s),None)
            if anchor:
                need(isinstance(anchor,list) and len(anchor)==3,'SIGNAL_ANCHOR_SHAPE')
                anchor_day=anchor[0]
                need(anchor_day in self.index and self.paired(sid,anchor_day),'SIGNAL_ANCHOR_UNAVAILABLE')
                anchors[sid]=_vendor(self.bar(sid,anchor_day))
        def defensive(d):
            b=self.bench['BIL'];return DefensiveBar(d,'SENTINEL:BIL','BIL',b['split'][d]['open'],b['split'][d]['close'],
                b['all'][d]['close'],b['raw'][d]['close'])
        proof=None
        if prior.last_processed_session:
            proof=(FormationWindowProof if formation else CurrentWindowProof)(prior_version=prior.data_version,
                publication_version=version,prior_session=prior.last_processed_session,session=day,
                prior_state_sha256=prior.state_hash,snapshot_sha256=material.snapshot_sha256,features_sha256=material.sha256,
                protected_economics_sha256=digest({sid:[r.model_dump(mode='json') for r in rows] for sid,rows in material.histories.items()})).model_dump(by_alias=True)
        published=PublishedSession(session=day,data_version=version,bars=[_vendor(self.bar(sid,day)) for sid in sorted(meta)],
            meta=meta,sectors={sid:None for sid in meta},spy_closeadj=[self.bench['SPY']['all'][d]['close'] for d in days],
            spy_sessions=days,spy_expected_sessions=days,defensive_bar=defensive(day),
            defensive_previous_bar=defensive(calendar.previous_sessions(day,2)[0]),signal_basis_anchors=anchors,
            history_proof=proof,window_features=material.model_dump(mode='json',by_alias=True))
        return published,admission,qualification
