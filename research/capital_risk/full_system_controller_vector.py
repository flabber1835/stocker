"""Independent array equations for the declared research controller class."""
import numpy as np


def targets(rows,profiles):
    n=len(profiles)
    def p(key):
        parts=key.split('.')
        def value(profile):
            v=profile
            for part in parts:v=v[part]
            return float(v)
        return np.array([value(v) for v in profiles])
    par=lambda name:p('parent.'+name)
    own=lambda name:p('owned.'+name)
    b=lambda:np.zeros(n,dtype=bool)
    z=lambda:np.zeros(n,dtype=np.int64)
    ordinary=b();armed=~b();oa=z();oh=z();bf=b();bfa=~b();b_age=z();bh=z();anchor=np.full(n,np.nan);duration=z()
    fast=b();fa=~b();age=z();fh=z();slow=b();sa=z();sh=z()
    episode=b();latch=b();full=z();recent=z();prev_full=~b();previous=np.ones(n);effective=np.ones(n)
    owned_active=b();entry=z();recovery=z();paths=[]
    for row in rows:
        ob=row['evidence']['observation'];w=row['evidence']['recent_leadership']
        def num(key):
            v=ob.get(key);return float(v) if v is not None else np.nan
        dd,r5,r10,r20,r40,dam,green,delta,spy,vol,stops,nav=[num(k) for k in
            ('shadow_drawdown','shadow_r5','shadow_r10','shadow_r20','shadow_r40','damaged_breadth','green_breadth',
             'damaged_breadth_delta5','spy_r20','spy_vol_ratio','stops20','shadow_nav')]
        healthy=(r20>0)&(dam<=.63)&(green>=.20)
        signal=((dd<=par('fast.dd'))&(dam>=par('fast.dam'))&(green<=par('fast.green'))
            &((r5<=par('fast.r5'))|(r10<=par('fast.r10')))&(delta>=par('fast.ddam5'))
            &(vol>=par('fast.volacc'))&((spy<=par('fast.spy20'))|(r10<=par('fast.r10confirm'))))
        prior_base=ordinary|bf
        armed|=dd>par('ordinary_dd');new=(dd<=par('ordinary_dd'))&armed&~ordinary
        old=ordinary.copy();oa=np.where(new,0,np.where(old,oa+1,oa));oh=np.where(new,0,np.where(old,np.where((r20>0)&(stops<=2),oh+1,0),oh))
        release=old&~new&(oa>=20)&(oh>=3);ordinary=(old|new)&~release;oh=np.where(release,0,oh);armed&=~new
        bfa|=dd>-.06;new=signal&bfa&~bf&~ordinary;old=bf.copy()
        b_age=np.where(new,0,np.where(old,b_age+1,b_age));bh=np.where(new,0,np.where(old,np.where(healthy,bh+1,0),bh))
        release=old&~new&(b_age>=10)&(bh>=3);bf=(old|new)&~release;bh=np.where(release,0,bh);bfa&=~new
        base=ordinary|bf;anchor=np.where(base&~prior_base,nav,np.where(~base,np.nan,anchor));duration=np.where(base,np.where(prior_base,duration+1,1),0)
        since=nav/anchor-1
        slow_signal=(base&(duration>=par('slow.dur'))&(since<=par('slow.ret'))&(r40<=par('slow.r40'))
            &(dam>=par('slow.dam'))&(green<=par('slow.green')))
        fa|=dd>-.06;new=signal&fa&~fast;old=fast.copy()
        age=np.where(new,0,np.where(old,age+1,age));fh=np.where(new,0,np.where(old,np.where(healthy,fh+1,0),fh))
        release=old&~new&(age+1>=10)&(fh>=3);fast=(old|new)&~release;fh=np.where(release,0,fh);fa&=~new
        old=slow.copy();new=~old&slow_signal;sa=np.where(new,0,np.where(old,sa+1,sa));sh=np.where(new,0,np.where(old,np.where(healthy,sh+1,0),sh))
        release=old&(sa+1>=20)&(sh>=6);slow=(old|new)&~release;sh=np.where(release,0,sh)
        native=np.where(fast|slow,0.,1.)
        oa=np.minimum(oa,20);oh=np.minimum(oh,3);b_age=np.minimum(b_age,10);bh=np.minimum(bh,3)
        duration=np.minimum(duration,par('slow.dur'));age=np.minimum(age,9);fh=np.minimum(fh,3);sa=np.minimum(sa,19);sh=np.minimum(sh,6)
        wr20=float(w['recent_r20']) if w.get('recent_r20') is not None else np.nan
        wr40=float(w['recent_r40']) if w.get('recent_r40') is not None else np.nan
        full=np.where((wr20>0)&(wr40>par('recovery_r40')),full+1,0)
        start=prev_full&(native<1);episode|=start;recent=np.where(start,0,recent)
        recent=np.where(episode&(native>0)&(wr20>0),recent+1,0)
        latch&=~(full>=par('recovery_sessions'))
        concord=(recent>=par('recovery_sessions'))&(r20>0)&(wr20>=r20)&(spy>=r20)
        clear=episode&(native>=1)&((full>=par('recovery_sessions'))|concord)
        desired=np.where(episode&(native>=1)&~clear,0.,native);episode&=~clear;recent=np.where(clear,0,recent)
        latch|=(~latch)&(native>=1)&(effective>=1)&(dd<=par('recovery_dd'))&(wr20<=par('recovery_r20'))&(spy>=0)
        desired=np.minimum(native,np.minimum(desired,np.where(latch,par('recovery_ceiling'),1.)))
        full=np.minimum(full,par('recovery_sessions'));recent=np.minimum(recent,par('recovery_sessions'));prev_full=native==1
        effective,previous=previous.copy(),native.copy()
        impaired=(dd<=own('entry_drawdown'))&(dam>=own('entry_damage'))&(green<=own('entry_green'))
        heal=(r20>own('recovery_core_r20_above'))&(dam<=own('recovery_damage'))&(green>=own('recovery_green'))
        old=owned_active.copy();recovery=np.where(old,np.where(heal,recovery+1,0),0);entry=np.where(~old,np.where(impaired,entry+1,0),0)
        release=old&(recovery>=own('recovery_sessions'));activate=~old&(entry>=own('entry_sessions'))
        owned_active=(old|activate)&~release;entry=np.where(activate,0,entry);recovery=np.where(release,0,recovery)
        paths.append(np.minimum(desired,np.where(owned_active,own('active_ceiling'),1.)))
    return np.asarray(paths,dtype=float).T
