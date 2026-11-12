"""Issuer child records preserve the exact installed operational contract."""
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import textwrap

import pytest

from sentinel import operational_catalog, operational_ddl_epoch, operational_schema
from sentinel import retained_input_namespaces
from sentinel.execution import issuer_admission, journal
from sentinel.feed.issuer_reference import IssuerReferenceSnapshot
from sentinel.panel import operational_schema as panel_schema
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401

PREDECESSOR = '20065ee9db6231bffe52498f1ec692fbd9933018'
# Extracted from exact Git predecessor bytes, independently of current imports.
PREDECESSOR_SOURCE_SHA256 = {
    'retained_input_namespaces.py': 'a6cf3ad730474696bc9cd99b4b46a11960f737d20af801aa8fa964a599e283a6',
    'execution/evidence_schema.py': '1ea9ff8c5105841c2726782c66e3c11b0f3131c6eb716b5e229bf514794217e8',
    'mirror_schema.py': '1fca20eaaf7a4cb029867acf4699c9491817c4cb9a7dd7c301a5f2ef6259aaf6',
    'panel/operational_schema.py': '04e1ad2e9173111c4ad71389d033bd683d16f3cf3288b92a4d071ff0b7d4e66a',
    'feed/normalized_layout.py': 'ee4c969df6fcf66aab60064fe7b081e1d85163e30fcb574585cae42c0bff1e53',
    'feed/generation_admission.py': '89e3a88e19bf74ecb241950efa46d9e6c9fb847fe882e960c1a6a9b55a3c75c7',
    'operational_ddl_epoch.py': 'b13648c84d2a677963343500320e973071668734ac5460c32dc90ddf1696abb9',
    'operational_schema.py': '2a63ef4a57d12308c85dfd828f38474caafce602369753d8de3c74bd131863aa',
    'operational_catalog.py': '9533edea8aaea8af7cef456d416c4308ea4fdeaa021f6f92e65da6aa914b3f36',
    'operational-catalog-v1.json': 'ea3f77ef0d5f532d16dcc0368f383344cc4d2ec80a6ccca7160b37eaf0ce4611',
}
# Independently read from the installed predecessor's original authenticated marker.
PREDECESSOR_CONTRACTS = {
    'sentinel.execution.evidence_schema': '1e9ed6fec6fa737400f79e2040af73bbec43855675fd7823aea34058f7d4adff',
    'sentinel.mirror_schema': '1003ffc74e39caf888d4490400c1eaddb0b3ab3d8f199b30babc406baff6669a',
    'sentinel.panel.operational_schema': '777d37fdd99199e3dd74ef7f8b3802aae6142712be82174b3df7f9f0948f628b',
    'sentinel.feed.normalized_layout': '3e1e78aac11e620aa03a2753211c3d2a8007c25e4cb326d161ea714abab9f838',
    'sentinel.feed.generation_admission': '8f302d90322ac1433f28633b25e30aebc676ee442bc1e23d74c9e2bc7f09c105',
    'sentinel.operational_ddl_epoch': '18564d7e9ffcf22c91e1b463944c3aa722aeecf2b943d6a71e55f1809c649da6',
    'sentinel.operational_schema': '255f03baf4ec3cdb74c927a7538ffea218dfbc66a910f00e948ed835aa91fd76',
}


# Remove only the reviewed presentation overlay, then retain every original
# predecessor byte hash. This is not a new pin for the financial contract.
_PRESENTATION_OVERLAY = (
    ("# Presentation metadata is not part of the immutable financial installation\n"
     "# marker. Its exact catalog is recognized when present, never silently hidden.\n"
     "PRESENTATION_COMPONENTS = ('sentinel.panel.review_schema',)\n", ''),
    ("def presentation_components():\n"
     "    return tuple(importlib.import_module(name) for name in PRESENTATION_COMPONENTS)\n\n\n", ''),
    ("    optional = presentation_components()\n"
     "    # Also detect orphaned functions/triggers when both tables were lost.\n"
     "    optional_present = [module for module in optional\n"
     "                        if module.require_schema(conn, allow_absent=True)]\n", ''),
    ('    if not present and marker is None and not optional_present:\n',
     '    if not present and marker is None:\n'),
    ('    for module in optional_present:\n'
     '        excluded_tables.update(names(module))\n'
     '        excluded_triggers.update(module.extension_triggers)\n', ''),
)


