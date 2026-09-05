from __future__ import annotations

import argparse, csv, gzip, hashlib, html, json, re, shutil
from pathlib import Path

SEED_RUN_ID = 33820201471
SEED_HEAD = "403527ea3b245481a4d80ae3dab0a03e95d5bf8d"
SEED_ARTIFACT_SHA256 = "d32630ab939344e5b018dafdaf8314cc2ce175aafeb057e671d74ffcdf9185f2"
REGISTRANT = "iShares Trust"
REGISTRANT_CIK = "0001100663"
PARSER_VERSION = "r3000-proxy-source-parser/1"
CAVEAT = "This is an IWB/IWM-derived Russell 3000 proxy and is not a licensed FTSE Russell constituent history."

FIELDS = [
    "snapshot_date","holdings_effective_date","source_publication_date","available_to_model_date",
    "fund","source_type","source_id","source_sha256","source_row_number","reported_ticker",
    "reported_issuer_name","reported_cusip","reported_isin","reported_asset_class","reported_shares",
    "reported_market_value","reported_weight","currency","normalized_security_id",
    "normalized_ticker_on_snapshot_date","normalized_issuer_id","identity_authority","identity_status",
    "identity_evidence_refs"
]

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def _dp(payload, key):
    d=payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]["dataPointsByNameMap"][key]
    v=d.get("formattedValue")
    return v if isinstance(v,list) else d.get("value")

def parse_blackrock(path: Path, fund: str, effective_date: str, source_sha: str):
    j=json.load(path.open())
    keys=["ticker","issueName","cusip","isin","assetClass","unitsHeld","marketValue","holdingPercent","currencyCode"]
    vals={k:_dp(j,k) for k in keys}
    n=len(vals["ticker"])
    if any(not isinstance(vals[k],list) or len(vals[k]) != n for k in keys):
        raise ValueError(f"unaligned BlackRock holdings arrays: {path}")
    rows=[]
    for i in range(n):
        if str(vals["assetClass"][i]).strip().lower() != "equity" or str(vals["ticker"][i]).strip() in ("", "-"): continue
        def norm(v): return "" if v in (None,"-") else str(v).strip()
        rows.append({
            "snapshot_date":effective_date,"holdings_effective_date":effective_date,
            "source_publication_date":"","available_to_model_date":"",
            "fund":fund,"source_type":"blackrock_product_data_v2",
            "source_id":path.name,"source_sha256":source_sha,"source_row_number":i+1,
            "reported_ticker":norm(vals["ticker"][i]),"reported_issuer_name":norm(vals["issueName"][i]),
            "reported_cusip":norm(vals["cusip"][i]),"reported_isin":norm(vals["isin"][i]),
            "reported_asset_class":"Equity","reported_shares":norm(vals["unitsHeld"][i]),
            "reported_market_value":norm(vals["marketValue"][i]),"reported_weight":norm(vals["holdingPercent"][i]),
            "currency":norm(vals["currencyCode"][i]),"normalized_security_id":"",
            "normalized_ticker_on_snapshot_date":"","normalized_issuer_id":"","identity_authority":"",
            "identity_status":"UNRESOLVED","identity_evidence_refs":""
        })
    return rows

