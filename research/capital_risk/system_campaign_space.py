"""Frozen broad Core proposal universe, without prices, histories or scores."""
import hashlib,json
from copy import deepcopy

LEVELS={
 'lookback':[84,126,189,252],'skip':[10,21,42],'volatility':['log_returns_certified_v1','simple_returns_v1'],
 'liquidity':[10,20,40],'minimum_price':[.5,1.,5.],'average_dollars':[10000000,20000000,50000000],
 'current_dollars':[2000000,5000000,10000000],'leadership':[.05,.10,.20],'minimum_leaders':[15,25,40],
 'rank_memory':[1,5,10],'front':[1,3,5],'freshness':[-.02,0.,.02],'slots':[10,20,30],'admissions':[1,2,4],
 'stop':[.6,.7,.8],'review':[63,119,189],'slot_cooldown':[10,21,42],'security_cooldown':[10,21,42],
 'c_trigger':[.08,.10,.15],'c_target':[.05,.08,.10],
 'v_horizon':[10,21,42],'v_multiplier':[1.5,2.,3.],'v_minimum':[.10,.15,.20],'v_maximum':[.25,.30,.40]}
DEFAULT={'family':'CORE','lookback':126,'skip':21,'volatility':'log_returns_certified_v1','liquidity':20,
 'minimum_price':1.,'average_dollars':20000000,'current_dollars':5000000,'leadership':.10,'minimum_leaders':25,
 'rank_memory':5,'front':3,'freshness':0.,'slots':20,'admissions':1,'stop':.7,'review':119,'slot_cooldown':21,'security_cooldown':21,
 'c_trigger':None,'c_target':None,'v_horizon':None,'v_multiplier':None,'v_minimum':None,'v_maximum':None}
C_FIELDS=('c_trigger','c_target');V_FIELDS=('v_horizon','v_multiplier','v_minimum','v_maximum')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def canonical(parameters):
    p=dict(parameters)
    if set(p)!=set(DEFAULT) or p['family'] not in ('CORE','C','V'):raise ValueError('REFUSED_CAMPAIGN_PARAMETER_SHAPE')
    for fields,active in ((C_FIELDS,p['family']=='C'),(V_FIELDS,p['family']=='V')):
        if not active:
            for name in fields:p[name]=None
    for k,values in LEVELS.items():
        if p[k] is not None and (isinstance(p[k],bool) or p[k] not in values):raise ValueError('REFUSED_CAMPAIGN_PARAMETER:'+k)
        if p[k] is None and k not in C_FIELDS+V_FIELDS:raise ValueError('REFUSED_INACTIVE_CORE_PARAMETER')
    if p['family']=='C' and (any(p[k] is None for k in C_FIELDS) or p['c_target']>=p['c_trigger']):raise ValueError('REFUSED_CONCENTRATION_BAND')
    if p['family']=='V' and (any(p[k] is None for k in V_FIELDS) or p['v_minimum']>p['v_maximum']):raise ValueError('REFUSED_VOLATILITY_BAND')
    return p
def record(p):
    p=canonical(p);return {'id':p['family']+'_'+digest(p)[:20],'parameters':p}
def coordinates(p):
    p=canonical(p);x=[float(p['family']==f) for f in ('CORE','C','V')]
    for k,values in LEVELS.items():x.append(0. if p[k] is None else values.index(p[k])/max(1,len(values)-1))
    return x
def distance(a,b):
    return sum(x!=y for x,y in zip(coordinates(a),coordinates(b)))/len(coordinates(a))
def universe():
    result={};index=0
    while len(result)<4096:
        p=dict(DEFAULT);p['family']=('CORE','C','V')[index%3]
        for k,values in LEVELS.items():
            seed=hashlib.sha256(f'system-optimization-002/universe/{index}/{k}'.encode()).digest()
            p[k]=values[int.from_bytes(seed[:8],'big')%len(values)]
        index+=1
        try:r=record(p)
        except ValueError:continue
        result[r['id']]=r
    return sorted(result.values(),key=lambda r:r['id'])
def initial():
    selected=[record(DEFAULT)];pool=[p for p in universe() if p['parameters']['family']=='CORE']
    for _ in range(7):
        available=[p for p in pool if p['id'] not in {r['id'] for r in selected}]
        selected.append(min(available,key=lambda p:(-min(distance(p['parameters'],r['parameters']) for r in selected),p['id'])))
    for family,changes in (
        ('C',{'slots':20,'c_trigger':.08,'c_target':.05}),('C',{'slots':10,'c_trigger':.15,'c_target':.08}),
        ('V',{'v_horizon':21,'v_multiplier':2.,'v_minimum':.15,'v_maximum':.30}),
        ('V',{'v_horizon':10,'v_multiplier':1.5,'v_minimum':.10,'v_maximum':.25})):
        selected.append(record({**DEFAULT,'family':family,**changes}))
    assert len(selected)==len({r['id'] for r in selected})==12
    return selected
