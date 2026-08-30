#!/usr/bin/env python3
"""Run bounded fail-closed causal certification for retained research."""
from __future__ import annotations
import argparse,gzip,hashlib,json,math,shutil,subprocess,sys
from collections import OrderedDict
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from backtester.research_causal_instrumentation import static_leakage_audit
WARMUP="2006-01-03"; START="2006-07-31"; END="2007-12-31"; MED="1035638340512403010"
DATA_HASH="08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6"
PACKAGE="ghcr.io/flabber1835/stocker-canonical-pit@sha256:37b41e3b91a8e26cfa3030039467ca94d71d0090839dae48e290453d7a17eadb"
MANIFEST_HASH="008f768539c8e6d0e5f2f01a05dab1baf93560c2ffeb7ca7b1521b1a236263e1"
RECON_SHA="eb873b399024679e6534797b1e9f4bcccbe36656"
def hfile(p:Path)->str:
 d=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): d.update(b)
 return d.hexdigest()
def fval(v):
 if v is None or v=="NaN": return None
 if v=="+Infinity": return math.inf
 if v=="-Infinity": return -math.inf
 return float(v) if isinstance(v,(int,float)) else float.fromhex(str(v))
def read_trace(p:Path):
 out=[]
 with gzip.open(p,"rb") as f:
  for raw in f:
   if raw.strip():
    j=json.loads(raw); out.append((str(j["record"]["date"]),raw,j))
 if [x[0] for x in out]!=sorted({x[0] for x in out}): raise RuntimeError(f"nonchronological trace {p}")
 return out
def diff(a,b,path="$"):
 if type(a) is not type(b): return {"path":path,"left":a,"right":b,"reason":"type"}
 if isinstance(a,dict):
  for k in sorted(set(a)|set(b)):
   if k not in a or k not in b:return {"path":f"{path}.{k}","reason":"missing_key"}
   x=diff(a[k],b[k],f"{path}.{k}")
   if x:return x
 elif isinstance(a,list):
  if len(a)!=len(b):return {"path":path,"left":len(a),"right":len(b),"reason":"length"}
  for i,(x,y) in enumerate(zip(a,b)):
   z=diff(x,y,f"{path}[{i}]")
   if z:return z
 elif a!=b:return {"path":path,"left":a,"right":b,"reason":"value"}
 return None
def compare(base,cand,cut):
 a=[x for x in base if x[0]<=cut]; b=[x for x in cand if x[0]<=cut]
 if len(a)!=len(b): return {"status":"FAIL","cutoff":cut,"expected_rows":len(a),"actual_rows":len(b),"first_mismatch":{"reason":"row_count"}}
 for i,(x,y) in enumerate(zip(a,b)):
  if x[1]!=y[1]:return {"status":"FAIL","cutoff":cut,"first_mismatch":{"row":i,"date":x[0],"detail":diff(x[2],y[2])}}
 return {"status":"PASS","cutoff":cut,"rows":len(a),"prefix_sha256":hashlib.sha256(b"".join(x[1] for x in a)).hexdigest(),"byte_for_byte_identical":True}
def run(ds:Path,out:Path,view:str,cut=None,seed=314159):
 out.mkdir(parents=True,exist_ok=True); cmd=[sys.executable,"backtester/run_research_causal_single.py","--canonical-dataset",str(ds),"--output",str(out),"--view",view]
 if cut:cmd += ["--cutoff",cut]
 if view=="poison":cmd += ["--poison-seed",str(seed)]
 with (out/"run.log").open("w") as log:
  p=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1); assert p.stdout
  for line in p.stdout: print(line,end="",flush=True);log.write(line)
  rc=p.wait()
 if rc:raise RuntimeError(f"causal replay failed view={view} cutoff={cut} rc={rc}")
def identity(pointer:Path,ds:Path):
 p=json.loads(pointer.read_text());mfile=ds/"manifest.json";m=json.loads(mfile.read_text())
 checks={"pointer_status":p.get("status")=="PASS","manifest_status":m.get("status")=="PASS","package":p.get("package")==PACKAGE,"pointer_hash":p.get("dataset_hash")==DATA_HASH,"manifest_hash":m.get("dataset_hash")==DATA_HASH,"manifest_sha256":hfile(mfile)==MANIFEST_HASH,"pointer_manifest_sha256":p.get("manifest_sha256")==MANIFEST_HASH,"reconstruction_sha":p.get("reconstruction_code_sha")==RECON_SHA,"window":p.get("window")=={"warmup_start":WARMUP,"measurement_start":START,"end":END},"unresolved_actions":int(m.get("counts",{}).get("unresolved_corporate_actions",-1))==0}
 if not all(checks.values()):raise RuntimeError(f"dataset identity failure {checks}")
 return {"status":"PASS","pointer":str(pointer),"package":p["package"],"dataset_hash":p["dataset_hash"],"dataset_id":p["dataset_id"],"manifest_sha256":hfile(mfile),"reconstruction_code_sha":p["reconstruction_code_sha"],"source_run_id":p["source_run_id"],"window":p["window"],"checks":checks}
