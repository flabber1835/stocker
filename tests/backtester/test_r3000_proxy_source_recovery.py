import hashlib
from pathlib import Path
from backtester.r3000_proxy.source_recovery import parse_blackrock, parse_sec_nq

def test_blackrock_2007_geometry(seed: Path):
    for fund,count,sha in [
        ("IWB",1023,"634ca5d6a405d53362408b9dce03c407d4756423c9d56f49ab9615bf31aa14ba"),
        ("IWM",1953,"6a8dd2c8a3299b5dc0a8a319f1d26729ef64f2876066950526af32fb9fd93531")]:
        p=seed/"raw"/f"{fund}_20070629_product_data_v2.json"
        assert len(parse_blackrock(p,fund,"2007-06-29",sha))==count

def test_sec_missing_year_geometry(seed: Path):
    specs={2006:("0001193125-06-181552","2006-08-29",993,1995),2017:("0001193125-17-271743","2017-08-29",987,2012)}
    for year,(accession,filed,iwb,iwm) in specs.items():
        p=seed/"raw"/f"SEC_{year}_IWB_IWM_combined_N-Q.txt"; sha=hashlib.sha256(p.read_bytes()).hexdigest()
        assert len(parse_sec_nq(p,year,"IWB",sha,accession,filed))==iwb
        assert len(parse_sec_nq(p,year,"IWM",sha,accession,filed))==iwm
