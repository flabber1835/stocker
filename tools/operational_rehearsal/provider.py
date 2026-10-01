"""Streaming synthetic provider for consecutive production-shaped sessions."""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json

from sentinel.feed import calendar
from sentinel.feed.rolling_contract import CurrentFormationWindow
from tools.acquisition_resources import fixtures as base


class Profile(base.Profile):
    def window(self):
        return CurrentFormationWindow.through(base.END)


def rows(profile, table, lo=None, hi=None):
    if table in ('TICKERS', 'ACTIONS'):
        for row in ORIGINAL_ROWS(profile, table, lo, hi):
            if table == 'TICKERS':
                row[5] = row[2]  # Explicit issuer evidence, no cross-issuer alias.
                if int(row[1]) <= profile.securities:
                    row[6] = '2000-01-01'
            yield row
        if table == 'ACTIONS':
            # Preserve the installed reviewed source facts, just as the
            # existing canonical GO provider fixture does. No guard is patched.
            from sentinel.feed.source_authority.corporate_action_data import CASH_ADJUDICATION_AUTHORITIES
            for fact in CASH_ADJUDICATION_AUTHORITIES:
                yield [fact['source_action_date'], fact['source_action'], fact['ticker'],
                       'Installed source fact', fact['stale_source_amount'], None, None]
        return
    for session in profile.window().sessions:
        if lo and not lo <= str(session) <= hi:
            continue
        index = (session - date(2024, 1, 1)).days
        if table == 'SFP':
            for symbol, slope in (('SPY', '0.2'), ('BIL', '0.001')):
                price = str(Decimal('100') + Decimal(slope) * index)
                yield [symbol, str(session), price, price, price, price, '1000000']
        else:
            for i in range(profile.securities):
                # The existing simulated broker fills at $100. Source marks
                # stay above that so its fixed-price funding oracle can settle
                # every whole-share target without synthetic leverage.
                price = str(Decimal(100 + i % 100) + Decimal('0.04') * index)
                yield [f'S{i:05}', str(session), price, price, price, price, price,
                       '1000000', base.END]


ORIGINAL_ROWS = base.rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--small', action='store_true')
    args = parser.parse_args()
    from sentinel.feed.source_authority.corporate_action_data import CASH_ADJUDICATION_AUTHORITIES
    profile = Profile(name='joint-small' if args.small else 'joint-full',
        securities=30 if args.small else 6000, tickers=100 if args.small else 30000,
        actions=(500 if args.small else 1000000)-len(CASH_ADJUDICATION_AUTHORITIES))
    base.rows = rows
    root = Path('/fixtures')
    # Start with a weekday followed by another ordinary trading session.
    base.END = '2026-09-23'
    base.REFRESH = '2026-09-24T04:00:00+00:00'
    manifest = base.build(profile, root)
    handler = base.handler(profile, root, manifest)
    class Handler(handler):
        def do_POST(self):
            if self.path != '/advance':
                self.send_error(404)
                return
            base.END = calendar.next_session(base.END)
            now = datetime.fromisoformat(base.END).replace(tzinfo=timezone.utc) + timedelta(days=1, hours=4)
            base.REFRESH = now.isoformat()
            # Generations change only between completed acquisition cycles.
            root.mkdir(exist_ok=True)
            manifest.clear()
            manifest.update(base.build(profile, root))
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            q = parse_qs(parsed.query)
            table = Path(parsed.path).stem.upper()
            if table == 'SFP':
                data = list(rows(profile, 'SFP', q.get('date.gte', [None])[0],
                                 q.get('date.lte', [base.END])[0]))
                payload = {'datatable': {'columns': [{'name': c, 'type':'text'}
                    for c in base.COLUMNS['SFP']], 'data': data}, 'meta': {'next_cursor_id': None}}
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if table == 'SEP' and q.get('qopts.export') == ['true']:
                lo, hi = q['date.gte'][0], q['date.lte'][0]
                key = base.export_key('SEP', lo, hi)
                if key not in manifest:
                    # Acquisition's 300-session daily lower bound differs from
                    # the provider's 426-session retained source window.
                    import csv, io, zipfile, hashlib
                    path = root / (key + '.zip')
                    count = 0
                    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                        with archive.open('SEP.csv', 'w') as raw:
                            with io.TextIOWrapper(raw, encoding='utf-8', newline='') as out:
                                writer = csv.writer(out)
                                writer.writerow(base.COLUMNS['SEP'])
                                for row in rows(profile, 'SEP', lo, hi):
                                    writer.writerow(row)
                                    count += 1
                        csv_bytes = archive.getinfo('SEP.csv').file_size
                    with path.open('rb') as source:
                        sha = hashlib.file_digest(source, 'sha256').hexdigest()
                    manifest[key] = dict(rows=count, compressed_bytes=path.stat().st_size,
                                         csv_bytes=csv_bytes, sha256=sha)
            super().do_GET()
    print(json.dumps(dict(event='fixture_ready', profile=profile.model_dump())), flush=True)
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


if __name__ == '__main__':
    main()
