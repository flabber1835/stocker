#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIT = ROOT / 'PIT input data'
TICKERS_ZIP = ROOT / 'sharadar' / 'SHARADAR_TICKERS.zip'
GAPS = PIT / 'SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv'
OUT = PIT / 'SEC_SECURITY_TYPE_GAP_TICKERS_METADATA.csv'


def parse(raw: bytes):
    text = raw.decode('utf-8-sig', errors='replace')
    first = text.splitlines()[0] if text else ''
    return csv.DictReader(io.StringIO(text), delimiter='\t' if first.count('\t') >= first.count(',') else ',')


def toks(value: str):
    return {x.upper() for x in re.split(r'[\s,;]+', (value or '').strip()) if x}


def main():
    with GAPS.open(newline='', encoding='utf-8-sig') as f:
        gap_rows = list(csv.DictReader(f))
    gaps = {r['ticker'].strip().upper() for r in gap_rows}

    with zipfile.ZipFile(TICKERS_ZIP) as z:
        name = next(n for n in z.namelist() if 'tickers' in Path(n).name.lower() and Path(n).suffix.lower() in {'.csv', '.tsv'})
        reader = parse(z.read(name))
        rows = list(reader)
        headers = list(reader.fieldnames or [])

    by_ticker = {str(r.get('ticker') or '').strip().upper(): r for r in rows if str(r.get('ticker') or '').strip()}
    seeds = [by_ticker[t] for t in gaps if t in by_ticker]
    seed_permatickers = {str(r.get('permaticker') or '').strip() for r in seeds if str(r.get('permaticker') or '').strip()}
    aliases = set(gaps)
    for r in seeds:
        aliases |= toks(str(r.get('relatedtickers') or ''))
        t = str(r.get('ticker') or '').strip().upper()
        if t:
            aliases.add(t)

    # Close transitively over related tickers and permaticker so renamed/delisted aliases are visible.
    changed = True
    selected = []
    while changed:
        changed = False
        selected = []
        for r in rows:
            t = str(r.get('ticker') or '').strip().upper()
            p = str(r.get('permaticker') or '').strip()
            rt = toks(str(r.get('relatedtickers') or ''))
            if t in aliases or (p and p in seed_permatickers) or bool(rt & aliases):
                selected.append(r)
                before = len(aliases)
                if t:
                    aliases.add(t)
                aliases |= rt
                if p:
                    seed_permatickers.add(p)
                changed |= len(aliases) != before

    preferred = [
        'ticker','name','category','isdelisted','exchange','location','currency','permaticker',
        'cusips','siccode','sicsector','sicindustry','famasector','famaindustry','sector','industry',
        'relatedtickers','firstadded','firstpricedate','lastpricedate','firstquarter','lastquarter','lastupdated',
        'secfilings','companysite'
    ]
    fields = ['gap_ticker'] + [h for h in preferred if h in headers] + [h for h in headers if h not in preferred]
    fields = list(dict.fromkeys(fields))

    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in sorted(selected, key=lambda x: (str(x.get('permaticker') or ''), str(x.get('ticker') or ''))):
            t = str(r.get('ticker') or '').strip().upper()
            rt = toks(str(r.get('relatedtickers') or ''))
            p = str(r.get('permaticker') or '').strip()
            matches = sorted(g for g in gaps if g == t or g in rt or (g in by_ticker and str(by_ticker[g].get('permaticker') or '').strip() == p))
            row = dict(r)
            row['gap_ticker'] = '|'.join(matches)
            w.writerow(row)

    print(f'gaps={len(gaps)} seed_rows={len(seeds)} selected_rows={len(selected)} aliases={len(aliases)}')
    print(OUT)


if __name__ == '__main__':
    main()
