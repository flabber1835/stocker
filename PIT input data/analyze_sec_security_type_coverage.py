#!/usr/bin/env python3
from __future__ import annotations
import csv,gzip,io,json,re,zipfile
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SEC_DIR=ROOT/'sec'; PIT_DIR=ROOT/'PIT input data'; TICKERS_ZIP=ROOT/'sharadar'/'SHARADAR_TICKERS.zip'
BUYS=ROOT/'research'/'sentinel-fastgate'/'experiments'/'2026-08-25-pit-vs-full-c'/'recovered'/'terminal_issuer_corrected'/'output'/'executed_buys.csv'
COMMON_PATTERNS=[re.compile(r'\bcommon\s+(stock|shares?)\b',re.I),re.compile(r'\bclass\s+[a-z0-9]+\s+common\b',re.I),re.compile(r'\bordinary\s+shares?\b',re.I),re.compile(r'\bordinary\s+stock\b',re.I)]
EXCLUDE_PATTERNS=[re.compile(x,re.I) for x in [r'preferred',r'warrant',r'option',r'restricted\s+stock\s+unit|\brsu\b',r'phantom',r'convertible']]
def norm(s): return (s or '').strip()
def pick(headers,names):
 c={re.sub(r'[^a-z0-9]','',h.lower()):h for h in headers}
 for n in names:
  k=re.sub(r'[^a-z0-9]','',n.lower())
  if k in c:return c[k]
def parse_table(raw):
 text=raw.decode('utf-8-sig',errors='replace'); first=text.splitlines()[0] if text else ''
 return csv.DictReader(io.StringIO(text),delimiter='\t' if first.count('\t')>=first.count(',') else ',')
def classify_title(title): return bool(title) and not any(p.search(title) for p in EXCLUDE_PATTERNS) and any(p.search(title) for p in COMMON_PATTERNS)
def load_legacy_tickers():
 with zipfile.ZipFile(TICKERS_ZIP) as z:
  names=z.namelist(); target=next(n for n in names if 'tickers' in Path(n).name.lower() and Path(n).suffix.lower() in {'.csv','.tsv'})
  r=parse_table(z.read(target)); out={}
  for row in r:
   t=norm(row.get('ticker')); cat=norm(row.get('category'))
   if t: out[t]=cat
  return out
def load_executed_buys():
 if not BUYS.exists(): return []
 with BUYS.open(newline='',encoding='utf-8') as f:
  r=csv.DictReader(f); rows=[]
  for row in r:
   t=norm(row.get('ticker')); d=norm(row.get('date') or row.get('session') or row.get('entry_date'))
   if t: rows.append((t,d))
  return rows
