"""Frozen finite joint search identities; no prices, states or performance."""
import hashlib,itertools
from system_campaign_space import digest
from full_system_controller_policy import profiles

CORRELATION_LEVELS={'lookback':(126,189,252),'minimum_observations':(63,90,120),
    'cutoff':(0.,.145,.3,.5),'neighbors':(1,3,5),'stress':(.33,.5,.67),
    'own_dd':(-.075,-.1,-.15),'r21':(-.01,-.03,-.06)}
DEFAULT_CORRELATION={'lookback':252,'minimum_observations':120,'cutoff':.145,
    'neighbors':3,'stress':.5,'own_dd':-.1,'r21':-.03}


def correlation_record(p):
    p=dict(p)
    if set(p)!=set(CORRELATION_LEVELS) or any(type(p[k]) is bool or p[k] not in values for k,values in CORRELATION_LEVELS.items()):
        raise ValueError('REFUSED_JOINT_CORRELATION_PARAMETER')
    return {'id':'CORR_'+digest(p)[:20],'parameters':p}


def correlations():
    default=correlation_record(DEFAULT_CORRELATION);keys=list(CORRELATION_LEVELS)
    result=[correlation_record(dict(zip(keys,v))) for v in itertools.product(*CORRELATION_LEVELS.values())]
    result=[default]+sorted((v for v in result if v['id']!=default['id']),key=lambda v:v['id'])
    assert len(result)==len({v['id'] for v in result})==2916
    return result


def joint_profiles():
    controls=profiles();classifiers=correlations();pairs={(0,i) for i in range(len(classifiers))}|{(i,0) for i in range(len(controls))}
    counter=0
    while len(pairs)<4096:
        raw=hashlib.sha256(f'system-optimization-002/joint-interaction/{counter}'.encode()).digest();counter+=1
        pairs.add((1+int.from_bytes(raw[:8],'big')%255,1+int.from_bytes(raw[8:16],'big')%2915))
    result=[]
    for i,j in [(0,0)]+sorted(pairs-{(0,0)}):
        identity={'controller_id':controls[i]['id'],'correlation_id':classifiers[j]['id']}
        result.append({'id':'JOINT_'+digest(identity)[:20],**identity,'controller_index':i,'correlation_index':j})
    assert len(result)==len({v['id'] for v in result})==4096
    return {'schema':'research.system-campaign-joint-class/1','controllers':controls,'correlations':classifiers,
        'joint_profiles':result,'baseline_id':result[0]['id'],'interaction_pairs':925,
        'full_cartesian_product_count':len(controls)*len(classifiers),'global_optimum_claim':False}
