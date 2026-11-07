"""Finite large-fixture qualification, never a production installer or pytest lane.

Run only in the private network-none, one-CPU, <=2-GiB PostgreSQL16 image.
No DSN, existing cluster, provider input or credential can be supplied. Default
is a plan; --execute creates and removes one fresh private cluster. The real
additive installation runs in a separately supervised child with its original
120-second statement and 150-second result-admission limits.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import closing
from datetime import timedelta
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import signal
from threading import Event, Thread
import time
import uuid

MIB = 1024*1024
MIN_BYTES, MAX_BYTES = 700*MIB, 1280*MIB
PAYLOAD_BYTES, LARGE_ROWS = 2*MIB, 384
INSTALL_SECONDS, TOTAL_SECONDS = 150, 900
QUALIFICATION_QUERY_MS = 3000
TABLE = 'sentinel_processed_sessions'
PARAMS = (['rolling-cold-start:v1', 'rolling-daily-checkpoint:v1',
           'shadow-observation:v1:primary:genesis'],
          'shadow-observation:v1:primary:session:%',
          'rolling-daily-input:v1:primary:%', 'shadow-rolling-runtime:v1:primary:%')
KEYS = ('allowed_names', 'session_pattern', 'input_pattern', 'authority_pattern')


class Refused(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise Refused(code)


def cpu():
    values = {}
    for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines():
        name, value = line.split()
        values[name] = int(value)
    return values


def isolation():
    forbidden = ('SENTINEL_DATABASE_URL', 'DATABASE_URL', 'PGHOST', 'PGPORT',
        'PGUSER', 'PGDATABASE', 'PGPASSWORD', 'PGSERVICE', 'ALPACA_API_KEY',
        'ALPACA_SECRET_KEY', 'SENTINEL_PUBLICATION_RECEIPT_KEY',
        'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY')
    require(not any(os.environ.get(name) for name in forbidden), 'INHERITED_CONNECTION_OR_CREDENTIAL')
    require({path.name for path in Path('/sys/class/net').iterdir()} == {'lo'}, 'NETWORK_NOT_ISOLATED')
    require(not Path('/var/run/docker.sock').exists(), 'DOCKER_SOCKET_FORBIDDEN')
    maximum, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
    memory = Path('/sys/fs/cgroup/memory.max').read_text().strip()
    require(maximum != 'max' and int(maximum) == int(period), 'ONE_CPU_REQUIRED')
    require(memory != 'max' and 0 < int(memory) <= 2*1024*MIB, 'MEMORY_BOUND_REQUIRED')
    return {'cpu.max': maximum+' '+period, 'memory.max': int(memory), 'network': 'loopback-only'}


def save(path, report, *, final=False):
    raw = (json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    require(len(raw) <= MIB, 'REPORT_BOUND')
    destination = path if final else path.with_name(path.name+'.partial')
    temporary = path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    descriptor = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()


def sizes(conn):
    row = conn.execute('SELECT pg_relation_size(%s::regclass),'
        'pg_total_relation_size(%s::regclass)', (TABLE, TABLE)).fetchone()
    require(row[1] <= MAX_BYTES, 'FIXTURE_SIZE_CAP')
    return {'heap_bytes': row[0], 'total_bytes': row[1]}


def financial_rows_digest(conn):
    material = []
    for table, order in (('sentinel_observations', 'seq'),
                         ('sentinel_observation_provenance', 'observation_seq'),
                         ('sentinel_account_binding', 'id')):
        value = conn.execute('SELECT encode(sha256(convert_to(coalesce(jsonb_agg('
            "jsonb_build_array(xmin::text,ctid::text,to_jsonb(t)) ORDER BY "+order+
            ")::text,'[]'),'UTF8')),'hex') FROM "+table+' t').fetchone()[0]
        material.append((table, value))
    material.append(('broker_cursors', conn.execute(
        'SELECT encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_array('
        "cursor_name,xmin::text,ctid::text,state) ORDER BY cursor_name)::text,'[]'),'UTF8')),'hex') "
        f"FROM {TABLE} WHERE cursor_name LIKE 'broker-observation:v4:%'").fetchone()[0]))
    return hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()


def payload(seed):
    return base64.b64encode(hashlib.shake_256(seed.encode()).digest(PAYLOAD_BYTES//4*3)).decode()


def load(conn, progress):
    from psycopg.types.json import Jsonb
    started = time.monotonic()
    for number in range(LARGE_ROWS):
        name = ('ordinary-large:' if number < 256 else
                'shadow-observation:v1:primary:session:large-')+f'{number:04}'
        conn.execute(f'INSERT INTO {TABLE}(cursor_name,session,state) VALUES(%s,%s,%s)',
            (name, '2026-11-05', Jsonb({'payload': payload(name)})))
        if number%16 == 15:
            conn.commit()
            progress({'large_rows_written': number+1, **sizes(conn)})
    for number in range(183):
        name = ('ordinary-inline:' if number < 128 else
                'shadow-observation:v1:primary:session:inline-')+f'{number:04}'
        conn.execute(f'INSERT INTO {TABLE}(cursor_name,session,state) VALUES(%s,%s,%s)',
                     (name, '2026-11-05', Jsonb({'payload': name*16})))
    for name in PARAMS[0]:
        conn.execute(f'INSERT INTO {TABLE}(cursor_name,session,state) VALUES(%s,%s,%s)',
            (name, '2026-11-05', Jsonb({'wealth_core': {'fixture': True}, 'strategy_identity': False})))
    conn.execute(f"INSERT INTO {TABLE}(cursor_name,session,state) VALUES('mutable-small','2026-11-05','{{}}')")
    conn.commit()
    result = sizes(conn)
    require(MIN_BYTES <= result['total_bytes'], 'FIXTURE_BELOW_700_MIB')
    return {**result, 'synthetic_rows': 571, 'large_rows': LARGE_ROWS,
            'payload_bytes': PAYLOAD_BYTES, 'seconds': time.monotonic()-started}


def preserved(conn):
    from sentinel import checkpoint_lineage_access as access, operational_schema
    rows = conn.execute(f'SELECT cursor_name,session::text,extract(epoch FROM updated_at)::text,'
        "encode(sha256(convert_to(state::text,'UTF8')),'hex') "
        f'FROM {TABLE} WHERE cursor_name<>%s ORDER BY cursor_name', (access.CURSOR,)).fetchall()
    marker = operational_schema.installation(conn, required=True)
    counts = conn.execute('SELECT (SELECT count(*) FROM sentinel_commands),'
        '(SELECT count(*) FROM sentinel_command_events)').fetchone()
    physical = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
    financial = financial_rows_digest(conn)
    conn.rollback()
    return {'synthetic_cursor_rows_sha256': hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest(),
        'original_marker_sha256': hashlib.sha256(json.dumps(marker, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'original_contracts_sha256': hashlib.sha256(json.dumps(marker['contracts'], sort_keys=True).encode()).hexdigest(),
        'financial_rows_sha256': financial,
        'command_count': counts[0], 'command_event_count': counts[1], 'system_identifier': physical}


def coverage_state(conn):
    from sentinel import operational_ddl_epoch
    from sentinel.execution import evidence_projection as coverage, journal
    result = {'epoch': list(operational_ddl_epoch.current(conn)), 'domains': {}}
    for domain in ('OBSERVATION', 'MIRROR'):
        value = coverage.require_current(conn, domain)
        unchanged = {key: item for key, item in value.items() if key != 'inventory'}
        result['domains'][domain] = {
            'content_sha256': coverage.digest(unchanged),
            'body_sha256': coverage.digest(value['body']), 'through': value['through'],
            'head': list(coverage.head(conn, domain)), 'inventory': value['inventory']}
    journal.require_observation_integrity(conn)
    conn.rollback()
    return result


def bootstrap_coverage(conn):
    from sentinel import mirror_projection
    from sentinel.execution import journal
    for producer in (journal.bootstrap_observation_integrity, mirror_projection.bootstrap_step):
        for _ in range(20):
            value = producer(conn, limit=128)
            conn.commit()
            if value['body']['stage'] == 'COMPLETE':
                break
        else:
            raise Refused('REAL_COVERAGE_BOOTSTRAP_DID_NOT_COMPLETE')
    require(conn.execute('SELECT count(*) FROM sentinel_observations').fetchone() == (2,), 'NONEMPTY_OBSERVATIONS_REQUIRED')
    conn.rollback()
    return coverage_state(conn)


def _milliseconds(value):
    matched = re.fullmatch(r'([0-9]+)(ms|s|min)', value)
    require(matched is not None, 'UNRECOGNIZED_TIMEOUT_UNIT')
    return int(matched[1])*{'ms': 1, 's': 1000, 'min': 60000}[matched[2]]


def _install_child(channel, dsn, scenario, parent_pid):
    from sentinel.supervisor_io import _parent_death
    _parent_death(parent_pid)
    from sentinel import checkpoint_lineage_access as access, operational_schema
    from sentinel.execution.journal import WRITER_LOCK_KEY
    from sentinel.feed import store
    metadata = {'scenario': scenario}
    class Connection:
        def __init__(self, current): self.current = current
        def __getattr__(self, name): return getattr(self.current, name)
        def execute(self, statement, *args, **kwargs):
            if statement != access.DDL[0]:
                return self.current.execute(statement, *args, **kwargs)
            metadata['statement_ms'] = _milliseconds(self.current.execute('SHOW statement_timeout').fetchone()[0])
            metadata['lock_ms'] = _milliseconds(self.current.execute('SHOW lock_timeout').fetchone()[0])
            require(metadata['statement_ms'] == 120000 and metadata['lock_ms'] == 2000, 'MIGRATION_LIMIT_CHANGED')
            with closing(store.connect(dsn, connect_timeout=3, statement_timeout_ms=1000)) as probe:
                migration = probe.execute('SELECT pg_try_advisory_lock(%s,%s)', operational_schema._LOCK).fetchone()[0]
                writer = probe.execute('SELECT pg_try_advisory_lock(%s)', (WRITER_LOCK_KEY,)).fetchone()[0]
                require(not migration and not writer, 'ORIGINAL_MIGRATION_OR_WRITER_LOCK_NOT_HELD')
                metadata['both_original_locks_held'] = True
            if scenario == 'budget-refusal':
                self.current.execute("SET LOCAL statement_timeout='1ms'")
            metadata['index_started_monotonic'] = time.monotonic()
            try:
                return self.current.execute(statement, *args, **kwargs)
            finally:
                metadata['index_finished_monotonic'] = time.monotonic()
                metadata['index_seconds'] = metadata['index_finished_monotonic']-metadata['index_started_monotonic']
    started = time.monotonic()
    try:
        with closing(store.connect(dsn, connect_timeout=3, statement_timeout_ms=3000)) as conn:
            original = operational_schema.installation(conn, required=True)
            conn.rollback()
            migration_started = time.monotonic()
            try:
                require(operational_schema.install_quiescent(Connection(conn)) == original, 'ORIGINAL_MARKER_CHANGED')
            finally:
                metadata['migration_seconds'] = time.monotonic()-migration_started
            access.require_schema(conn)
            metadata['index_bytes'] = conn.execute('SELECT pg_relation_size(%s::regclass)', (access.INDEX,)).fetchone()[0]
        metadata['outcome'] = 'INSTALLED'
    except Exception as error:
        metadata.update(outcome='REFUSED', exception_type=type(error).__name__)
        if isinstance(error, operational_schema.OperationalSchemaRefused) and str(error) in {
                'OPERATIONAL_MIGRATION_FINANCIAL_WRITER_BUSY', 'OPERATIONAL_MIGRATION_ALREADY_OWNED'}:
            metadata['refusal_code'] = str(error)
        elif isinstance(error, Refused):
            metadata['refusal_code'] = str(error)
    metadata['child_seconds'] = time.monotonic()-started
    raw = json.dumps(metadata, separators=(',', ':')).encode()
    require(len(raw) <= 2048, 'INSTALLER_METADATA_BOUND')
    channel.send_bytes(raw)
    channel.close()


def install(dsn, scenario):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_install_child, args=(sender, dsn, scenario, os.getpid()))
    started = time.monotonic()
    try:
        child.start()
        sender.close()
        child.join(max(0, INSTALL_SECONDS-(time.monotonic()-started)))
        require(not child.is_alive(), 'INSTALLER_150_SECOND_LIMIT')
        require(child.exitcode == 0 and receiver.poll(), 'INSTALLER_PROCESS_REFUSED')
        value = json.loads(receiver.recv_bytes(maxlength=2048))
        value['whole_child_seconds'] = time.monotonic()-started
        require(value['whole_child_seconds'] < INSTALL_SECONDS, 'INSTALLER_LATE_RESULT')
        return value
    finally:
        sender.close()
        receiver.close()
        if child.pid is not None:
            if child.is_alive():
                child.kill()
                child.join(2)
            require(not child.is_alive(), 'PRIVATE_INSTALLER_NOT_REAPED')
            child.close()


def stats(conn):
    conn.execute('SELECT pg_stat_force_next_flush()')
    conn.commit()
    with closing(type(conn).connect(conn.info.dsn, autocommit=True)) as observer:
        observer.execute('SELECT pg_stat_clear_snapshot()')
        return observer.execute('SELECT n_tup_upd,n_tup_hot_upd FROM pg_stat_user_tables WHERE relname=%s', (TABLE,)).fetchone()


def mixed_writes(conn, label):
    from psycopg.types.json import Jsonb
    before, usage = stats(conn), cpu()
    lsn = conn.execute('SELECT pg_current_wal_insert_lsn()').fetchone()[0]
    conn.commit()
    started = time.monotonic()
    for number in range(16):
        conn.execute(f'UPDATE {TABLE} SET updated_at=updated_at+interval \'1 microsecond\' '
            "WHERE cursor_name='shadow-observation:v1:primary:session:large-0256'")
        conn.execute(f"UPDATE {TABLE} SET state=%s WHERE cursor_name='mutable-small'", (Jsonb({'iteration': number}),))
        if number%8 == 0:
            for name in ('ordinary-large:0000', 'shadow-observation:v1:primary:session:large-0256'):
                conn.execute(f'UPDATE {TABLE} SET state=%s WHERE cursor_name=%s',
                    (Jsonb({'payload': payload(label+name+str(number))}), name))
        conn.commit()
    wal = conn.execute('SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),%s::pg_lsn)', (lsn,)).fetchone()[0]
    after, used = stats(conn), cpu()
    return {'seconds': time.monotonic()-started, 'wal_interval_bytes': int(wal),
        'updates': after[0]-before[0], 'hot_updates': after[1]-before[1],
        'cgroup_cpu_usage_usec': used['usage_usec']-usage['usage_usec'], 'size': sizes(conn)}


def query_text(statement, *, original=False):
    result = statement.replace('%%', '%')
    if original:
        parts = result.split('%s')
        result = parts[0]+''.join('$'+str(index)+part for index, part in enumerate(parts[1:], 1))
    else:
        for index, key in enumerate(KEYS, 1): result = result.replace('%('+key+')s', '$'+str(index))
    return result


def nodes(plan):
    yield plan
    for child in plan.get('Plans', []): yield from nodes(child)


def explain(conn, name):
    from psycopg import sql
    from psycopg.errors import QueryCanceled
    arguments = sql.SQL(',').join(sql.Literal(value) for value in PARAMS)
    require(_milliseconds(conn.execute('SHOW statement_timeout').fetchone()[0]) == QUALIFICATION_QUERY_MS,
            'QUALIFICATION_QUERY_LIMIT_CHANGED')
    started = time.monotonic()
    try:
        value = conn.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) EXECUTE {} ({})').format(
            sql.Identifier(name), arguments)).fetchone()[0][0]
        return {'outcome': 'COMPLETED', 'wall_seconds': time.monotonic()-started,
            'qualification_statement_ms': QUALIFICATION_QUERY_MS,
            'timeout': False, 'actual_rows': value['Plan']['Actual Rows'],
            'execution_ms': value['Execution Time'],
            'indexes': sorted({item['Index Name'] for item in nodes(value['Plan']) if 'Index Name' in item}), 'plan': value}
    except QueryCanceled:
        conn.rollback()
        return {'outcome': 'READ_TIMEOUT', 'wall_seconds': time.monotonic()-started,
                'qualification_statement_ms': QUALIFICATION_QUERY_MS,
                'timeout': True, 'actual_rows': None, 'execution_ms': None,
                'indexes': [], 'plan': None}


def reader(dsn, stopped, observations, failures):
    import psycopg
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=3,
                options='-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=500') as conn:
            while not stopped.is_set():
                started = time.monotonic()
                count = conn.execute(f'SELECT count(*) FROM {TABLE}').fetchone()[0]
                observations.append((started, time.monotonic(), count))
                stopped.wait(.05)
    except Exception as error:
        failures.append(type(error).__name__)


def qualify(path):
    bounds = isolation()
    from psycopg.types.json import Jsonb
    from sentinel import binding, checkpoint_lineage_access as access, operational_schema, schema
    from sentinel.execution import journal
    from sentinel.execution.contract import BrokerAccountIdentity
    from sentinel.execution.simulator import SimulatedBroker
    from sentinel.execution.journal import WRITER_LOCK_KEY
    from sentinel.feed import store
    from sentinel.panel.sources import STATEMENT_TIMEOUT_MS
    from tests.support.postgres import _EphemeralPostgres
    report = {'schema': 'sentinel.checkpoint-lineage-large-qualification/1',
        'status': 'RUNNING', 'stage': 'STARTING', 'isolation': bounds,
        'target_bytes': 768*MIB, 'maximum_bytes': MAX_BYTES}
    report['query_budget'] = {'qualification_ms': QUALIFICATION_QUERY_MS,
        'general_financial_source_ms': STATEMENT_TIMEOUT_MS,
        'scope': 'Stricter existing preparation-read cap; not the general financial-source deadline.'}
    root = Path(__file__).resolve().parents[1]
    report['source_sha256'] = {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
        for name in ('tools/qualify_checkpoint_lineage_access.py',
            'sentinel/checkpoint_lineage_access.py', 'sentinel/operational_catalog.py',
            'sentinel/operational_schema.py', 'sentinel/operational_ddl_handoff.py')}
    save(path, report)
    cluster = None
    try:
        os.environ['LANG'] = os.environ['LC_ALL'] = 'en_US.utf8'
        os.environ['SENTINEL_PUBLICATION_RECEIPT_KEY'] = 'private-lineage-qualification-'+uuid.uuid4().hex*3
        cluster = _EphemeralPostgres()
        cluster.start()
        with closing(store.connect(cluster.sync_dsn, connect_timeout=3, statement_timeout_ms=120000)) as conn:
            # Keep explicit custom/generic PREPARE controls outside psycopg's
            # automatic cache, whose rollback maintenance clears every server
            # prepared statement once that cache becomes populated.
            conn.prepare_threshold = None
            report['control_connection_prepare_threshold'] = conn.prepare_threshold
            version, collation, provider = conn.execute('SELECT current_setting(\'server_version_num\')::int,'
                'datcollate,datlocprovider FROM pg_database WHERE datname=current_database()').fetchone()
            require(160000 <= version < 170000 and collation == 'en_US.utf8' and provider == 'c', 'PG16_DEFAULT_EN_US_UTF8_REQUIRED')
            report.update(server_version_num=version, database_collation=collation, provider=provider)
            conn.rollback()
            report['stage'] = 'SCHEMA'
            schema.ensure_schema(conn)
            store.migrate_schema(conn)
            # Install this private measurement-only extension before the
            # original operational authority/DDL epoch or any signed prefix.
            conn.execute('CREATE EXTENSION pg_visibility WITH SCHEMA pg_catalog')
            report['visibility_extension_setup'] = {'before_original_operational_install': True,
                'public_epoch_before': conn.execute("SELECT to_regclass('public.sentinel_operational_ddl_epoch')").fetchone()[0],
                'namespace': conn.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n "
                    "ON n.oid=e.extnamespace WHERE e.extname='pg_visibility'").fetchone()[0]}
            require(report['visibility_extension_setup']['public_epoch_before'] is None
                    and report['visibility_extension_setup']['namespace'] == 'pg_catalog',
                    'VISIBILITY_EXTENSION_NOT_BEFORE_AUTHORITY')
            conn.commit()
            def progress(value):
                report.update(stage='LOADING', fixture_progress=value)
                save(path, report)
            report['fixture'] = load(conn, progress)
            report['stage'] = 'PREDECESSOR'
            binding.bind(conn, deployment_id='fixture-paper', broker='alpaca', broker_account_id='PA-fixture')
            broker = SimulatedBroker(account=BrokerAccountIdentity(broker='alpaca', account_id='PA-fixture'))
            for _ in range(2):
                journal.record_observation(conn, asyncio.run(broker.observe()))
                broker.now += timedelta(seconds=1)
            conn.commit()
            conn.rollback()
            registry = operational_schema.ACCESS_PATH_COMPONENTS
            try:
                operational_schema.ACCESS_PATH_COMPONENTS = ()
                original = operational_schema.install_quiescent(conn)
            finally:
                operational_schema.ACCESS_PATH_COMPONENTS = registry
            require(access.__name__ in registry, 'CONCRETE_COMPONENT_NOT_REGISTERED')
            require(access.require_schema(conn, allow_absent=True) is False, 'PREDECESSOR_NOT_CLEAN')
            conn.rollback()
            report['stage'] = 'BASELINE_WRITES_AND_COVERAGE'
            report['original_mixed_writes'] = mixed_writes(conn, 'before')
            report['coverage_before'] = bootstrap_coverage(conn)
            report['before_install'] = preserved(conn)
            original_sql = query_text(access.ORIGINAL_QUERY, original=True)
            require(hashlib.sha256(original_sql.encode()).hexdigest() == '251c144d218a3280db4150a063c7ba6dda3ccd37be5755f2ad066d581e1f1e5e', 'ORIGINAL_CONTROL_CHANGED')
            conn.execute('PREPARE lineage_predecessor(text[],text,text,text) AS '+original_sql)
            conn.execute("SET statement_timeout='3000ms'")
            conn.execute("SET lock_timeout='500ms'")
            conn.commit()
            report['stage'] = 'PREINDEX_CONTROLS'
            report['preindex_original_controls'] = []
            for mode in ('force_custom_plan', 'force_generic_plan'):
                conn.execute("SELECT set_config('plan_cache_mode',%s,false)", (mode,))
                conn.commit()
                report['preindex_original_controls'].append({'mode': mode, **explain(conn, 'lineage_predecessor')})
            conn.rollback()
            conn.execute("SET statement_timeout='120000ms'")
            conn.commit()
            save(path, report)
            report['stage'] = 'STRICT_BUDGET_REFUSAL'
            report['budget_refusal'] = install(cluster.sync_dsn, 'budget-refusal')
            require(report['budget_refusal'].get('exception_type') == 'QueryCanceled', 'BUDGET_REFUSAL_NOT_OBSERVED')
            require(access.require_schema(conn, allow_absent=True) is False, 'BUDGET_REFUSAL_LEFT_COMPONENT')
            conn.rollback()
            require(preserved(conn) == report['before_install'], 'BUDGET_REFUSAL_CHANGED_ROWS')
            require(coverage_state(conn) == report['coverage_before'], 'BUDGET_REFUSAL_CHANGED_COVERAGE')
            with closing(store.connect(cluster.sync_dsn)) as owner:
                owner.execute('SELECT pg_advisory_xact_lock(%s)', (WRITER_LOCK_KEY,))
                report['writer_refusal'] = install(cluster.sync_dsn, 'writer-busy')
            require(report['writer_refusal'].get('refusal_code') == 'OPERATIONAL_MIGRATION_FINANCIAL_WRITER_BUSY', 'WRITER_REFUSAL_NOT_OBSERVED')
            require(preserved(conn) == report['before_install'], 'WRITER_REFUSAL_CHANGED_ROWS')
            require(coverage_state(conn) == report['coverage_before'], 'WRITER_REFUSAL_CHANGED_COVERAGE')
            save(path, report)
            report['stage'] = 'INSTALLATION'
            usage = cpu()
            stopped, reads, failures = Event(), [], []
            thread = Thread(target=reader, args=(cluster.sync_dsn, stopped, reads, failures), daemon=True)
            thread.start()
            try:
                report['installation'] = install(cluster.sync_dsn, 'normal')
            finally:
                stopped.set()
                thread.join(4)
            require(not thread.is_alive() and not failures, 'READONLY_READER_REFUSED')
            installed = report['installation']
            report['installation_cgroup_cpu_usage_usec'] = cpu()['usage_usec']-usage['usage_usec']
            require(installed.get('outcome') == 'INSTALLED', 'INSTALLATION_REFUSED')
            overlaps = [row for row in reads if row[0] < installed['index_finished_monotonic']
                        and row[1] > installed['index_started_monotonic']]
            require(overlaps, 'READONLY_READER_DID_NOT_OVERLAP_INDEX_BUILD')
            report['readers'] = {'completed': len(reads), 'overlapped_index_build': len(overlaps),
                'max_seconds': max(end-start for start, end, _ in reads), 'failures': failures}
            report['after_install'] = preserved(conn)
            require(report['after_install'] == report['before_install'], 'INSTALLATION_CHANGED_ORIGINAL_ROWS')
            report['coverage_after'] = coverage_state(conn)
            before, after = report['coverage_before'], report['coverage_after']
            require(after['epoch'] == [before['epoch'][0], before['epoch'][1]+2], 'INSTALLATION_DDL_EPOCH_CHANGED_UNEXPECTEDLY')
            for domain in ('OBSERVATION', 'MIRROR'):
                require({key: value for key, value in before['domains'][domain].items() if key != 'inventory'} ==
                        {key: value for key, value in after['domains'][domain].items() if key != 'inventory'},
                        'INSTALLATION_CHANGED_COVERAGE_CONTENT')
                require(before['domains'][domain]['inventory'] != after['domains'][domain]['inventory'],
                        'INSTALLATION_DID_NOT_TRANSFER_COVERAGE_INVENTORY')
            require(operational_schema.installation(conn) == original and operational_schema.contracts() == original['contracts'], 'ORIGINAL_INSTALLATION_CHANGED')
            conn.rollback()
            save(path, report)
            report['stage'] = 'NATURAL_PLANS'
            conn.execute('PREPARE lineage_original(text[],text,text,text) AS '+original_sql)
            conn.execute('PREPARE lineage_selected(text[],text,text,text) AS '+query_text(access.QUERY))
            conn.commit()
            report['plans'] = []
            for visibility in ('vacuumed', 'dirty'):
                conn.rollback()
                with closing(store.connect(cluster.sync_dsn, statement_timeout_ms=120000)) as maintenance:
                    maintenance.autocommit = True
                    maintenance.execute(f'VACUUM (ANALYZE) {TABLE}')
                conn.execute("SET statement_timeout='120000ms'")
                if visibility == 'dirty':
                    conn.execute(f'UPDATE {TABLE} SET session=session WHERE '
                        "cursor_name LIKE 'ordinary-large:%' OR cursor_name LIKE 'ordinary-inline:%' "
                        "OR cursor_name LIKE 'shadow-observation:v1:primary:session:large-%' "
                        "OR cursor_name LIKE 'shadow-observation:v1:primary:session:inline-%' "
                        "OR cursor_name='mutable-small'")
                    conn.commit()
                conn.execute("SET statement_timeout='3000ms'")
                conn.execute("SET lock_timeout='500ms'")
                require(conn.execute('SHOW enable_seqscan').fetchone() == ('on',), 'NATURAL_PLANNER_REQUIRED')
                for mode in ('force_custom_plan', 'force_generic_plan'):
                    conn.execute("SELECT set_config('plan_cache_mode',%s,false)", (mode,))
                    # A cancelled original control rolls back its transaction;
                    # commit the ordinary session limits first so subsequent
                    # measurements retain the same three-second budget.
                    conn.execute("SET statement_timeout='3000ms'")
                    conn.execute("SET lock_timeout='500ms'")
                    conn.commit()
                    visible = conn.execute('SELECT all_visible,all_frozen FROM pg_visibility_map_summary(%s::regclass)', (TABLE,)).fetchone()
                    relations = conn.execute('SELECT relname,relpages,reltuples,relallvisible '
                        'FROM pg_class WHERE oid IN (%s::regclass,%s::regclass) ORDER BY relname',
                        (TABLE, access.INDEX)).fetchall()
                    selected = []
                    lane = {'phase': report['stage'], 'visibility': visibility,
                        'all_visible_pages': visible[0], 'all_frozen_pages': visible[1],
                        'mode': mode, 'selected': selected,
                        'relation_metadata': [dict(zip(('name', 'relpages', 'reltuples', 'relallvisible'), row))
                            for row in relations]}
                    report['plans'].append(lane)
                    save(path, report)
                    for _ in range(3):
                        selected.append(explain(conn, 'lineage_selected'))
                        save(path, report)
                    require(all(item['outcome'] == 'COMPLETED' and access.INDEX in item['indexes']
                                and item['plan']['Plan']['Actual Rows'] == 0 for item in selected), 'NATURAL_INDEX_PLAN_NOT_QUALIFIED')
                    lane['original'] = explain(conn, 'lineage_original')
                    save(path, report)
            for name, value in [('unfamiliar-paper-foreign', {'wealth_core': False}), ('catchup', None)]:
                conn.execute(f'INSERT INTO {TABLE}(cursor_name,session,state) VALUES(%s,%s,%s)',
                             (name, '2026-11-05', Jsonb(value)))
                conn.commit()
                require(access.find_foreign(conn, **dict(zip(KEYS, PARAMS))) == (name,), 'FOREIGN_LINEAGE_NOT_REFUSED')
                conn.execute(f'DELETE FROM {TABLE} WHERE cursor_name=%s', (name,))
                conn.commit()
            conn.execute("SET statement_timeout='120000ms'")
            report['indexed_mixed_writes'] = mixed_writes(conn, 'after')
            report['final_coverage'] = coverage_state(conn)
            require(report['final_coverage'] == report['coverage_after'], 'QUALIFICATION_CHANGED_COVERAGE_CONTENT')
            report['final_size'] = sizes(conn)
            require(financial_rows_digest(conn) == report['before_install']['financial_rows_sha256'],
                    'QUALIFICATION_CHANGED_FINANCIAL_ROWS')
            report['scope'] = 'Synthetic cursor/marker preservation and access cost; no certified economic replay or production stability claim.'
            report['wal_hot_caveat'] = ('Private intervals include ordinary cluster background WAL/CPU and differing '
                'heap/visibility histories. These are descriptive interval costs, not isolated causal index '
                'overhead; a state-dependent index can reduce HOT eligibility.')
            report['status'] = 'QUALIFIED'
            report['stage'] = 'COMPLETE'
    except Exception as error:
        report.update(status='REFUSED', exception_type=type(error).__name__)
        if isinstance(error, Refused): report['refusal_code'] = str(error)
        if report['stage'] == 'STARTING' and type(error) is RuntimeError:
            # Only fresh initdb/pg_ctl/createdb diagnostics: no application or
            # provider data has been initialized at this phase. Keep runtime
            # SQL/financial exceptions out of the private report afterward.
            detail = str(error)
            report['startup_detail'] = detail[:4096]
            report['startup_detail_truncated'] = len(detail) > 4096
    finally:
        if cluster is not None: cluster.stop()
    report['sha256'] = save(path, report, final=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'mode': 'PLAN', 'target_mib': 768, 'maximum_mib': 1280,
            'postgres': '16/en_US.utf8', 'cpu': 1, 'maximum_memory_gib': 2,
            'installer_seconds': INSTALL_SECONDS, 'overall_seconds': TOTAL_SECONDS}))
        return 0
    path = args.output
    require(path is not None and path.is_absolute() and path.parent.resolve() == path.parent
            and path.parent == Path('/evidence') and not path.exists()
            and not path.is_symlink() and not path.with_name(path.name+'.partial').exists(), 'NEW_PRIVATE_EVIDENCE_PATH_REQUIRED')
    os.umask(0o077)
    def expired(_signal, _frame): raise Refused('QUALIFICATION_900_SECOND_LIMIT')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(TOTAL_SECONDS)
    report = qualify(path)
    signal.alarm(0)
    print(json.dumps({key: report.get(key) for key in ('status', 'exception_type', 'refusal_code', 'sha256')}, sort_keys=True))
    return 0 if report['status'] == 'QUALIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
