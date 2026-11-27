"""Typed, authenticated material shared by preparation and its exact opening cycle."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, fields
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from tempfile import gettempdir

from sentinel import receipt_authentication
from sentinel.feed.rolling_contract import canonical_json, digest

_active = ContextVar('prepared_opening_material', default=None)
_LIMIT = 16 * 1024 * 1024
_PURPOSE = 'sentinel.prepared-opening-material/1'
_SCOPE_FIELDS = ('cycle_id', 'decision_session', 'effective_session', 'deployment_id', 'broker',
                 'broker_account_id', 'takeover_epoch', 'control_generation', 'certificate_sha256',
                 'rollout_mode', 'rollout_version', 'config_sha256')


def active():
    return _active.get() is not None


@contextmanager
def cycle(record, *, directory=None):
    revision = os.environ.get('SENTINEL_IMAGE_SOURCE_REVISION')
    image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST')
    if not revision or not image or not hasattr(os, 'geteuid'):
        yield
        return
    values = {name: str(getattr(record, name)) for name in _SCOPE_FIELDS}
    uid = os.geteuid()
    root = directory if directory is not None else Path(gettempdir()) / f'sentinel-opening-material-{uid}'
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        private = stat.S_ISDIR(info.st_mode) and info.st_uid == uid and not info.st_mode & 0o077
    except OSError:
        private = False
    if not private:
        yield
        return
    token = _active.set((root, digest([values, revision, image])))
    try:
        yield
    finally:
        _active.reset(token)


def _read(path, subject, decode):
    try:
        limit = _limit(path)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with os.fdopen(os.open(path, flags), 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                return None
            header, signature = json.loads(handle.readline(1024))
            if (not isinstance(header, dict) or set(header) != {'purpose', 'subject', 'sha256'}
                    or header['purpose'] != _PURPOSE or header['subject'] != subject or not hmac.compare_digest(
                    signature, receipt_authentication.sign(header))):
                return None
            encoded = handle.read(limit + 1)
        if hashlib.sha256(encoded).hexdigest() != header['sha256']:
            return None
        return decode(json.loads(encoded))
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError, OverflowError):
        return None


def _save(path, subject, value):
    if value is None:
        return
    encoded = canonical_json(value).encode('ascii')
    if len(encoded) > _limit(path) - 1024:
        return
    header = {'purpose': _PURPOSE, 'subject': subject,
              'sha256': hashlib.sha256(encoded).hexdigest()}
    first = canonical_json([header, receipt_authentication.sign(header)]).encode('ascii')
    import fcntl
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path.with_suffix('.lock'), flags, 0o600), 'wb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        temp = path.with_suffix('.tmp')
        with os.fdopen(os.open(temp, flags | os.O_TRUNC, 0o600), 'wb') as handle:
            handle.write(first + b'\n' + encoded)
        os.replace(temp, path)


def _limit(path):
    return 64 * 1024 * 1024 if path.name == 'prepared-opening-shadow.json' else _LIMIT


def _measure(slot, witness, load, encode, decode, *, validate_hit=None):
    owner = _active.get()
    if owner is None:
        return load()
    before = witness()
    if before is None:
        return load()
    path = owner[0] / ('prepared-opening-' + slot + '.json')
    subject = digest([owner[1], slot, before])
    value = _read(path, subject, decode)
    if value is not None and witness() == before:
        if validate_hit is not None:
            validate_hit(value)
        return value
    value = load()
    if witness() == before:
        try:
            _save(path, subject, encode(value))
        except (OSError, receipt_authentication.ReceiptKeyUnavailable):
            pass  # An unavailable local handoff never replaces the canonical computation.
    return value


def _feed_witness(conn, pub):
    from sentinel.feed import shadow_readiness_memo
    return shadow_readiness_memo._witness(conn, pub, financial_pin=True)


def version_epoch(conn, rows):
    """Exclude ambiguous frozen/future xids before saving a physical tuple version."""
    xmax = int(conn.execute('SELECT pg_snapshot_xmax(pg_current_snapshot())::text').fetchone()[0])
    def current(values):
        for index, value in enumerate(values):
            if isinstance(value, (list, tuple)):
                if not current(value):
                    return False
            elif isinstance(value, str) and value.startswith('(') and value.endswith(')'):
                # Every physical tuple is selected as ... xmin::text,ctid::text.
                xid = values[index - 1] if index else None
                if isinstance(xid, str) and xid.isdecimal() and (xmax - int(xid)) % 2**32 >= 2**31:
                    return False
        return True
    # One bucket spans less than half an XID epoch. Even a frozen original
    # cannot be replaced by a different tuple with the same xid in this span.
    return xmax // 2**30 if current(rows) else None


def verified_snapshot(conn, pub, load):
    if not active():
        return load()
    from sentinel.feed import rolling_store as store

    def encode(value):
        facts = value.readiness
        return [value.manifest.model_dump(mode='json', by_alias=True),
                None if facts is None else [
                    facts.counts, facts.positive, [row.model_dump(mode='json') for row in facts.benchmarks],
                    [[sid, ticker, mask] for (sid, ticker), mask in facts.reference_uses.items()]]]

    def decode(data):
        manifest = store.SnapshotManifest.model_validate(data[0])
        facts = data[1]
        if facts is not None:
            counts, positive, benchmarks, uses = facts
            facts = store.SnapshotReadiness(pub.evidence['rolling_snapshot']['candidate_id'],
                manifest.snapshot_id, manifest.window.sessions, tuple(counts), tuple(map(tuple, positive)),
                tuple(store.CanonicalBenchmark.model_validate(row) for row in benchmarks),
                {(sid, ticker): mask for sid, ticker, mask in uses})
        return store.VerifiedSnapshot(manifest, facts)

    return _measure('snapshot', lambda: _feed_witness(conn, pub), load, encode, decode)


def readiness(conn, pub, load):
    from sentinel.core.rolling_inputs import ReadinessInputs
    from sentinel.feed.rolling_contract import CanonicalBenchmark

    def encode(value):
        data = asdict(value)
        data['benchmarks'] = [row.model_dump(mode='json') for row in value.benchmarks]
        return data

    def decode(data):
        data['benchmarks'] = tuple(CanonicalBenchmark.model_validate(r) for r in data['benchmarks'])
        return ReadinessInputs(**data)

    return _measure('readiness', lambda: _feed_witness(conn, pub), load, encode, decode)


def _checkpoint_witness(conn, context):
    from sentinel import checkpoint_lineage_access as lineage, local_paper
    from sentinel.execution.journal import LEGACY_FILL_CASH_PREFIX
    from sentinel.feed import readiness_scope
    from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES

    pin = readiness_scope.capture(conn)
    if pin is None:
        return None
    publication = _feed_witness(conn, pin.publication_object)
    if publication is None:
        return None
    # Include every unknown cursor. Even a nominally operational cursor is
    # economic when its contents satisfy the canonical foreign-lineage predicate.
    names = list(PAPER_CURSOR_NAMES)
    prefixes = [prefix + '%' for prefix in (*PAPER_CURSOR_PREFIXES, LEGACY_FILL_CASH_PREFIX)]
    relation = _relations(conn, ['sentinel_processed_sessions', 'sentinel_account_binding',
                                 'sentinel_rollout_state', 'sentinel_corpus_publications'])
    if relation is None:
        return None
    if conn.execute('SELECT cursor_name FROM sentinel_processed_sessions WHERE (' +
            lineage.JSON_PREDICATE.replace('%','%%') + ') AND (cursor_name=ANY(%s) OR cursor_name LIKE ANY(%s)) '
            'ORDER BY cursor_name LIMIT 1', (names, prefixes)).fetchone():
        return None
    rows = conn.execute("SELECT cursor_name,tableoid,xmin::text,ctid::text FROM sentinel_processed_sessions "
        "WHERE cursor_name<>ALL(%s) AND NOT (cursor_name LIKE ANY(%s)) ORDER BY cursor_name LIMIT 10001",
        (names, prefixes)).fetchall()
    account = conn.execute('SELECT tableoid,xmin::text,ctid::text FROM sentinel_account_binding').fetchall()
    rollout = conn.execute('SELECT tableoid,xmin::text,ctid::text FROM sentinel_rollout_state').fetchall()
    if len(rows) > 10000:
        return None
    epoch = version_epoch(conn, (rows, account, rollout))
    if epoch is None:
        return None
    policy = [os.environ.get(name) for name in (local_paper.MODE_ENV, local_paper.ACCOUNT_ENV,
              local_paper.BACKUP_POLICY_ENV, 'ALPACA_BASE_URL')]
    return [publication, relation, rows, account, rollout, epoch, policy, context]


def _relations(conn, names):
    rows = conn.execute("SELECT c.relname,c.oid,pg_relation_filenode(c.oid),c.reltoastrelid,"
        "pg_relation_filenode(c.reltoastrelid),c.relfrozenxid::text FROM pg_class c "
        "WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s) "
        "AND to_regclass(c.relname)=c.oid ORDER BY c.relname", (names,)).fetchall()
    return rows if len(rows) == len(names) else None


def shadow(conn, context, load):
    if not active():
        return load()
    from sentinel import rolling_authority, rolling_runtime, shadow_observation
    from sentinel.core.production import SessionState

    def wire(value):
        bound, _, result, attested, previous = value
        from sentinel.feed import readiness_scope
        pin = readiness_scope.capture(conn)
        if (pin is None or type(attested) is not rolling_authority.Authority
                or bound.publication != pin.publication_object.to_dict()):
            return None
        body = {f.name: getattr(result, f.name) for f in fields(result) if f.name != 'state'}
        body['state'] = result.state.to_dict()
        return [asdict(bound), body, *[a.model_dump(mode='json', by_alias=True) if a else None
                                       for a in (attested, previous)]]

    def decode(data):
        bound, body, *records = data
        body['state'] = SessionState.from_dict(body['state'])
        def authority(record):
            if record is None:
                return None
            cls = (rolling_authority.ReconstructionReceipt if record['schema'] ==
                   'sentinel.rolling-reconstruction-receipt/1' else rolling_authority.Authority)
            return cls.model_validate(record)
        return (rolling_runtime._StatusBinding(**bound), None, shadow_observation.ShadowObservationResult(**body),
                *(authority(record) for record in records))

    key = {**context, 'controller': context['controller'].to_dict()}
    from sentinel import runtime_admission
    return _measure('shadow', lambda: _checkpoint_witness(conn, key), load, wire, decode,
        validate_hit=lambda value: runtime_admission.require_retained_process(conn, value[0].runtime_identity, key))


def sizing(conn, key, load):
    from sentinel import structural_verification
    from sentinel.feed import readiness_scope
    def witness():
        pin = readiness_scope.capture(conn)
        if pin is None:
            return None
        publication = _feed_witness(conn, pin.publication_object)
        if publication is None:
            return None
        tables = ['sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills',
                  'sentinel_processed_sessions', 'sentinel_action_coverage', 'sentinel_action_history']
        relation = _relations(conn, tables)
        if relation is None:
            return None
        publications = conn.execute(
            'SELECT version,tableoid,xmin::text,ctid::text FROM sentinel_corpus_publications '
            'WHERE version<=%s ORDER BY version LIMIT 10001', (pin.publication_object.version,)).fetchall()
        actions = conn.execute(
            'SELECT publication_version,tableoid,xmin::text,ctid::text FROM sentinel_action_coverage '
            'ORDER BY publication_version LIMIT 10001').fetchall()
        events = conn.execute(
            'SELECT publication_version,session::text,tableoid,xmin::text,ctid::text FROM sentinel_action_history '
            'ORDER BY publication_version,session LIMIT 10001').fetchall()
        if any(len(rows) > 10000 for rows in (publications, actions, events)):
            return None
        inventory = structural_verification._inventory(conn, 'dual-sizing', key)
        # PostgreSQL date labels in the structural inventory need a stable JSON representation.
        epoch = version_epoch(conn, (publications, actions, events, inventory, key[-1]))
        if epoch is None:
            return None
        return [publication, relation, publications, actions, events, epoch, repr(inventory), repr(key)]
    return _measure('sizing', witness, load, lambda data: data, lambda data: data)