def main():
 zips=sorted(SEC_DIR.glob('*_form345.zip'))
 if not zips: raise SystemExit('No SEC Form 3/4/5 archives found')
 title_counter=Counter(); evidence=[]; first_common={}; archive_stats=[]
 for zp in zips:
  quarter=zp.stem.replace('_form345','')
  with zipfile.ZipFile(zp) as z:
   members=z.namelist(); local_meta={}
   for m in members:
    if 'submission' not in Path(m).name.lower(): continue
    r=parse_table(z.read(m)); h=r.fieldnames or []
    a=pick(h,['accession_number','accessionnumber','accession']); fd=pick(h,['filing_date','filingdate','filed']); sy=pick(h,['issuer_trading_symbol','issuertradingsymbol','issuersymbol']); cik=pick(h,['issuer_cik','issuercik'])
    if not(a and fd and sy): continue
    for row in r:
     acc=norm(row.get(a)); sym=norm(row.get(sy)).upper(); filed=norm(row.get(fd)); c=norm(row.get(cik)) if cik else ''
     if acc and sym and filed: local_meta[acc]=(filed,sym,c)
   q_titles=q_joined=q_common=0
   for m in members:
    base=Path(m).name.lower()
    if not('nonderiv' in base or 'non_deriv' in base or 'non-deriv' in base): continue
    r=parse_table(z.read(m)); h=r.fieldnames or []
    a=pick(h,['accession_number','accessionnumber','accession']); st=pick(h,['security_title','securitytitle','security_title_value','securitytitlevalue'])
    if not(a and st): continue
    for row in r:
     acc=norm(row.get(a)); title=norm(row.get(st))
     if not title: continue
     q_titles+=1; title_counter[title]+=1; meta=local_meta.get(acc)
     if not meta: continue
     q_joined+=1; filed,sym,cik=meta
     if classify_title(title):
      q_common+=1; prev=first_common.get(sym)
      if prev is None or filed<prev[0]: first_common[sym]=(filed,title,cik,quarter)
      evidence.append((sym,filed,cik,title,quarter,acc))
   archive_stats.append({'quarter':quarter,'members':len(members),'submission_rows':len(local_meta),'security_title_rows':q_titles,'joined_title_rows':q_joined,'positive_common_rows':q_common})
 legacy=load_legacy_tickers(); legacy_common={t for t,cat in legacy.items() if 'common stock' in cat.lower() and 'warrant' not in cat.lower() and 'preferred' not in cat.lower()}
 evidence_tickers=set(first_common); common_covered=legacy_common&evidence_tickers
 buys=load_executed_buys(); buy_tickers={t for t,_ in buys}; buy_any=buy_tickers&evidence_tickers; causal=0; dated=0; gaps=[]
 for t,d in buys:
  if not d: continue
  dated+=1; ev=first_common.get(t)
  if ev and ev[0]<d: causal+=1
  else: gaps.append((t,d,ev[0] if ev else ''))
 with gzip.open(PIT_DIR/'SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz','wt',newline='',encoding='utf-8') as f:
  w=csv.writer(f); w.writerow(['ticker','filed','cik','security_title','source_quarter','accession']); w.writerows(sorted(evidence,key=lambda x:(x[0],x[1],x[5])))
 with (PIT_DIR/'SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.writer(f); w.writerow(['ticker','buy_date','first_positive_common_filing']); w.writerows(sorted(gaps))
 report={'archives':len(zips),'archive_range':[zips[0].name,zips[-1].name],'distinct_positive_common_tickers':len(evidence_tickers),'legacy_common_tickers':len(legacy_common),'legacy_common_ticker_coverage':len(common_covered),'legacy_common_ticker_coverage_pct':len(common_covered)/len(legacy_common) if legacy_common else None,'executed_buy_tickers':len(buy_tickers),'executed_buy_tickers_with_any_positive_evidence':len(buy_any),'executed_buy_ticker_coverage_pct':len(buy_any)/len(buy_tickers) if buy_tickers else None,'executed_buy_rows_with_dates':dated,'executed_buy_rows_causally_covered_before_buy':causal,'executed_buy_row_causal_coverage_pct':causal/dated if dated else None,'executed_buy_rows_not_causally_covered':len(gaps),'top_security_titles':title_counter.most_common(100),'archive_stats':archive_stats,'classification_rule':{'positive_only':True,'rule':'A symbol becomes common-stock-eligible only after a filed Form 3/4/5 non-derivative security title positively matches common/ordinary equity and matches the submission issuer trading symbol. Negative instrument titles do not classify the issuer symbol as non-common.','decision_cutoff':'evidence filing date must be strictly earlier than decision/buy date','unknown_policy':'unknown remains ineligible'}}
 (PIT_DIR/'SEC_SECURITY_TYPE_COVERAGE.json').write_text(json.dumps(report,indent=2)+'\n')
 pct=lambda x:'n/a' if x is None else f'{x:.2%}'
 md=['# Orion SEC security-type coverage analysis','',f"Archives inspected: **{len(zips)}** ({zips[0].name} through {zips[-1].name}).",'','## Coverage','',f"- Positive common-stock symbols from Form 3/4/5 security-title evidence: **{len(evidence_tickers):,}**",f"- Legacy Sharadar common-stock symbols: **{len(legacy_common):,}**",f"- Legacy common-stock ticker coverage: **{len(common_covered):,}/{len(legacy_common):,} ({pct(report['legacy_common_ticker_coverage_pct'])})**",f"- Authoritative executed-buy tickers with any positive evidence: **{len(buy_any):,}/{len(buy_tickers):,} ({pct(report['executed_buy_ticker_coverage_pct'])})**",f"- Executed-buy rows causally covered before buy date: **{causal:,}/{dated:,} ({pct(report['executed_buy_row_causal_coverage_pct'])})**",f"- Executed-buy rows lacking prior positive evidence: **{len(gaps):,}**",'','## PIT rule','','A ticker becomes eligible as common stock only after an SEC filing whose issuer trading symbol matches the ticker and whose non-derivative security title positively identifies common/ordinary equity. Preferred, warrant, option, RSU, phantom, and convertible titles are not positive evidence. Absence of evidence is **unknown/ineligible**. Filing-date evidence must be strictly earlier than the Orion decision session.','','## Interpretation','','This is a coverage diagnostic, not yet a certification. Form 3/4/5 security titles can provide causal positive evidence, but final use depends on whether candidate/session coverage is sufficiently complete. Executed-buy coverage is the first economic materiality gate; full candidate/session coverage remains the promotion gate.']
 (PIT_DIR/'SEC_SECURITY_TYPE_COVERAGE.md').write_text('\n'.join(md)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in {'top_security_titles','archive_stats'}},indent=2))
if __name__=='__main__': main()
