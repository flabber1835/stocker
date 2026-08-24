import importlib.util,sys,pandas as pd,numpy as np,json
from pathlib import Path
ROOT=Path('/mnt/data');OUT=ROOT/'sector_symbolic_v22_geometry_out';OUT.mkdir(exist_ok=True)
s=importlib.util.spec_from_file_location('core','/mnt/data/sector_peer_core.py');v=importlib.util.module_from_spec(s);sys.modules['core22']=v;s.loader.exec_module(v)
sym=pd.read_csv(ROOT/'sector_symbolic_v5_out/symbolic_days.csv',parse_dates=['date']).set_index('date').reindex(v.base.index);ctrl=sym.symbolic_status.eq('controllable');inev=sym.symbolic_status.eq('inevitable')
market=pd.read_csv(ROOT/'sector_peer_v10_market_only_out/market_res252_0.150.csv',parse_dates=['date']).set_index('date').fast.astype(bool).reindex(v.base.index,fill_value=False)
jac=pd.read_csv(ROOT/'sector_peer_v3_extra_out/jaccard_knn3_252.csv',parse_dates=['date']).set_index('date').fast.astype(bool).reindex(v.base.index,fill_value=False)
ext=pd.read_csv(ROOT/'sector_peer_v19_external_peers_out/external_resid_monthly_k3_rankw.csv',parse_dates=['date']).set_index('date').fast.astype(bool).reindex(v.base.index,fill_value=False)
min_d=sym.min_d.astype(float)
def gate(mask):return inev|(ctrl&mask)
variants={'market15_jaccard':gate(market&jac),'market15_ext':gate(market&ext),'market15_actual':market}
for floor in [.65,.70,.75,.80,.85]:
 variants[f'm15_jac_or_corele{int(floor*100)}']=gate(market & (jac | (min_d<=floor)))
 variants[f'm15_ext_or_corele{int(floor*100)}']=gate(market & (ext | (min_d<=floor)))
 variants[f'm15_2struct_or_corele{int(floor*100)}']=gate(market & ((jac&ext) | (min_d<=floor)))
capacity=(sym.max_d-sym.min_d)>=.25
variants['m15_jac_or_capacity25']=gate(market & (jac|capacity))

dam=pd.read_csv(ROOT/'sector_peer_v2_strict_out/damaged_breadth.csv',parse_dates=['date']).set_index('date').sec_ff12.reindex(v.base.index)
def metric(x,a=None,b=None):
 if a is not None:x=x.loc[(x.index>=pd.Timestamp(a))&(x.index<=pd.Timestamp(b))]
 yrs=(x.index[-1]-x.index[0]).days/365.2425;c=(x.iloc[-1]/x.iloc[0])**(1/yrs)-1;r=x.pct_change().dropna();return {'cagr':float(c),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)),'mdd':float((x/x.cummax()-1).min()),'multiple':float(x.iloc[-1]/x.iloc[0])}
rows=[]
for name,f in variants.items():
 out=v.replay(dam,override=f);out.to_csv(OUT/(name+'.csv'));row={'variant':name,'episodes':int((f&~f.shift(1,fill_value=False)).sum()),'starts':[str(d.date()) for d in f.index[f&~f.shift(1,fill_value=False)]]}
 for lab,a,b in [('full',None,None),('discovery','2006-07-31','2015-12-31'),('v1','2016-01-04','2020-12-31'),('v2','2021-01-04','2026-07-31'),('validation','2016-01-04','2026-07-31')]:
  mm=metric(out.nav,a,b);row.update({f'{lab}_{k}':vv for k,vv in mm.items()})
 rows.append(row)
df=pd.DataFrame([{k:v for k,v in r.items() if k!='starts'} for r in rows]).sort_values(['validation_cagr','full_cagr'],ascending=False);df.to_csv(OUT/'summary.csv',index=False);Path(OUT/'summary.json').write_text(json.dumps(rows,indent=2));print(df[['variant','full_cagr','full_sharpe','full_mdd','discovery_cagr','v1_cagr','v2_cagr','validation_cagr','validation_sharpe','validation_mdd','episodes']].to_string(index=False));
for r in rows:print(r['variant'],r['starts'])
