"""Frozen bounded parent/Owned proposal class and training-only selection."""
import hashlib,json,math,os,types
from pathlib import Path
from fractions import Fraction as Q

BASE_PARENT={'ordinary_dd':-.155,
    'fast':{'dd':-.10,'dam':.88,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10},
    'slow':{'dur':30,'ret':-.02,'r40':-.03,'dam':.75,'green':.25},
    'recovery_dd':-.10,'recovery_r20':-.085,'recovery_ceiling':.55,'recovery_sessions':8,'recovery_r40':-.04}
BASE_OWNED={'entry_drawdown':'-0.10','entry_damage':'0.88','entry_green':'0.20','entry_sessions':5,
    'recovery_damage':'0.63','recovery_green':'0.20','recovery_core_r20_above':'0','recovery_sessions':8,'active_ceiling':'0.55'}
LEVELS={
 'ordinary_dd':[-.10,-.155,-.20],
 'fast.dd':[-.075,-.10,-.15], 'fast.dam':[.63,.75,.88], 'fast.green':[.10,.20,.30],
 'fast.r5':[-.03,-.05,-.075], 'fast.r10':[-.05,-.08,-.12], 'fast.ddam5':[.15,.30,.45],
 'fast.volacc':[0.,.04,.10], 'fast.spy20':[-.03,-.01,.01], 'fast.r10confirm':[-.075,-.10,-.15],
 'slow.dur':[15,30,45], 'slow.ret':[-.01,-.02,-.04], 'slow.r40':[-.01,-.03,-.06],
 'slow.dam':[.60,.75,.88], 'slow.green':[.10,.25,.40],
 'recovery_dd':[-.075,-.10,-.15], 'recovery_r20':[-.05,-.085,-.12],
 'recovery_ceiling':[.25,.55,.75], 'recovery_sessions':[3,5,8], 'recovery_r40':[-.08,-.04,0.],
 'owned.entry_drawdown':['-0.075','-0.10','-0.15'], 'owned.entry_damage':['0.50','0.63','0.75','0.88'],
 'owned.entry_green':['0.10','0.20','0.30'], 'owned.entry_sessions':[1,3,5],
 'owned.recovery_damage':['0.50','0.63','0.75'], 'owned.recovery_green':['0.10','0.20','0.30'],
 'owned.recovery_core_r20_above':['-0.02','0','0.02'], 'owned.recovery_sessions':[3,5,8],
 'owned.active_ceiling':['0.25','0.55','0.75']}


def need(value,code):
    if not value:raise ValueError('REFUSED_FULL_CONTROLLER_'+code)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def profiles():
    result=[]
    for row in range(256):
        parent=json.loads(json.dumps(BASE_PARENT));owned=dict(BASE_OWNED)
        if row:
            for key,values in LEVELS.items():
                seed=int.from_bytes(hashlib.sha256(('full-system-parent-latin-001/'+key).encode()).digest()[:8],'big')
                multiplier=2*(seed%128)+1
                while math.gcd(multiplier,255)!=1:multiplier+=2
                index=((multiplier*(row-1)+(seed//128)%255)%255)*len(values)//255
                value=values[index]
                if key.startswith('owned.'):owned[key[6:]]=value
                elif '.' in key:
                    section,item=key.split('.');parent[section][item]=value
                else:parent[key]=value
        config={'parent':parent,'owned':owned};result.append({'id':'CTRL_'+digest(config)[:20],**config})
    need(len({p['id'] for p in result})==256,'UNIQUE_FROZEN_PROPOSALS')
    return result


def parent_module(raw,profile,expected_sha):
    need(os.environ.get('FULL_SYSTEM_HOSTED')=='1','HOSTED_PARENT_ONLY')
    need(hashlib.sha256(raw).hexdigest()==expected_sha,'FROZEN_PARENT_SOURCE')
    text=raw.decode();p=profile['parent']
    def replace(old,new):
        nonlocal text
        need(text.count(old)==1,'PARENT_PARAMETER_SITE:'+old);text=text.replace(old,new)
    # Execute the exact canonical state transitions with declared constants.
    # Duration saturation and serialized restoration limits change together.
    replace('ORD_DD = -0.155','ORD_DD = '+repr(p['ordinary_dd']))
    first=next(line for line in text.splitlines() if line.startswith('FAST = '));replace(first,'FAST = '+repr(p['fast']))
    first=next(line for line in text.splitlines() if line.startswith('SLOW = '));replace(first,'SLOW = '+repr(p['slow']))
    for key,variable in (('recovery_dd','LDRC_DD'),('recovery_r20','LDRC_R20'),('recovery_ceiling','LDRC_CEIL'),('recovery_sessions','LDRC_REC')):
        first=next(line for line in text.splitlines() if line.startswith(variable+' = '));replace(first,variable+' = '+repr(p[key]))
    replace('self.base_dur = min(self.base_dur, 30)','self.base_dur = min(self.base_dur, '+str(p['slow']['dur'])+')')
    replace("'base_dur': 30", "'base_dur': "+str(p['slow']['dur']))
    replace("_caps = {'full_streak': 8, 'recent_positive_streak': 8}",
        "_caps = {'full_streak': "+str(p['recovery_sessions'])+", 'recent_positive_streak': "+str(p['recovery_sessions'])+'}')
    replace('(recent_r40 > -0.04)','(recent_r40 > '+repr(p['recovery_r40'])+')')
    module=types.ModuleType('_private_full_system_parent_'+profile['id']);exec(compile(text,'<private-parameterized-canonical-parent>','exec'),module.__dict__)
    module.compiled_sha256=hashlib.sha256(text.encode()).hexdigest()
    return module


def select(training,baseline,budgets=('0.50','0.75','1.0')):
    # This interface cannot accept evaluation metrics.
    expected={'id','core_id','group','metrics','turnover'}
    need(training and all(set(r)==expected for r in training),'TRAINING_ONLY_RECORD_SHAPE')
    by_id={r['id']:r for r in training};need(len(by_id)==len(training) and baseline in by_id,'BASELINE_IN_CLASS')
    base=by_id[baseline];draw=Q(base['metrics']['maximum_drawdown_magnitude'])
    need(all(all(r['metrics'][k]==base['metrics'][k] for k in ('anchor','start','end','closes')) for r in training),
        'COMMON_TRAINING_WINDOW')
    def order(r):return (-Q(r['metrics']['multiple']),Q(r['turnover']),r['id']!=baseline,r['id'])
    choices=[];budget_rows=[]
    for budget in budgets:
        eligible=[r for r in training if Q(r['metrics']['maximum_drawdown_magnitude'])<=draw*Q(budget)]
        chosen=min(eligible,key=order) if eligible else None
        budget_rows.append({'relative_budget':budget,'id':None if chosen is None else chosen['id']})
        if chosen:choices.append(chosen['id'])
    joint=[r for r in training if Q(r['metrics']['multiple'])>Q(base['metrics']['multiple'])
        and Q(r['metrics']['maximum_drawdown_magnitude'])<draw]
    best=min(joint,key=order) if joint else None
    if best:choices.append(best['id'])
    return {'status':'TRAINING_SELECTION_LOCKED','selected':list(dict.fromkeys(choices)),
        'baseline':baseline,'budget_choices':budget_rows,'training_joint_improvements':len(joint),
        'best_joint':None if best is None else best['id'],'evaluation_used':False,
        'coverage':'BOUNDED_INITIAL_CLASS_NOT_GLOBAL_OPTIMUM'}