# Reverse only exact reviewed common-access-path hunks. Every predecessor
# SHA and immutable contracts pin below remains independently unchanged.
_CATALOG_START = (
    '    relations, columns, constraints, indexes, triggers = catalog\n'
    '    modules = components()\n'
    '    optional = (*presentation_components(), *access_path_components())\n')
_MARKER_CATALOG_GUARD = '''    names = lambda module: set(module.extension_tables) | set(getattr(module, 'extension_views', ()))
    present = any(names(module) & set(relations) for module in modules)
    marker_possible = 'sentinel_processed_sessions' in relations
    if marker_possible:
        required = {'cursor_name': ('text', True), 'session': ('date', True),
                    'state': ('jsonb', False)}
        observed = columns.get('sentinel_processed_sessions', {})
        if (relations['sentinel_processed_sessions'] != ('r', 'p', False, False, False)
                or any(observed.get(name, ())[:2] != definition
                       for name, definition in required.items())):
            raise InstallationCatalogRefused(
                'OPERATIONAL_INSTALLATION_CATALOG_CHANGED: sentinel_processed_sessions')
'''
_OPTIONAL_INSTALLATIONS = (
    '    # Also detect orphaned functions/triggers when both tables were lost.\n'
    '    optional_present = [module for module in optional\n'
    '                        if module.require_schema(conn, allow_absent=True)]\n')
_READ_ORDER_COMMENT = (
    '    # Optional installations read the same marker columns; validate those\n'
    "    # columns before any component can query them in the caller's transaction.\n")

_NORMALIZED_PREDECESSOR_BATCH = '''_PREDECESSOR_BATCH = (
    'SELECT session,security_id,close_signal,close_unadjusted FROM sentinel_snapshot_bars '
    'WHERE candidate_id=%s AND session<%s AND security_id=ANY(%s) ORDER BY session')


def predecessor_prices(conn, candidate_id, coordinates, *, query):
    """Resolve strictly earlier prices for all action days in one ordered scan."""
    from sentinel.feed import store

    days = sorted((date.fromisoformat(day), ids) for day, ids in coordinates.items() if ids)
    if not days:
        return {}
    securities = sorted({sid for _, ids in days for sid in ids})
    latest = {}
    result = {}
    rolling_work.checkpoint()
    with store.streaming_cursor(conn, query(_PREDECESSOR_BATCH),
                                (candidate_id, days[-1][0], securities)) as prices:
        prices = iter(prices)
        price = next(prices, None)
        consumed = 0
        for day, ids in days:
            rolling_work.checkpoint()
            while price is not None and price[0] < day:
                observed, sid, signal, raw = price
                latest[sid] = (str(observed), signal, raw)
                price = next(prices, None)
                consumed += 1
                if consumed % 5000 == 0:
                    rolling_work.checkpoint()
            result[str(day)] = [[sid, *latest[sid]] for sid in ids if sid in latest]
    return result

'''

