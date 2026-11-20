"""Synthetic Alpaca SIP and OpenFIGI HTTP endpoints for isolated qualification."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs

from pydantic import BaseModel, Field

from sentinel.feed import calendar
from sentinel.feed.rolling_contract import CurrentFormationWindow, PriceWindow
from tools.acquisition_resources.profiles import SPECS


END = "2026-09-25"


class Profile(BaseModel):
    name: str
    securities: int = Field(gt=0)
    tickers: int = Field(gt=0)
    actions: int = Field(gt=0)
    formation: bool = True

    def window(self):
        return (CurrentFormationWindow if self.formation else PriceWindow).through(END)


PROFILES = {name: Profile(name=name, **spec) for name, spec in SPECS.items()}


@lru_cache(maxsize=256)
def sessions(first, last):
    return calendar.sessions_in_range(first, last)


def handler(profile, *, end=END, requests=None):
    counts = Counter()
    pay = calendar.previous_sessions(end, 3)[0]

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, path, payload):
            raw = json.dumps(payload, separators=(',', ':')).encode()
            counts[path] += 1
            if requests is not None:
                requests.append({'endpoint': path, 'method': self.command})
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_CONNECT(self):
            # A host-side financial account probe can never escape the fixture.
            self.send_error(403)

        def do_POST(self):
            if self.path != '/v3/mapping':
                self.send_error(404)
                return
            jobs = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if not 1 <= len(jobs) <= 100 or any(job['idType'] != 'TICKER' or job['exchCode'] != 'US' for job in jobs):
                self.send_error(400)
                return
            def result(symbol):
                admitted = symbol.startswith('S') and symbol[1:].isdigit() and int(symbol[1:]) < profile.securities
                kind = 'Common Stock' if admitted else 'ETF'
                return {'data': [{'ticker': symbol, 'exchCode': 'US', 'marketSector': 'Equity',
                    'compositeFIGI': 'C-' + symbol, 'shareClassFIGI': 'S-' + symbol,
                    'securityType': kind, 'securityType2': kind}]}
            self.send_json(self.path, [result(job['idValue']) for job in jobs])

        def do_GET(self):
            path, _, query = self.path.partition('?')
            q = {key: values[0] for key, values in parse_qs(query).items()}
            if path == '/metrics':
                self.send_json(path, dict(counts))
            elif path == '/v2/assets':
                self.send_json(path, [{'id': f'id-{i}', 'symbol': f'S{i:05}', 'name': f'Issuer {i}',
                    'exchange': 'NYSE', 'status': 'active', 'class': 'us_equity'} for i in range(profile.tickers)] +
                    [{'id': s, 'symbol': s, 'name': s, 'exchange': 'ARCA', 'status': 'active', 'class': 'us_equity'}
                     for s in ('BIL', 'SPY')])
            elif path == '/v2/stocks/bars':
                if q.get('feed') != 'sip' or q.get('adjustment') not in ('split', 'raw', 'all') or q.get('timeframe') != '1Day':
                    self.send_error(400)
                    return
                symbols = q['symbols'].split(',')
                days = sessions(q['start'][:10], q['end'][:10])
                size = len(days)
                first, last, token = self.page(q, len(symbols)*size)
                bars = {}
                for index in range(first, last):
                    symbol, day = symbols[index // size], days[index % size]
                    n = (date.fromisoformat(day) - date(2020, 1, 1)).days
                    price = round(100 + (0.001 if symbol == 'BIL' else 0.04)*n +
                                  (int(symbol[1:]) % 100 if symbol[1:].isdigit() else 0), 4)
                    bars.setdefault(symbol, []).append({'t': day+'T12:00:00Z', 'o': price,
                        'h': price, 'l': price, 'c': price, 'v': 1000000})
                self.send_json(path, {'bars': bars, 'next_page_token': token})
            elif path == '/v1/corporate-actions':
                first, last, token = self.page(q, profile.actions)
                # Stable facts across adjacent windows and query overlap. Only
                # one observed cash action applies to a selected ordinary stock.
                if not q['start'] <= pay <= q['end']:
                    first, last, token = 0, 0, None
                rows = [{'id': f'dividend-{i}', 'symbol': 'S00000' if not i else f'OTHER{i}',
                         'process_date': pay, 'ex_date': pay, 'payable_date': pay, 'rate': '0.01',
                         'foreign': False, 'currency': 'USD'} for i in range(first, last)]
                self.send_json(path, {'corporate_actions': {'cash_dividends': rows}, 'next_page_token': token})
            else:
                self.send_error(404)

        def page(self, query, count):
            first = int(query.get('page_token', '0'))
            last = min(count, first + int(query['limit']))
            return first, last, str(last) if last < count else None

        def log_message(self, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=PROFILES, required=True)
    args = parser.parse_args()
    ThreadingHTTPServer(('0.0.0.0', 8080), handler(PROFILES[args.profile])).serve_forever()


if __name__ == '__main__':
    main()
