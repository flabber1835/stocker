from __future__ import annotations
import importlib.util,sys,pandas as pd,numpy as np,json
from pathlib import Path
ROOT=Path('/mnt/data');OUT=ROOT/'sector_symbolic_v29_walkforward_threshold_out';OUT.mkdir(exist_ok=True)
s=importlib.util.spec_from_file_location('core','/mnt/data/sector_peer_core.py');v=importlib.util.module_from_spec(s);sys.modules['core29']=v;s.loader.exec_module(v)
sym=pd.read_csv(ROOT/'sector_symbolic_v5_out/symbolic_days.csv',parse_dates=['date']).set_index('date').reindex(v.base.index);ctrl=sym.symbolic_status.eq('controllable');inev=sym.symbolic_status.eq('inevitable');jac=pd.read_csv(ROOT/'sector_peer_v3_extra_out/jaccard_knn3_252.csv',parse_dates=['date']).set_index('date').fast.astype(bool).reindex(v.base.index,fill_value=False);ffdam=pd.read_csv(ROOT/'sector_peer_v2_strict_out/damaged_breadth.csv',parse_dates=['date']).set_index('date').sec_ff12.reindex(v.base.index)
def marketfast(th):
 vals=[]
 for d in v.base.index:
  g=v.groups[d];core=g.core.to_numpy(bool);target=g.target.to_numpy(bool);sco=g.resmax252.to_numpy(float);add=target&np.isfinite(sco)&(sco>=th);vals.append((core|add).mean())
 dam=pd.Series(vals,index=v.base.index);return v.replay(dam).fast.astype(bool)
def metric(x,a,b):
 x=x.loc[(x.index>=pd.Timestamp(a))&(x.index<=pd.Timestamp(b))]
 yrs=(x.index[-1]-x.index[0]).days/365.2425;c=(x.iloc[-1]/x.iloc[0])**(1/yrs)-1;r=x.pct_change().dropna();return {'cagr':float(c),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)),'mdd':float((x/x.cummax()-1).min())}
ths=np.array([.10,.125,.13,.135,.14,.145,.15,.155,.16,.165,.17,.20,.25,.30]);curves={};rows=[]
for th in ths:
 mf=marketfast(float(th));override=inev|(ctrl&mf&(jac|(sym.min_d.astype(float)<=.75)));out=v.replay(ffdam,override=override);curves[float(th)]=out.nav
 for label,a,b in [('train2010','2006-07-31','2010-12-31'),('train2015','2006-07-31','2015-12-31'),('train2020','2006-07-31','2020-12-31'),('test1115','2011-01-03','2015-12-31'),('test1620','2016-01-04','2020-12-31'),('test2126','2021-01-04','2026-07-31'),('full','2006-07-31','2026-07-31')]:
  m=metric(out.nav,a,b);rows.append({'threshold':float(th),'window':label,**m})
pd.DataFrame(rows).to_csv(OUT/'threshold_windows.csv',index=False)
sel=[]
for train_label,test_label in [('train2010','test1115'),('train2015','test1620'),('train2020','test2126')]:
 d=pd.DataFrame(rows);tr=d[d.window.eq(train_label)].copy();mx=tr.cagr.max();eligible=tr[tr.cagr>=mx-.0001];best=eligible.sort_values('threshold').iloc[0];th=float(best.threshold);te=d[(d.window.eq(test_label))&(d.threshold.eq(th))].iloc[0]
 sh=tr.sort_values(['sharpe','threshold'],ascending=[False,True]).iloc[0];tes=d[(d.window.eq(test_label))&(d.threshold.eq(float(sh.threshold)))].iloc[0]
 sel.append({'train':train_label,'test':test_label,'selected_cagr_threshold':th,'train_cagr':float(best.cagr),'test_cagr':float(te.cagr),'test_sharpe':float(te.sharpe),'test_mdd':float(te.mdd),'selected_sharpe_threshold':float(sh.threshold),'train_sharpe':float(sh.sharpe),'sharpe_selector_test_cagr':float(tes.cagr),'sharpe_selector_test_sharpe':float(tes.sharpe),'sharpe_selector_test_mdd':float(tes.mdd)})
pd.DataFrame(sel).to_csv(OUT/'walkforward_selection.csv',index=False);Path(OUT/'summary.json').write_text(json.dumps(sel,indent=2));print(pd.DataFrame(sel).to_string(index=False))
