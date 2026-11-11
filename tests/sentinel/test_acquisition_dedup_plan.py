"""Real PostgreSQL selection and planning of the production price-part lookup."""
import ast
import inspect
import textwrap
from uuid import uuid4

import pytest

from sentinel.feed import acquisition_parts as parts
from sentinel.feed.rolling_contract import canonical_json, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, enqueue, pg

__all__ = ['conn', 'pg']

COMPONENT = 'SEP.2025-03-12.2025-03-31'
CONTENT = 'b' * 64
NEW_PART = 'f' * 64


def production_query():
    """Exercise the actual SQL used by put(), including its omission mutants."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(parts.Parts.put)))
    values = [node.args[0].value for node in ast.walk(tree)
              if isinstance(node, ast.Call) and node.args
              and isinstance(node.func, ast.Attribute) and node.func.attr == 'execute'
              and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and 'SELECT a.part_id' in node.args[0].value
              and 'sentinel_acquisition_prices' in node.args[0].value]
    assert len(values) == 1
    return values[0]


def replace_once(statement, before, after):
    assert statement.count(before) == 1
    return statement.replace(before, after)


def candidate(conn, *, component=COMPONENT, content=CONTENT, declared=2,
              stored=2, pinned=False, linked=False, excluded=False, age=0):
    job = enqueue(conn) if pinned else str(uuid4())
    manifest = dict(schema=parts.SCHEMA, job_id=job, component=component,
                    generation={}, content_sha256=content,
                    reference_sha256=None, rows=declared, evidence=None)
    part_id = NEW_PART if excluded else digest(manifest)
    conn.execute('INSERT INTO sentinel_acquisition_parts(part_id,manifest,created_at) '
                 "VALUES(%s,%s::jsonb,clock_timestamp()-(%s*interval '1 second'))",
                 (part_id, canonical_json(manifest), age))
    if stored:
        conn.execute("INSERT INTO sentinel_acquisition_prices(part_id,session,ticker,payload) "
                     "SELECT %s,'2025-03-12'::date,'T'||n,'{}' FROM generate_series(1,%s) n",
                     (part_id, stored))
    if pinned:
        conn.execute('INSERT INTO sentinel_acquisition_bindings VALUES(%s,%s,%s)',
                     (job, component, part_id))
    if linked:
        target = candidate(conn, component='OTHER')
        # Deliberately invalid linked-and-owned storage tests the explicit
        # anti-link guard independently of the ordinary insertion trigger.
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('INSERT INTO sentinel_acquisition_price_links VALUES(%s,%s)',
                     (part_id, target))
        conn.execute('SET LOCAL session_replication_role=origin')
    return part_id


def selected(conn, statement=None):
    return conn.execute(statement or production_query(),
                        (COMPONENT, CONTENT, '2', NEW_PART)).fetchone()


@pytest.mark.parametrize('case,changes,eligible', [
    ('complete_unpinned', {}, True),
    ('complete_pinned', {'pinned': True}, True),
    ('other_component', {'component': 'SEP.2025-04-01.2025-04-30'}, False),
    ('other_content', {'content': 'c' * 64}, False),
    ('other_row_count', {'declared': 3, 'stored': 3}, False),
    ('self', {'excluded': True}, False),
    ('linked', {'linked': True}, False),
    ('empty', {'stored': 0, 'pinned': True}, False),
    ('partial_orphan', {'stored': 1}, False),
    # Selecting a pinned incomplete part is intentional: subsequent byte
    # verification must diagnose corruption instead of silently replacing it.
    ('partial_pinned', {'stored': 1, 'pinned': True}, True),
])
def test_lookup_preserves_each_candidate_boundary(conn, case, changes, eligible):
    part_id = candidate(conn, **changes)
    assert selected(conn) == ((part_id,) if eligible else None), case


def test_lookup_keeps_earliest_complete_owner_order(conn):
    candidate(conn, age=10)
    oldest = candidate(conn, age=30)
    candidate(conn, age=20)
    assert selected(conn) == (oldest,)


@pytest.mark.parametrize('case,changes,needle,replacement,eligible', [
    ('component', {'component': 'OTHER'}, "a.manifest->>'component'=%s", '%s::text IS NOT NULL', False),
    ('content', {'content': 'c' * 64}, "a.manifest->>'content_sha256'=%s", '%s::text IS NOT NULL', False),
    ('row_count', {'declared': 3, 'stored': 3}, "a.manifest->>'rows'=%s", '%s::text IS NOT NULL', False),
    ('self', {'excluded': True}, 'a.part_id<>%s', '%s::text IS NOT NULL', False),
    ('anti_link', {'linked': True},
     'NOT EXISTS(SELECT 1 FROM sentinel_acquisition_price_links l WHERE l.part_id=a.part_id)',
     'TRUE', False),
    ('existence', {'stored': 0, 'pinned': True},
     '(SELECT true FROM sentinel_acquisition_prices p WHERE p.part_id=a.part_id LIMIT 1) IS TRUE',
     'TRUE', False),
    ('completeness', {'stored': 1}, 'sentinel_acquisition_part_pinned(a.part_id) OR ', 'TRUE OR ', False),
    ('pinned_corruption', {'stored': 1, 'pinned': True},
     'sentinel_acquisition_part_pinned(a.part_id) OR ', '', True),
])
def test_executed_omission_falsifiers(conn, case, changes, needle, replacement, eligible):
    part_id = candidate(conn, **changes)
    expected = (part_id,) if eligible else None
    assert selected(conn) == expected
    mutant = replace_once(production_query(), needle, replacement)
    # The same selection oracle must reject the executed production mutant.
    with pytest.raises(AssertionError):
        assert selected(conn, mutant) == expected, case


def nodes(plan):
    yield plan
    for child in plan.get('Plans', []):
        yield from nodes(child)


def explain(conn, statement):
    return conn.execute('EXPLAIN (FORMAT JSON) '+statement,
                        (COMPONENT, CONTENT, '2', NEW_PART)).fetchone()[0][0]['Plan']


def require_bounded_price_access(plan):
    price_nodes = [node for node in nodes(plan)
                   if node.get('Relation Name') == 'sentinel_acquisition_prices']
    assert price_nodes
    for node in price_nodes:
        if node['Node Type'] == 'Bitmap Heap Scan':
            assert 'part_id' in node.get('Recheck Cond', '')
            assert any(child['Node Type'] == 'Bitmap Index Scan'
                       and child.get('Index Name') == 'sentinel_acquisition_prices_pkey'
                       and 'part_id' in child.get('Index Cond', '') for child in nodes(node))
        else:
            assert node['Node Type'] in {'Index Scan', 'Index Only Scan'}, node
            assert 'part_id' in node.get('Index Cond', ''), node


def legacy_global_existence(statement):
    statement = replace_once(statement, 'WITH candidate_parts AS MATERIALIZED (', '')
    statement = replace_once(statement,
        'SELECT a.part_id,a.created_at,a.manifest FROM ', 'SELECT a.part_id FROM ')
    statement = replace_once(statement,
        ') SELECT a.part_id FROM candidate_parts a WHERE ', ' AND ')
    return replace_once(statement,
        '(SELECT true FROM sentinel_acquisition_prices p WHERE p.part_id=a.part_id LIMIT 1) IS TRUE',
        'EXISTS(SELECT 1 FROM sentinel_acquisition_prices p WHERE p.part_id=a.part_id)')


def test_large_catalog_plan_and_old_query_falsifier(conn):
    candidate(conn, stored=0)
    for index in range(293):
        candidate(conn, component='OTHER.'+str(index), stored=0)
    conn.execute("INSERT INTO sentinel_acquisition_prices(part_id,session,ticker,payload) "
                 "SELECT part_id,'2025-03-12'::date,'T1','{}' FROM sentinel_acquisition_parts")
    # A tiny sample otherwise records a *fractional* distinct estimate, which
    # would incorrectly grow to millions of part IDs when modeling 31M prices.
    conn.execute('ALTER TABLE sentinel_acquisition_prices ALTER COLUMN part_id '
                 'SET (n_distinct=262)')
    conn.execute('ANALYZE sentinel_acquisition_parts')
    conn.execute('ANALYZE sentinel_acquisition_prices')
    # Isolated ephemeral database only: model the captured 31M-row catalog
    # cardinality without loading production history or running a heavy query.
    # Keep physical page counts accurate so estimates are not scaled downward.
    conn.execute("UPDATE pg_class SET reltuples=31429121 WHERE oid="
                 "'sentinel_acquisition_prices'::regclass")
    conn.execute("UPDATE pg_class SET reltuples=31429121 WHERE oid="
                 "'sentinel_acquisition_prices_pkey'::regclass")
    conn.execute('SET LOCAL max_parallel_workers_per_gather=0')
    require_bounded_price_access(explain(conn, production_query()))
    # Exercise the pulled-up semi-join alternative independently of the tiny
    # fixture's physical heap/cache cost. Production selected global enumeration
    # under ordinary planning; the new shape must also stay bounded when join
    # costing changes. No production setting is changed, and neither old query
    # nor its hypothetical 31M-row scan is executed.
    conn.execute('SET LOCAL enable_nestloop=off')
    require_bounded_price_access(explain(conn, production_query()))
    legacy = explain(conn, legacy_global_existence(production_query()))
    assert any(node.get('Relation Name') == 'sentinel_acquisition_prices'
               and node.get('Plan Rows', 0) > 1_000_000
               and 'part_id' not in node.get('Index Cond', '')
               and 'part_id' not in node.get('Recheck Cond', '')
               for node in nodes(legacy)), legacy
    with pytest.raises(AssertionError):
        require_bounded_price_access(legacy)
