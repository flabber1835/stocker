"""Bounded dated-intent memo. Never an executable sizing-authority loader.

Each hit reads the physical row version again. Only a canonical full validation
can admit a small projection; timestamps and every mutable fact stay uncached.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import os
import threading
import time

MAX_ENTRIES = 16
MAX_BYTES = 262144


def row_version(conn, plan_id):
    from sentinel.dual_plan_authority import _cursor
    row = conn.execute("""WITH snapshot AS MATERIALIZED (
        SELECT pg_snapshot_xmax(pg_current_snapshot())::text::numeric AS xmax,
               pg_current_xact_id_if_assigned() IS NULL AS read_only_version)
        SELECT s.session,s.tableoid::oid,s.xmin::text,s.ctid::text,
        pg_relation_filenode(s.tableoid),d.oid,
        (SELECT system_identifier::text FROM pg_control_system()),
        pg_postmaster_start_time(),
        floor(snapshot.xmax/4294967296)::text,
        (snapshot.read_only_version AND s.xmin::text::numeric < mod(snapshot.xmax,4294967296))
        FROM sentinel_processed_sessions s CROSS JOIN pg_database d CROSS JOIN snapshot
        WHERE s.cursor_name=%s AND d.datname=current_database()""", (_cursor(plan_id),)).fetchone()
    return tuple(row) if row else None


def _reusable(version):
    # A prior-epoch frozen xmin can be ahead of this epoch's allocation counter.
    # Until it has passed, raw xmin/ctid could recur without an epoch change.
    # Assigned writer transactions also exclude their own subtransaction rows.
    return (version is not None and len(version) == 10
            and type(version[4]) is int and version[4] > 0
            and version[9] is True)


def projection(value):
    from sentinel.paper_plan_preview import opening_sizing_basis

    observation = value['broker_observation']
    return dict(plan_id=value['plan_id'], plan_fingerprint=value['plan_fingerprint'],
        decision_session=value['decision_session'], tickers=dict(value['tickers']),
        opening_sizing_basis=opening_sizing_basis(value),
        broker_observation=dict(completeness=observation['completeness'],
            account_identity=observation['account_identity'], observed_at=observation['observed_at'],
            positions=[dict(instrument=dict(security_id=item['instrument']['security_id'],
                                            symbol=item['instrument'].get('symbol')),
                            quantity=item['quantity']) for item in observation['positions']]))


class IntentMemo:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.entries = OrderedDict()
        self.configuration = None
        self.last_clock = None

    def read(self, conn, *, plan_id):
        from sentinel.dual_plan_authority import DualPlanAuthorityRefused, load_authority
        # The raw DSN is never serialized, logged, hashed into an event or exposed.
        configuration = (conn.info.dsn, os.environ.get('SENTINEL_GIT_COMMIT'),
                         os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST'),
                         os.environ.get('SENTINEL_STATE_DIR'))
        now = self.clock()
        version = row_version(conn, plan_id)
        key = (plan_id, version)
        with self.lock:
            if configuration != self.configuration or self.last_clock is not None and now < self.last_clock:
                self.entries.clear()
            self.configuration, self.last_clock = configuration, now
            if _reusable(version) and key in self.entries:
                self.entries.move_to_end(key)
                return deepcopy(self.entries[key])
        value = load_authority(conn, plan_id=plan_id)
        if row_version(conn, plan_id) != version:
            raise DualPlanAuthorityRefused('dated intent changed during canonical validation')
        if value is None:
            return None
        if version is None or str(version[0]) != value['decision_session']:
            raise DualPlanAuthorityRefused('dated intent row version disagrees with canonical authority')
        result = projection(value)
        encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if _reusable(version) and len(encoded) <= MAX_BYTES:
            with self.lock:
                if self.configuration == configuration and self.last_clock == now:
                    self.entries[key] = deepcopy(result)
                    while len(self.entries) > MAX_ENTRIES:
                        self.entries.popitem(last=False)
        return result


memo = IntentMemo()
read = memo.read