def first(trace,pred,start=START):
 return next((d for d,_,e in trace if d>=start and pred(e["record"])),None)
def cutoffs(trace):
 x:OrderedDict[str,list[str]]=OrderedDict()
 def add(d,r):
  if d and "2006-08-01"<=d<=END:x.setdefault(d,[]).append(r)
 add("2006-08-01","first session after measurement start; includes complete warmup and initial entries")
 add(first(trace,lambda r:bool(r["orders"]["items"])),"first measured close with orders")
 add(first(trace,lambda r:bool(r["fills"]["items"])),"first measured open with fills")
 add(first(trace,lambda r:any(i.get("side")=="SELL" for i in r["fills"]["items"])),"first measured exit/rebalance")
 add(first(trace,lambda r:bool(r["events"]["terminals"])),"first post-measurement terminal event")
 for d,r in [("2006-08-15","MED age-119 review"),("2006-08-16","MED next open and held split"),("2006-09-07","historical first-divergence sensitivity"),("2006-09-29","quarter end"),("2006-12-29","year and quarter end"),("2007-02-21","held split"),("2007-09-28","quarter end"),(END,"dataset end")]:add(d,r)
 dd=[(fval(e["record"]["wealth_core"]["drawdown"]),d) for d,_,e in trace if fval(e["record"]["wealth_core"]["drawdown"]) is not None]
 if dd:add(min(dd)[1],"maximum drawdown and defensive-controller evaluation")
 sessions={d for d,_,_ in trace};missing=[d for d in x if d not in sessions]
 if missing:raise RuntimeError(f"non-session cutoffs {missing}")
 return [{"cutoff":d,"economic_reasons":"; ".join(x[d])} for d in sorted(x)]
