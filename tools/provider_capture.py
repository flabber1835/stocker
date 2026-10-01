"""GET-only, resumable Sharadar/Alpaca capture. No production or broker writes.

python -m tools.provider_capture --end 2026-09-29 --output /data/comparison
python -m tools.provider_capture --output /data/comparison --preprocess-only
Credentials: SHARADAR_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY (environment).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sentinel.feed import calendar

DATA = 'https://data.alpaca.markets'
ASSETS = 'https://paper-api.alpaca.markets/v2/assets'
NASDAQ = 'https://data.nasdaq.com/api/v3/datatables/SHARADAR/'
MAX_BYTES = 32 * 1024 * 1024


class CaptureError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Response:
    def __init__(self, response):
        self.response = response
        self.status_code = response.code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.response.close()

    def iter_content(self, size):
        while chunk := self.response.read(size):
            yield chunk


class _Transport:
    def get(self, url, *, params, headers, timeout, **kwargs):
        request = Request(url+'?'+urlencode(params), headers=headers, method='GET')
        try:
            response = build_opener(_NoRedirect()).open(request, timeout=timeout[1])
        except HTTPError as exc:
            response = exc
        return _Response(response)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


class Capture:
    def __init__(self, root, *, transport=None):
        self.root = Path(root)
        self.transport = transport or _Transport()

    def page(self, provider, url, params):
        # Only fixed provider endpoints; credentials never enter the cache key,
        # request manifest, error message or original-response file.
        if not ((provider == 'sharadar' and url in tuple(NASDAQ+t+'.json' for t in ('SEP','SFP','TICKERS','ACTIONS')))
                or (provider == 'alpaca' and url in (ASSETS, DATA+'/v2/stocks/bars', DATA+'/v1/corporate-actions'))):
            raise CaptureError('unsupported provider endpoint')
        request = dict(provider=provider, url=url, params=params)
        key = hashlib.sha256(encoded(request)).hexdigest()
        path = self.root/'raw'/provider/(key+'.json')
        if path.exists():
            retained = json.loads(path.read_bytes())
            if (retained['request'] != request
                    or retained['sha256'] != hashlib.sha256(encoded(retained['response'])).hexdigest()):
                raise CaptureError('retained response failed integrity check')
            return retained['response'], str(path.relative_to(self.root))
        query, headers = dict(params), {}
        if provider == 'sharadar':
            key_value = os.environ.get('SHARADAR_API_KEY', '').strip()
            if not key_value:
                raise CaptureError('SHARADAR_API_KEY is missing')
            query['api_key'] = key_value
        else:
            key_value = os.environ.get('ALPACA_API_KEY', os.environ.get('APCA_API_KEY_ID', '')).strip()
            secret = os.environ.get('ALPACA_SECRET_KEY', os.environ.get('APCA_API_SECRET_KEY', '')).strip()
            if not key_value or not secret:
                raise CaptureError('Alpaca environment credentials are missing')
            headers = {'APCA-API-KEY-ID':key_value, 'APCA-API-SECRET-KEY':secret}
        for attempt in range(5):
            retry = False
            try:
                with self.transport.get(url, params=query, headers=headers, timeout=(10, 60),
                                        stream=True, allow_redirects=False) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        retry = True
                    elif response.status_code != 200:
                        raise CaptureError(f'{provider} HTTP {response.status_code}; response body withheld')
                    else:
                        chunks, size = [], 0
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise CaptureError('provider response exceeded 32 MiB')
                            chunks.append(chunk)
                        try:
                            value = json.loads(b''.join(chunks))
                        except (ValueError, UnicodeError):
                            raise CaptureError('provider returned invalid JSON') from None
                        save(path, dict(request=request, acquired_at=datetime.now(timezone.utc).isoformat(),
                            sha256=hashlib.sha256(encoded(value)).hexdigest(), response=value))
                        time.sleep(.35)  # Stay below Basic Alpaca's 200 requests/minute.
                        return value, str(path.relative_to(self.root))
            except (URLError, OSError):
                retry = True
            if retry:
                time.sleep(min(2**attempt, 16))
        raise CaptureError(f'{provider} retry budget exhausted; rerun to resume completed pages')

    def pages(self, provider, url, params, *, kind):
        token, seen, files = None, set(), []
        for _ in range(10000):
            query = dict(params)
            if token:
                query['qopts.cursor_id' if provider == 'sharadar' else 'page_token'] = token
            value, path = self.page(provider, url, query)
            files.append(path)
            if provider == 'sharadar':
                if not isinstance(value.get('datatable', {}).get('data'), list):
                    raise CaptureError('Sharadar datatable absent')
                token = value.get('meta', {}).get('next_cursor_id')
            else:
                if not isinstance(value.get(kind), dict):
                    raise CaptureError(f'Alpaca {kind} response absent')
                token = value.get('next_page_token')
            print(f'{provider} {kind}: page {len(files)} retained', flush=True)
            if not token:
                return files
            if not isinstance(token, str) or token in seen:
                raise CaptureError('provider pagination repeated or invalid')
            seen.add(token)
        raise CaptureError('provider pagination exceeded bound')


def datatable(root, paths):
    for path in paths:
        value = json.loads((root/path).read_bytes())['response']['datatable']
        columns = [c['name'] for c in value['columns']]
        for row in value['data']:
            if len(row) != len(columns):
                raise CaptureError('datatable row width differs')
            yield dict(zip(columns, row))


def acquire(root, *, end):
    axis = calendar.previous_sessions(end, 300)
    if len(axis) != 300 or axis[-1] != end:
        raise CaptureError('end must be an XNYS session with 300-session coverage')
    capture = Capture(root)
    specification = dict(schema='sentinel.provider-comparison-request/1', sessions=axis,
        scope='CURRENT_UNIVERSE_UNION', alpaca_feed='sip', alpaca_asof=end,
        price_adjustments=['raw', 'split'], purpose='OFFLINE_COMPARISON_ONLY')
    request_path = root/'request.json'
    if request_path.exists() and json.loads(request_path.read_bytes()) != specification:
        raise CaptureError('output belongs to a different request; choose a new directory')
    save(request_path, specification)
    manifest = dict(request=specification, status='INCOMPLETE', files={})
    save(root/'manifest.json', manifest)
    assets, asset_path = capture.page('alpaca', ASSETS, {'status':'active', 'asset_class':'us_equity'})
    if not isinstance(assets, list) or not assets:
        raise CaptureError('Alpaca asset universe is empty or malformed')
    manifest['files']['alpaca_assets'] = [asset_path]
    tickers = capture.pages('sharadar', NASDAQ+'TICKERS.json',
        {'table':'SEP', 'qopts.per_page':10000}, kind='tickers')
    manifest['files']['sharadar_tickers'] = tickers
    listed = list(datatable(root, tickers))
    symbols = sorted({r['symbol'] for r in assets} | {r['ticker'] for r in listed
        if r.get('isdelisted') == 'N'} | {'SPY','BIL'})
    save(root/'universe.json', dict(symbols=symbols, count=len(symbols),
        identity_equivalence='NOT_ESTABLISHED', metadata='CURRENT_INFORMATION'))
    bounds = {'date.gte':axis[0], 'date.lte':end, 'qopts.per_page':10000}
    for table, extra in [('SEP',{}), ('SFP',{'ticker':'SPY,BIL'}), ('ACTIONS',{})]:
        manifest['files']['sharadar_'+table.lower()] = capture.pages(
            'sharadar', NASDAQ+table+'.json', {**bounds, **extra}, kind=table)
        save(root/'manifest.json', manifest)
    for adjustment in ('raw','split'):
        files = []
        for offset in range(0,len(symbols),100):
            params = dict(symbols=','.join(symbols[offset:offset+100]), timeframe='1Day',
                start=datetime.fromisoformat(axis[0]+'T00:00:00').replace(tzinfo=ZoneInfo('America/New_York')).isoformat(),
                end=datetime.fromisoformat(end+'T23:59:59').replace(tzinfo=ZoneInfo('America/New_York')).isoformat(),
                limit=10000, feed='sip', adjustment=adjustment, asof=end, sort='asc')
            files.extend(capture.pages('alpaca', DATA+'/v2/stocks/bars', params, kind='bars'))
        manifest['files']['alpaca_'+adjustment] = files
        save(root/'manifest.json', manifest)
    # Capture all announcements within the interval, including incomplete ones.
    manifest['files']['alpaca_actions'] = capture.pages('alpaca', DATA+'/v1/corporate-actions',
        dict(start=axis[0], end=end, limit=1000, data_quality='all', sort='asc'), kind='corporate_actions')
    manifest.update(status='COMPLETE', completed_at=datetime.now(timezone.utc).isoformat())
    save(root/'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--end')
    parser.add_argument('--preprocess-only', action='store_true')
    args = parser.parse_args()
    try:
        if not args.preprocess_only:
            if not args.end:
                parser.error('--end is required for download')
            acquire(args.output, end=args.end)
        from tools.provider_preprocess import preprocess
        preprocess(args.output)
    except Exception as exc:
        # Provider exceptions can contain credential-bearing request URLs.
        message = str(exc) if isinstance(exc, CaptureError) else type(exc).__name__
        print('INCOMPLETE: '+message, flush=True)
        return 1
    print('COMPLETE: '+str(args.output), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
