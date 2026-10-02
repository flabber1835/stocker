"""Internal test-only driver for the separately capped automated paper process."""
from datetime import datetime
import faulthandler
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import signal
from pathlib import Path

from pytest import MonkeyPatch

from sentinel import backup_runtime_authority, rolling_initialization, shadow_runtime
from sentinel.feed import operational_snapshot as snapshots, store
from tools.acquisition_resources.measurement import Measurement
from tools.acquisition_resources.worker import source_identity
from tools.operational_rehearsal.paper import PaperTape
from tools.operational_rehearsal.worker import OBS


def main():
    faulthandler.register(signal.SIGUSR1)
    root = Path('/var/lib/sentinel')
    root.mkdir(exist_ok=True)
    clock, tape, finished, cycles = [None], [None], [False], []
    conn = store.connect(os.environ['RESOURCE_DSN'])
    with MonkeyPatch.context() as patch, Measurement(root) as measure:
        patch.setattr(backup_runtime_authority, 'POLICY_MARKER', root/'no-backup-policy')
        patch.setattr(snapshots, '_now', lambda: clock[0])
        patch.setattr(rolling_initialization, '_now', lambda c: clock[0])
        class Handler(BaseHTTPRequestHandler):
            def answer(self, value, status=200):
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.answer({'ready': True}, 200 if self.path == '/health' else 404)

            def do_POST(self):
                if self.path == '/complete':
                    finished[0] = True
                    self.answer({'complete': True})
                    return
                if self.path != '/cycle':
                    self.answer({}, 404)
                    return
                try:
                    value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    clock[0] = datetime.fromisoformat(value['now'])
                    with measure.phase('paper:'+value['session']):
                        if tape[0] is None:
                            with snapshots.pinned(conn) as (pub, _):
                                subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
                            patch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: {
                                'schema':'local-rehearsal-runtime/1', 'source_sha256':source_identity(),
                                'validated_data_publication_sha256':subject})
                            tape[0] = PaperTape(conn, patch, observation_id=OBS)
                        result = tape[0].cycle(conn, day=value['session'], now=clock[0],
                                              state_sha256=value['state_sha256'])
                        cycles.append(result)
                    self.answer(result)
                except Exception as exc:
                    import traceback
                    traceback.print_exc()
                    self.answer({'error':type(exc).__name__, 'detail':str(exc)}, 500)
        server = HTTPServer(('0.0.0.0',8081), Handler)
        while not finished[0]:
            server.handle_request()
        server.server_close()
    conn.close()
    assert len(cycles) == 3
    print(json.dumps(dict(event='result', daily_cycles=cycles, measurement=measure.result()),
                     sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
