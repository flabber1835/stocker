"""Read admitted Core/controller evidence; no Core or controller advancement."""
import gzip
import hashlib
import json
from pathlib import Path
from fractions import Fraction as Q
from alpaca_fit_inputs import hosted,need
from alpaca_fit_baseline import encoded


class Source:
    def __init__(self,root,protocol,stage):
        hosted();self.root=Path(root);self.protocol=protocol;self.stage=stage
        self.end=protocol['training_end'] if stage=='TRAINING' else protocol['data_end']
        review=json.loads((self.root.parent/'stopped-independent-review/review/independent-review.json').read_bytes())
        need(review['status'] in ('COMPLETE_TRACE_REVIEWED','PARTIAL_PREFIX_REVIEWED')
             and review['last_committed_session']>=self.end and review['uncommitted_tail_bytes']==0,'FUNDED_SOURCE_NOT_REVIEWED')
        status=json.loads((self.root/'baseline-status.json').read_bytes());commit=status['journal']
        h=hashlib.sha256();chain='0'*64;count=0;length=0;self.rows=[]
        train=hashlib.sha256();train_bytes=0;train_count=0;train_chain='0'*64
        with (self.root/'canonical.jsonl').open('rb') as f:
            for raw in f:
                row=json.loads(raw);need(encoded(row)==raw and row['previous_chain_sha256']==chain,'FUNDED_SOURCE_CHAIN')
                chain=hashlib.sha256(raw).hexdigest();h.update(raw);count+=1;length+=len(raw)
                if row['phase']=='WARMUP_ORIGIN' or row['session']<=protocol['training_end']:
                    train.update(raw);train_bytes+=len(raw);train_count+=1;train_chain=chain
                if row['phase']!='WARMUP_ORIGIN' and row['session']<=self.end:self.rows.append(row)
        need((length,h.hexdigest(),count,chain)==(commit['bytes'],commit['sha256'],commit['records'],commit['chain_sha256']),
             'FUNDED_SOURCE_COMMITMENT')
        from sentinel.feed import calendar
        measured=calendar.sessions_in_range(protocol['measured_start'],self.end)
        self.measured=[r for r in self.rows if r['phase']=='MEASURED'];formation=[r for r in self.rows if r['phase']=='FORMATION']
        need(len(formation)==126 and [r['session'] for r in self.measured]==measured,'FUNDED_SOURCE_DATE_AXIS')
        self.anchor=formation[-1];self.by_day={r['session']:r for r in self.rows};self.navs={r['session']:r['shadow_nav'] for r in self.rows}
        self.commitment=commit;self.source_sha256=h.hexdigest()
        self.training_prefix={'bytes':train_bytes,'records':train_count,'sha256':train.hexdigest(),'chain_sha256':train_chain}
        self.dataset_sha256=json.loads((self.root/'normalization.json').read_bytes())['dataset_sha256']
        checked=0
        for row in self.rows:
            for order in row['pending']:
                need(order['operation'] in ('OPEN_SLOT_POSITION','CLOSE_POSITION'),'FUNDED_UNSUPPORTED_PENDING_PREFLIGHT')
                if order['operation']=='OPEN_SLOT_POSITION':
                    origin=order['signal_session'];need(origin in self.navs and origin<=row['session'],'FUNDED_ORIGINAL_SIGNAL_PREFLIGHT')
                    original=Q(str(self.navs[origin]));actual=Q(str(order['intended_dollars']))
                    need(abs(actual-original/20)<=max(Q('0.00000001'),original*Q('0.0000000001')),'FUNDED_SOURCE_ENTRY_BUDGET_PREFLIGHT')
                    checked+=1
        self.preflight={'source_pending_budget_observations':checked,'all_original_NAV20_budgets_equal':True}
        self.review=review


def benchmark_inputs(root,prefix,bil,protocol,source):
    """Select only benchmark pages; authenticate each exact raw preimage."""
    from sentinel.feed.alpaca_observation import bar_page_rows
    from sentinel.feed import calendar
    from alpaca_fit_account import defensive_factors
    axis=set(calendar.sessions_in_range(protocol['data_start'],protocol['data_end']));bars={}
    for directory in (Path(prefix),Path(root),Path(bil)):
        manifest=json.loads((directory/'manifest.json').read_bytes())
        for line in (directory/'capture/request-receipts.jsonl').read_bytes().splitlines():
            p=json.loads(line);params=p.get('params') or {};symbols=set(params.get('symbols','').split(','))
            if not p['endpoint'].endswith('/bars') or symbols not in ({'SPY','BIL'},{'BIL'}):continue
            need(params['asof']==protocol['data_end'] and params['feed']=='sip','FUNDED_BENCHMARK_QUERY')
            name='capture/'+p['file'];packed=(directory/name).read_bytes();expected=manifest['members'][name]
            need(len(packed)==p['bytes']==expected['bytes'] and hashlib.sha256(packed).hexdigest()==p['sha256']==expected['sha256'],
                 'FUNDED_BENCHMARK_RESPONSE')
            raw=gzip.decompress(packed);need(len(raw)==p['raw_bytes'] and hashlib.sha256(raw).hexdigest()==p['raw_sha256'],'FUNDED_BENCHMARK_RAW')
            reply=json.loads(raw)
            for (symbol,day),bar in bar_page_rows(reply['bars'],symbols=symbols,sessions=axis).items():
                key=(symbol,params['adjustment'],day);need(key not in bars,'FUNDED_BENCHMARK_DUPLICATE');bars[key]=bar
    checked=0
    for row in source.rows:
        day=row['session'];previous=row['defensive_previous_bar']['session']
        for label,d in (('defensive_bar',day),('defensive_previous_bar',previous)):
            b=row[label];split=bars[('BIL','split',d)];raw=bars[('BIL','raw',d)];all_=bars[('BIL','all',d)]
            need(b['open_signal']==split['open'] and b['close_signal']==split['close']
                 and b['close_unadjusted']==raw['close'] and b['close_adjusted']==all_['close'],'FUNDED_DEFENSIVE_PREIMAGE')
        need(row['spy_close_adjusted']==bars[('SPY','all',day)]['close'],'FUNDED_SPY_CLOSE_PREIMAGE')
        if 'spy_open_adjusted' in row:need(row['spy_open_adjusted']==bars[('SPY','all',day)]['open'],'FUNDED_SPY_OPEN_PREIMAGE')
        gap,intraday=defensive_factors(row);need(gap>0 and intraday>0,'FUNDED_DEFENSIVE_FACTORS');checked+=1
    first=source.measured[0]['session'];initial=Q(str(bars[('SPY','all',first)]['open']))
    spy=[(r['session'],str(Q(protocol['capital'])*Q(str(bars[('SPY','all',r['session'])]['close']))/initial)) for r in source.measured]
    return {'schema':'research.alpaca-funded-benchmark-proof/1','source_rows_checked':checked,
        'all_defensive_and_spy_preimages_equal':True,'first_funded_open':first,'spy_gross_initial_fee_excluded':True},spy
