"""Bounded causal intended-exposure controllers; no account input."""
import numpy as np

from .data import FEATURES, GRID, WARMUP, action_indices


def smooth(raw, baseline, down, up, hold):
    raw, baseline = np.asarray(raw), np.asarray(baseline)
    action_indices(raw); action_indices(baseline)
    if min(down,up,hold)<1: raise ValueError('confirmation lengths must be positive')
    out = baseline.copy()
    state = baseline[WARMUP-1] if len(raw)>=WARMUP else baseline[-1]
    proposal, streak, age = state, 0, hold
    for i in range(WARMUP,len(raw)):
        target = raw[i]
        age += 1
        if target==state:
            proposal,streak = state,0
        else:
            streak = streak+1 if proposal==target else 1
            proposal = target
            if age>=hold and streak >= (down if target<state else up):
                state,streak,age = target,0,0
        out[i] = state
    return out


def state_path(x, baseline, p):
    out = baseline.copy()
    active = False
    age = impaired_run = healthy_run = recovery_run = wait_age = 0
    impaired = x[:,FEATURES.index('core_impaired')]
    healthy = x[:,FEATURES.index('core_healthy')]
    native = x[:,FEATURES.index('native_target')]
    champion = x[:,FEATURES.index('champion_target')]
    m5 = x[:,FEATURES.index('core_momentum_5')]
    m20 = x[:,FEATURES.index('core_momentum_20')]
    for i in range(WARMUP,len(x)):
        impaired_run = impaired_run+1 if impaired[i]==1 else 0
        healthy_run = healthy_run+1 if healthy[i]==1 else 0
        if active: age += 1
        if not active and impaired_run>=p['entry']:
            active,age = True,1
        if active and (healthy_run>=p['release'] or (p['expiry'] and age>=p['expiry'])):
            active,age,impaired_run = False,0,0
        wait = native[i]==1 and champion[i]==0
        wait_age = wait_age+1 if wait else 0
        recovery_run = recovery_run+1 if wait and healthy[i]==1 else 0
        target = champion[i]
        if native[i]==0:
            target = 0.
        elif wait:
            if recovery_run>=2*p['recovery'] and m20[i]>0:
                target = 1.
            elif recovery_run>=p['recovery'] or (p['timeout'] and wait_age>=p['timeout'] and m5[i]>0):
                target = .55
        if active: target = min(target,.55)
        out[i] = target
    action_indices(out)
    return out


def trend_path(x, baseline, p):
    def value(name):
        if p['asset']=='blend':
            return (x[:,FEATURES.index('core_'+name)]+x[:,FEATURES.index('spy_'+name)])/2
        return x[:,FEATURES.index(p['asset']+'_'+name)]
    momentum = value('momentum_'+str(p['momentum']))
    dd = value('drawdown_'+str(p['drawdown']))
    vol = value('volatility_20')
    warning = (momentum<p['warning_momentum']) | (vol>p['warning_vol'])
    severe = ((momentum<p['severe_momentum']) & (dd<p['severe_dd'])) | (vol>p['severe_vol'])
    raw = np.where(severe,0.,np.where(warning,.55,1.))
    return smooth(raw,baseline,p['down'],p['up'],p['hold'])


def forecast_path(predictions, baseline, p):
    if not np.isfinite(predictions[WARMUP:]).all():
        raise ValueError('nonfinite forecast')
    score = predictions[:,0]-p['risk']*np.maximum(predictions[:,1],0.)
    raw = np.where(score<p['low'],0.,np.where(score<p['high'],.55,1.))
    return smooth(raw,baseline,p['down'],p['up'],p['hold'])


def combine(paths, p):
    members = np.stack([paths['state'][p['state']],paths['trend'][p['trend']],
                        paths['predictive'][p['predictive']]])
    if p['vote']=='minimum': out = np.min(members,axis=0)
    elif p['vote']=='median': out = np.median(members,axis=0)
    elif p['vote']=='mean':
        mean = members.mean(axis=0)
        out = GRID[np.argmin(abs(mean[:,None]-GRID),axis=1)]
    else: raise ValueError('unknown combination vote')
    action_indices(out)
    return out


SIMPLE_TREND = dict(asset='core',momentum=20,drawdown=63,severe_momentum=-.05,
    severe_dd=-.12,warning_momentum=0.,warning_vol=.025,severe_vol=.04,down=2,up=3,hold=3)