_ACCESS_PATH_OVERLAY = {
    # The close reliability patch added a read path while retaining the DDL.
    'feed/normalized_layout.py': (
        ('import json\nfrom datetime import date\nfrom typing import Literal\n',
         'import json\nfrom typing import Literal\n'),
        (_NORMALIZED_PREDECESSOR_BATCH, ''),
    ),
    "operational_catalog.py": (
        ("\n\ndef _index_pairs(module):\n    values = getattr(module, 'extension_index_pairs', ())\n    _require(isinstance(values, (tuple, list, set, frozenset))\n             and all(isinstance(item, tuple) and len(item) == 2\n                     and all(isinstance(name, str) and name for name in item)\n                     for item in values), 'OPERATIONAL_INDEX_DECLARATION_INVALID')\n    pairs = set(values)\n    _require(len({name for _, name in pairs}) == len(pairs),\n             'OPERATIONAL_INDEX_DECLARATION_INVALID')\n    return pairs\n\n\ndef capture_extension(conn, module):\n    \"\"\"Read a deterministic exact structural witness; no data or DDL writes.\"\"\"\n    tables = set(module.extension_tables) | set(getattr(module, 'extension_views', ()))\n    pairs = _pairs(module)\n    index_pairs = _index_pairs(module)\n    functions = sorted(module.extension_functions)\n    names = sorted(tables)\n",
         "\n\ndef capture_extension(conn, module):\n    \"\"\"Read a deterministic exact structural witness; no data or DDL writes.\"\"\"\n    tables = set(module.extension_tables) | set(getattr(module, 'extension_views', ()))\n    pairs = _pairs(module)\n    functions = sorted(module.extension_functions)\n    names = sorted(tables)\n"),
        ("        'FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid '\n        'JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace '\n        'WHERE n.nspname=\\'public\\' AND (t.relname=ANY(%s) OR i.relname=ANY(%s)) '\n        'ORDER BY t.relname,i.relname',\n        (names, sorted({name for _, name in index_pairs}))).fetchall()\n    all_triggers = conn.execute(\n        'SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid,true),t.tgenabled '\n",
         "        'FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid '\n        'JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace '\n        'WHERE n.nspname=\\'public\\' AND t.relname=ANY(%s) ORDER BY t.relname,i.relname', (names,)).fetchall()\n    all_triggers = conn.execute(\n        'SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid,true),t.tgenabled '\n"),
        ("        \"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace \"\n        \"WHERE n.nspname='public' AND c.relname=ANY(%s)\", (tables,)).fetchone()[0]\n    index_pairs = _index_pairs(module)\n    found_indexes = (conn.execute(\n        \"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace \"\n        \"WHERE n.nspname='public' AND c.relname=ANY(%s)\",\n        (sorted({name for _, name in index_pairs}),)).fetchone()[0] if index_pairs else 0)\n    if not found and not found_indexes and allow_absent:\n        functions = conn.execute(\n            \"SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace \"\n",
         "        \"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace \"\n        \"WHERE n.nspname='public' AND c.relname=ANY(%s)\", (tables,)).fetchone()[0]\n    if not found and allow_absent:\n        functions = conn.execute(\n            \"SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace \"\n"),
        ("                 'OPERATIONAL_INSTALLED_COMPONENT_LOST: '+module_name)\n        return False\n    _require(found == len(tables) and found_indexes == len(index_pairs),\n             'OPERATIONAL_CATALOG_PARTIAL: '+module_name)\n    expected = _catalog().get(module_name)\n    _require(isinstance(expected, dict), 'OPERATIONAL_CATALOG_COMPONENT_UNQUALIFIED')\n    actual = capture_extension(conn, module)\n    _require(index_pairs <= {tuple(row[:2]) for row in actual['indexes']},\n             'OPERATIONAL_CATALOG_CHANGED: '+module_name)\n    _require(actual == expected,\n             'OPERATIONAL_CATALOG_CHANGED: '+module_name)\n    return True\n",
         "                 'OPERATIONAL_INSTALLED_COMPONENT_LOST: '+module_name)\n        return False\n    _require(found == len(tables), 'OPERATIONAL_CATALOG_PARTIAL: '+module_name)\n    expected = _catalog().get(module_name)\n    _require(isinstance(expected, dict), 'OPERATIONAL_CATALOG_COMPONENT_UNQUALIFIED')\n    _require(capture_extension(conn, module) == expected,\n             'OPERATIONAL_CATALOG_CHANGED: '+module_name)\n    return True\n"),
    ),
    "operational_schema.py": (
        ("# marker. Its exact catalog is recognized when present, never silently hidden.\nPRESENTATION_COMPONENTS = ('sentinel.panel.review_schema',)\n# Access paths have independent installation witnesses; never re-sign the\n# original immutable operational contracts map to add one.\nACCESS_PATH_COMPONENTS = ('sentinel.checkpoint_lineage_access',)\n_LOCK = (1397706832, 1330660145)\n_FUNCTION = 'sentinel_operational_installation_guard'\n",
         "# marker. Its exact catalog is recognized when present, never silently hidden.\nPRESENTATION_COMPONENTS = ('sentinel.panel.review_schema',)\n_LOCK = (1397706832, 1330660145)\n_FUNCTION = 'sentinel_operational_installation_guard'\n"),
        ("\n\ndef access_path_components():\n    return tuple(importlib.import_module(name) for name in ACCESS_PATH_COMPONENTS)\n\n\ndef contracts():\n    return {module.__name__: hashlib.sha256(_canonical(list(module.DDL))).hexdigest()\n",
         "\n\ndef contracts():\n    return {module.__name__: hashlib.sha256(_canonical(list(module.DDL))).hexdigest()\n"),
        # Reverse only the exact reviewed read-order correction before applying
        # the original closed overlay. Every historical digest stays unchanged.
        (_CATALOG_START + _MARKER_CATALOG_GUARD + _READ_ORDER_COMMENT + _OPTIONAL_INSTALLATIONS,
         _CATALOG_START + _OPTIONAL_INSTALLATIONS + _MARKER_CATALOG_GUARD),
        ("    relations, columns, constraints, indexes, triggers = catalog\n    modules = components()\n    optional = (*presentation_components(), *access_path_components())\n    # Also detect orphaned functions/triggers when both tables were lost.\n    optional_present = [module for module in optional\n",
         "    relations, columns, constraints, indexes, triggers = catalog\n    modules = components()\n    optional = presentation_components()\n    # Also detect orphaned functions/triggers when both tables were lost.\n    optional_present = [module for module in optional\n"),
        ("        return catalog\n    excluded_tables = set()\n    excluded_indexes = set()\n    from sentinel.operational_catalog import _index_pairs\n    excluded_triggers = {('sentinel_processed_sessions', _TRIGGER),\n                         ('sentinel_processed_sessions', _TRUNCATE_TRIGGER)} if marker else set()\n",
         "        return catalog\n    excluded_tables = set()\n    excluded_triggers = {('sentinel_processed_sessions', _TRIGGER),\n                         ('sentinel_processed_sessions', _TRUNCATE_TRIGGER)} if marker else set()\n"),
        ("        excluded_tables.update(names(module))\n        excluded_triggers.update(module.extension_triggers)\n        excluded_indexes.update(_index_pairs(module))\n    for module in modules:\n        active = bool(names(module) & set(relations))\n",
         "        excluded_tables.update(names(module))\n        excluded_triggers.update(module.extension_triggers)\n    for module in modules:\n        active = bool(names(module) & set(relations))\n"),
        ("            excluded_tables.update(names(module))\n            excluded_triggers.update(getattr(module, 'extension_trigger_pairs', module.extension_triggers))\n            excluded_indexes.update(_index_pairs(module))\n    def without_extensions(mapping):\n        return {name: value for name, value in mapping.items() if name not in excluded_tables}\n",
         "            excluded_tables.update(names(module))\n            excluded_triggers.update(getattr(module, 'extension_trigger_pairs', module.extension_triggers))\n    def without_extensions(mapping):\n        return {name: value for name, value in mapping.items() if name not in excluded_tables}\n"),
        ("        name: {key: value for key, value in values.items() if (name, key) not in excluded_triggers}\n        for name, values in triggers.items() if name not in excluded_tables}\n    filtered_indexes = {\n        name: {key: value for key, value in values.items() if (name, key) not in excluded_indexes}\n        for name, values in indexes.items() if name not in excluded_tables}\n    return (*(without_extensions(item) for item in (relations, columns, constraints)),\n            filtered_indexes, filtered_triggers)\n\n\n",
         "        name: {key: value for key, value in values.items() if (name, key) not in excluded_triggers}\n        for name, values in triggers.items() if name not in excluded_tables}\n    return (*(without_extensions(item) for item in (relations, columns, constraints, indexes)),\n            filtered_triggers)\n\n\n"),
        ("\n\ndef _require_quiescence(conn):\n    uncertain = conn.execute(\n        \"SELECT COUNT(*) FROM sentinel_commands WHERE state IN \"\n        \"('SEND_PENDING','UNKNOWN','ACKNOWLEDGED','PARTIALLY_FILLED','CANCEL_PENDING')\"\n    ).fetchone()[0]\n    active_jobs = conn.execute(\n        \"SELECT COUNT(*) FROM sentinel_snapshot_jobs WHERE state NOT IN \"\n        \"('PUBLISHED','REFUSED','ABORTED') AND reason<>'COMPARISON_ONLY'\"\n    ).fetchone()[0]\n    active_cycles = conn.execute(\n        \"SELECT COUNT(*) FROM sentinel_automation_cycles WHERE state NOT IN \"\n        \"('WAITING_OPEN','SUCCEEDED','MISSED_STATE_ONLY','SUPERSEDED','BLOCKED')\"\n    ).fetchone()[0]\n    _require(not uncertain and not active_jobs and not active_cycles,\n             'OPERATIONAL_MIGRATION_REQUIRES_QUIESCENCE')\n\n\ndef _install_access_paths(conn, original, *, quiescent=False):\n    pending = [module for module in access_path_components()\n               if not module.require_schema(conn, allow_absent=True)]\n    if not pending:\n        return\n    if not quiescent:\n        _require_quiescence(conn)\n    for module in pending:\n        module.install(conn)\n        _require(module.require_schema(conn, allow_absent=False) is not False,\n                 'OPERATIONAL_ACCESS_PATH_ABSENT: '+module.__name__)\n    _require(installation(conn, required=True) == original,\n             'OPERATIONAL_INSTALLATION_CHANGED_DURING_ACCESS_PATH_INSTALL')\n\n\ndef install_quiescent(conn):\n    \"\"\"Explicit additive extension install under the existing single writer.\n",
         "\n\ndef install_quiescent(conn):\n    \"\"\"Explicit additive extension install under the existing single writer.\n"),
        ("            if current is not None:\n                require_schema(conn)\n                _install_access_paths(conn, current)\n                return current\n            _require_quiescence(conn)\n            for module in components():\n                module.install(conn)\n",
         "            if current is not None:\n                require_schema(conn)\n                return current\n            uncertain = conn.execute(\n                \"SELECT COUNT(*) FROM sentinel_commands WHERE state IN \"\n                \"('SEND_PENDING','UNKNOWN','ACKNOWLEDGED','PARTIALLY_FILLED','CANCEL_PENDING')\"\n            ).fetchone()[0]\n            active_jobs = conn.execute(\n                \"SELECT COUNT(*) FROM sentinel_snapshot_jobs WHERE state NOT IN \"\n                \"('PUBLISHED','REFUSED','ABORTED') AND reason<>'COMPARISON_ONLY'\"\n            ).fetchone()[0]\n            active_cycles = conn.execute(\n                \"SELECT COUNT(*) FROM sentinel_automation_cycles WHERE state NOT IN \"\n                \"('WAITING_OPEN','SUCCEEDED','MISSED_STATE_ONLY','SUPERSEDED','BLOCKED')\"\n            ).fetchone()[0]\n            _require(not uncertain and not active_jobs and not active_cycles,\n                     'OPERATIONAL_MIGRATION_REQUIRES_QUIESCENCE')\n            for module in components():\n                module.install(conn)\n"),
        ("                    'hmac_sha256': _signature(value)}).decode('ascii')))\n            require_schema(conn)\n            _install_access_paths(conn, value, quiescent=True)\n            return value\n",
         "                    'hmac_sha256': _signature(value)}).decode('ascii')))\n            require_schema(conn)\n            return value\n"),
    ),
}