def _clean(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",fragment,flags=re.I|re.S)).replace("\xa0"," ").split())

def _number(s: str):
    t=s.replace("$","").replace(",","").replace("(","-").replace(")","").strip()
    try: return float(t)
    except ValueError: return None

def _sec_bounds(text: str, year: int, fund: str):
    u=text.upper()
    if year == 2006:
        target = "RUSSELL 1000 INDEX FUND" if fund=="IWB" else "RUSSELL 2000 INDEX FUND"
        nxt = "RUSSELL 1000 GROWTH" if fund=="IWB" else "RUSSELL 2000 GROWTH"
    elif year == 2017:
        target = "RUSSELL 1000 ETF" if fund=="IWB" else "RUSSELL 2000 ETF"
        nxt = "RUSSELL 1000 GROWTH" if fund=="IWB" else "RUSSELL 2000 GROWTH"
    else: raise ValueError(year)
    p=u.find(target, 200000 if year==2006 else 1000000)
    if p < 0: raise ValueError(f"target fund schedule missing: {year} {fund}")
    start=u.rfind("SCHEDULE OF INVESTMENTS",0,p)
    q=u.find(nxt,p+len(target))
    if q < 0: raise ValueError(f"next fund boundary missing: {year} {fund}")
    end=u.rfind("SCHEDULE OF INVESTMENTS",p,q)
    if start < 0 or end <= start: raise ValueError(f"invalid SEC bounds: {year} {fund}")
    return start,end

def parse_sec_nq(path: Path, year: int, fund: str, source_sha: str, accession: str, filed: str):
    text=path.read_text(encoding="utf-8",errors="ignore")
    start,end=_sec_bounds(text,year,fund)
    segment=text[start:end]
    equity=False; rows=[]
    for source_row,tr in enumerate(re.findall(r"<TR\b.*?</TR>",segment,flags=re.I|re.S),1):
        cells=[_clean(c) for c in re.findall(r"<TD\b.*?</TD>",tr,flags=re.I|re.S)]
        cells=[c for c in cells if c and c != "$"]
        joined=" ".join(cells).upper()
        if joined.startswith("COMMON STOCK") and len(cells)<=3:
            if not joined.startswith("TOTAL"): equity=True
            continue
        if equity and len(cells)<=3 and joined.startswith(("SHORT-TERM INVEST","MONEY MARKET FUND","PREFERRED STOCK","WARRANTS","RIGHTS —","RIGHTS—","FUTURES CONTRACT","REPURCHASE AGREEMENT")):
            equity=False; continue
        if not equity or len(cells)<3: continue
        name=cells[0]
        nums=[_number(c) for c in cells[1:]]; nums=[v for v in nums if v is not None]
        if len(nums)<2: continue
        if name.upper().startswith(("TOTAL ","NET ASSETS","OTHER ASSETS","LIABILITIES")): continue
        if re.match(r"^\d+(?:\.\d+)?%[, -]",name): continue
        rows.append({
            "snapshot_date":f"{year}-06-30","holdings_effective_date":f"{year}-06-30",
            "source_publication_date":filed,"available_to_model_date":filed,
            "fund":fund,"source_type":"sec_n-q","source_id":accession,"source_sha256":source_sha,
            "source_row_number":source_row,"reported_ticker":"","reported_issuer_name":name,
            "reported_cusip":"","reported_isin":"","reported_asset_class":"Common Stock",
            "reported_shares":str(int(nums[-2])) if nums[-2].is_integer() else str(nums[-2]),
            "reported_market_value":str(int(nums[-1])) if nums[-1].is_integer() else str(nums[-1]),
            "reported_weight":"","currency":"USD","normalized_security_id":"",
            "normalized_ticker_on_snapshot_date":"","normalized_issuer_id":"","identity_authority":"",
            "identity_status":"UNRESOLVED","identity_evidence_refs":""
        })
    return rows

def write_csv_gz(path: Path, rows):
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            import io
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as fh:
                w=csv.DictWriter(fh,fieldnames=FIELDS,lineterminator="\n"); w.writeheader(); w.writerows(rows)

def recover(seed: Path, out: Path):
    out.mkdir(parents=True,exist_ok=True); raw_out=out/"raw"; raw_out.mkdir(exist_ok=True)
    summary=json.load((seed/"summary.json").open())
    if summary["years_requested"] != 21 or not summary["all_source_years_retrieved"]: raise ValueError("seed source coverage incomplete")
    manifest=list(csv.DictReader((seed/"retrieval_manifest.csv").open(newline="")))
    if len(manifest)!=21: raise ValueError("expected 21 retrieval manifest years")
    all_rows=[]; source_files=[]; snapshots=[]
    for row in manifest:
        year=int(row["year"])
        if row["rows_pair_status"]=="PASS":
            for fund in ("IWB","IWM"):
                date=row[f"{fund.lower()}_source_date"]
                expected=row[f"{fund.lower()}_sha256"]
                p=seed/"raw"/f"{fund}_{date.replace('-','')}_product_data_v2.json"
                actual=sha256(p)
                if actual!=expected: raise ValueError(f"source digest mismatch: {p.name}")
                parsed=parse_blackrock(p,fund,date,actual)
                expected_count=int(row[f"{fund.lower()}_equity_rows"])
                if len(parsed)!=expected_count: raise ValueError(f"equity row count mismatch: {year} {fund} {len(parsed)} != {expected_count}")
                shutil.copyfile(p,raw_out/p.name)
                source_files.append({"path":f"raw/{p.name}","sha256":actual,"source_type":"blackrock_product_data_v2","year":year,"fund":fund})
                snapshots.append({"year":year,"fund":fund,"holdings_effective_date":date,"source_publication_date":"","available_to_model_date":"","source_type":"blackrock_product_data_v2","source_id":p.name,"source_sha256":actual,"equity_row_count":len(parsed),"information_available_status":"UNPROVEN_ARCHIVAL_PUBLICATION_DATE"})
                all_rows.extend(parsed)
        else:
            sec={2006:("0001193125-06-181552","2006-08-29"),2017:("0001193125-17-271743","2017-08-29")}
            if year not in sec: raise ValueError(f"unexpected missing direct year {year}")
            accession,filed=sec[year]; p=seed/"raw"/f"SEC_{year}_IWB_IWM_combined_N-Q.txt"; actual=sha256(p)
            shutil.copyfile(p,raw_out/p.name)
            source_files.append({"path":f"raw/{p.name}","sha256":actual,"source_type":"sec_n-q","year":year,"fund":"IWB+IWM"})
            for fund in ("IWB","IWM"):
                parsed=parse_sec_nq(p,year,fund,actual,accession,filed)
                snapshots.append({"year":year,"fund":fund,"holdings_effective_date":f"{year}-06-30","source_publication_date":filed,"available_to_model_date":filed,"source_type":"sec_n-q","source_id":accession,"source_sha256":actual,"equity_row_count":len(parsed),"information_available_status":"AVAILABLE_FROM_SEC_FILING_DATE"})
                all_rows.extend(parsed)
    counts={(int(x["year"]),x["fund"]):int(x["equity_row_count"]) for x in snapshots}
    for key,expected in { (2006,"IWB"):993,(2006,"IWM"):1995,(2017,"IWB"):987,(2017,"IWM"):2012}.items():
        if counts[key]!=expected: raise ValueError(f"SEC parser regression {key}: {counts[key]} != {expected}")
    write_csv_gz(out/"parsed_holdings.csv.gz",all_rows)
    with (out/"source_snapshot_manifest.csv").open("w",newline="",encoding="utf-8") as fh:
        cols=list(snapshots[0]); w=csv.DictWriter(fh,fieldnames=cols,lineterminator="\n");w.writeheader();w.writerows(snapshots)
    raw_manifest={"schema":"stocker.r3000-proxy.raw-source-manifest/1","corpus_id":"r3000-proxy-pit-2006-2026-v1","seed_run_id":SEED_RUN_ID,"seed_head_sha":SEED_HEAD,"seed_artifact_sha256":SEED_ARTIFACT_SHA256,"parser_version":PARSER_VERSION,"source_files":source_files,"caveat":CAVEAT}
    (out/"raw_source_manifest.json").write_text(json.dumps(raw_manifest,sort_keys=True,indent=2)+"\n")
    stage={"schema":"stocker.r3000-proxy.source-recovery-summary/1","status":"PASS","years_source_covered":21,"fund_snapshots":42,"blackrock_fund_snapshots":38,"sec_fund_snapshots":4,"parsed_equity_rows":len(all_rows),"sec_counts":{"2006":{"IWB":993,"IWM":1995},"2017":{"IWB":987,"IWM":2012}},"historical_state_proxy_source_coverage":"PASS","information_available_proxy_source_coverage":"INCOMPLETE_ARCHIVAL_PUBLICATION_AUTHORITY","identity_stage":"NOT_STARTED","caveat":CAVEAT}
    (out/"summary.json").write_text(json.dumps(stage,sort_keys=True,indent=2)+"\n")
    files=[p for p in out.rglob("*") if p.is_file() and p.name!="SHA256SUMS.txt"]
    lines=[f"{sha256(p)}  {p.relative_to(out).as_posix()}" for p in sorted(files)]
    (out/"SHA256SUMS.txt").write_text("\n".join(lines)+"\n")
    return stage

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--seed",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args()
    print(json.dumps(recover(a.seed,a.output),indent=2,sort_keys=True))
if __name__=="__main__": main()
