"""Selected future ordinary facts, with read-only actual cash/risk postconditions."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha

HERE = Path(__file__).parent
OVERLAY = 'future-financial-overlay.json'
HYDRATED = 'hydrated-future-financial-terminal-catalog.json'
REFERENCE = 'research:system-optimization-002/selected-future-ordinary-input/1'
PLANS = {
    'P04': ('system_campaign_following_completions_facts', 'FollowingFacts',
            'system-campaign-following-completions-terminal-facts.json', ('APHA', 'CATM', 'REGI', 'PLAN')),
    'P10': ('system_campaign_autumn2020_cash_facts', 'CashCompletionFacts',
            'system-campaign-autumn2020-cash-terminal-facts.json', ('MNTA', 'AIMT', 'IMMU', 'MYOK', 'VRTU')),
    'P07': ('system_campaign_medicines_facts', 'MedicinesFacts',
            'system-campaign-medicines-terminal-facts.json', ('MDCO',)),
}
CASH_PHASES = {
    ('P04', '2022-04-29'): ('system-campaign-december-cash-calendar-terminal-facts.json', ('EPAY',)),
    ('P10', '2022-01-31'): ('system-campaign-february-cash-calendar-terminal-facts.json', ('VCRA',)),
}
COMPOSITION = 'research.selected-future-catalog-composition/1'
COMBINED_PHASES = {
    ('P07', '2019-12-31'): (
        PLANS['P07'],
        ('system_campaign_arqule_facts', 'ArQuleFacts', 'system-campaign-arqule-terminal-facts.json', ('ARQL',)),
    ),
}
SINGLE_PHASES = {('P07', '2020-02-28'):
    ('system_campaign_sprint_facts', 'SprintFacts', 'system-campaign-sprint-terminal-facts.json', ('S2',))}
FOLLOWING_PHASES = {('P07', '2020-03-31'):
    ('system_campaign_spring2020_cash_facts', 'CashCompletionFacts', 'system-campaign-spring2020-cash-terminal-facts.json', ('CY', 'MLNX', 'WBC'))}
COMBINED_PHASES['P07', '2020-03-31'] = (FOLLOWING_PHASES['P07', '2020-03-31'], PLANS['P10'])
SOURCE_WITNESS_SCHEMA = 'research.own-parent-frozen-source-witnesses/1'
SOURCE_WITNESS_PENDING_SCHEMA = 'research.own-parent-frozen-source-witnesses/2'
SOURCE_WITNESS_FILE = 'source-witnesses.json'
OWN_CASH_CATALOG = 'system-campaign-selected-own-cash-terminal-facts.json'
OWN_CASH_SHA = '3611cd9a337bb084a335832f9cdebb720ad36164472b3b55297c94598842262e'
OWN_CASH_PHASES = {('P04', '2022-06-30'): 'SAFM', ('P10', '2022-07-29'): 'ACC',
                   ('P10', '2024-04-30'): 'SWAV', ('P00', '2018-08-31'): 'ILG',
                   ('P04', '2022-08-31'): 'CTXS'}
CLOSED_CASH_GENERATIONS = {'7b58c64413b5f513ce76b9c7382f34cf8df612969e0865604ba283eb8a464be9': 2,
    'd2b2ee65c2a029d6bc885a35dcf8138233a23b8654aaf1958a6a2677416605e3': 3,
    '629b3e64ab7cf6aae2cf54c733d65acc8c9cc3b2465d68b19a58b0918a09efe2': 4}
CASH_GENERATION_LENGTHS = {('P04', '2022-06-30'): 2, ('P10', '2022-07-29'): 2,
                           ('P10', '2024-04-30'): 3, ('P00', '2018-08-31'): 4, ('P04', '2022-08-31'): 5}
NEXT_COMPLETION = 'FIRST_FROZEN_SESSION_AFTER_CONFIRMED_COMPLETION_DATE'
OWN_CASH_SOURCE_CLOCKS = {
    ('P04', '2022-08-31'): (41798315426, 'c750169a3cadb1d18fc58cdb6e5ec3cc807c6dd7', 13307310013),
    ('P00', '2018-08-31'): (41807854617, '4bd9083c233779cbfbb00503a6bfee9bf7d2ddcd', 13311490065),
    ('P04', '2022-06-30'): (41783795694, 'cddd0dfb84433998b52c46b5e53e836a84fc5d58', 13299799904),
    ('P10', '2022-07-29'): (41783795694, 'cddd0dfb84433998b52c46b5e53e836a84fc5d58', 13299684770),
    ('P10', '2024-04-30'): (41799737694, '3ea65d6eefefc66d593858dc0ee6a4b476769c2a', 13307052219),
}
HISTORICAL_WITNESS_SCOPES = {
    'P04': dict(parent_outer_sha256='0e6028db71e0a12efd603580870f57495e5c66d1d46a0aaf264567e6aacf68fe',
        parent_cursor='2022-06-30', terms=[dict(ticker='SAFM', security_id='962454383671746307',
            session='2022-07-20', native_session='2022-07-21',
            native_term_sha256='d00cf559bcc50db02d1e30e69194f3f92949e1085b4bd23b53c4f134aba86d09',
            parent_positions=[dict(slot_id=6, ticker='SAFM', quantity=29, entry_date='2022-06-30')])]),
    'P10': dict(parent_outer_sha256='e1c1c823374d10e0cbf62752b0465e39c23165ec80a61e3f357bea13217462e4',
        parent_cursor='2022-07-29', terms=[dict(ticker='ACC', security_id='209530306982231273',
            session='2022-08-08', native_session='2022-08-09',
            native_term_sha256='dedc2034f8b43302ab25e6be16e3c4896563412b8510b3cb4083281b6cbf21a7',
            parent_positions=[])]),
}
NEXT_WITNESS_SCOPES = {
    'P00': dict(parent_outer_sha256='ad12b8a58f00560f1393cccdc0d9718b59d172265fc89f4bc36cb1ec7a4b37d2',
        parent_cursor='2018-08-31', terms=[dict(ticker='ILG', security_id='278081346388915134',
            session='2018-08-30', native_session='2018-08-31',
            native_term_sha256='9aa688a1c3a76f03ed5f2ca463b75a19d20b10937333e51946ab3d74cdce1703',
            parent_positions=[dict(slot_id=1, ticker='ILG', quantity=90, entry_date='2017-07-05')],
            pending_at_parent=dict(pending_sessions=0, stale_at_event=0, unresolved=False,
                native_term_sha256='9aa688a1c3a76f03ed5f2ca463b75a19d20b10937333e51946ab3d74cdce1703'))],
        additional_rows=[dict(ticker='VAC', security_id='851672149700415133', session='2018-09-04',
            source_observation_sha256='e76a958ab2504c0372cbe44096c1d3e4d4b156723574705b93df34c3afebf595',
            parent_positions=[])]),
    'P04': dict(parent_outer_sha256='5ff96b14f5e463494d22816ee6a61464411498324cd8298ec48461e12a5f90ac',
        parent_cursor='2022-08-31', terms=[dict(ticker='CTXS', security_id='554480052825212855',
            session='2022-09-28', native_session='2022-09-29',
            native_term_sha256='6c306190c326bc01b52d3fb9fda5f2cd2cdf09fdc447cb5a41064136c6c4329a',
            parent_positions=[])]),
    'P10': dict(parent_outer_sha256='6ffb77026ee113108e175f22c6aa24c2d68963b24b48100340b9ce9888d58377',
        parent_cursor='2024-04-30', terms=[dict(ticker='SWAV', security_id='158012003593585084',
            session='2024-05-29', native_session='2024-05-30',
            native_term_sha256='011cbd286ef8f6e57519452164b18187177190814dfe5742ce4ac52d70f02a0c',
            parent_positions=[])]),
}
WITNESS_SCOPE_REGISTRY = {digest(scope): deepcopy(scope)
    for scopes in (HISTORICAL_WITNESS_SCOPES, NEXT_WITNESS_SCOPES) for scope in scopes.values()}
ACTIVE_WITNESS_SCOPES = {'P00': digest(NEXT_WITNESS_SCOPES['P00'])}
WITNESS_SCOPES = {arm: deepcopy(WITNESS_SCOPE_REGISTRY[key]) for arm, key in ACTIVE_WITNESS_SCOPES.items()}


def registered_scope(key):
    scope = WITNESS_SCOPE_REGISTRY.get(key)
    need(scope is not None and digest(scope) == key, 'SOURCE_WITNESS_EXACT_REGISTERED_SCOPE_DIGEST')
    return deepcopy(scope)


def source_terms(scope, natives, rows, positions, pending_contexts=None):
    """Validate only declared source preimages and parent-role observations."""
    from datetime import date
    declared = scope['terms']
    pending_contexts = [None] * len(declared) if pending_contexts is None else pending_contexts
    keys = {(t['session'], t['security_id']) for t in declared}
    need(declared and len(keys) == len(declared) == len(rows) == len(positions) == len(natives) == len(pending_contexts),
         'SOURCE_WITNESS_EXACT_UNIQUE_DECLARED_COUNTS')
    need({(r['session'], r['security_id']) for r in rows} == keys,
         'SOURCE_WITNESS_NO_MISSING_DUPLICATE_OR_EXTRA_ROWS')
    result = []
    for term, native, held, pending in zip(declared, natives, positions, pending_contexts):
        sid = term['security_id']
        row, = [r for r in rows if (r['session'], r['security_id']) == (term['session'], sid)]
        future = scope['parent_cursor'] < term['native_session']
        if future:
            need(pending is None and 'pending_at_parent' not in term, 'SOURCE_WITNESS_FUTURE_NATIVE_UNCONSUMED_SCOPE')
        else:
            need(term['native_session'] == scope['parent_cursor'] and held
                 and pending == term.get('pending_at_parent') and pending is not None
                 and type(pending['pending_sessions']) is int and pending['pending_sessions'] == 0
                 and type(pending['stale_at_event']) is int and pending['stale_at_event'] == 0
                 and pending['unresolved'] is False and pending['native_term_sha256'] == term['native_term_sha256'],
                 'SOURCE_WITNESS_ONLY_EXACT_OWN_PENDING_NATIVE_AT_PARENT')
        need(term['session'] < term['native_session']
             and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session'])
             and row['ticker'] == term['ticker'] and row['security_type_eligible'] in ('0', '1')
             and type(row['issuer_id']) is str, 'SOURCE_WITNESS_EXACT_UNMODIFIED_IDENTITY')
        need(native['session'] == term['native_session'] and native['security_id'] == sid
             and native['kind'] == 'CASH_MERGER' and native['cash_per_share'] is None
             and digest(native) == term['native_term_sha256'], 'SOURCE_WITNESS_EXACT_INCOMPLETE_NATIVE')
        need(held == term['parent_positions'], 'SOURCE_WITNESS_EXACT_PARENT_POSITION_SCOPE')
        witness = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                       'listing_first_session', 'security_type_eligible')}
        witness['source_observation_sha256'] = digest(row)
        result.append(dict(source_row=deepcopy(row), identity_witness=witness,
                           native_term=deepcopy(native), parent_positions=deepcopy(held)))
        if pending is not None:
            result[-1]['pending_context'] = deepcopy(pending)
    return result


def source_schema(scope):
    return (SOURCE_WITNESS_PENDING_SCHEMA if scope.get('additional_rows')
            or any('pending_at_parent' in t for t in scope['terms']) else SOURCE_WITNESS_SCHEMA)


def additional_source_rows(scope, rows, positions):
    from datetime import date
    declared = scope.get('additional_rows', [])
    keys = {(t['session'], t['security_id']) for t in declared}
    native_keys = {(t['session'], t['security_id']) for t in scope['terms']}
    need(len(keys) == len(declared) == len(rows) == len(positions) and not keys & native_keys
         and {(r['session'], r['security_id']) for r in rows} == keys,
         'SOURCE_WITNESS_EXACT_ADDITIONAL_IDENTITY_ROWS')
    result = []
    for term, held in zip(declared, positions):
        row, = [r for r in rows if (r['session'], r['security_id']) == (term['session'], term['security_id'])]
        need(scope['parent_cursor'] < row['session'] and row['ticker'] == term['ticker']
             and row['security_type_eligible'] in ('0', '1') and type(row['issuer_id']) is str
             and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session'])
             and digest(row) == term['source_observation_sha256'] and held == term['parent_positions'],
             'SOURCE_WITNESS_UNMODIFIED_ADDITIONAL_ROW_AND_PARENT_ROLE')
        witness = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                       'listing_first_session', 'security_type_eligible')}
        witness['source_observation_sha256'] = digest(row)
        result.append(dict(source_row=deepcopy(row), identity_witness=witness, parent_positions=deepcopy(held)))
    return result


def witness_payload(cp, arm, scope, natives, rows, additional_rows=()):
    need(cp['sha256'] == scope['parent_outer_sha256'] and cp['source_cursor'] == scope['parent_cursor'],
         'SOURCE_WITNESS_EXACT_OWN_PARENT')
    episodes = cp['run']['state']['wealth_core']['episodes']
    def positions(terms):
        return [[dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'],
                       entry_date=e['entry_date'])
                  for _, e in sorted(episodes.items(), key=lambda item: int(item[0]))
                  if e['security_id'] == t['security_id']] for t in terms]
    w = cp['run']['state']['wealth_core']
    pending = []
    for term in scope['terms']:
        sid = term['security_id']
        recorded = w.get('terminal_pending_terms', {}).get(sid, {})
        pending.append(dict(pending_sessions=w.get('terminal_pending_sessions', {}).get(sid),
            stale_at_event=recorded.get('stale_at_event'), native_term_sha256=digest(recorded.get('terms')),
            unresolved=sid in w.get('unresolved_terminals', {})) if 'pending_at_parent' in term else None)
    payload = dict(schema=source_schema(scope), arm=arm, parent_outer_sha256=cp['sha256'],
        parent_cursor=cp['source_cursor'], archive_sha256=cp['base']['archive_sha256'],
        bundle_sha256=cp['base']['bundle_sha256'], scope=deepcopy(scope), scope_sha256=digest(scope),
        producer_sha256=sha(Path(__file__).read_bytes()), terms=source_terms(scope, natives, rows, positions(scope['terms']), pending),
        financial_sessions_advanced=0, financial_authority=False, input_adopted=False,
        provider_metadata_upgraded=False, production_contacted=False)
    if source_schema(scope) == SOURCE_WITNESS_PENDING_SCHEMA:
        payload['additional_rows'] = additional_source_rows(scope, additional_rows, positions(scope.get('additional_rows', [])))
    return payload


def validate_witness_capture(payload, spec, scope):
    need(payload['schema'] == source_schema(scope) and payload['arm'] == spec['arm']
         and payload['parent_outer_sha256'] == spec['outer_sha256'] == scope['parent_outer_sha256']
         and payload['parent_cursor'] == spec['selected_session'] == scope['parent_cursor']
         and payload['archive_sha256'] == spec['base']['archive_sha256']
         and payload['bundle_sha256'] == spec['base']['bundle_sha256']
         and payload['scope'] == scope and payload['scope_sha256'] == digest(scope)
         and payload['producer_sha256'] == sha(Path(__file__).read_bytes())
         and type(payload['financial_sessions_advanced']) is int and payload['financial_sessions_advanced'] == 0
         and all(payload[k] is False for k in ('financial_authority', 'input_adopted',
                                               'provider_metadata_upgraded', 'production_contacted')),
         'SOURCE_WITNESS_EXACT_SOURCE_ONLY_CAPTURE')
    terms = payload['terms']
    need(terms == source_terms(scope, [v['native_term'] for v in terms],
          [v['source_row'] for v in terms], [v['parent_positions'] for v in terms],
          [v.get('pending_context') for v in terms]),
          'SOURCE_WITNESS_FULL_PAYLOAD_RECONSTRUCTION')
    if source_schema(scope) == SOURCE_WITNESS_PENDING_SCHEMA:
        rows = payload['additional_rows']
        need(rows == additional_source_rows(scope, [v['source_row'] for v in rows],
                                           [v['parent_positions'] for v in rows]),
             'SOURCE_WITNESS_COMPLETE_ADDITIONAL_ROW_RECONSTRUCTION')
    return payload


def capture_source_witnesses(cp, out, arm, scope):
    hosted()
    from research.pooled_input_support import inputs
    before = digest(cp)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    natives = []
    for term in scope['terms']:
        native, = [asdict(t) for t in actions.terminal.get(term['native_session'], ())
                   if t.security_id == term['security_id']]
        natives.append(native)
    native_keys = {(t['session'], t['security_id']) for t in scope['terms']}
    additional_keys = {(t['session'], t['security_id']) for t in scope.get('additional_rows', [])}
    keys = native_keys | additional_keys
    rows = []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in keys}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                if (row['session'], row['security_id']) in keys:
                    rows.append(row)
    payload = witness_payload(cp, arm, scope, natives,
        [r for r in rows if (r['session'], r['security_id']) in native_keys],
        [r for r in rows if (r['session'], r['security_id']) in additional_keys])
    need(digest(cp) == before, 'SOURCE_WITNESS_PARENT_STATE_UNCHANGED')
    save(out / SOURCE_WITNESS_FILE, payload)
    return payload


def own_cash_selection(arm, cursor):
    from system_campaign_cash_calendar import validate_term
    import system_campaign_cash_calendar as calendar
    from system_campaign_financial_partial import root_spec
    raw = (HERE / OWN_CASH_CATALOG).read_bytes()
    need(sha(raw) == OWN_CASH_SHA, 'OWN_CASH_EXACT_REVIEWED_LITERAL_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.selected-own-parent-completions/2'
         and all(catalog[k] is False for k in ('canonical_financial_source_changed',
                                              'provider_metadata_upgraded', 'production_contacted'))
         and len(catalog['terms']) == len(OWN_CASH_PHASES), 'OWN_CASH_EXACT_NEW_CATALOG_SCOPE')
    def generation(count):
        value = dict(deepcopy(catalog), terms=deepcopy(catalog['terms'][:count]))
        if count in (2, 3):
            value['schema'] = 'research.selected-own-parent-cash-completions/1'
        encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        return value, sha(encoded)
    for old_sha, count in CLOSED_CASH_GENERATIONS.items():
        need(generation(count)[1] == old_sha, 'OWN_CASH_CLOSED_CATALOG_GENERATION_BYTES')
    for term in catalog['terms']:
        if term['recognition_rule'] == NEXT_COMPLETION:
            completion_cash_term(term)
        elif term['added']['kind'] == 'CASH_MERGER':
            validate_term(term)
        else:
            selected_stock_term(term)
        phase = term['arm'], term['parent_cursor']
        source = term['source_capture']
        parent = root_spec(term['arm'], term['parent_root_admission_sha256'])
        scope = registered_scope(source['scope_sha256'])
        declared, = scope['terms']
        retained_primary(term)
        need(OWN_CASH_PHASES.get(phase) == term['ticker']
             and term['parent_outer_sha256'] == scope['parent_outer_sha256']
             and term['parent_outer_sha256'] == parent['outer_sha256']
             and term['parent_cursor'] == parent['selected_session']
             and term['parent_positions'] == declared['parent_positions']
             and term['identity_witness']['session'] == declared['session']
             and term['native_session'] == declared['native_session']
             and term['native_term_sha256'] == declared['native_term_sha256']
             and term['security_id'] == declared['security_id']
             and (source['run_id'], source['head'], source['artifact_id']) == OWN_CASH_SOURCE_CLOCKS.get(phase)
             and source['scope_sha256'] == digest(scope)
             and all(type(source[k]) is str and len(source[k]) == 64
                     and all(c in '0123456789abcdef' for c in source[k])
                     for k in ('payload_sha256', 'independent_data_review_sha256')),
             'OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE')
    chosen, = [t for t in catalog['terms'] if (t['arm'], t['parent_cursor']) == (arm, cursor)]
    need(len({(t['arm'], t['parent_cursor']) for t in catalog['terms']}) == len(catalog['terms']),
         'OWN_CASH_UNIQUE_DECLARED_PHASES')
    selected_catalog, selected_sha = generation(CASH_GENERATION_LENGTHS[arm, cursor])
    need(chosen in selected_catalog['terms'], 'OWN_CASH_EXACT_PHASE_CATALOG_GENERATION')
    codec = SimpleNamespace(catalog=selected_catalog, catalog_sha=selected_sha,
        compiler_sha=sha(Path(calendar.__file__).read_bytes()),
        parent_outer_sha256=chosen['parent_outer_sha256'], parent_positions=chosen['parent_positions'],
        validator_description='Unchanged cash-calendar term validator; new own-source catalog validated by the shared selector.')
    if chosen['added']['kind'] != 'CASH_MERGER':
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Source-bound selected stock term; raw ratio preserved in catalog and exactly normalized for the canonical typed parser.'
        return codec, OWN_CASH_CATALOG, [selected_stock_term(chosen)]
    if chosen['recognition_rule'] == NEXT_COMPLETION:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Shared source-bound mandatory cash right with explicit first-session-after-confirmed-completion timing convention.'
    return codec, OWN_CASH_CATALOG, [deepcopy(chosen)]


def completion_cash_term(term):
    a, w = term['added'], term['identity_witness']
    primary = term['primary_extraction']
    need(term['recognition_rule'] == NEXT_COMPLETION and term['preopen_completion_confirmed'] is False
         and term['mandatory_common_share_completion_confirmed'] is True
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and w['session'] < term['last_trading_session'] == term['native_session']
             <= term['actual_completion_date'] < a['session']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and primary['actual_completion_date'] == term['actual_completion_date']
         and Fraction(primary['cash_per_ordinary_common_share']) == Fraction(str(a['cash_per_share']))
         and primary['mandatory_conversion'] is True and primary['preopen_time_established'] is False
         and primary['recognition_convention'] == 'FIRST_FROZEN_SESSION_STRICTLY_AFTER_CONFIRMED_COMPLETION',
         'OWN_INPUT_EXACT_CONFIRMED_CASH_RIGHT_AND_LATER_SESSION_CONVENTION')


def completion_session(term, dates):
    if term.get('recognition_rule') != NEXT_COMPLETION:
        return
    completed = term['actual_completion_date']
    need(dates == sorted(set(dates)) and completed in dates
         and dates.index(completed) + 1 < len(dates)
         and dates[dates.index(completed) + 1] == term['added']['session'],
         'OWN_INPUT_ACTUAL_FROZEN_FIRST_SESSION_AFTER_COMPLETION')


def selected_stock_term(term):
    """Normalize only a literal ratio, preserving its exact rational value."""
    from datetime import date
    a, w, dw = term['added'], term['identity_witness'], term['delivered_identity_witness']
    ratio = a['exchange_ratio']
    value = float(ratio)
    need(a['kind'] == 'CASH_PLUS_STOCK' and type(ratio) is str
         and math.isfinite(value) and value > 0 and Fraction(str(value)) == Fraction(ratio)
         and type(a['cash_per_share']) is float and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER' and a['cash_in_lieu_price_per_delivered_share'] is None
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and (a['delivered_security_id'], a['delivered_ticker'], a['delivered_issuer_id'])
             == (dw['security_id'], dw['ticker'], dw['issuer_id'])
         and w['session'] < term['last_trading_session'] == term['native_session']
         and term['native_session'] < term['actual_completion_date'] < a['session']
         and date.fromisoformat(term['actual_completion_date']).weekday() >= 5
         and term['recognition_rule'] == 'FIRST_FROZEN_SESSION_AFTER_CONFIRMED_NONTRADING_DAY_COMPLETION'
         and term['mandatory_common_share_completion_confirmed'] is True
         and dw['session'] == term['proxy']['session'] == a['session']
         and dw['source_observation_sha256'] == term['proxy']['source_observation_sha256']
         and dw['ticker'] == term['proxy']['ticker']
         and term['proxy']['convention'] == 'RETAINED_CHILD_RAW_OPEN_RESEARCH_PROXY'
         and term['proxy']['actual_settlement_rate_observed'] is False,
         'OWN_INPUT_EXACT_RETAINED_STOCK_RIGHT_AND_RATIO_NORMALIZATION')
    result = deepcopy(term)
    result['added']['exchange_ratio'] = value
    return result


def retained_primary(term):
    source = term.get('retained_primary_catalog')
    if source is None:
        return
    raw = (HERE / source['filename']).read_bytes()
    original, = [t for t in json.loads(raw)['terms']
                 if t.get('security_id', t['added']['security_id']) == term['security_id']]
    identity = ('security_id', 'ticker', 'issuer_id', 'listing_first_session', 'security_type_eligible')
    need(sha(raw) == source['sha256'] and digest(original) == source['term_sha256']
         and all(term[k] == v for k, v in original.items() if k != 'identity_witness')
         and ('identity_witness' not in original or
              all(term['identity_witness'][k] == original['identity_witness'][k] for k in identity)),
         'OWN_CASH_UNCHANGED_RETAINED_PRIMARY_TERM_AND_SOURCE_METADATA')


def catalog_terms(codec, tickers):
    if 'terms' not in codec.catalog:
        c = codec.catalog
        need(tickers == ('S2',) and c['schema'] == 'research.system-campaign-sprint-terminal-facts/1',
             'FUTURE_ONLY_DECLARED_SINGLE_CATALOG_NORMALIZATION')
        return [dict(ticker='S2', security_id=c['added']['security_id'], native_session=c['native_session'],
            native_term_sha256=c['native_term_sha256'], added=deepcopy(c['added']),
            identity_witness=deepcopy(c['source_identity_witness']),
            delivered_identity_witness=deepcopy(c['delivered_identity_witness']),
            last_trading_session=c['native_session'], primary_source=c['primary_source'],
            timing_source=c['acquirer_source'], description=c['added']['reference'])]
    terms = [deepcopy(t) for t in codec.catalog['terms'] if t['ticker'] in tickers]
    need(tuple(t['ticker'] for t in terms) == tickers, 'FUTURE_EXACT_DECLARED_CATALOG_SUBSET')
    if 'identity_witness' in codec.catalog:
        for term in terms:
            need('identity_witness' not in term and term['native_session'] < term['added']['session']
                 and codec.catalog['identity_witness']['security_id'] == term['security_id'],
                 'FUTURE_EXACT_CATALOG_LEVEL_WITNESS_NORMALIZATION')
            term.update(identity_witness=deepcopy(codec.catalog['identity_witness']),
                        last_trading_session=term['native_session'], timing_source=term['exchange_source'])
    return terms


def compose(plans):
    """Compose only validated literal source terms; preserve every original term."""
    import importlib
    sources, terms = [], []
    for module, cls, catalog, tickers in plans:
        original = importlib.import_module(module)
        codec = getattr(original, cls)(HERE / catalog)
        terms.extend(catalog_terms(codec, tickers))
        sources.append(dict(catalog_file=catalog, catalog_sha256=codec.catalog_sha,
            validator_file=Path(original.__file__).name, validator_sha256=codec.compiler_sha,
            selected_tickers=list(tickers)))
    need(len(sources) > 1 and len({v['catalog_file'] for v in sources}) == len(sources)
         and len({v['validator_file'] for v in sources}) == len(sources), 'FUTURE_UNIQUE_COMPOSITION_SOURCES')
    need(len({t['ticker'] for t in terms}) == len({t['security_id'] for t in terms}) == len(terms)
         and len({(t['native_session'], t['security_id']) for t in terms}) == len(terms)
         and len({(t['added']['session'], t['security_id']) for t in terms}) == len(terms),
         'FUTURE_DISJOINT_COMPOSITION_EVENTS')
    manifest = dict(schema=COMPOSITION, sources=sources)
    selection = SimpleNamespace(catalog=dict(terms=terms), catalog_sha=digest(manifest),
        compiler_sha=digest([{v['validator_file']: v['validator_sha256']} for v in sources]), composition=manifest)
    return selection, 'EXPLICIT_ORDERED_CATALOG_COMPOSITION', terms


def selected(arm, *, cursor=None):
    import importlib
    if (arm, cursor) in OWN_CASH_PHASES:
        return own_cash_selection(arm, cursor)
    if arm == 'P07':
        need(cursor == '2019-12-31' or (arm, cursor) in SINGLE_PHASES or (arm, cursor) in FOLLOWING_PHASES,
             'FUTURE_EXACT_ADMITTED_MDCO_PHASE')
    if (arm, cursor) in COMBINED_PHASES:
        return compose(COMBINED_PHASES[arm, cursor])
    module, cls, catalog, tickers = {**SINGLE_PHASES, **FOLLOWING_PHASES}.get((arm, cursor), PLANS[arm])
    if (arm, cursor) in CASH_PHASES:
        from system_campaign_cash_calendar import CashCalendar
        catalog, tickers = CASH_PHASES[arm, cursor]
        raw = (HERE / catalog).read_bytes()
        codec = CashCalendar(json.loads(raw))
        codec.catalog_sha = sha(raw)
        codec.compiler_sha = sha(Path(importlib.import_module('system_campaign_cash_calendar').__file__).read_bytes())
    else:
        codec = getattr(importlib.import_module(module), cls)(HERE / catalog)
    terms = catalog_terms(codec, tickers)
    return codec, catalog, terms


def stage_selected_sources(spec, old, out):
    """Host-only bounded fetch of one pinned source; workers remain offline."""
    phase = spec['arm'], spec['selected_session']
    if phase not in SINGLE_PHASES and phase not in FOLLOWING_PHASES:
        return
    import os
    from urllib.request import urlopen
    from system_campaign_sprint_facts import ALIAS_BYTES, ALIAS_SHA, ALIAS_URL, alias_rows
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
         and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'FUTURE_PUBLIC_SOURCE_HOSTED_ORCHESTRATOR_ONLY')
    folder = out / 'provider-source'
    folder.mkdir()
    target = folder / 'SHARADAR_ACTIONS.zip'
    retained = old / 'provider-source/SHARADAR_ACTIONS.zip'
    need(phase not in FOLLOWING_PHASES or retained.is_file(), 'FUTURE_CONSUMED_ALIAS_SOURCE_MUST_BE_RETAINED_NOT_REFETCHED')
    if retained.is_file():
        raw = retained.read_bytes()
        mode = 'EXACT_RETAINED_ORIGINAL'
    else:
        with urlopen(ALIAS_URL, timeout=60) as response:
            need(response.status == 200 and response.headers.get('Content-Encoding', 'identity') == 'identity',
                 'FUTURE_PINNED_PUBLIC_SOURCE_RESPONSE')
            raw = response.read(ALIAS_BYTES + 1)
        mode = 'EXACT_FROZEN_PUBLIC_OBJECT_FETCHED_ONCE'
    need(len(raw) == ALIAS_BYTES and sha(raw) == ALIAS_SHA, 'FUTURE_ORIGINAL_PROVIDER_BYTES_BEFORE_PARSE')
    target.write_bytes(raw)
    catalog = json.loads((HERE / SINGLE_PHASES['P07', '2020-02-28'][2]).read_bytes())
    rows = alias_rows(target, catalog['provider_alias_source']['selected_row_sha256'])
    save(out / 'provider-alias-proof.json', dict(source_sha256=ALIAS_SHA, source_bytes=len(raw),
        selected_rows=rows, selected_security_ids=[catalog['added']['security_id']], acquisition=mode,
        descriptive_fields_used_only_for_action_identity=True, strategy_metadata_upgraded=False))


def pending_completion(cp, term):
    """Only separately source-bound pending natives may be completed after consumption."""
    if term.get('arm') == 'P00' and term['added']['kind'] == 'CASH_PLUS_STOCK':
        return pending_source_completion(cp, term)
    sid = term['security_id']
    w = cp['run']['state']['wealth_core']
    held = [(k, e) for k, e in w['episodes'].items() if e['security_id'] == sid]
    pending = w.get('terminal_pending_terms', {}).get(sid, {})
    need(sid == '510659411298086546' and term['ticker'] == 'MNTA'
         and cp['source_cursor'] == term['native_session'] == '2020-09-30'
         and term['added']['session'] == '2020-10-01' and term['added']['cash_per_share'] == 52.5
         and w['terminal_pending_sessions'].get(sid) == 0 and pending.get('stale_at_event') == 0
         and digest(pending.get('terms')) == term['native_term_sha256']
         and len(held) == 1 and held[0][0] == '5' and held[0][1]['slot_id'] == 5
         and held[0][1]['current_shares'] == 101 and held[0][1]['exit_pending'] is False
         and w['slots']['5']['occupied_by'] == sid and sid not in w.get('unresolved_terminals', {})
         and w['terminal_carry_audit'][sid] == dict(carry_price=52.49, carry_session='2020-09-30',
             grace_prints=[dict(price=52.48, session='2020-09-30')], grace_split_multiplier=1.,
             grace_splits=[], last_trustworthy_print_session='2020-09-29', shares_at_carry=101),
         'FUTURE_EXACT_ADMITTED_HELD_MNTA_PENDING_NATIVE')


def pending_source_completion(cp, term):
    source = term['source_capture']
    scope = registered_scope(source['scope_sha256'])
    declared, = scope['terms']
    sid = term['security_id']; w = cp['run']['state']['wealth_core']
    held = [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
            for _, e in sorted(w['episodes'].items(), key=lambda item: int(item[0])) if e['security_id'] == sid]
    pending = w.get('terminal_pending_terms', {}).get(sid, {})
    need((term['arm'], term['parent_cursor']) == ('P00', '2018-08-31')
         and cp['sha256'] == term['parent_outer_sha256'] == scope['parent_outer_sha256']
         and cp['source_cursor'] == scope['parent_cursor'] == term['native_session']
         and (source['run_id'], source['head'], source['artifact_id']) == OWN_CASH_SOURCE_CLOCKS['P00', '2018-08-31']
         and held == term['parent_positions'] == declared['parent_positions'] and held
         and w['terminal_pending_sessions'].get(sid) == declared['pending_at_parent']['pending_sessions'] == 0
         and pending.get('stale_at_event') == declared['pending_at_parent']['stale_at_event'] == 0
         and digest(pending.get('terms')) == term['native_term_sha256'] == declared['native_term_sha256']
         and sid not in w.get('unresolved_terminals', {})
         and all(w['slots'][str(e['slot_id'])]['occupied_by'] == sid and e['exit_pending'] is False
                 for e in w['episodes'].values() if e['security_id'] == sid)
         and not any(e['security_id'] == term['added']['delivered_security_id'] for e in w['episodes'].values())
         and term['added']['session'] > cp['source_cursor'],
         'FUTURE_EXACT_SOURCE_BOUND_OWN_PENDING_STOCK_COMPLETION')


def suppressions(cp, terms):
    result = []
    for t in terms:
        need(t['added']['session'] > cp['source_cursor'], 'FUTURE_COMPLETE_TERMS_UNCONSUMED')
        if t['native_session'] <= cp['source_cursor']:
            pending_completion(cp, t)
        else:
            result.append(dict(session=t['native_session'], security_id=t['security_id'],
                               term_sha256=t['native_term_sha256']))
    return result


def hydrate(cp, arm, *, source_root=None):
    hosted()
    from research.pooled_input_support import inputs
    from system_campaign_2021_completions_facts import require_witness, CIL
    codec, catalog, terms = selected(arm, cursor=cp['source_cursor'])
    aliases = None
    alias_catalog = None
    if (arm, cp['source_cursor']) in SINGLE_PHASES or (arm, cp['source_cursor']) in FOLLOWING_PHASES:
        from system_campaign_sprint_facts import alias_rows
        need(source_root is not None, 'FUTURE_EXPLICIT_OWN_PROVIDER_SOURCE_ROOT')
        alias_catalog = json.loads((HERE / SINGLE_PHASES['P07', '2020-02-28'][2]).read_bytes())
        aliases = alias_rows(Path(source_root) / 'provider-source/SHARADAR_ACTIONS.zip',
                            alias_catalog['provider_alias_source']['selected_row_sha256'])
    if hasattr(codec, 'parent_outer_sha256'):
        need(cp['sha256'] == codec.parent_outer_sha256, 'OWN_CASH_EXACT_CURRENT_PARENT_OUTER')
        held = [[dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
                 for _, e in sorted(cp['run']['state']['wealth_core']['episodes'].items(), key=lambda item: int(item[0]))
                 if e['security_id'] == t['security_id']] for t in terms]
        need(held == [codec.parent_positions], 'OWN_CASH_CURRENT_PARENT_POSITION_SCOPE')
    suppressions(cp, terms)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    if any(t.get('recognition_rule') == NEXT_COMPLETION for t in terms):
        from research.pooled_input_support.bundle import axis
        dates = axis()
        for t in terms:
            completion_session(t, dates)
    wanted = {}
    for t in terms:
        native, = [v for v in actions.terminal.get(t['native_session'], ()) if v.security_id == t['security_id']]
        need(digest(asdict(native)) == t['native_term_sha256'] and not native.completeness(0)[0],
             'FUTURE_EXACT_INCOMPLETE_FROZEN_NATIVE')
        other = [v for v in actions.terminal.get(t['added']['session'], ()) if v.security_id == t['security_id']]
        need(other == [native] if t['native_session'] == t['added']['session'] else not other,
             'FUTURE_NO_CONFLICTING_EFFECTIVE_TERM')
        for w in (t['identity_witness'], *([t['delivered_identity_witness']] if 'delivered_identity_witness' in t else [])):
            key = w['session'], w['security_id']
            need(key not in wanted, 'FUTURE_UNIQUE_DECLARED_WITNESS')
            wanted[key] = w
    seen = {}
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in wanted}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                key = row['session'], row['security_id']
                if key not in wanted:
                    continue
                need(key not in seen, 'FUTURE_UNIQUE_ACTUAL_WITNESS')
                require_witness(row, wanted[key])
                seen[key] = row
    need(set(seen) == set(wanted), 'FUTURE_ALL_SELECTED_NATIVE_AND_DELIVERY_WITNESSES')
    delivered = {}
    for t in terms:
        if 'delivered_identity_witness' not in t:
            continue
        w = t['delivered_identity_witness']
        row = seen[w['session'], w['security_id']]
        price = float(row['raw_open'])
        need(math.isfinite(price) and price > 0, 'FUTURE_POSITIVE_DECLARED_RAW_OPEN_CIL_PROXY')
        t['added']['cash_in_lieu_price_per_delivered_share'] = price
        delivered[t['security_id']] = row
    material = dict(schema=REFERENCE, arm=arm, catalog=catalog, catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha, selector_sha256=sha(Path(__file__).read_bytes()),
        parent_outer_sha256=cp['sha256'], terms=terms,
        cil_convention=codec.catalog.get('cil_convention', CIL) if delivered else None,
        native_and_delivery_witnesses_verified=len(seen),
        consumed_native_preserved=[t['security_id'] for t in terms if t['native_session'] <= cp['source_cursor']],
        financial_source_changed=False, provider_metadata_upgraded=False)
    if hasattr(codec, 'composition'):
        material['composition'] = deepcopy(codec.composition)
    if hasattr(codec, 'validator_description'):
        material['original_validator_description'] = codec.validator_description
    if aliases is not None:
        material['original_alias_source'] = deepcopy(alias_catalog['provider_alias_source'])
        material['verified_alias_rows_sha256'] = digest(aliases)
    return material, delivered, actions


def document(cp, material, hydrated_sha):
    if 'composition' in material:
        manifest = material['composition']
        need(manifest['schema'] == COMPOSITION and digest(manifest) == material['catalog_sha256']
             and digest([{v['validator_file']: v['validator_sha256']} for v in manifest['sources']])
                 == material['original_validator_sha256'], 'FUTURE_EXACT_COMPOSITION_EVIDENCE_DIGESTS')
        evidence = [dict(reference=REFERENCE + '/composition',
                        description='Ordered manifest of independently validated original source catalogs.',
                        sha256=digest(manifest))]
        for source in manifest['sources']:
            evidence.extend(dict(reference=REFERENCE + '/' + source[file], description=description, sha256=source[value])
                for file, value, description in (
                    ('catalog_file', 'catalog_sha256', 'Unchanged literal source catalog.'),
                    ('validator_file', 'validator_sha256', 'Unchanged original literal validator.')))
    else:
        evidence = [dict(reference=REFERENCE + '/' + name, description=description, sha256=value)
            for name, description, value in (
                ('catalog', 'Unchanged literal ordinary completion catalog.', material['catalog_sha256']),
                ('validator', material.get('original_validator_description',
                    'Original literal catalog validator; original compiler guard remains intact.'), material['original_validator_sha256']))]
    evidence.extend(dict(reference=REFERENCE + '/' + name, description=description, sha256=value)
        for name, description, value in (
            ('selector', 'Own-parent future-only selected ordinary input.', material['selector_sha256']),
            ('hydrated', 'Actual frozen native and complete identity/delivery witnesses.', hydrated_sha)))
    for t in material['terms']:
        evidence.extend((dict(reference=t['primary_source'], description=t['description'], sha256=None),
            dict(reference=t['timing_source'], description='Actual mandatory completion; preserve native trading history.', sha256=None)))
        if 'source_capture' in t:
            evidence.extend(dict(reference=REFERENCE + '/source-capture/' + t['arm'] + '/' + name,
                description=description, sha256=t['source_capture'][key]) for name, key, description in (
                    ('payload', 'payload_sha256', 'Authenticated frozen source/native payload from the exact own admitted parent.'),
                    ('independent-data-review', 'independent_data_review_sha256', 'Separate DATA review of the complete row/native and admitted parent role.')))
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=evidence, suppress=suppressions(cp, material['terms']),
        add=[deepcopy(t['added']) for t in material['terms']])


def qualify(cp, material, delivered, actions, loaded, path, out):
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.repair import load_repair
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from system_campaign_sprint_facts import published_packet, qualify_packet_schema
    from system_campaign_2021_completions_facts import notional, require_witness
    qualify_packet_schema(Packet, cp['base']['sources']['research/pooled_input_support/adapter.py'])
    checks = 0
    for t in material['terms']:
        sid = t['security_id']
        bar = vendor(delivered[sid]) if sid in delivered else None
        prior = SimpleNamespace(median5={'selected': [sid]}, feed={'series': {sid: {
            'signal_basis_anchor': (t['last_trading_session'], 1., 1.)}}}, last_processed_session=t['last_trading_session'])
        for day in sorted({t['native_session'], t['added']['session']}):
            original = Packet(day, (bar,) if bar and day == t['added']['session'] else (), {}, {}, 1., {},
                              tuple(actions.terminal.get(day, ())), ())
            before = asdict(original)
            fixed = backtest.apply_repair(original, loaded)
            expected = deepcopy(before)
            expected['terminal'] = asdict(fixed)['terminal']
            need(asdict(original) == before and asdict(fixed) == expected,
                 'FUTURE_ONLY_TERMINAL_PACKET_FIELD_CHANGED')
            matches = [v for v in fixed.terminal if v.security_id == sid]
            if day == t['added']['session']:
                need(len(matches) == 1 and asdict(matches[0]) == t['added'] and matches[0].completeness(1)[0],
                     'FUTURE_EXACT_COMPLETE_ORDINARY_TERM')
                values = terminal_returns.values(prior=prior, published=published_packet(fixed))
                need(values[sid] == float(notional(t['added'], bar)), 'FUTURE_EXACT_CANONICAL_CONTROLLER_NOTIONAL')
                if bar:
                    try:
                        terminal_returns.values(prior=prior, published=SimpleNamespace(session=day, bars=(), terminal_events=fixed.terminal))
                    except ValueError as error:
                        need('lacks delivered close' in str(error), 'FUTURE_MISSING_DELIVERY_REFUSAL_REASON')
                    else:
                        raise ValueError('REFUSED_FUTURE_MISSING_DELIVERY_QUOTE_ACCEPTED')
                    try:
                        require_witness({**delivered[sid], 'issuer_id': 'WRONG'}, t['delivered_identity_witness'])
                    except ValueError:
                        pass
                    else:
                        raise ValueError('REFUSED_FUTURE_WRONG_DELIVERY_IDENTITY_ACCEPTED')
            elif day <= cp['source_cursor']:
                need(fixed == original and len(matches) == 1, 'FUTURE_CONSUMED_NATIVE_PACKET_UNCHANGED')
            else:
                need(not matches, 'FUTURE_LAST_NATIVE_TRADING_SESSION_PRESERVED')
            # A same-day native replacement requires this falsifier too.
            if day == t['native_session'] and day > cp['source_cursor']:
                bad = json.loads(path.read_bytes())
                row, = [r for r in bad['suppress'] if r['security_id'] == sid]
                row['term_sha256'] = '0' * 64
                target = out / ('wrong-native-' + t['ticker'] + '.json')
                save(target, bad)
                wrong = load_repair(target, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
                try:
                    backtest.apply_repair(original, wrong)
                except ValueError as error:
                    need(str(error).startswith('suppressed original terminal differs:'), 'FUTURE_NATIVE_PREIMAGE_REFUSAL_REASON')
                else:
                    raise ValueError('REFUSED_FUTURE_WRONG_NATIVE_ACCEPTED')
            checks += 1
        # The original canonical incomplete-term guard must still refuse.
        native = Packet(t['native_session'], (), {}, {}, 1., {}, tuple(actions.terminal.get(t['native_session'], ())), ())
        day = t['identity_witness']['session']
        native_prior = SimpleNamespace(median5={'selected': [sid]}, feed={'series': {sid: {
            'signal_basis_anchor': (day, 1., 1.)}}}, last_processed_session=day)
        try:
            terminal_returns.values(prior=native_prior, published=published_packet(native))
        except ValueError as error:
            need('incomplete leadership cash terminal' in str(error), 'FUTURE_ORIGINAL_INCOMPLETE_GUARD_REASON')
        else:
            raise ValueError('REFUSED_FUTURE_ORIGINAL_INCOMPLETE_GUARD_MISSING')
    for cursor, predecessor in ((cp['source_cursor'], '0' * 64),
                                (loaded.earliest_affected_session, cp['run']['checkpoint_sha256'])):
        try:
            load_repair(path, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
        except ValueError:
            pass
        else:
            raise ValueError('REFUSED_FUTURE_ORDINARY_PARSER_FALSIFIER_ACCEPTED')
    save(out / 'future-input-qualification.json', dict(passed=True, packet_checks=checks,
        only_terminal_field_changed=True, complete_terms_and_canonical_notional_verified=True,
        original_incomplete_guard_retained=True, wrong_predecessor_and_consumed_date_refused=True,
        wrong_native_and_delivery_witness_refused=True, financial_sessions_advanced=0))


def prepare(cp, out, arm):
    material, delivered, actions = hydrate(cp, arm, source_root=out)
    hydrated = out / hydration_name(cp)
    save(hydrated, material)
    path = out / OVERLAY
    save(path, document(cp, material, sha(hydrated.read_bytes())))
    from research.pooled_vacancy_funding.repair import load_repair
    loaded = load_repair(path, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    qualify(cp, material, delivered, actions, loaded, path, out)
    return path, loaded


def review_input(cp, evidence, arm):
    material, _, _ = hydrate(cp, arm, source_root=evidence)
    hydrated = evidence / hydration_name(cp)
    need(json.loads(hydrated.read_bytes()) == material
         and json.loads((evidence / OVERLAY).read_bytes()) == document(cp, material, sha(hydrated.read_bytes())),
         'FUTURE_INDEPENDENT_RECONSTRUCTION_OF_COMPLETE_SELECTED_INPUT')
    return min(r['session'] for field in ('suppress', 'add') for r in json.loads((evidence / OVERLAY).read_bytes())[field])


def hydration_name(cp):
    value = cp['sha256']
    need(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
         'FUTURE_HYDRATION_EXACT_PARENT_HASH')
    return HYDRATED.removesuffix('.json') + '-' + value + '.json'


def cash_postcondition(before, after, ledger_before, ledger_after, terms, result):
    sid, price = terms['security_id'], terms['cash_per_share']
    held = [(k, v) for k, v in sorted(before['episodes'].items(), key=lambda x: int(x[0])) if v['security_id'] == sid]
    if not held:
        need(result['reason'] == 'NOT_HELD' and before == after and ledger_before == ledger_after,
             'FUTURE_UNHELD_CASH_EXACT_NOOP')
        return dict(actual_held=False, quantity=0, nominal_cash=0.)
    running = before['cash']
    events = ledger_after['events'][len(ledger_before['events']):]
    need(result['applied'] is True and ledger_after['events'][:len(ledger_before['events'])] == ledger_before['events']
         and len(events) == len(held), 'FUTURE_EXACT_NUMBER_AND_PREFIX_OF_CASH_POSTS')
    for (slot, episode), event in zip(held, events):
        q = episode['current_shares']
        proceeds = q * price
        need(event['event_type'] == 'CASH_MERGER' and event['security_id'] == sid
             and event['price'] == price and event['shares_delta'] == -q and event['cash_delta'] == proceeds
             and event['detail']['shares'] == q and event['detail']['reference'] == terms['reference']
             and event['fees'] == 0. and event['cash_before'] == running and event['cash_after'] == running + proceeds
             and after['slots'][str(slot)]['occupied_by'] is None, 'FUTURE_EXACT_CONTRACTUAL_CASH_OPERATION_ORDER')
        running += proceeds
    need(after['cash'] == running
         and {k: v for k, v in before['episodes'].items() if v['security_id'] != sid} == after['episodes']
         and ledger_before.get('receivables', []) == ledger_after.get('receivables', [])
         and sid not in after.get('terminal_pending_sessions', {}) and sid not in after.get('terminal_pending_terms', {}),
         'FUTURE_CASH_SETTLED_SOURCE_REMOVED_OTHER_EPISODES_RECEIVABLES_UNCHANGED')
    return dict(actual_held=True, quantity=sum(e['current_shares'] for _, e in held),
                nominal_cash=sum(e['current_shares'] * price for _, e in held))


def actual_terminal_call(frame, step_code, state, ledger, session):
    return (frame.f_code is step_code and frame.f_locals.get('state') is state
            and frame.f_locals.get('ledger') is ledger and frame.f_locals.get('session') == session)


def cash_before_v(record, result, sid, quantity, nominal_cash):
    actual = [r for r in record['cash'] if r['actual_context_call'] and r['security_id'] == sid]
    need(len(actual) == 1 and actual[0]['postcondition'] == dict(
             actual_held=True, quantity=quantity, nominal_cash=nominal_cash)
         and record['engine_calls'] > 0 and record['order'].index('CASH:' + sid) < record['order'].index('ENGINE')
         and not any(s == sid for _, s in record['risk'])
         and not any(p['security_id'] == sid for p in result.state.pending),
         'FUTURE_EXACT_CASH_REMOVAL_BEFORE_UNCHANGED_V_LOOP')


def actual_cash_phase(record, result, arm, selected):
    for term in selected:
        if term['session'] != record['session'] or term['kind'] != 'CASH_MERGER':
            continue
        actual = [v for v in record['cash'] if v['security_id'] == term['security_id']
                  and v['actual_context_call'] is True]
        need(len(actual) == 1, 'FUTURE_ONE_SELECTED_CASH_CALL_IN_ACTUAL_CANONICAL_STEP')
        proof = actual[0]['postcondition']
        if arm == 'P10' and proof['actual_held']:
            cash_before_v(record, result, term['security_id'], proof['quantity'], proof['nominal_cash'])


def actual_stock_phase(record, selected):
    for term in selected:
        if term['session'] != record['session'] or term['kind'] != 'CASH_PLUS_STOCK':
            continue
        actual = [v for v in record['stock'] if v['security_id'] == term['security_id']
                  and v['actual_context_call'] is True]
        need(len(actual) == 1 and actual[0]['applied'] is True,
             'FUTURE_ONE_SELECTED_APPLIED_STOCK_CALL_IN_ACTUAL_CANONICAL_STEP')


class ActualEvents:
    """Delegate unchanged canonical calls; check postconditions before journal commit."""
    def __init__(self, out, arm):
        self.out, self.arm = out, arm
        self.terms = {(t['session'], t['security_id']): t for t in json.loads((out / OVERLAY).read_bytes())['add']}
        self.saved, self.current = [], None

    def patch(self, owner, name, replacement):
        old = getattr(owner, name)
        self.saved.append((owner, name, old))
        setattr(owner, name, replacement)
        return old

    def __enter__(self):
        hosted()
        from research.pooled_vacancy_funding import runtime
        from stock_strategy_shared.wealth_core import terminal, adapter
        # actual_parent already verified the entire own canonical source map.
        self.step_code = adapter.step_session.__code__
        self.advance_original = self.patch(runtime, 'advance', self.advance)
        self.terminal_original = self.patch(terminal, 'apply_terminal', self.terminal)
        if self.arm == 'P10':
            from stock_strategy_shared.wealth_core import capital_risk
            self.decide_original = self.patch(adapter, 'decide', self.decide)
            self.risk_original = self.patch(capital_risk, 'volatility_stop', self.risk)
        return self

    def __exit__(self, *args):
        for owner, name, old in reversed(self.saved):
            setattr(owner, name, old)

    def terminal(self, state, terms, **kwargs):
        key = terms.session, terms.security_id
        if self.current is None or key not in self.terms or terms.kind not in ('CASH_MERGER', 'CASH_PLUS_STOCK'):
            return self.terminal_original(state, terms, **kwargs)
        before, ledger = deepcopy(state.to_dict()), deepcopy(kwargs['ledger'].to_dict())
        caller = inspect.currentframe().f_back
        actual = actual_terminal_call(caller, self.step_code, state, kwargs['ledger'], terms.session)
        need(asdict(terms) == self.terms[key], 'FUTURE_ACTUAL_TERMS_EXACT_SELECTED_CONTRACT')
        result = self.terminal_original(state, terms, **kwargs)
        if terms.kind == 'CASH_PLUS_STOCK':
            after, ledger_after = state.to_dict(), kwargs['ledger'].to_dict()
            need(kwargs.get('phase', 'OPEN') == 'OPEN' and result.get('applied') is True
                 and ledger_after['events'][:len(ledger['events'])] == ledger['events']
                 and not any(e['security_id'] == terms.security_id for e in after['episodes'].values())
                 and terms.security_id not in after.get('terminal_pending_terms', {})
                 and terms.security_id not in after.get('terminal_pending_sessions', {}),
                 'FUTURE_ACTUAL_SELECTED_STOCK_APPLIED_SOURCE_CLEARED')
            self.current['stock'].append(dict(session=terms.session, security_id=terms.security_id,
                actual_context_call=actual, applied=True, result=deepcopy(result),
                before_state_sha256=digest(before), after_state_sha256=digest(after),
                before_ledger_sha256=digest(ledger), after_ledger_sha256=digest(ledger_after)))
            return result
        proof = cash_postcondition(before, state.to_dict(), ledger, kwargs['ledger'].to_dict(), asdict(terms), result)
        need(kwargs.get('phase', 'OPEN') == 'OPEN', 'FUTURE_ACTUAL_CASH_OPEN_PHASE')
        self.current['cash'].append(dict(session=terms.session, security_id=terms.security_id,
            actual_context_call=actual, postcondition=proof))
        if actual:
            self.current['order'].append('CASH:' + terms.security_id)
        return result

    def decide(self, **kwargs):
        if self.current is None:
            return self.decide_original(**kwargs)
        eligible = [(int(k), v['security_id']) for k, v in sorted(kwargs['state'].to_dict()['episodes'].items(), key=lambda x: int(x[0])) if not v['exit_pending']]
        offset = len(self.current['risk'])
        self.current['order'].append('ENGINE')
        result = self.decide_original(**kwargs)
        need(self.current['risk'][offset:] == eligible, 'FUTURE_ALL_SURVIVING_EPISODES_TRAVERSE_ORIGINAL_V_GUARD')
        self.current['engine_calls'] += 1
        return result

    def risk(self, ep, *, bars, session, cfg):
        try:
            result = self.risk_original(ep, bars=bars, session=session, cfg=cfg)
        except BaseException as error:
            if self.current is not None:
                self.current['failed_risk_call'] = dict(slot_id=ep.slot_id, security_id=ep.security_id,
                                                       session=session, error=str(error))
            raise
        if self.current is not None:
            from sentinel.feed.calendar import previous_sessions
            bar = next((b for b in bars if b.security_id == ep.security_id), None)
            need(cfg.economic_profile == 'wealth-core-capital-risk-v-v1' and bar is not None
                 and list(bar.signal_sessions or ()) == previous_sessions(session, 21) and len(bar.closes) >= 21,
                 'FUTURE_ORIGINAL_V21_CAUSAL_AXIS')
            self.current['risk'].append((ep.slot_id, ep.security_id))
        return result

    def advance(self, run, publication):
        need(self.current is None, 'FUTURE_SINGLE_ACTUAL_ADVANCE')
        record = self.current = dict(session=publication.session, cash=[], stock=[], risk=[], order=[], engine_calls=0)
        try:
            result = self.advance_original(run, publication)
            actual_cash_phase(record, result, self.arm, self.terms.values())
            actual_stock_phase(record, self.terms.values())
            if self.arm == 'P10':
                if publication.session == '2020-10-01':
                    cash_before_v(record, result, '510659411298086546', 101, 5302.5)
                elif publication.session == '2022-02-23':
                    cash_before_v(record, result, '576374012507208201', 69, 5468.25)
            if record['cash'] or publication.session in {d for d, _ in self.terms}:
                save(self.out / ('actual-future-event-' + publication.session + '.json'), dict(record, passed=True, financial_source_changed=False))
            return result
        except BaseException as error:
            save(self.out / 'actual-future-event-refusal.json', dict(record, passed=False, error=str(error), financial_source_changed=False))
            raise
        finally:
            self.current = None
