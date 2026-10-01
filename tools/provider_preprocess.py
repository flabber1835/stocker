"""Offline, bounded-memory price-domain preprocessing; no trading or statistics."""
import csv
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from tools.provider_capture import CaptureError, datatable, encoded, save


def number(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise CaptureError('nonfinite or negative provider numeric field')
    return result


def sharadar_row(row):
    raw, signal = number(row['closeunadj']), number(row['close'])
    if not raw or not signal:
        raise CaptureError('zero price in Sharadar row')
    ratio = raw/signal
    return (row['ticker'], row['date'], str(number(row['open'])*ratio), str(raw),
            str(signal), str(number(row['volume'])/ratio), str(number(row['volume'])))


def preprocess(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_bytes())
    if manifest['status'] != 'COMPLETE':
        raise CaptureError('capture is incomplete; preprocessing cannot certify missing pages')
    axis = set(manifest['request']['sessions'])
    symbols = set(json.loads((root/'universe.json').read_bytes())['symbols'])
    save(root/'preprocessing.json', dict(status='INCOMPLETE'))
    for paths in manifest['files'].values():
        for path in paths:
            value = json.loads((root/path).read_bytes())
            if value['sha256'] != hashlib.sha256(encoded(value['response'])).hexdigest():
                raise CaptureError('raw response integrity failed before preprocessing')
    database = root/'preprocessing.partial.sqlite'
    # Rebuild only this script's scratch database; original capture is immutable.
    database.unlink(missing_ok=True)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute('CREATE TABLE bars(provider TEXT,ticker TEXT,session TEXT,raw_open TEXT,raw_close TEXT,'
                     'signal_close TEXT,raw_volume TEXT,adjusted_volume TEXT,PRIMARY KEY(provider,ticker,session))')
        for table in ('sep','sfp'):
            for row in datatable(root, manifest['files']['sharadar_'+table]):
                if row['date'] in axis and row['ticker'] in symbols:
                    conn.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)', ('sharadar', *sharadar_row(row)))
        conn.execute('CREATE TABLE splits(ticker TEXT,session TEXT,signal_close TEXT,volume TEXT,PRIMARY KEY(ticker,session))')
        for adjustment in ('raw','split'):
            for path in manifest['files']['alpaca_'+adjustment]:
                data = json.loads((root/path).read_bytes())['response']['bars']
                for ticker, rows in data.items():
                    if ticker not in symbols:
                        raise CaptureError('Alpaca returned an unrequested symbol')
                    for row in rows:
                        instant = datetime.fromisoformat(row['t'].replace('Z','+00:00'))
                        if instant.tzinfo is None:
                            raise CaptureError('Alpaca timestamp lacks timezone')
                        day = instant.astimezone(ZoneInfo('America/New_York')).date().isoformat()
                        if day not in axis:
                            raise CaptureError('Alpaca bar is outside requested XNYS axis')
                        if not number(row['c']) or (adjustment == 'raw' and not number(row['o'])):
                            raise CaptureError('zero price in Alpaca row')
                        if adjustment == 'raw':
                            conn.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)',
                                ('alpaca',ticker,day,str(number(row['o'])),str(number(row['c'])),
                                 None,str(number(row['v'])),None))
                        else:
                            conn.execute('INSERT INTO splits VALUES (?,?,?,?)',
                                (ticker,day,str(number(row['c'])),str(number(row['v']))))
        unmatched = conn.execute("SELECT count(*) FROM splits s LEFT JOIN bars b ON b.provider='alpaca' "
            'AND b.ticker=s.ticker AND b.session=s.session WHERE b.ticker IS NULL').fetchone()[0]
        missing = conn.execute("SELECT count(*) FROM bars b LEFT JOIN splits s ON b.ticker=s.ticker "
            "AND b.session=s.session WHERE b.provider='alpaca' AND s.ticker IS NULL").fetchone()[0]
        conn.execute("UPDATE bars SET signal_close=(SELECT signal_close FROM splits s WHERE s.ticker=bars.ticker "
                     "AND s.session=bars.session),adjusted_volume=(SELECT volume FROM splits s WHERE s.ticker=bars.ticker "
                     "AND s.session=bars.session) WHERE provider='alpaca'")
        columns = ['ticker','session','raw_open','raw_close','signal_close','raw_volume','adjusted_volume']
        counts = {}
        for provider in ('sharadar','alpaca'):
            path = root/(provider+'.csv.gz')
            temporary = path.with_suffix('.partial.gz')
            count = 0
            with gzip.open(temporary,'wt',newline='',encoding='utf-8') as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                for row in conn.execute('SELECT '+','.join(columns)+' FROM bars WHERE provider=? ORDER BY ticker,session',(provider,)):
                    writer.writerow(row)
                    count += 1
            temporary.replace(path)
            counts[provider] = count
        coverage = root/'coverage.csv'
        with coverage.open('w',newline='',encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['provider','ticker','sessions','first_session','last_session'])
            coverage = {(p,t):(count,lo,hi) for p,t,count,lo,hi in conn.execute(
                'SELECT provider,ticker,count(*),min(session),max(session) FROM bars GROUP BY provider,ticker')}
            for provider in ('sharadar','alpaca'):
                for ticker in sorted(symbols):
                    writer.writerow((provider,ticker,*coverage.get((provider,ticker),(0,'',''))))
    database.unlink()
    save(root/'preprocessing.json', dict(schema='sentinel.provider-comparison-preprocessing/1', rows=counts,
        status='COMPLETE_WITH_GAPS' if unmatched or missing else 'COMPLETE',
        alpaca_raw_without_split=missing, alpaca_split_without_raw=unmatched,
        identity_equivalence='NOT_ESTABLISHED', source_vintage_causality='NOT_PROVEN',
        adjustment_basis='PROVIDER_NATIVE_SPLIT_ONLY', production_authority=False))
