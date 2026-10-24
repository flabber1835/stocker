"""Exact, qualification-pinned catalogs for additive operational components.

Runtime only performs SELECTs and compares complete catalog records. The capture
function is shared with the explicit private qualification tool; it never writes
DDL, changes evidence or accepts an unpinned catalog.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

SCHEMA = 'sentinel.operational-catalog/1'
CATALOG_PATH = Path(__file__).with_name('operational-catalog-v1.json')
CATALOG_SHA256 = 'ea3f77ef0d5f532d16dcc0368f383344cc4d2ec80a6ccca7160b37eaf0ce4611'


class OperationalCatalogRefused(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _require(condition, reason):
    if not condition:
        raise OperationalCatalogRefused(reason)


def _pairs(module):
    values = set(getattr(module, 'extension_trigger_pairs', module.extension_triggers))
    _require(all(isinstance(item, tuple) and len(item) == 2
                 and all(isinstance(name, str) and name for name in item) for item in values),
             'OPERATIONAL_TRIGGER_DECLARATION_INVALID')
    return values


def capture_extension(conn, module):
    """Read a deterministic exact structural witness; no data or DDL writes."""
    tables = set(module.extension_tables) | set(getattr(module, 'extension_views', ()))
    pairs = _pairs(module)
    functions = sorted(module.extension_functions)
    names = sorted(tables)
    relations = conn.execute(
        'SELECT c.relname,c.relkind,c.relpersistence,c.relispartition,c.relrowsecurity,'
        'c.relforcerowsecurity,c.relhasrules,c.reloptions '
        'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
        'WHERE n.nspname=\'public\' AND c.relname=ANY(%s) ORDER BY c.relname', (names,)).fetchall()
    columns = conn.execute(
        'SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,'
        'a.attgenerated,a.attidentity,pg_get_expr(d.adbin,d.adrelid) '
        'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
        'JOIN pg_attribute a ON a.attrelid=c.oid '
        'LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum '
        'WHERE n.nspname=\'public\' AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped '
        'ORDER BY c.relname,a.attnum', (names,)).fetchall()
    constraints = conn.execute(
        'SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,true),'
        'k.convalidated,k.condeferrable,k.condeferred,k.connoinherit '
        'FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid '
        'JOIN pg_namespace n ON n.oid=c.relnamespace '
        'WHERE n.nspname=\'public\' AND c.relname=ANY(%s) '
        'ORDER BY c.relname,k.conname', (names,)).fetchall()
    indexes = conn.execute(
        'SELECT t.relname,i.relname,pg_get_indexdef(i.oid),x.indisunique,x.indisprimary,'
        'x.indisvalid,x.indisready,x.indislive '
        'FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid '
        'JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace '
        'WHERE n.nspname=\'public\' AND t.relname=ANY(%s) ORDER BY t.relname,i.relname', (names,)).fetchall()
    all_triggers = conn.execute(
        'SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid,true),t.tgenabled '
        'FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid '
        'JOIN pg_namespace n ON n.oid=c.relnamespace '
        'WHERE n.nspname=\'public\' AND NOT t.tgisinternal '
        'AND (c.relname=ANY(%s) OR t.tgname=ANY(%s)) '
        'ORDER BY c.relname,t.tgname', (names, sorted({name for _, name in pairs}))).fetchall()
    triggers = [row for row in all_triggers if row[0] in tables or tuple(row[:2]) in pairs]
    definitions = conn.execute(
        'SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_function_result(p.oid),'
        'l.lanname,p.prokind,p.proisstrict,p.proretset,p.provolatile,p.proparallel,p.proleakproof,'
        'p.prosecdef,p.proconfig,pg_get_functiondef(p.oid) '
        'FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace '
        'JOIN pg_language l ON l.oid=p.prolang '
        'WHERE n.nspname=\'public\' AND p.proname=ANY(%s) ORDER BY p.proname,p.oid::regprocedure::text',
        (functions,)).fetchall()
    event_names = sorted(getattr(module, 'extension_event_triggers', ()))
    event_triggers = conn.execute(
        'SELECT e.evtname,e.evtevent,e.evtenabled,e.evttags,'
        'n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) '
        'FROM pg_event_trigger e JOIN pg_proc p ON p.oid=e.evtfoid '
        'JOIN pg_namespace n ON n.oid=p.pronamespace '
        'WHERE e.evtname=ANY(%s) ORDER BY e.evtname', (event_names,)).fetchall()
    views = []
    for name in sorted(getattr(module, 'extension_views', ())):
        row = conn.execute('SELECT pg_get_viewdef(to_regclass(%s),true)', ('public.'+name,)).fetchone()
        views.append([name, row[0] if row else None])
    value = {'relations': relations, 'columns': columns, 'constraints': constraints,
             'indexes': indexes, 'triggers': triggers, 'functions': definitions, 'views': views,
             'event_triggers': event_triggers}
    return json.loads(canonical(value))


def _catalog():
    raw = CATALOG_PATH.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == CATALOG_SHA256,
             'OPERATIONAL_CATALOG_PIN_CHANGED')
    value = json.loads(raw)
    _require(isinstance(value, dict) and set(value) == {'schema', 'components'}
             and value['schema'] == SCHEMA and isinstance(value['components'], dict),
             'OPERATIONAL_CATALOG_PIN_MALFORMED')
    return value['components']


def require_extension(conn, module_name, *, allow_absent=False):
    """Reject any missing, additional, disabled or semantically changed object."""
    module = importlib.import_module(module_name)
    tables = sorted(set(module.extension_tables) | set(getattr(module, 'extension_views', ())))
    found = conn.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(%s)", (tables,)).fetchone()[0]
    if not found and allow_absent:
        functions = conn.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname=ANY(%s)",
            (sorted(module.extension_functions),)).fetchone()[0]
        triggers = conn.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND t.tgname=ANY(%s)", (sorted({name for _, name in _pairs(module)}),)).fetchone()[0]
        events = conn.execute(
            'SELECT count(*) FROM pg_event_trigger WHERE evtname=ANY(%s)',
            (sorted(getattr(module, 'extension_event_triggers', ())),)).fetchone()[0]
        _require(not functions and not triggers and not events,
                 'OPERATIONAL_CATALOG_ORPHANED: '+module_name)
        marker_table = conn.execute(
            "SELECT to_regclass('public.sentinel_processed_sessions')").fetchone()[0]
        marker = marker_table and conn.execute(
            'SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s',
            ('operational-schema:v1',)).fetchone()
        authority = conn.execute(
            "SELECT to_regprocedure('public.sentinel_operational_installation_guard()') IS NOT NULL").fetchone()[0]
        _require(not marker and not authority,
                 'OPERATIONAL_INSTALLED_COMPONENT_LOST: '+module_name)
        return False
    _require(found == len(tables), 'OPERATIONAL_CATALOG_PARTIAL: '+module_name)
    expected = _catalog().get(module_name)
    _require(isinstance(expected, dict), 'OPERATIONAL_CATALOG_COMPONENT_UNQUALIFIED')
    _require(capture_extension(conn, module) == expected,
             'OPERATIONAL_CATALOG_CHANGED: '+module_name)
    return True