def _predecessor_bytes(name, raw):
    if name in _ACCESS_PATH_OVERLAY:
        text = raw.decode('utf-8')
        for current, previous in _ACCESS_PATH_OVERLAY[name]:
            assert text.count(current) == 1, 'access-path overlay changed'
            text = text.replace(current, previous)
        raw = text.encode('utf-8')
    if name == 'operational_schema.py':
        text = raw.decode('utf-8')
        for current, previous in _PRESENTATION_OVERLAY:
            assert text.count(current) == 1, 'presentation overlay changed'
            text = text.replace(current, previous)
        return text.encode('utf-8')
    if name == 'operational_catalog.py':
        current = "CATALOG_SHA256 = '"+operational_catalog.CATALOG_SHA256+"'"
        assert raw.count(current.encode()) == 1
        return raw.replace(current.encode(), ("CATALOG_SHA256 = '"+
            PREDECESSOR_SOURCE_SHA256['operational-catalog-v1.json']+"'").encode())
    if name == 'operational-catalog-v1.json':
        value = json.loads(raw)
        assert value['components'].pop('sentinel.panel.review_schema')
        assert value['components'].pop('sentinel.checkpoint_lineage_access')
        return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode('ascii')
    return raw


def assert_predecessor_contracts():
    root = Path(operational_schema.__file__).resolve().parent
    for name, expected in PREDECESSOR_SOURCE_SHA256.items():
        assert hashlib.sha256(_predecessor_bytes(name, (root/name).read_bytes())).hexdigest() == expected, (PREDECESSOR, name)
    assert operational_schema.contracts() == PREDECESSOR_CONTRACTS
    assert operational_catalog.CATALOG_SHA256 == hashlib.sha256(
        (root/'operational-catalog-v1.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('name,old,new', [
    ('operational_schema.py', b"'sentinel.mirror_schema',", b"'sentinel.changed_schema',"),
    ('operational_catalog.py', b'expected = _catalog()', b'expected = {}'),
    ('operational-catalog-v1.json', b'sentinel_operational_read_revisions', b'changed_operational_read_revisions'),
])
def test_presentation_overlay_cannot_hide_predecessor_contract_edits(name, old, new):
    root = Path(operational_schema.__file__).resolve().parent
    raw = (root/name).read_bytes()
    assert old in raw
    if name == 'operational_catalog.py':
        with pytest.raises(AssertionError, match='access-path overlay changed'):
            _predecessor_bytes(name, raw.replace(old, new))
        return
    assert hashlib.sha256(_predecessor_bytes(name, raw.replace(old,new))).hexdigest() != PREDECESSOR_SOURCE_SHA256[name]


