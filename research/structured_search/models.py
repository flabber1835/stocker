"""Small deterministic forecast models with JSON exports and purged fitting."""
import hashlib
import json

import numpy as np

from . import data


def key(p):
    names = ['model','features','horizon']
    names += {'ridge':['alpha'],'tree':['depth','leaf'],
              'neural':['width','alpha','rate']}[p['model']]
    return json.dumps({k:p[k] for k in names},sort_keys=True)


def scaler(x):
    mean,std = x.mean(axis=0),x.std(axis=0)
    std[std<1e-10] = 1.
    return mean,std


def neural_fit(x,y,p,seed):
    """Fixed full-batch Adam; no validation-driven stopping or random splits."""
    rng = np.random.default_rng(seed)
    w = rng.normal(0,1/np.sqrt(x.shape[1]),(x.shape[1],p['width']))
    b = np.zeros(p['width'])
    v = rng.normal(0,1/np.sqrt(p['width']),(p['width'],2))
    c = np.zeros(2)
    arrays = [w,b,v,c]
    first = [np.zeros_like(a) for a in arrays]
    second = [np.zeros_like(a) for a in arrays]
    losses = []
    for step in range(1,121):
        h = np.tanh(x@w+b)
        error = h@v+c-y
        delta = error/len(x)
        hidden = (delta@v.T)*(1-h*h)
        grads = [x.T@hidden+p['alpha']*w,b*0+hidden.sum(axis=0),
                 h.T@delta+p['alpha']*v,delta.sum(axis=0)]
        for j,(array,grad) in enumerate(zip(arrays,grads)):
            first[j] = .9*first[j]+.1*grad
            second[j] = .999*second[j]+.001*grad*grad
            array -= p['rate']*(first[j]/(1-.9**step))/(np.sqrt(second[j]/(1-.999**step))+1e-8)
        if step in (1,30,60,90,120): losses.append(float(np.mean(error**2)))
    return dict(w=w.tolist(),b=b.tolist(),v=v.tolist(),c=c.tolist(),epochs=120,losses=losses)


def fit(x, days, p, cutoff):
    indices,y = data.labels(days,p['horizon'],cutoff)
    cols = data.columns(p['features'])
    xx = x[indices][:,cols]
    if len(xx)<100 or not np.isfinite(xx).all(): raise ValueError('insufficient finite training data')
    xm,xs = scaler(xx); ym,ys = scaler(y)
    xx = np.clip((xx-xm)/xs,-10,10)
    yy = (y-ym)/ys
    seed = int(hashlib.sha256(key(p).encode()).hexdigest()[:8],16)
    if p['model']=='ridge':
        z = np.column_stack([xx,np.ones(len(xx))])
        penalty = np.eye(z.shape[1])*p['alpha']; penalty[-1,-1] = 0
        fitted = dict(coef=np.linalg.solve(z.T@z+penalty,z.T@yy).tolist())
    elif p['model']=='tree':
        from sklearn.tree import DecisionTreeRegressor
        model = DecisionTreeRegressor(max_depth=p['depth'],min_samples_leaf=p['leaf'],random_state=seed)
        model.fit(xx,yy)
        t = model.tree_
        fitted = dict(left=t.children_left.tolist(),right=t.children_right.tolist(),
                      feature=t.feature.tolist(),threshold=t.threshold.tolist(),value=t.value[:,:,0].tolist())
    elif p['model']=='neural': fitted = neural_fit(xx,yy,p,seed)
    else: raise ValueError('unknown forecast model')
    result = dict(kind=p['model'],columns=cols,xmean=xm.tolist(),xscale=xs.tolist(),
        ymean=ym.tolist(),yscale=ys.tolist(),fit=fitted,cutoff=cutoff,horizon=p['horizon'],
        first_example=int(indices[0]),last_example=int(indices[-1]),
        last_outcome=int(indices[-1]+p['horizon']),examples=len(indices),seed=seed)
    if result['last_outcome']>cutoff: raise ValueError('fitted outcome exceeds cutoff')
    return result


def predict(model,x):
    cols = model['columns']
    xx = np.clip((x[:,cols]-np.array(model['xmean']))/np.array(model['xscale']),-10,10)
    # Warmup rows never supply a learned decision; neutral placeholders avoid NaN exports.
    xx = np.nan_to_num(xx)
    f = model['fit']
    if model['kind']=='ridge':
        pred = np.column_stack([xx,np.ones(len(xx))])@np.array(f['coef'])
    elif model['kind']=='neural':
        pred = np.tanh(xx@np.array(f['w'])+np.array(f['b']))@np.array(f['v'])+np.array(f['c'])
    elif model['kind']=='tree':
        node = np.zeros(len(xx),dtype=int)
        left,right = np.array(f['left']),np.array(f['right'])
        feature,threshold = np.array(f['feature']),np.array(f['threshold'])
        active = left[node]!=-1
        while active.any():
            pos = np.flatnonzero(active); n = node[pos]
            node[pos] = np.where(xx[pos,feature[n]]<=threshold[n],left[n],right[n])
            active = left[node]!=-1
        pred = np.array(f['value'])[node]
    else: raise ValueError('unknown model export')
    result = pred*np.array(model['yscale'])+np.array(model['ymean'])
    if not np.isfinite(result).all(): raise ValueError('invalid model prediction')
    return result
