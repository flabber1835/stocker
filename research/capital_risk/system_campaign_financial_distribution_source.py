"""Exact own-parent terminal/distribution source witnesses; never financial authority."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal
import zipfile

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = 'research.own-parent-frozen-source-witnesses/6'
FILE = 'source-witnesses.json'
PARSER_SHA = '5381b3b41b14cfc2f9d9d6e97c35929c9acc3d237d6df359a9ad7e6d0e4df7ec'
ACTIONS_SHA = 'ec6f1d96c0beed8bf4baba45a55cc56a881f001d27456b9630471d69e2d46139'
ACTIONS_BYTES = 5322055
HASH = r'^[0-9a-f]{64}$'
DAY = r'^\d{4}-\d{2}-\d{2}$'


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


class NativeDistributionQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.exact-native-distribution-query/1'] = Field(alias='schema')
    session: Annotated[str, Field(pattern=DAY)]
    parent_security_id: Annotated[str, Field(min_length=1)]
    parent_ticker: Annotated[str, Field(min_length=1)]
    source_row_id: Annotated[str, Field(pattern=HASH)]
    native_term_sha256: Annotated[str, Field(pattern=HASH)]
    raw_source_row_sha256: Annotated[str, Field(pattern=HASH)]
    maximum_records: Literal[1]
    financial_use_authorized: Literal[False]


def validate_scope(scope):
    need(set(scope) == {'parent_outer_sha256', 'parent_cursor', 'terms',
                       'additional_rows', 'native_distribution_queries'},
         'DISTRIBUTION_SOURCE_EXACT_SCOPE_FIELDS')
    day = scope['parent_cursor']
    need(date.fromisoformat(day).isoformat() == day
         and len(scope['parent_outer_sha256']) == 64
         and all(c in '0123456789abcdef' for c in scope['parent_outer_sha256']),
         'DISTRIBUTION_SOURCE_EXACT_PARENT_BINDING_SHAPE')
    need(len(scope['terms']) == len(scope['native_distribution_queries']) == 1,
         'DISTRIBUTION_SOURCE_ONE_COMPOUND_SOURCE')
    terminal, query = scope['terms'][0], scope['native_distribution_queries'][0]
    NativeDistributionQuery.model_validate(query)
    need(type(query['maximum_records']) is int and query['maximum_records'] == 1
         and query['financial_use_authorized'] is False
         and terminal['security_id'] == query['parent_security_id']
         and terminal['ticker'] == query['parent_ticker']
         and day < terminal['session'] < terminal['native_session'] <= query['session'],
         'DISTRIBUTION_SOURCE_EXACT_UNCONSUMED_TWO_LEGS')
    need(set(terminal) == {'session', 'native_session', 'security_id', 'ticker',
                          'native_term_sha256', 'parent_positions'}
         and len(terminal['native_term_sha256']) == 64
         and all(c in '0123456789abcdef' for c in terminal['native_term_sha256']),
         'DISTRIBUTION_SOURCE_KNOWN_TERMINAL_PREIMAGE')
    keys = {(r['session'], r['security_id']) for r in scope['additional_rows']}
    need(len(keys) == len(scope['additional_rows']) == 3
         and (terminal['session'], terminal['security_id']) not in keys
         and all(set(r) == {'session', 'security_id', 'ticker', 'source_observation_sha256', 'parent_positions'}
                 and day < r['session'] for r in scope['additional_rows'])
         and sum(r['security_id'] == terminal['security_id'] for r in scope['additional_rows']) == 1,
         'DISTRIBUTION_SOURCE_THREE_EXACT_DISTINCT_ADDITIONAL_ROWS')
    return terminal, query


def identity(row, declared, held):
    need(row['session'] == declared['session'] and row['security_id'] == declared['security_id']
         and row['ticker'] == declared['ticker']
         and row['security_type_eligible'] in ('0', '1')
         and type(row['issuer_id']) is str
         and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session'])
         and held == declared['parent_positions'],
         'DISTRIBUTION_SOURCE_UNMODIFIED_IDENTITY_AND_ACTUAL_ROLE')
    if 'source_observation_sha256' in declared:
        need(digest(row) == declared['source_observation_sha256'],
             'DISTRIBUTION_SOURCE_FULL_OBSERVATION_DIGEST')
    witness = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                  'listing_first_session', 'security_type_eligible')}
    witness['source_observation_sha256'] = digest(row)
    return dict(source_row=deepcopy(row), identity_witness=witness, parent_positions=deepcopy(held))


def distribution_material(query, source_row, native):
    fields = {'session', 'parent_ticker', 'parent_security_id', 'child_ticker',
              'child_security_id', 'source_row_id', 'value_evidence',
              'child_shares_per_parent', 'child_price', 'cash_in_lieu_price', 'policy'}
    need(set(native) == fields and native['session'] == query['session']
         and native['parent_security_id'] == query['parent_security_id']
         and native['parent_ticker'] == query['parent_ticker']
         and native['source_row_id'] == query['source_row_id']
         and digest(native) == query['native_term_sha256']
         and native['policy'] == 'REQUIRE_REVIEWED_CHILD_OWNERSHIP'
         and all(native[k] is None for k in ('child_ticker', 'child_security_id',
                                            'child_shares_per_parent', 'child_price', 'cash_in_lieu_price')),
         'DISTRIBUTION_SOURCE_EXACT_UNRESOLVED_NATIVE_PREIMAGE')
    need(source_row['action'].lower() in ('spinoff', 'spinoffdividend')
         and source_row['effective_session'] == query['session']
         and source_row['security_id'] == query['parent_security_id']
         and source_row['ticker'] == query['parent_ticker']
         and source_row['vendor_value'] == native['value_evidence']
         and digest(source_row) == query['raw_source_row_sha256']
         and sha(json.dumps(source_row, sort_keys=True).encode()) == query['source_row_id'],
         'DISTRIBUTION_SOURCE_EXACT_RAW_ROW_AND_ORIGINAL_PARSER_HASH')
    return dict(raw_source_row=deepcopy(source_row), raw_source_row_sha256=digest(source_row),
                native_distribution=deepcopy(native), native_distribution_sha256=digest(native))


def material(scope, terminals, rows, additional, native_distributions, positions):
    terminal, query = validate_scope(scope)
    need(len(terminals) == len(rows) == len(native_distributions) == 1
         and len(additional) == 3
         and len({(r['session'], r['security_id']) for r in additional}) == 3,
         'DISTRIBUTION_SOURCE_EXACT_COUNTS_NO_TRUNCATION')
    fields = {'session', 'security_id', 'kind', 'reference', 'cash_per_share',
              'delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
              'exchange_ratio', 'cash_in_lieu_price_per_delivered_share', 'entitlement_aggregation'}
    native = terminals[0]
    need(set(native) == fields and native['session'] == terminal['native_session']
         and native['security_id'] == terminal['security_id'] and native['kind'] == 'CASH_MERGER'
         and native['entitlement_aggregation'] == 'HOLDER' and type(native['reference']) is str
         and bool(native['reference']) and digest(native) == terminal['native_term_sha256']
         and all(native[k] is None for k in ('cash_per_share', 'delivered_security_id', 'delivered_ticker',
              'delivered_issuer_id', 'exchange_ratio', 'cash_in_lieu_price_per_delivered_share')),
         'DISTRIBUTION_SOURCE_EXACT_INCOMPLETE_TERMINAL_PREIMAGE')
    expected_ids = {r['security_id'] for r in scope['additional_rows']} | {terminal['security_id']}
    need(set(positions) == expected_ids, 'DISTRIBUTION_SOURCE_EXACT_ROLE_IDENTITIES')
    term = identity(rows[0], terminal, positions[terminal['security_id']])
    term['native_term'] = deepcopy(native)
    source, spin = native_distributions[0]
    spins = [distribution_material(query, source, spin)]
    selected = []
    for declared in scope['additional_rows']:
        found = [r for r in additional if (r['session'], r['security_id']) == (declared['session'], declared['security_id'])]
        need(len(found) == 1, 'DISTRIBUTION_SOURCE_MISSING_OR_DUPLICATE_FULL_ROW')
        selected.append(identity(found[0], declared, positions[declared['security_id']]))
    return dict(terms=[term], additional_rows=selected, native_distributions=spins)


def payload(binding, scope, source_material, producer_sha256):
    return dict(schema=SCHEMA, arm=binding['arm'], parent_outer_sha256=binding['outer_sha256'],
        parent_cursor=binding['selected_session'], archive_sha256=binding['base']['archive_sha256'],
        bundle_sha256=binding['base']['bundle_sha256'], scope=deepcopy(scope), scope_sha256=digest(scope),
        producer_sha256=producer_sha256, distribution_producer_sha256=sha(Path(__file__).read_bytes()),
        parser_sha256=PARSER_SHA, **source_material, financial_sessions_advanced=0,
        financial_authority=False, input_adopted=False, provider_metadata_upgraded=False, production_contacted=False)


def validate(value, spec, scope, producer_sha256):
    validate_scope(scope)
    need(spec['outer_sha256'] == scope['parent_outer_sha256']
         and spec['selected_session'] == scope['parent_cursor'], 'DISTRIBUTION_SOURCE_EXACT_ADMITTED_PARENT')
    positions = {}
    for item in value['terms'] + value['additional_rows']:
        sid = item['source_row']['security_id']
        need(sid not in positions or positions[sid] == item['parent_positions'],
             'DISTRIBUTION_SOURCE_REPEATED_PARENT_ROLE_EQUAL')
        positions[sid] = item['parent_positions']
    data = material(scope, [v['native_term'] for v in value['terms']], [v['source_row'] for v in value['terms']],
        [v['source_row'] for v in value['additional_rows']],
        [(v['raw_source_row'], v['native_distribution']) for v in value['native_distributions']], positions)
    need(type(value['financial_sessions_advanced']) is int
         and all(value[k] is False for k in ('financial_authority', 'input_adopted',
                                            'provider_metadata_upgraded', 'production_contacted'))
         and value == payload(spec, scope, data, producer_sha256),
         'DISTRIBUTION_SOURCE_EXACT_RECONSTRUCTION_NO_FINANCIAL_AUTHORITY')
    return value


def capture(cp, out, arm, scope, producer_sha256):
    from full_system_core import hosted
    hosted()
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1' and Path('/variant').is_dir()
         and str(Path(__file__).resolve()).startswith('/driver/'), 'HOSTED_DISTRIBUTION_SOURCE_ONLY')
    from research.pooled_input_support import inputs
    from research.bounded_20y import run
    need(sha(Path(run.__file__).read_bytes()) == PARSER_SHA, 'DISTRIBUTION_SOURCE_FROZEN_ORIGINAL_PARSER')
    terminal, query = validate_scope(scope)
    need(cp['sha256'] == scope['parent_outer_sha256'] and cp['source_cursor'] == scope['parent_cursor'],
         'DISTRIBUTION_SOURCE_EXACT_CAPTURE_PARENT')
    before = digest(cp)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    natives = [asdict(v) for v in actions.terminal.get(terminal['native_session'], ())
               if v.security_id == terminal['security_id']]
    keys = {(terminal['session'], terminal['security_id'])}
    extra_keys = {(r['session'], r['security_id']) for r in scope['additional_rows']}
    observations, raw_spins = [], []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        raw = archive.read('actions.csv.gz')
        need(len(raw) == ACTIONS_BYTES and sha(raw) == ACTIONS_SHA, 'DISTRIBUTION_SOURCE_EXACT_ACTIONS_MEMBER')
        for row in inputs._archive_rows(archive, 'actions.csv.gz'):
            if (row['effective_session'] == query['session']
                    and row['security_id'] == query['parent_security_id']
                    and row['action'].lower() in ('spinoff', 'spinoffdividend')):
                raw_spins.append(row)
        for year in sorted({day[:4] for day, _ in keys | extra_keys}):
            observations.extend(r for r in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz')
                                if (r['session'], r['security_id']) in keys | extra_keys)
    need(len(raw_spins) == 1, 'DISTRIBUTION_SOURCE_ONE_ORIGINAL_ACTION_PREIMAGE')
    typed = run.distributions(raw_spins)
    distribution = [asdict(v) for values in typed.values() for v in values]
    need(len(distribution) == 1, 'DISTRIBUTION_SOURCE_ONE_TYPED_NATIVE')
    episodes = cp['run']['state']['wealth_core']['episodes']
    positions = {sid: [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
        for _, e in sorted(episodes.items(), key=lambda pair: int(pair[0])) if e['security_id'] == sid]
        for _, sid in keys | extra_keys}
    source = material(scope, natives,
        [r for r in observations if (r['session'], r['security_id']) in keys],
        [r for r in observations if (r['session'], r['security_id']) in extra_keys],
        [(raw_spins[0], distribution[0])], positions)
    binding = dict(arm=arm, outer_sha256=cp['sha256'], selected_session=cp['source_cursor'], base=cp['base'])
    value = payload(binding, scope, source, producer_sha256)
    validate(value, binding, scope, producer_sha256)
    need(digest(cp) == before, 'DISTRIBUTION_SOURCE_PARENT_STATE_UNCHANGED')
    with (out / FILE).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    return value


# V7 is an appended source-only capability. The complete V6 byte prefix and
# function definitions above remain available for their original contracts.
DISTRIBUTION_ONLY_SCHEMA = 'research.own-parent-frozen-source-witnesses/7'
DISTRIBUTION_ONLY_SCOPE = 'research.distribution-only-source-scope/1'
MAX_DISTRIBUTION_RECORDS = 8
MAX_DISTRIBUTION_OBSERVATIONS = 32
_capture_v6 = capture
_validate_v6 = validate
_validate_scope_v6 = validate_scope


def distribution_only_scope(scope):
    need(set(scope) == {'schema', 'parent_outer_sha256', 'parent_cursor', 'terms',
                       'additional_rows', 'native_distribution_queries',
                       'expected_native_distribution_count'}
         and scope['schema'] == DISTRIBUTION_ONLY_SCOPE and scope['terms'] == [],
         'DISTRIBUTION_ONLY_EXACT_SCOPE_NO_TERMINAL')
    cursor, outer = scope['parent_cursor'], scope['parent_outer_sha256']
    need(type(cursor) is str and date.fromisoformat(cursor).isoformat() == cursor
         and type(outer) is str and len(outer) == 64
         and all(c in '0123456789abcdef' for c in outer),
         'DISTRIBUTION_ONLY_EXACT_PARENT_BINDING')
    queries, expected = scope['native_distribution_queries'], scope['expected_native_distribution_count']
    need(type(expected) is int and 1 <= expected <= MAX_DISTRIBUTION_RECORDS
         and type(queries) is list and len(queries) == expected,
         'DISTRIBUTION_ONLY_EXPLICIT_BOUNDED_NATIVE_COUNT')
    for query in queries:
        NativeDistributionQuery.model_validate(query)
        need(type(query['maximum_records']) is int and query['maximum_records'] == 1
             and query['financial_use_authorized'] is False
             and date.fromisoformat(query['session']).isoformat() == query['session']
             and cursor < query['session'], 'DISTRIBUTION_ONLY_UNCONSUMED_ORIGINAL_QUERY')
    parent, ticker, session = (queries[0][key] for key in ('parent_security_id', 'parent_ticker', 'session'))
    need(all((q['parent_security_id'], q['parent_ticker'], q['session']) == (parent, ticker, session) for q in queries)
         and all(len({q[key] for q in queries}) == expected
                 for key in ('source_row_id', 'native_term_sha256', 'raw_source_row_sha256')),
         'DISTRIBUTION_ONLY_ONE_PARENT_DATE_ALL_DISTINCT_PREIMAGES')
    observations = scope['additional_rows']
    need(type(observations) is list and 1 <= len(observations) <= MAX_DISTRIBUTION_OBSERVATIONS
         and len({(r['session'], r['security_id']) for r in observations}) == len(observations)
         and any(r['security_id'] == parent and r['ticker'] == ticker and r['session'] < session for r in observations),
         'DISTRIBUTION_ONLY_BOUNDED_DISTINCT_ROWS_AND_PRIOR_PARENT_IDENTITY')
    roles = {}
    for row in observations:
        need(set(row) == {'session', 'security_id', 'ticker', 'source_observation_sha256', 'parent_positions'}
             and type(row['session']) is str and date.fromisoformat(row['session']).isoformat() == row['session']
             and cursor < row['session'] <= session
             and type(row['security_id']) is str and bool(row['security_id'])
             and type(row['ticker']) is str and bool(row['ticker'])
             and type(row['source_observation_sha256']) is str and len(row['source_observation_sha256']) == 64
             and all(c in '0123456789abcdef' for c in row['source_observation_sha256'])
             and type(row['parent_positions']) is list,
             'DISTRIBUTION_ONLY_FULL_ROW_DIGEST_AND_FUTURE_SCOPE')
        sid = row['security_id']
        need((sid != parent or row['ticker'] == ticker)
             and (sid not in roles or roles[sid] == row['parent_positions']),
             'DISTRIBUTION_ONLY_REPEATED_PARENT_ROLE_AND_TICKER')
        roles[sid] = row['parent_positions']
    return queries


def distribution_only_native_rows(scope, rows):
    """Count all exact parent/date natives before checking any requested hash."""
    queries = distribution_only_scope(scope)
    query = queries[0]
    selected = [row for row in rows if row['effective_session'] == query['session']
                and row['security_id'] == query['parent_security_id']
                and row['action'].lower() in ('spinoff', 'spinoffdividend')]
    need(len(selected) == scope['expected_native_distribution_count'],
         'DISTRIBUTION_ONLY_ALL_PARENT_DATE_NATIVE_COUNT_NO_HASH_PREFILTER')
    return selected


def distribution_only_material(scope, observations, native_distributions, positions):
    queries = distribution_only_scope(scope)
    declared = scope['additional_rows']
    expected = scope['expected_native_distribution_count']
    need(len(observations) == len(declared)
         and {(r['session'], r['security_id']) for r in observations}
             == {(r['session'], r['security_id']) for r in declared}
         and len(native_distributions) == expected
         and len({native['source_row_id'] for _, native in native_distributions}) == expected,
         'DISTRIBUTION_ONLY_EXACT_COUNTS_NO_MISSING_DUPLICATE_EXTRA')
    # Replay the parent/date count predicate during reconstruction as well as
    # during capture. Unexpected native source rows cannot be hidden by hashes.
    distribution_only_native_rows(scope, [source for source, _ in native_distributions])
    expected_ids = {row['security_id'] for row in declared}
    need(set(positions) == expected_ids, 'DISTRIBUTION_ONLY_EXACT_ROLE_IDENTITIES')
    selected = []
    for row in declared:
        found = [value for value in observations if (value['session'], value['security_id'])
                 == (row['session'], row['security_id'])]
        need(len(found) == 1, 'DISTRIBUTION_ONLY_ONE_FULL_OBSERVATION_PER_DECLARATION')
        selected.append(identity(found[0], row, positions[row['security_id']]))
    spins = []
    for query in queries:
        found = [(source, native) for source, native in native_distributions
                 if native['source_row_id'] == query['source_row_id']]
        need(len(found) == 1, 'DISTRIBUTION_ONLY_ONE_ORIGINAL_TYPED_NATIVE_PER_QUERY')
        spins.append(distribution_material(query, *found[0]))
    return dict(terms=[], additional_rows=selected, native_distributions=spins)


def distribution_only_payload(binding, scope, source_material, producer_sha256):
    return dict(schema=DISTRIBUTION_ONLY_SCHEMA, arm=binding['arm'], parent_outer_sha256=binding['outer_sha256'],
        parent_cursor=binding['selected_session'], archive_sha256=binding['base']['archive_sha256'],
        bundle_sha256=binding['base']['bundle_sha256'], scope=deepcopy(scope), scope_sha256=digest(scope),
        producer_sha256=producer_sha256, distribution_producer_sha256=sha(Path(__file__).read_bytes()),
        parser_sha256=PARSER_SHA, **source_material, financial_sessions_advanced=0,
        financial_authority=False, input_adopted=False, provider_metadata_upgraded=False, production_contacted=False)


def distribution_only_pairing(scope, raw_spins, natives):
    distribution_only_native_rows(scope, raw_spins)
    expected = scope['expected_native_distribution_count']
    need(len(natives) == expected and len({v['source_row_id'] for v in natives}) == expected,
         'DISTRIBUTION_ONLY_ALL_ORIGINAL_TYPED_NATIVES')
    by_raw_id = {sha(json.dumps(row, sort_keys=True).encode()): row for row in raw_spins}
    by_native_id = {native['source_row_id']: native for native in natives}
    need(len(by_raw_id) == expected and set(by_raw_id) == set(by_native_id),
         'DISTRIBUTION_ONLY_EXACT_ORIGINAL_PARSER_SOURCE_PAIRING')
    return [(by_raw_id[key], by_native_id[key]) for key in by_raw_id]


def distribution_only_validate(value, spec, scope, producer_sha256):
    distribution_only_scope(scope)
    need(spec['outer_sha256'] == scope['parent_outer_sha256']
         and spec['selected_session'] == scope['parent_cursor'],
         'DISTRIBUTION_ONLY_EXACT_ADMITTED_PARENT')
    positions = {}
    need(value['terms'] == [], 'DISTRIBUTION_ONLY_NO_TERMINAL_PAYLOAD')
    for item in value['additional_rows']:
        sid = item['source_row']['security_id']
        need(sid not in positions or positions[sid] == item['parent_positions'],
             'DISTRIBUTION_ONLY_REPEATED_ACTUAL_PARENT_ROLE')
        positions[sid] = item['parent_positions']
    data = distribution_only_material(scope, [v['source_row'] for v in value['additional_rows']],
        [(v['raw_source_row'], v['native_distribution']) for v in value['native_distributions']], positions)
    need(type(value['financial_sessions_advanced']) is int
         and all(value[k] is False for k in ('financial_authority', 'input_adopted',
                                            'provider_metadata_upgraded', 'production_contacted'))
         and value == distribution_only_payload(spec, scope, data, producer_sha256),
         'DISTRIBUTION_ONLY_EXACT_RECONSTRUCTION_NO_FINANCIAL_AUTHORITY')
    return value


def capture_distribution_only(cp, out, arm, scope, producer_sha256):
    from full_system_core import hosted
    hosted()
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1' and Path('/variant').is_dir()
         and str(Path(__file__).resolve()).startswith('/driver/'), 'HOSTED_DISTRIBUTION_ONLY_SOURCE')
    from research.pooled_input_support import inputs
    from research.bounded_20y import run
    need(sha(Path(run.__file__).read_bytes()) == PARSER_SHA,
         'DISTRIBUTION_ONLY_FROZEN_ORIGINAL_PARSER')
    distribution_only_scope(scope)
    need(cp['sha256'] == scope['parent_outer_sha256'] and cp['source_cursor'] == scope['parent_cursor'],
         'DISTRIBUTION_ONLY_EXACT_CAPTURE_PARENT')
    before = digest(cp)
    keys = {(r['session'], r['security_id']) for r in scope['additional_rows']}
    observations = []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        raw = archive.read('actions.csv.gz')
        need(len(raw) == ACTIONS_BYTES and sha(raw) == ACTIONS_SHA,
             'DISTRIBUTION_ONLY_EXACT_ACTIONS_MEMBER')
        raw_spins = distribution_only_native_rows(scope, inputs._archive_rows(archive, 'actions.csv.gz'))
        for year in sorted({day[:4] for day, _ in keys}):
            observations.extend(r for r in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz')
                                if (r['session'], r['security_id']) in keys)
    typed = run.distributions(raw_spins)
    natives = [asdict(value) for values in typed.values() for value in values]
    pairs = distribution_only_pairing(scope, raw_spins, natives)
    episodes = cp['run']['state']['wealth_core']['episodes']
    positions = {sid: [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
        for _, e in sorted(episodes.items(), key=lambda pair: int(pair[0])) if e['security_id'] == sid]
        for _, sid in keys}
    source = distribution_only_material(scope, observations, pairs, positions)
    binding = dict(arm=arm, outer_sha256=cp['sha256'], selected_session=cp['source_cursor'], base=cp['base'])
    value = distribution_only_payload(binding, scope, source, producer_sha256)
    distribution_only_validate(value, binding, scope, producer_sha256)
    need(digest(cp) == before, 'DISTRIBUTION_ONLY_PARENT_STATE_UNCHANGED')
    with (out / FILE).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    return value


def source_capture(cp, out, arm, scope, producer_sha256):
    if scope.get('schema') == DISTRIBUTION_ONLY_SCOPE:
        return capture_distribution_only(cp, out, arm, scope, producer_sha256)
    return _capture_v6(cp, out, arm, scope, producer_sha256)


def source_validate(value, spec, scope, producer_sha256):
    if scope.get('schema') == DISTRIBUTION_ONLY_SCOPE:
        return distribution_only_validate(value, spec, scope, producer_sha256)
    return _validate_v6(value, spec, scope, producer_sha256)


def source_validate_scope(scope):
    if scope.get('schema') == DISTRIBUTION_ONLY_SCOPE:
        return distribution_only_scope(scope)
    return _validate_scope_v6(scope)


# Public API dispatch happens after every V6 definition has been preserved.
capture = source_capture
validate = source_validate
validate_scope = source_validate_scope