@pytest.mark.parametrize('name,old,new', [
    ('operational_catalog.py', b'index_pairs <=', b'set() <='),
    ('operational_schema.py', b'if not quiescent:', b'if False:'),
    ('operational_schema.py', b'(name, key) not in excluded_indexes', b'False'),
    ('operational_schema.py', b"'state': ('jsonb', False)", b"'state': ('text', False)"),
    ('operational_schema.py', b'if marker_possible:', b'if False:'),
    ('feed/normalized_layout.py', b'price[0] < day:', b'price[0] <= day:'),
])
def test_access_path_overlay_cannot_hide_changed_ownership_or_install_guards(name, old, new):
    root = Path(operational_schema.__file__).resolve().parent
    raw = (root/name).read_bytes()
    assert old in raw
    with pytest.raises(AssertionError, match='access-path overlay changed'):
        _predecessor_bytes(name, raw.replace(old, new))


def test_issuer_storage_keeps_exact_predecessor_sources_catalog_and_contracts():
    assert_predecessor_contracts()
    assert not any(prefix.startswith('issuer-')
        for prefix in retained_input_namespaces.PAPER_CURSOR_PREFIXES)
    assert all(prefix.startswith('protected-buy-funding:v1:issuer-policy:v1:')
        for prefix in issuer_admission.PREFIXES)


