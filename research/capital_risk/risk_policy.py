"""Causal shadow-only decisions for the frozen twelve-profile search."""
from copy import deepcopy
from fractions import Fraction as Q

def need(v,c):
    if not v:raise ValueError(c)
def cold(cap=False):return dict(active=False,entry=0,recovery=0,**(dict(age=0,ratio='1') if cap else {}))
def valid(s,cap=False):
    need(set(s)==set(cold(cap)) and type(s['active']) is bool and all(type(s[k]) is int and s[k]>=0 for k in ('entry','recovery')),'REFUSED_POLICY_STATE')
    if cap:need(type(s['age']) is int and s['age']>=0 and 0<Q(s['ratio'])<=1,'REFUSED_BAND_STATE')

def step(profile,previous,observations,*,enabled=True):
    need(enabled is True,'REFUSED_SEARCH_POLICY_MODE');need(len({r['episode'] for r in observations})==len(observations),'REFUSED_SEARCH_DUPLICATE_EPISODE')
    weights={};impairment={}
    for r in observations:
        w,d=Q(r['weight']),Q(r['drawdown']);need(w>=0 and d>=0,'REFUSED_SEARCH_NEGATIVE_RISK');sid=r['security_id'];weights[sid]=weights.get(sid,Q(0))+w
        if r['red'] and not r['unknown']:impairment[sid]=impairment.get(sid,Q(0))+w*d
    live=[r for r in observations if not r['core_exit']];result={};transitions=[];audit=[];bookaudit=None
    if profile.family=='BOOK_DAMAGE':
        old=deepcopy(previous.get('__book__',cold()));valid(old);s=deepcopy(old);total=sum(weights.values(),Q(0));damage=sum(impairment.values(),Q(0))
        green=sum((Q(r['weight']) for r in observations if r['green']),Q(0))/total if total else Q(0)
        unknown=not observations or total==0 or any(r['unknown'] for r in observations);change=None
        if unknown:s.update(entry=0,recovery=0)
        elif s['active']:
            s['entry']=0;s['recovery']=s['recovery']+1 if green>=Q('.5') else 0
            if s['recovery']>=profile.recovery:s=cold();change='RECOVER'
        else:
            s['recovery']=0;s['entry']=s['entry']+1 if damage>=Q(profile.threshold) else 0
            if s['entry']>=profile.entry:s=dict(active=True,entry=0,recovery=0);change='ENTER'
        result['__book__']=s;bookaudit=dict(state_before=old,state_after=s,impairment=str(damage),green_fraction=str(green),unknown=unknown,transition=change)
        for r in live:
            key=r['episode'];before=previous.get(key,cold());after=dict(active=s['active'],entry=0,recovery=0);result[key]=after
            if change:transitions.append(dict(episode=key,security_id=r['security_id'],transition=change))
            audit.append({**r,'state_before':before,'state_after':after,'transition':change,'security_impairment':str(impairment.get(r['security_id'],Q(0)))})
    elif profile.family=='CONCENTRATION_BAND':
        groups={}
        for r in live:groups.setdefault(r['security_id'],[]).append(r)
        for sid,group in groups.items():
            existing=[previous[r['episode']] for r in group if r['episode'] in previous]
            old=deepcopy(existing[0] if existing else cold(True));valid(old,True)
            need(all(s==old for s in existing),'REFUSED_INCONSISTENT_SECURITY_BAND_STATE');s=deepcopy(old);w=weights[sid];change=None
            if s['active']:
                s['entry']=0;s['age']+=1;s['recovery']=s['recovery']+1 if w<=Q(profile.release) else 0
                if s['recovery']>=profile.recovery:s=cold(True);change='RECOVER'
                elif s['age']>=profile.rebalance:s['age']=0;change='ENTER'
            else:
                s['recovery']=0;s['entry']=s['entry']+1 if w>Q(profile.threshold) else 0
                if s['entry']>=profile.entry:s=dict(active=True,entry=0,recovery=0,age=0,ratio='1');change='ENTER'
            s['ratio']=str(min(Q(1),Q(profile.release)/w)) if s['active'] and w else '1'
            for r in group:
                key=r['episode'];result[key]=deepcopy(s)
                if change:transitions.append(dict(episode=key,security_id=sid,transition=change))
                audit.append({**r,'state_before':previous.get(key,cold(True)),'state_after':s,'transition':change,'security_weight':str(w),'security_impairment':str(impairment.get(sid,Q(0)))})
        # Preserve source slot order even when permanent-security groups have duplicates.
        order={r['episode']:i for i,r in enumerate(live)};audit.sort(key=lambda r:order[r['episode']]);transitions.sort(key=lambda r:order[r['episode']])
    else:
        need(profile.family=='LOCAL_RED','REFUSED_SEARCH_POLICY_FAMILY')
        for r in live:
            key=r['episode'];old=deepcopy(previous.get(key,cold()));valid(old);s=deepcopy(old);change=None
            if r['unknown']:s.update(entry=0,recovery=0)
            elif s['active']:
                s['entry']=0;s['recovery']=s['recovery']+1 if r['green'] else 0
                if s['recovery']>=profile.recovery:s=cold();change='RECOVER'
            else:
                s['recovery']=0;s['entry']=s['entry']+1 if r['red'] else 0
                if s['entry']>=profile.entry:s=dict(active=True,entry=0,recovery=0);change='ENTER'
            result[key]=s
            if change:transitions.append(dict(episode=key,security_id=r['security_id'],transition=change))
            audit.append({**r,'state_before':old,'state_after':s,'transition':change,'security_impairment':str(impairment.get(r['security_id'],Q(0)))})
    return result,transitions,dict(profile_id=profile.id,observations=audit,book=bookaudit)

def retention(profile,states,key):
    if profile.family=='BOOK_DAMAGE':return Q(1)  # Applied once through effective global exposure.
    s=states.get(key,{})
    if not s.get('active'):return Q(1)
    return Q(s['ratio']) if profile.family=='CONCENTRATION_BAND' else Q(profile.retained)

def projection(profile,original,frame,nav,states,transitions,held_global,execution_session=None):
    source=Q(frame['row']['economics']['pending_allocation']);book=profile.family=='BOOK_DAMAGE' and states.get('__book__',{}).get('active',False)
    effective=source*(Q(profile.retained) if book else 1);view=frame
    if profile.family=='BOOK_DAMAGE':view={**frame,'row':{**frame['row'],'economics':{**frame['row']['economics'],'pending_allocation':str(effective)}}}
    result=original(view,nav,states,transitions,held_global,execution_session)
    if profile.family=='BOOK_DAMAGE':
        held={r['episode']:r for r in frame['holdings']};core=Q(frame['row']['economics']['parent_core_close_equity'])
        for key,target in result['targets'].items():
            w=Q(1,20) if key in result['opens'] else Q(held[key]['shares'])*Q(frame['prices'][held[key]['security_id']]['raw_close'])/core
            target['neutral_dollars']=str(nav*source*w);target['local_active']=bool(book)
    result.update(profile_id=profile.id,original_global_target=str(source),risk_scope=profile.family,risk_book_active=bool(book))
    return result