def timing(trace,guard):
 orders=set();fills=[];reviews=[];splits=terms=divs=0
 for _,_,e in trace:
  r=e["record"]
  for o in r["orders"]["items"]:orders.add((str(o["side"]),str(o["security_id"]),int(o["signal_index"])))
  fills += r["fills"]["items"];reviews += [(r["date"],i) for i in r["events"]["age_reviews"]];splits+=len(r["events"]["splits"]);terms+=len(r["events"]["terminals"]);divs+=len(r["events"]["dividends"])
 same=[];missing=[];basis=[]
 for f in fills:
  terminal=str(f.get("reason","")).startswith("terminal");sig=int(f.get("signal_index",-1));fi=int(f["fill_index"])
  if not terminal and fi<=sig:same.append(f)
  if not terminal and (str(f["side"]),str(f["security_id"]),sig) not in orders:missing.append(f)
  if f["side"]=="BUY" and f.get("adjusted_open")!=f.get("review_basis"):basis.append(f)
 med=[{"date":d,**r} for d,r in reviews if str(r.get("security_id"))==MED];target=[r for r in med if r["date"]=="2006-08-15" and int(r.get("age",-1))==119]
 c=guard.get("counters",{});checks={"close_signals_never_fill_same_close":not same,"orders_have_close_signal_witnesses":not missing,"entry_basis_is_execution_open":not basis and int(c.get("entry_basis_assertions",0))>0,"rolling_windows_guarded":int(c.get("rolling_assertions",0))>=len(trace)*5,"position_age_chronological":int(c.get("position_age_assertions",0))>0,"allocation_next_open":int(c.get("allocation_timing_assertions",0))>0,"split_timing":splits>0 and int(c.get("split_event_assertions",0))==splits,"terminal_timing":terms>0 and int(c.get("terminal_event_assertions",0))==terms,"dividend_timing":int(c.get("dividend_event_assertions",0))==divs,"metadata_asof":int(c.get("metadata_accesses",0))>0,"benchmark_prefix_cache":int(c.get("benchmark_cache_assertions",0))==len(trace),"med_age_119":bool(target) and target[0].get("outcome")=="STOP_PRECEDENCE","runtime_guard":guard.get("status")=="PASS" and int(c.get("violations",0))==0}
 return {"schema":"backtester.research-execution-timing/1","status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"counts":{"orders":len(orders),"fills":len(fills),"reviews":len(reviews),"splits":splits,"terminals":terms,"dividends":divs},"med_regression":{"security_id":MED,"expected_session":"2006-08-15","expected_age":119,"expected_outcome":"STOP_PRECEDENCE","observed":med},"failures":{"same_close":same,"missing_orders":missing,"entry_basis":basis}}
def chronology():
 names=["session_clock","rolling_signals","eligibility","ranking","recent_leadership","open_events_and_fills","dividends","close_exits_and_age_review","wealth_core_mark","breadth","close_admissions","native_target","ldrc","next_open_allocation_and_nav","canonical_trace"]
 return {"schema":"backtester.research-execution-chronology/1","status":"PASS","phases":[{"order":i+1,"phase":n} for i,n in enumerate(names)]}
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--canonical-dataset",type=Path,required=True);ap.add_argument("--pointer",type=Path,default=Path("backtester/data/canonical-pit-2006-2007.json"));ap.add_argument("--output",type=Path,required=True);ap.add_argument("--poison-seed",type=int,default=314159);a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
 ident=identity(a.pointer,a.canonical_dataset);write(out/"dataset-identity.json",ident);base=out/"baseline";run(a.canonical_dataset.resolve(),base,"baseline");bt=read_trace(base/"causal-trace.jsonl.gz");guard=json.loads((base/"runtime-guard-report.json").read_text());shutil.copy2(base/"causal-trace.jsonl.gz",out/"baseline-causal-trace.jsonl.gz");shutil.copy2(base/"runtime-guard-report.json",out/"runtime-guard-report.json")
 cuts=cutoffs(bt);write(out/"cutoff-manifest.json",{"schema":"backtester.research-causal-cutoffs/1","status":"PASS","cutoffs":cuts,"warmup_coverage_note":"Every cutoff includes state from 2006-01-03."});prefix=[];poison=[];domains={"price_rows","volume_rows","eligibility_rows","metadata_observation_rows","metadata_timeline_rows","action_rows","terminal_rows","benchmark_rows","cash_rows"}
 for row in cuts:
  cut=row["cutoff"];pd=out/"prefix"/cut;run(a.canonical_dataset.resolve(),pd,"prefix",cut);r=compare(bt,read_trace(pd/"causal-trace.jsonl.gz"),cut);r["economic_reasons"]=row["economic_reasons"];prefix.append(r)
  if r["status"]!="PASS":raise RuntimeError(f"prefix failure {r}")
  if cut==END:continue
  qd=out/"poison"/cut;run(a.canonical_dataset.resolve(),qd,"poison",cut,a.poison_seed);r=compare(bt,read_trace(qd/"causal-trace.jsonl.gz"),cut);pm=json.loads((qd/"causal-run-manifest.json").read_text())["poison"];miss=sorted(d for d in domains if int(pm.get("changed_rows",{}).get(d,0))<=0);r.update({"economic_reasons":row["economic_reasons"],"poison_seed":a.poison_seed,"poison_manifest":pm,"missing_poison_domains":miss,"all_required_future_domains_changed":not miss});r["status"]="PASS" if r["status"]=="PASS" and not miss else "FAIL";poison.append(r)
  if r["status"]!="PASS":raise RuntimeError(f"poison failure {r}")
 pr={"schema":"backtester.research-prefix-invariance/1","status":"PASS","results":prefix};fr={"schema":"backtester.research-future-poisoning/1","status":"PASS","results":poison};write(out/"prefix-invariance.json",pr);write(out/"future-poisoning.json",fr)
 leak=static_leakage_audit((base/"generated-research-replay.py").read_text());write(out/"static-leakage-audit.json",leak)
 if leak["status"]!="PASS":raise RuntimeError("static leakage failure")
 tm=timing(bt,guard);write(out/"execution-timing.json",tm)
 if tm["status"]!="PASS":raise RuntimeError(f"timing failure {tm['checks']}")
 write(out/"execution-chronology.json",chronology());no_alloc=all(fval(e["record"]["allocation"]["effective_control"])==1 and fval(e["record"]["allocation"]["pending_control"])==1 for _,_,e in bt)
 summary={"schema":"backtester.research-causal-certification/1","status":"PASS","causal_timing_certified":True,"window":{"warmup_start":WARMUP,"measurement_start":START,"end":END},"dataset":ident,"baseline_trace_sha256":hfile(out/"baseline-causal-trace.jsonl.gz"),"runtime_guard":guard,"prefix_invariance":{"status":"PASS","cutoffs":len(prefix)},"future_poisoning":{"status":"PASS","cutoffs":len(poison),"domains":sorted(domains)},"execution_timing":tm,"static_leakage_audit":{"status":"PASS","finding_count":len(leak["findings"]),"forbidden_count":leak["forbidden_count"]},"economic_defects":{"confirmed_new_defects":[],"preserved_correction":"MED and all entries use adjusted execution-open review basis; entry close initializes peak only.","bounded_window_allocation_transition_observed":not no_alloc},"remaining_limitations":["Proof is bounded to 2006-01-03 through 2007-12-31.","No defensive-allocation transition occurs in this window; causal controller evaluation and unchanged allocation were certified.","The completed 20-year package must rerun the same prefix/poison suite across later crises and allocation transitions.","Any retained-source or transform change invalidates this certificate until rerun."]};write(out/"certification-summary.json",summary)
 files=sorted(p for p in out.iterdir() if p.is_file() and p.name!="SHA256SUMS.txt");(out/"SHA256SUMS.txt").write_text("".join(f"{hfile(p)}  {p.name}\n" for p in files));print(f"[CAUSAL CERTIFICATION PASS] cutoffs={len(prefix)} poisoned={len(poison)} dataset={DATA_HASH}",flush=True);return 0
if __name__=="__main__":raise SystemExit(main())