def test_native_sec_cache_updates_advance_only_paper_without_changing_retained_contracts(conn,monkeypatch):
    from sentinel.execution import issuer_refresh
    from tests.sentinel.test_issuer_refresh import EMAIL,NOW,Opener,setup
    assert_predecessor_contracts()
    installed=operational_schema.install_quiescent(conn)
    marker=conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (operational_schema.CURSOR,)).fetchone()
    epoch=operational_ddl_epoch.current(conn)
    revisions=dict(conn.execute('SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    conn.rollback()
    setup(conn,monkeypatch)
    assert issuer_refresh.collect(conn,email=EMAIL,now=NOW,opener=Opener())['status']=='REFRESHED'
    after=dict(conn.execute('SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    assert after['PAPER']>revisions['PAPER'] and after['SHADOW']==revisions['SHADOW']
    assert operational_ddl_epoch.current(conn)==epoch
    assert conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (operational_schema.CURSOR,)).fetchone()==marker
    assert operational_schema.installation(conn)==installed
    assert operational_schema.require_schema(conn)
    assert_predecessor_contracts()


def test_private_issuer_appends_advance_only_paper_without_schema_or_epoch_change(conn):
    from tests.sentinel.test_issuer_admission import (
        BINDING, NOW, instruments, prepare, reconciliation, state,
    )

    assert_predecessor_contracts()

    installation = operational_schema.install_quiescent(conn)
    assert installation['contracts'] == PREDECESSOR_CONTRACTS
    before_marker = conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (operational_schema.CURSOR,)).fetchone()
    before_revisions = dict(conn.execute(
        'SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    before_epoch = operational_ddl_epoch.current(conn)
    conn.rollback()
    source = IssuerReferenceSnapshot.create(observed_at_utc=NOW,
        associations=[dict(cik='0000000001', ticker=ticker, exchange='NYSE')
            for ticker in ('AAA', 'AAA-A')], coverage='PARTIAL',
        source_method='WEB_EXTRACTED_REPRESENTATION')
    # The fixture owns only this freshly created private database. Exercise the
    # production append paths under their actual database writer lock.
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (journal.WRITER_LOCK_KEY,))
        issuer_admission.enroll(conn, binding=BINDING, state=state(),
            reconciliation=reconciliation(), snapshot=source, instruments=instruments(), now=NOW)
        _state, _plan, _projection, evidence = prepare(conn, source, pending=('A', 'A2'))
        denied = issuer_admission.check_buy(conn, evidence=evidence, security_id='A2',
            reconciliation=reconciliation(), now=NOW)
        assert not denied.allowed
        admitted = issuer_admission.check_buy(conn, evidence=evidence, security_id='A',
            reconciliation=reconciliation(), now=NOW, reserve=True)
        assert admitted.allowed
    for prefix in issuer_admission.PREFIXES:
        assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
            (prefix+'%',)).fetchone()[0] > 0
    after_revisions = dict(conn.execute(
        'SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
    assert after_revisions['PAPER'] > before_revisions['PAPER']
    assert after_revisions['SHADOW'] == before_revisions['SHADOW']
    assert operational_ddl_epoch.current(conn) == before_epoch
    assert conn.execute('SELECT session,state,updated_at FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (operational_schema.CURSOR,)).fetchone() == before_marker
    assert operational_schema.installation(conn) == installation
    assert operational_schema.require_schema(conn)
    for name in PREDECESSOR_CONTRACTS:
        assert operational_catalog.require_extension(conn, name)
        expected = operational_catalog._catalog()[name]
        assert operational_catalog.capture_extension(conn, importlib.import_module(name)) == expected
    assert_predecessor_contracts()


@pytest.mark.parametrize('deny,reserve',[(False,False),(True,False),(False,True)])
def test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,deny,reserve):
    from contextlib import closing
    from sentinel.execution import issuer_runtime
    from sentinel.execution.contract import BrokerInstrument
    from sentinel.feed import store
    from tests.sentinel.test_issuer_admission import BINDING,NOW,instruments,prepare,reconciliation,state

    operational_schema.install_quiescent(conn)
    source=IssuerReferenceSnapshot.create(observed_at_utc=NOW,
        associations=[dict(cik='0000000001',ticker='UNCOVERED' if deny else 'AAA',exchange='NYSE')])
    conn.execute('SELECT pg_advisory_lock(%s)',(journal.WRITER_LOCK_KEY,))
    try:
        issuer_admission.enroll(conn,binding=BINDING,state=state(),
            reconciliation=reconciliation(),snapshot=source,instruments=instruments(),now=NOW)
        conn.commit()
        current,plan,projection,_evidence=prepare(conn,source,pending=('A',))
        context=issuer_runtime.PaperIssuerAdmission(conn=conn,binding=BINDING,clock=lambda:NOW)
        context.prepare_for_transport(publication=None,state=current,plan=plan,
            projection=projection,reconciliation=reconciliation())
        assert context.evidence is not None and context.error is None
        if deny or reserve:
            decision=context.check_buy(security_id='A',reconciliation=reconciliation(),
                instruments={'A':BrokerInstrument('A','AAA','native-A')},reserve=True)
            if deny:
                assert not decision.allowed and decision.reason=='ISSUER_IDENTITY_UNRESOLVED'
            else:
                assert decision.allowed
        # This is the real dependency/trigger written by fresh guarded reads.
        # The second connection must complete while the session writer remains.
        with closing(store.connect(conn.info.dsn)) as fresh:
            if reserve:
                assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions '
                    'WHERE cursor_name LIKE %s',(issuer_admission.CLAIM_PREFIX+'%',)).fetchone()[0]==1
                assert fresh.execute('SELECT count(*) FROM sentinel_processed_sessions '
                    'WHERE cursor_name LIKE %s',(issuer_admission.CLAIM_PREFIX+'%',)).fetchone()[0]==0
                issuer_admission._lock(conn)
                assert not journal.load_commands(conn,BINDING)
                return
            fresh.execute("SET LOCAL lock_timeout='250ms'")
            fresh.execute("UPDATE sentinel_automation_control SET authority_verdict='PASS',"
                          "authority_detail='private fresh broker read' WHERE id=1")
            fresh.commit()
        issuer_admission._lock(conn)
        assert not journal.load_commands(conn,BINDING)
        assert_predecessor_contracts()
    finally:
        conn.rollback()
        conn.execute('SELECT pg_advisory_unlock(%s)',(journal.WRITER_LOCK_KEY,))
        conn.commit()


def test_removing_pre_transport_metadata_commit_is_detected(conn,monkeypatch):
    import psycopg
    from sentinel.execution import issuer_runtime
    source=textwrap.dedent(inspect.getsource(issuer_runtime.PaperIssuerAdmission.prepare_for_transport))
    guard='    self.conn.commit()'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'    pass'),'<missing issuer preparation commit>','exec'),
         issuer_runtime.__dict__,namespace)
    monkeypatch.setattr(issuer_runtime.PaperIssuerAdmission,'prepare_for_transport',
                        namespace['prepare_for_transport'])
    with pytest.raises(psycopg.errors.LockNotAvailable):
        test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,False,False)


def test_removing_denied_shortfall_commit_is_detected(conn,monkeypatch):
    import psycopg
    from sentinel.execution import issuer_runtime
    source=textwrap.dedent(inspect.getsource(issuer_runtime.PaperIssuerAdmission.check_buy))
    guard='        self.conn.commit()'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'        pass'),'<missing issuer shortfall commit>','exec'),
         issuer_runtime.__dict__,namespace)
    monkeypatch.setattr(issuer_runtime.PaperIssuerAdmission,'check_buy',namespace['check_buy'])
    with pytest.raises(psycopg.errors.LockNotAvailable):
        test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,True,False)


def test_committing_an_admitted_reservation_before_its_command_is_detected(conn,monkeypatch):
    from sentinel.execution import issuer_runtime
    source=textwrap.dedent(inspect.getsource(issuer_runtime.PaperIssuerAdmission.check_buy))
    guard='if decision.allowed is not True:'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'if True:'),'<premature issuer reservation commit>','exec'),
         issuer_runtime.__dict__,namespace)
    monkeypatch.setattr(issuer_runtime.PaperIssuerAdmission,'check_buy',namespace['check_buy'])
    with pytest.raises(AssertionError):
        test_prepared_issuer_metadata_does_not_block_fresh_authority_verdict(conn,monkeypatch,False,True)


def test_top_level_issuer_registration_contract_change_is_detected(monkeypatch):
    original = retained_input_namespaces.PAPER_CURSOR_PREFIXES
    assert_predecessor_contracts()
    try:
        monkeypatch.setattr(retained_input_namespaces, 'PAPER_CURSOR_PREFIXES',
            (*original, 'issuer-admission-enrollment:v1:'))
        importlib.reload(panel_schema)
        with pytest.raises(AssertionError):
            assert_predecessor_contracts()
        changed = operational_schema.contracts()
        assert {name for name in changed if changed[name] != PREDECESSOR_CONTRACTS[name]} == {
            'sentinel.panel.operational_schema'}
    finally:
        monkeypatch.setattr(retained_input_namespaces, 'PAPER_CURSOR_PREFIXES', original)
        importlib.reload(panel_schema)
    assert_predecessor_contracts()
