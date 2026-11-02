"""Stopped OWN627 suffix review; canonical restoration is hosted-only."""
from copy import deepcopy
import csv
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile

FALSIFIER_CASES = ('source_holding','source_exit_flag','source_future_buy','source_close_intent',
    'source_receivable','source_unresolved_terminal','source_pending_term','source_pending_session')


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P01_NATIVE_REVIEW_' + code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def read(path):
    path = Path(path); raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.name.endswith('.gz') else raw)


def same_resume_identity(parent, current):
    need(parent['completed'] == 627 and parent['source_cursor'] == '2020-06-29'
         and len(parent['repairs']) == 11, 'EXACT_ADMITTED627_RESUME')
    need(current['base'] == parent['base'] and current['repairs'] == parent['repairs']
         and current['run']['input_sha256'] == parent['run']['input_sha256']
         and parent['run']['input_sha256'] == '53c3b13673552dbf98263ab0272ac11c8951de619bf19e9ddf2020e59b01584a',
         'UNCHANGED_SOURCE_POLICY_INPUT_AND_ALL_ELEVEN_DESCRIPTORS')
    need(627 <= current['completed'] <= 628 and '2020-06-29' <= current['source_cursor'] <= '2020-06-30',
         'BOUNDED_ACTUAL_COMMITTED_CURSOR')


def prefix(raw, commitment):
    size = commitment['bytes']
    need(type(size) is int and 0 <= size <= len(raw), 'COMMITTED_PREFIX_BYTE_BOUND')
    selected = raw[:size]
    need(sha(selected) == commitment['prefix_sha256'] and (not selected or selected.endswith(b'\n')),
         'COMMITTED_PREFIX_EXACT_COMPLETE_ROWS')
    lines = selected.splitlines(keepends=True)
    need((sha(lines[-1]) if lines else None) == commitment['last_record_sha256'], 'COMMITTED_LAST_RECORD')
    return selected


def journal_suffixes(parent, current, old_streams, new_streams):
    suffixes, tails, proofs = {}, {}, {}
    need(set(parent['journals']) == set(current['journals']) == set(old_streams) == set(new_streams),
         'ALL_FOUR_JOURNAL_DOMAINS')
    for name, old_commitment in parent['journals'].items():
        before = old_streams[name]; after = new_streams[name]
        need(prefix(before, old_commitment) == before and after[:len(before)] == before,
             'WHOLE_ADMITTED627_PREFIX_UNCHANGED')
        committed = prefix(after, current['journals'][name])
        need(len(committed) >= len(before), 'NEW_PREFIX_CANNOT_REWIND_PARENT')
        suffixes[name] = [json.loads(v) for v in committed[len(before):].splitlines()]
        tail = after[len(committed):]
        tails[name] = dict(bytes=len(tail), sha256=sha(tail))
        proofs[name] = dict(old=old_commitment, current=current['journals'][name],
                            new_rows=len(suffixes[name]), full_bytes=len(after), full_sha256=sha(after))
    return suffixes, tails, proofs


def committed_attempts(actual, attempted, cursor, next_session):
    need(type(actual) is list and type(attempted) is list
         and all(type(r) is dict and type(r.get('session')) is str for r in attempted), 'ATTEMPT_RECORD_SCHEMA')
    sessions = [r['session'] for r in attempted]
    need(sessions == sorted(sessions)
         and all(day == '2020-06-30' and (day <= cursor or day == next_session) for day in sessions)
         and actual == [r for r in attempted if r['session'] <= cursor],
         'COMMITTED_RECORDS_EXACT_CURSOR_FILTER_OF_ALL_ATTEMPTS')
    return [r for r in attempted if r['session'] > cursor]


def first_one(parent, qualified, financial, current, next_session):
    path = qualified['actual_components']
    need([r['session'] for r in path] == ['2020-06-30']
         and qualified['financial_authority'] is False, 'ONE_ACTUAL_QUALIFIER_SESSION')
    previous = parent['run']
    for item in path:
        need(item['prior_checkpoint'] == previous and item['publication']['session'] == item['session']
             and item['checkpoint']['state']['last_processed_session'] == item['session'],
             'FULL_QUALIFIER_PUBLICATION_PRIOR_AND_CHECKPOINT_ADJACENCY')
        previous = item['checkpoint']
    actual, attempted = financial['actual_components'], financial['attempted_components']
    need(actual == path[:len(actual)] and len(actual) == min(1, current['completed'] - 627)
         and attempted == path[:len(attempted)] and len(attempted) <= 1
         and financial['financial_authority'] is False and financial['qualification_state_adopted'] is False,
         'FRESH_ORIGINAL627_ENTIRE_ONE_SESSION_PATH_EQUAL_NO_FIELD_EXCLUSIONS')
    return committed_attempts(actual, attempted, current['source_cursor'], next_session)


def role_rows(path):
    def roles(state):
        return dict(episodes=deepcopy(state['wealth_core']['episodes']), pending=deepcopy(state['pending']),
                    selected=deepcopy(state['median5']['selected']))
    return [dict(session=row['session'], prior_state_sha256=row['prior_checkpoint']['state_sha256'],
                 state_sha256=row['checkpoint']['state_sha256'],before=roles(row['prior_checkpoint']['state']),
                 after=roles(row['checkpoint']['state'])) for row in path]


def boundary_counts(old_rows, suffix):
    kinds = ('pooled-source-boundary/1', 'research.pooled-action-successor/1')
    need(not any(r.get('schema') in kinds for r in suffix), 'NO_NEW_SOURCE_OR_INPUT_WATCH_BOUNDARY')
    return {kind: sum(r.get('schema') == kind for r in old_rows) for kind in kinds}


def financial_chain(parent, daily, current):
    chain = parent['chain']
    for row in daily:
        need(row['phase'] == 'MEASURED' and row['input_sha256'] == parent['run']['input_sha256'],
             'EVERY_NEW_MEASURED_ROW_SAME_ELEVEN_INPUT_IDENTITY')
        chain = digest(dict(previous=chain, session=row['session'], state_sha256=row['state_sha256'],
                            economics=row['economics']))
        need(chain == row['chain_sha256'], 'NEW_DAILY_CHAIN_STARTS_EXACT_PARENT_CHAIN')
    need(chain == current['chain'], 'CURRENT_CHAIN_EXACT_NEW_PREFIX')
    return chain


def one_session_summary(value, parent):
    need(value.get('status') == 'OWN627_NATIVE_EPOCH_AND_ONE_SESSION_QUALIFIED'
         and type(value.get('component_transitions')) is int and value['component_transitions'] == 1
         and value.get('qualified_through') == '2020-06-30'
         and value.get('epoch_zero_outer_sha256') == parent['sha256']
         and value.get('original_input_sha256') == parent['run']['input_sha256']
         and value.get('original_inputs') == 11
         and value.get('source_epoch_boundary_reemitted') is False
         and value.get('input_boundary_reemitted') is False
         and value.get('financial_authority') is False and value.get('financial_predecessor_authorized') is False,
         'ACTUAL_ONE_SESSION_QUALIFICATION_SAME627_EPOCH')


def source_proof(value, clock, reused, contract):
    need(type(value) is dict and set(value) == {'schema','records','source_clock_qualification',
         'reused_action_qualification','source_contract','source_financial_files_unchanged'}
         and value['schema'] == 'research.p01-native-closing-source-proof/1'
         and type(value['records']) is list and value['source_clock_qualification'] == clock
         and value['reused_action_qualification'] == reused
         and value['source_contract'] == contract
         and value['source_financial_files_unchanged'] is True, 'SOURCE_PROOF_ENTIRE_EXACT_CLOCK_SOURCE_AND_REUSED_SCOPE')
    return value['records']


def refusal_falsifiers(value, cases):
    need(value['schema'] == 'research.p01-native-scope-refusal-falsifiers/1'
         and value['status'] == 'ALL_SCOPED_FALSIFIERS_REFUSED'
         and type(value['tested']) is list and len(value['tested']) == len(cases)
         and set(value['tested']) == set(cases)
         and value['financial_authority'] is False and value['actual_original_state_unchanged'] is True,
         'ALL_EXACT_ACTUAL_SCOPE_FALSIFIERS_WITHOUT_CALLER_MUTATION')
    return value['tested']


def source_scope(state):
    """Independent source-only scope; other securities retain ordinary behavior."""
    sid = '369995575874917058'; core = state['wealth_core']; ledger = state['ledger']
    need(type(core['episodes']) is dict and type(state['pending']) is list
         and all(type(row) is dict and type(row.get('security_id')) is str for row in state['pending']),
         'FULL_SOURCE_ROLE_AND_PENDING_SCHEMA')
    need(not any(row['security_id'] == sid for row in core['episodes'].values())
         and not any(row['security_id'] == sid for row in state['pending']),
         'CLOSING_PROXY_SOURCE_UNHELD_AND_ANY_PENDING_ABSENT')
    need(type(ledger) is dict and set(ledger) == {'events','receivables'}
         and type(ledger['receivables']) is list
         and all(type(row) is dict and type(row.get('security_id')) is str for row in ledger['receivables'])
         and not any(row['security_id'] == sid for row in ledger['receivables']),
         'CLOSING_PROXY_NO_SOURCE_RECEIVABLE')
    need(all(type(core.get(key,{})) is dict and sid not in core.get(key,{})
             for key in ('unresolved_terminals','terminal_pending_terms','terminal_pending_sessions')),
         'CLOSING_PROXY_NO_UNRESOLVED_SOURCE_CLAIM')
    return dict(scope_id='MTCH2_JUNE30_UNHELD_CLOSING_WITNESS_ONLY',session='2020-06-30',security_id=sid,
        unheld=True,all_source_pending_absent=True,source_exit_flags_absent=True,source_receivables_absent=True,
        source_selected=sid in state['median5']['selected'],no_unresolved_terminal_claim=True)


def closing_proxy(path, observations, closing, expected_bars, expected_row_hashes, native_sha):
    """Verify actual frozen CLOSE use and unchanged source ownership, not legal cash."""
    need(len(path) == len(closing) == len(observations) == 1, 'ONE_ACTUAL_CLOSING_PROXY_GATE_REQUIRED')
    item = path[0]; sid = '369995575874917058'; prior = item['prior_checkpoint']['state']; after = item['checkpoint']['state']
    need(item['session'] == item['publication']['session'] == '2020-06-30', 'CLOSING_PROXY_ONLY_JUNE30')
    before_scope, after_scope = source_scope(prior), source_scope(after)
    terms = [row for row in item['publication']['terminal_events'] if row['security_id'] == sid]
    need(len(terms) == 1 and digest(terms[0]) == native_sha, 'EXACT_SOURCE_NATIVE_TERMINAL_PREIMAGE')
    for security_id, expected in expected_bars.items():
        matches = [row for row in item['publication']['bars'] if row['security_id'] == security_id]
        need(len(matches) == 1 and matches[0] == expected, 'ENTIRE_ACTUAL_SOURCE_BARS_EQUAL_FROZEN_PREIMAGES')
    bar = expected_bars[sid]
    need(terms[0]['cash_per_share'] == bar['raw_close'] and bar['raw_close'] > 0 and bar['volume'] > 0,
         'PROXY_IS_ACTUAL_CURRENT_POSITIVE_VOLUME_CLOSE')
    for observed in observations:
        need(observed == dict(session='2020-06-30',post_all11_terminal=terms[0],native_term_sha256=native_sha,
             actual_source_bars=expected_bars,raw_source_row_sha256=expected_row_hashes,
             proxy_equals_current_raw_close=True,source_volume_positive=True,
             phase='CLOSING_WITNESS_ONLY_NOT_LEGAL_CASH_OR_OPENING_FILL',packet_mutated_by_observer=False),
             'ACTUAL_SOURCE_OBSERVER_ENTIRE_CLOSING_PHASE_RECORD')
    anchor = prior['feed']['series'][sid]['signal_basis_anchor']
    need(anchor[0] == prior['last_processed_session'] and Fraction(str(anchor[1])) > 0
         and Fraction(str(anchor[2])) > 0, 'OWN_PRIOR_SIGNAL_AND_RAW_BASIS')
    selected = before_scope['source_selected']
    expected = float(Fraction(str(bar['raw_close'])) * Fraction(str(bar['split_ratio']))
                     * Fraction(str(anchor[2])) / Fraction(str(anchor[1]))) if selected else None
    old_events = prior['ledger']['events']; events = after['ledger']['events']
    need(events[:len(old_events)] == old_events
         and not any(row.get('security_id') == sid for row in events[len(old_events):]),
         'UNHELD_PROXY_ADDS_NO_SOURCE_LEDGER_OR_CASH_SETTLEMENT')
    need(closing[0] == dict(session='2020-06-30',source_selected=selected,prior_signal_basis_anchor=anchor,
         actual_terminal_witness=expected,expected_current_close_normalized=expected,current_close_equivalence=True,
         actual_canonical_kernel_callsite_verified=True,
         source_ledger_events_added=0,source_claims_or_pending_created=False,financial_state_or_input_modified_by_guard=False),
         'EXACT_ACTUAL_CURRENT_CLOSE_NORMALIZED_SENSOR_PROOF')
    return dict(actual_source_scope=before_scope,actual_after_source_scope=after_scope,
        full_source_bars_verified=len(expected_bars),actual_source_observations=len(observations),
        source_current_close_only=True,source_ledger_events_added=0,legal_cash_or_opening_fill_claimed=False)


def correlation(old_raw, new_raw, rows, cursor):
    need(new_raw.startswith(old_raw) and (not old_raw or old_raw.endswith(b'\n')), 'ENTIRE_OLD_CORRELATION_PREFIX')
    old = old_raw.splitlines()
    chain = json.loads(old[-1])['chain_sha256'] if old else digest('system-optimization-002/raw-correlation/1')
    checked, tails = [], []
    for raw in new_raw[len(old_raw):].splitlines():
        record = json.loads(raw); body = dict(record); actual = body.pop('chain_sha256')
        need(record['session'] == '2020-06-30', 'NO_JULY1_OR_LATER_CORRELATION_ADVANCE')
        chain = digest(dict(previous=chain, record=body))
        need(chain == actual, 'EVERY_NEW_CORRELATION_CHAIN')
        if record['session'] <= cursor:
            row = rows[record['session']]
            need(record['next_state_sha256'] == row['state_sha256'] and record['input_sha256'] == row['input_sha256'],
                 'NEW_CORRELATION_ACTUAL_STATE_AND_INPUT')
            checked.append(record['session'])
        else:
            tails.append(dict(session=record['session'], sha256=sha(raw)))
    need(checked == sorted(rows), 'ALL_NEW_CORRELATION_COMMITTED_SESSIONS_NO_SKIP')
    return dict(new_committed_records=len(checked), uncommitted_records=tails, old_record_arithmetic_recomputed=0)


def held_quotes(quotes, expected_members, archive=Path('/frozen/archive/corpus.zip')):
    """Read actual frozen marks, using admitted member commitments, never a provider."""
    needed = dict.fromkeys(key for key, field, value in quotes)
    used = {}
    with zipfile.ZipFile(archive) as source:
        for year in sorted({day[:4] for day, sid in needed}):
            name = 'observations-' + year + '.csv.gz'
            info = source.getinfo(name); hasher = hashlib.sha256()
            with source.open(name) as stream:
                for block in iter(lambda: stream.read(1024**2), b''):
                    hasher.update(block)
            wanted = expected_members[name]
            need(dict(bytes=info.file_size, sha256=hasher.hexdigest())
                 == {key:wanted[key] for key in ('bytes','sha256')}, 'ADMITTED_FROZEN_YEAR_MEMBER_BYTES')
            count = 0
            with source.open(name) as compressed, gzip.GzipFile(fileobj=compressed) as raw, \
                    io.TextIOWrapper(raw, encoding='utf8', newline='') as text:
                for row in csv.DictReader(text):
                    count += 1; key = (row['session'], row['security_id'])
                    if key in needed:
                        need(needed[key] is None, 'UNIQUE_NEW_HELD_SOURCE_OBSERVATION')
                        needed[key] = row
            need(count == wanted['rows'], 'ADMITTED_FROZEN_YEAR_MEMBER_ROW_COUNT')
            used[name] = wanted
    need(all(row is not None for row in needed.values()), 'ALL_NEW_HELD_SOURCE_QUOTES_PRESENT')
    for key, field, value in quotes:
        need(field in ('raw_open','raw_close') and float(needed[key][field]) == value,
             'EXACT_NEW_HELD_FROZEN_RAW_QUOTE')
    return dict(new_held_raw_quote_checks=len(quotes), bounded_frozen_members=used)


def review(spec, out, evidence):
    """Restore saved new checkpoints only; never advance a strategy session."""
    from full_system_core import hosted
    hosted()
    from full_system_benchmark import save
    from p01_native_resume_epoch import historical_epoch
    from p01_native_resume_parent import ROOT_ADMISSION
    from p01_native_resume_accounting import AccountingCursor
    from p01_factual_batch_contract import facts
    from p01_factual_batch_codec import source_terms
    from p01_factual_batch_review import action_scope, advance_retry, pre_event_receipts
    from p01_native_resume_guard import native_seam_scope, source_contract
    from p01_native_resume_contract import specification, reused_qualification, source_rows, NATIVE_SHA
    need(spec == specification(), 'ENTIRE_EXACT_SOURCE_BOUND_SPECIFICATION')
    out, evidence, old = Path(out), Path(evidence), Path('/old')
    with historical_epoch(old, out, spec, checkpoint_path=evidence/'book/checkpoint.json.gz') as binding:
        from research.pooled_vacancy_funding import backtest, runtime, journal
        from research.pooled_input_support.bundle import axis
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding.monthly import MonthlyStats
        from system_campaign_readonly import reader
        from system_campaign_factual_run import preserve_tails
        from core_window_review import factor, near
        parent = binding.parent; current = journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
        same_resume_identity(parent, current)
        need(parent['base']['sources'] == backtest.source_files()
             == binding.source_map['successor_financial_sources']
             and len(binding.source_map['successor_all_sources']) == 516
             and len(parent['base']['sources']) == 224, 'EXACT_CURRENT516_PHYSICAL_AND224_CANONICAL_EPOCH')
        for descriptor in parent['repairs']:
            name = Path('book/repairs')/descriptor['filename']
            need((evidence/name).read_bytes() == (old/name).read_bytes()
                 and sha((evidence/name).read_bytes()) == descriptor['sha256'], 'ELEVEN_ORIGINAL_DOCUMENT_BYTES')
        need((evidence/'book/identity.json').read_bytes() == (old/'book/identity.json').read_bytes(),
             'ORIGINAL_BOOK_IDENTITY_BYTES')
        zero = read(evidence/'zero-session-resume.json')
        need(zero['schema']=='research.p01-native-epoch-zero/1' and zero['epoch_checkpoint'] == parent
             and zero['source']['status']=='OWN627_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS'
             and zero['source']['outer_sha256']==parent['sha256']
             and zero['source']['inner_sha256']==parent['run']['checkpoint_sha256']
             and zero['source']['state_sha256']==parent['run']['state_sha256']
             and zero['source']['input_sha256']==parent['run']['input_sha256']
             and zero['source']['source_boundary_reemitted'] is False
             and zero['source']['financial_predecessor_authorized'] is False
             and zero['prefixes']=={name:dict(before=c,after=c) for name,c in parent['journals'].items()}
             and zero['source']['checkpoint_writes'] == 3
             and zero['source']['financial_sessions_advanced'] == zero['source']['attempted_financial_transitions'] == 0
             and zero['source']['full_checkpoint_and_journals_unchanged'] is True
             and zero['source_epoch_boundary_reemitted'] is False and zero['input_boundary_reemitted'] is False
             and zero['input_sha256'] == parent['run']['input_sha256']
             and zero['financial_authority'] is False and zero['financial_predecessor_authorized'] is False,
             'FULL_ZERO_SESSION_ORIGINAL627_NO_BOUNDARIES')
        need((evidence/'qualification/zero-session-resume.json').read_bytes()
             == (evidence/'zero-session-resume.json').read_bytes(), 'FRESH_FINANCE_AND_QUALIFIER_ENTIRE_ZERO_PROOF')
        qualified = read(evidence/'qualification/qualification-summary.json')
        one_session_summary(qualified,parent)
        reused = reused_qualification(old,binding.source_map)
        need(qualified['reused_action_qualification']==reused
             and qualified['target_independence_qualified'] is True
             and qualified['held_target_holding_qualified'] is True
             and qualified['processing_endpoint']=='2020-06-30'
             and type(qualified['maximum_transitions']) is int and qualified['maximum_transitions']==1
             and qualified['qualification_state_adopted'] is False, 'ENTIRE_ONE_SESSION_QUALIFIER_METADATA_AND_REUSED_SCOPE')
        contract = source_contract(binding)
        qsource = source_proof(read(evidence/'qualification/native-scope-source-proof.json'),
            spec['source_clock_qualification'],reused,contract)
        fsource = source_proof(read(evidence/'native-scope-source-proof.json'),spec['source_clock_qualification'],reused,contract)
        falsifiers = refusal_falsifiers(read(evidence/'qualification/scope-refusal-falsifiers.json'),FALSIFIER_CASES)
        raw_rows = source_rows()
        from research.bounded_20y.run import vendor
        from system_campaign_discovery_context import material
        expected_bars = {row['security_id']:material(vendor(row)) for row in raw_rows.values()}
        expected_row_hashes = {key:digest(row) for key,row in raw_rows.items()}
        full = axis(); dates = full[full.index(backtest.START)-425:full.index(backtest.END)+1]
        end = '2020-06-30'
        wanted = [day for day in dates if parent['source_cursor'] < day <= current['source_cursor']]
        need(len(wanted) == current['completed']-627 and len(wanted) <= 1, 'EXACT_FROZEN_NEW_SESSION_COUNT')
        next_session = dates[dates.index(current['source_cursor'])+1] if current['source_cursor'] < end else None
        stream = reader(journal.Journal, evidence/'book', journal.STREAMS)
        checked, checkpoints, files = [], {}, {}
        def restore(label, checkpoint, verify=True):
            same_resume_identity(parent, checkpoint)
            backtest.validate_checkpoint(checkpoint, parent['base'], dates)
            restored = runtime.restore(checkpoint['run'], policy=parent['base']['policy'],
                input_sha256=backtest.input_hash(checkpoint['base'], checkpoint['repairs']))
            need(runtime.checkpoint(restored) == checkpoint['run'], 'NEW_CHECKPOINT_ENTIRE_CANONICAL_ROUNDTRIP')
            if verify: stream.verify(checkpoint['journals'])
            checked.append(label)
        try:
            restore('epoch-zero', parent); restore('current', current)
            for folder in ('pre-event','month-end'):
                for path in sorted((evidence/'book'/folder).glob('*.json.gz')):
                    checkpoint = journal.read_checkpoint(path)
                    label = path.relative_to(evidence).as_posix(); restore(label, checkpoint)
                    checkpoints[label] = checkpoint; raw = path.read_bytes()
                    files[label] = dict(bytes=len(raw), sha256=sha(raw))
            qrecord = read(evidence/'qualification/actual-one-session-component.json.gz')
            financial = read(evidence/'actual-financial-first-one-component.json.gz')
            need(set(qrecord) == {'actual_components','action_checks','pre_event_checkpoints','inherited_native_scope_checks',
                 'native_seam_scope_checks','closing_proofs','qualifier_checkpoint','financial_authority','qualification_state_adopted'}
                 and qrecord['qualification_state_adopted'] is False
                 and set(financial) == {'actual_components','attempted_components','financial_authority','qualification_state_adopted'},
                 'EXACT_ONE_SESSION_PRODUCER_RECORD_FIELDS_NO_DROPS_OR_Q3_ALIASES')
            qtail = first_one(parent, qrecord, financial, current, next_session)
            qpath = qrecord['actual_components']
            need(qualified['actual_role_and_full_state_checks'] == role_rows(qpath),
                 'QUALIFIER_ROLE_RECORDS_DERIVED_FROM_ENTIRE_ACTUAL_STATES')
            qclosing = closing_proxy(qpath,qsource,qrecord['closing_proofs'],expected_bars,expected_row_hashes,NATIVE_SHA)
            need(qrecord['native_seam_scope_checks'] == [source_scope(qpath[0]['prior_checkpoint']['state'])],
                 'QUALIFIER_ACTUAL_SOURCE_ONLY_SCOPE_FROM_FULL_PRIOR_STATE')
            qcheckpoint = qrecord['qualifier_checkpoint']; same_resume_identity(parent, qcheckpoint)
            need(qcheckpoint['completed'] == 628 and qcheckpoint['source_cursor'] == '2020-06-30'
                 and qcheckpoint['run'] == qpath[-1]['checkpoint'], 'WHOLE_QUALIFIER_CHECKPOINT_ONE_TRANSITION')
            restore('qualifier-current',qcheckpoint,False)
            if wanted:
                need(current['run'] == financial['actual_components'][0]['checkpoint'] == qcheckpoint['run'],
                     'ENTIRE_COMMITTED_CURRENT_RUNTIME_IS_ACTUAL_QUALIFIED_ONE_SESSION')
            else:
                need(current['run'] == parent['run'], 'ZERO_NEW_COMMITTED_ROWS_RETAIN_EXACT_PARENT_RUNTIME')
            for record in qpath:
                restored = runtime.restore(record['checkpoint'], policy=parent['base']['policy'],
                                            input_sha256=parent['run']['input_sha256'])
                need(runtime.checkpoint(restored) == record['checkpoint'], 'QUALIFIER_FULL_RUNTIME_RESTORE')
                checked.append('qualifier-'+record['session'])
        finally:
            stream.close()
        old_streams = {name:(old/f'book/{name}.jsonl').read_bytes() for name in parent['journals']}
        new_streams = {name:(evidence/f'book/{name}.jsonl').read_bytes() for name in parent['journals']}
        suffixes, tails, prefixes = journal_suffixes(parent, current, old_streams, new_streams)
        need(not suffixes['formation'] and [row['session'] for row in suffixes['daily']] == wanted,
             'ALL_NEW_SESSIONS_EXACT_NO_FORMATION_REPLAY_OR_SKIP')
        old_watch = [json.loads(row) for row in old_streams['watch'].splitlines()]
        boundaries = boundary_counts(old_watch, suffixes['watch'])
        financial_chain(parent, suffixes['daily'], current)
        pre = read(evidence/'native-resume-preflight.json')
        need(pre['schema']=='research.p01-native-resume-preflight/1'
             and pre['original_outer_sha256']==parent['sha256']
             and pre['root_admission_descriptor_sha256']==ROOT_ADMISSION
             and pre['next_session']==pre['processing_endpoint']=='2020-06-30'
             and type(pre['maximum_transitions']) is int and pre['maximum_transitions']==1
             and pre['original_inputs']==11 and pre['financial_source_epoch_unchanged'] is True
             and pre['old_financial_and_accounting_audits_reused'] is True
             and pre['old_financial_audits_repeated'] is False and pre['qualification_state_adopted'] is False
             and pre['tails_to_preserve']=={name:dict(bytes=0,sha256=sha(b'')) for name in parent['journals']},
             'ENTIRE_OWN627_ONE_SESSION_PREFLIGHT_AND_ZERO_OLD_TAILS')
        retained_component = pre['retained_action_component']
        retained_raw = (evidence/'retained-qualification/target-independence-component.json.gz').read_bytes()
        need(retained_component['member']=='retained-qualification/target-independence-component.json.gz'
             and retained_component['bytes']==len(retained_raw)==spec['reused_action_component']['bytes']
             and retained_component['sha256']==sha(retained_raw)==spec['reused_action_component']['sha256']
             and retained_component['financial_authority'] is False
             and retained_raw==(old/spec['reused_action_component']['member']).read_bytes(),
             'RETAINED_ADMITTED_COMPONENT_GZIP_VERBATIM_OUTSIDE_FINANCIAL_CHECKPOINT_LINEAGE')
        original = {path.relative_to(old).as_posix():dict(bytes=path.stat().st_size, sha256=sha(path.read_bytes()))
            for folder in ('book','lineage') for path in (old/folder).rglob('*.json.gz')}
        need(pre['original_checkpoint_files'] == original, 'ALL_INHERITED_CHECKPOINTS_NO_OMISSION')
        for name, entry in original.items():
            raw = (evidence/'lineage/original-checkpoints'/name).read_bytes()
            need(raw == (old/name).read_bytes() and dict(bytes=len(raw), sha256=sha(raw)) == entry,
                 'EVERY_HISTORICAL_GZIP_VERBATIM')
        ledger = current['run']['state']['ledger']['events']
        old_ledger = parent['run']['state']['ledger']['events']
        need(ledger[:len(old_ledger)] == old_ledger, 'ENTIRE_ADMITTED627_LEDGER_PREFIX')
        admitted = json.loads(old_streams['daily'].splitlines()[-1])
        anchor = admitted['evidence']['research_entry_audit']['closing_accounting']
        need(admitted['session'] == parent['source_cursor'] and admitted['state_sha256'] == parent['run']['state_sha256']
             and admitted['economics'] == parent['economics']
             and anchor['wealth_core'] == parent['run']['state']['wealth_core']
             and anchor['pending'] == parent['run']['state']['pending']
             and anchor['ledger']['event_count'] == len(old_ledger)
             and anchor['ledger']['receivables'] == parent['run']['state']['ledger']['receivables'],
             'ADMITTED627_CLOSING_AUDIT_AND_COMPLETE_LEDGER_ANCHOR')
        records = facts()['records']; native = source_terms(); scopes = {}
        for row in read('/frozen/bundle/supplements.json'):
            if row.get('security_id') not in {a['source_security_id'] for a in records} and (
                    'UNHELD' in row.get('disposition','').upper() or 'unheld' in row.get('reference','').lower()):
                scopes[(row['effective_session'],row['security_id'])] = digest(row)
        qactions = []; qnative = []
        qprior = qpath[0]['prior_checkpoint']['state']; qpublication = qpath[0]['publication']
        for action in records:
            if action['economic_session'] == '2020-06-30': qactions.append(action_scope(qprior,action,True,True))
        for terms in qpublication['terminal_events']:
            key = ('2020-06-30',terms['security_id']); sid = terms['security_id']
            if key in scopes:
                need(not any(e['security_id']==sid for e in qprior['wealth_core']['episodes'].values())
                     and not any(p['security_id']==sid for p in qprior['pending']), 'QUALIFIER_INHERITED_SCOPE_ACTUAL_PRIOR')
                qnative.append(dict(session='2020-06-30',security_id=sid,unheld=True,
                    all_source_pending_absent=True,source_record_sha256=scopes[key]))
        need(qrecord['action_checks']==qactions and qrecord['inherited_native_scope_checks']==qnative,
             'ALL_QUALIFIER_GROUPED_AND_INHERITED_SOURCE_SCOPE_RECORDS')
        qpre = qrecord['pre_event_checkpoints']
        need(len(qpre)==1 and qpre[0]['session']=='2020-06-30'
             and qpre[0]['outer_sha256']==parent['sha256']
             and qpre[0]['inner_sha256']==parent['run']['checkpoint_sha256']
             and qpre[0]['state_sha256']==parent['run']['state_sha256']
             and qpre[0]['prior_session']==parent['source_cursor']
             and qpre[0]['current_saved_identical_before_guard'] is True
             and qpre[0]['path']=='2020-06-30-'+parent['sha256']+'.json.gz'
             and qpre[0]['current_file']==spec['selected_file'], 'ACTUAL_QUALIFIER_PRE_EVENT_EXACT_ORIGINAL627_CURRENT')
        cursor = AccountingCursor(parent, binding.quote, records)
        prior = deepcopy(parent['economics']); prior_hash = parent['run']['state_sha256']
        stats = MonthlyStats.from_dict(parent['stats']); retries = deepcopy(parent['retries'])
        reports, quote_rows, action_checks, native_checks, seam_checks = [], [], [], [], []
        for row in suffixes['daily']:
            day = row['session']; work = deepcopy(row)
            need(row['state_sha256']==qpath[0]['checkpoint']['state_sha256'],
                 'COMMITTED_DAILY_STATE_EQUALS_ACTUAL_ENTIRE_QUALIFIED_RUNTIME')
            active = [a for a in records if a['economic_session'] == day]
            # Actual per-use roles come from the preserved canonical prior, never the parent role on a later date.
            candidates = [cp for name,cp in checkpoints.items() if name.startswith('book/pre-event/'+day+'-')
                and cp['run']['state_sha256'] == prior_hash
                and cp['source_cursor'] == dates[dates.index(day)-1]]
            if active or day == '2020-06-30':
                need(len(candidates) == 1, 'ACTUAL_CANONICAL_PRE_EVENT_FULL_PRIOR')
            state = candidates[0]['run']['state'] if candidates else None
            if active:
                action_checks.extend(action_scope(state,a,True,True) for a in active)
            if day == '2020-06-30':
                seam_checks.extend(native_seam_scope(state,day))
            packet = Packet(day,(),{},{},1.,{},tuple(native.get(day,())),())
            for obj in binding.objects: packet = backtest.apply_repair(packet,obj)
            for terms in packet.terminal:
                key = (day,terms.security_id)
                if key in scopes:
                    need(len(candidates) == 1, 'ACTUAL_NATIVE_SCOPE_PRE_EVENT_PRIOR')
                    state = candidates[0]['run']['state']; sid = terms.security_id
                    need(not any(e['security_id'] == sid for e in state['wealth_core']['episodes'].values())
                         and not any(p['security_id'] == sid for p in state['pending']), 'NATIVE_SCOPE_ACTUAL_UNHELD_NO_PENDING')
                    native_checks.append(dict(session=day,security_id=sid,unheld=True,
                        all_source_pending_absent=True,source_record_sha256=scopes[key]))
            for key,phase,valuation in (('opening_accounting','OPEN_BEFORE_FILLS','parent_core_open_equity'),
                                        ('closing_accounting','CLOSE_AFTER_DECISION','parent_core_close_equity')):
                snapshot = deepcopy(row['evidence']['research_entry_audit'][key])
                count = snapshot['ledger'].pop('event_count')
                need(type(count) is int and len(old_ledger) <= count <= len(ledger)
                     and snapshot['session'] == day and snapshot['phase'] == phase, 'NEW_RAW_SNAPSHOT_EVENT_PREFIX_AND_PHASE')
                snapshot['ledger']['events'] = ledger[:count]; cursor.reconcile(snapshot)
                near(snapshot['resolved_equity'], row['economics'][valuation], 'NEW_RAW_ACCOUNT_EQUITY_EQUALS_SENSOR')
                for episode in snapshot['wealth_core']['episodes'].values():
                    if not episode['current_shares']: continue
                    mark = snapshot['prices'][episode['security_id']]
                    need(mark['status'] in ('RAW_OPEN','CURRENT'), 'NO_UNEXPLAINED_NEW_HELD_CARRY')
                    quote_rows.append(((day,episode['security_id']),
                        'raw_open' if mark['status']=='RAW_OPEN' else 'raw_close',mark['raw_price']))
                work['evidence']['research_entry_audit'][key] = snapshot
            factor(prior,work); prior = row['economics']; prior_hash = row['state_sha256']
            retry_summary = advance_retry(retries,row)
            report = stats.advance(day,{k:Decimal(v) for k,v in row['comparison_navs'].items()},
                core_target=str(row['decision']['target_core_exposure']),month_end=dates[dates.index(day)+1][:7]!=day[:7])
            if report: report['slot_retries']=retry_summary; reports.append(report)
        need(prior == current['economics'] and prior_hash == current['run']['state_sha256']
             and stats.to_dict() == current['stats'] and retries == current['retries']
             and reports == suffixes['monthly'], 'ALL_NEW_FACTORS_MONTHLY_RETRIES_AND_CURRENT_STATE_STRICT')
        quarter_ends = [day for day in wanted if day[5:7] in ('03','06','09','12')
                        and dates[dates.index(day)+1][:7] != day[:7]]
        need(all(any(name.startswith('book/month-end/'+day+'-') and cp['source_cursor']==day
                     for name,cp in checkpoints.items()) for day in quarter_ends), 'CANONICAL_QUARTER_BOUNDARY_MONTH_END_CHECKPOINTS')
        outcome = read(evidence/'native-resume-outcome.json')
        need(outcome['source_cursor'] == current['source_cursor'] and outcome['completed'] == current['completed']
             and outcome['original_own627_resumed_fresh'] is True and outcome['qualification_state_adopted'] is False
             and outcome['source_epoch_boundary_reemitted'] is False and outcome['input_boundary_reemitted'] is False
             and outcome['actual_action_scope_checks'] == action_checks
             and outcome['actual_native_seam_scope_checks'] == seam_checks
             and outcome['actual_inherited_native_scope_guards'] == native_checks,
             'ACTUAL_FRESH_ORIGINAL627_SCOPE_AND_OUTCOME_BINDINGS')
        attempted = {}
        for actual in ('actual_role_and_full_state_checks','actual_action_scope_checks',
                       'actual_native_seam_scope_checks','actual_inherited_native_scope_guards','actual_closing_sensor_proofs'):
            key = actual.replace('actual_','attempted_',1)
            attempted[key] = committed_attempts(outcome[actual],outcome[key],current['source_cursor'],next_session)
        need(outcome['actual_role_and_full_state_checks']
             == qualified['actual_role_and_full_state_checks'][:min(1,len(wanted))]
             and outcome['attempted_role_and_full_state_checks']
             == qualified['actual_role_and_full_state_checks'][:len(outcome['attempted_role_and_full_state_checks'])],
             'ALL_FIRST_ONE_ROLE_AND_FULL_STATE_RECORDS_EXACT')
        need(outcome['actual_closing_sensor_proofs'] == qrecord['closing_proofs'][:len(financial['actual_components'])]
             and outcome['attempted_closing_sensor_proofs'] == qrecord['closing_proofs'][:len(financial['attempted_components'])],
             'FRESH_FINANCE_ENTIRE_ACTUAL_AND_ATTEMPTED_CLOSING_SENSOR_PROOFS')
        fclosing = None
        if financial['attempted_components']:
            fclosing = closing_proxy(financial['attempted_components'],fsource,
                outcome['attempted_closing_sensor_proofs'],expected_bars,expected_row_hashes,NATIVE_SHA)
        for row in attempted['attempted_action_scope_checks']:
            matches = [a for a in records if a['action_id']==row['action_id'] and a['economic_session']==row['session']]
            need(len(matches)==1 and row==action_scope(current['run']['state'],matches[0],True,True),
                 'UNCOMMITTED_ACTION_SCOPE_USES_ACTUAL_SAVED_PRIOR')
        if attempted['attempted_native_seam_scope_checks']:
            expected = native_seam_scope(current['run']['state'],next_session)
            need(attempted['attempted_native_seam_scope_checks'] == expected[:len(attempted['attempted_native_seam_scope_checks'])],
                 'UNCOMMITTED_SEAM_SCOPE_USES_ACTUAL_SAVED_PRIOR')
        for row in attempted['attempted_inherited_native_scope_guards']:
            key = (row['session'],row['security_id']); sid = row['security_id']
            need(key in scopes and row==dict(session=row['session'],security_id=sid,unheld=True,
                 all_source_pending_absent=True,source_record_sha256=scopes[key])
                 and not any(e['security_id']==sid for e in current['run']['state']['wealth_core']['episodes'].values())
                 and not any(p['security_id']==sid for p in current['run']['state']['pending']),
                 'UNCOMMITTED_NATIVE_SCOPE_USES_ACTUAL_SAVED_PRIOR')
        pre_event_receipts(outcome['actual_pre_event_checkpoints'],checkpoints,files)
        identical_current_archives = []
        current_raw = (evidence/'book/checkpoint.json.gz').read_bytes()
        for name, checkpoint in checkpoints.items():
            if checkpoint == current:
                need((evidence/name).read_bytes() == current_raw,
                     'CURRENT_AND_IDENTICAL_ARCHIVE_DETERMINISTIC_GZIP_BYTES')
                identical_current_archives.append(name)
        complete = current['source_cursor']==end and current['completed']==628 and len(wanted)==1
        need((outcome['status']=='COMPLETE_NATIVE_RESUME_SEGMENT_PENDING_REVIEW') == complete,
             'NO_COMPLETE_STATUS_FOR_PARTIAL_PREFIX')
        need(not complete or (outcome['canonical_return_code']==0 and all(v['bytes']==0 for v in tails.values())),
             'COMPLETE1_ONLY_WITH_RETURN0_AND_ZERO_CURRENT_TAILS')
        quotes = held_quotes(quote_rows,spec['frozen_observation_members'])
        corr = correlation(gzip.decompress((old/'correlation-inputs.jsonl.gz').read_bytes()),
            gzip.decompress((evidence/'correlation-inputs.jsonl.gz').read_bytes()),
            {r['session']:r for r in suffixes['daily']},current['source_cursor'])
        result = dict(schema='research.p01-native-resume-suffix-review/1',
            status='NATIVE_RESUME_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',
            checkpoint_sha256=current['sha256'],source_cursor=current['source_cursor'],completed=current['completed'],
            new_financial_rows=len(wanted),segment_complete=complete,accounting=cursor.result(),
            new_accounting_snapshots=2*len(wanted),new_monthly_reports=len(reports),
            all_new_monthly_and_retry_checkpoint_state_exact=True,all_new_accounting_factors_and_chains_verified=True,
            old_financial_admission_reused_sha256=ROOT_ADMISSION,old_accounting_snapshots_recomputed=0,
            old_audits_repeated=False,source_epoch_boundary_reemitted=False,input_boundary_reemitted=False,
            old_eleven_inputs_unchanged=True,input_sha256=parent['run']['input_sha256'],
            original_chain_sha256=parent['chain'],watch_boundary_counts=boundaries,checked_new_source_checkpoints=checked,
            all_historical_checkpoint_gzip_bytes_preserved=True,actual_quarter_boundary_checkpoints=quarter_ends,
            grouped_action_checks=action_checks,native_seam_scope_checks=seam_checks,inherited_native_scope_checks=native_checks,
            attempted_records_preserved_and_committed_subsets_exact=True,uncommitted_attempts=attempted,
            qualifier_uncommitted_first_one_records=qtail,actual_pre_event_checkpoint_receipts=outcome['actual_pre_event_checkpoints'],
            actual_qualified_closing_proxy=qclosing,actual_financial_closing_proxy=fclosing,
            actual_closing_sensor_proofs=outcome['actual_closing_sensor_proofs'],
            actual_scope_refusal_falsifiers=falsifiers,actual_closing_source_contract=contract,
            retained_action_component=retained_component,
            identical_current_archive_gzip_paths=identical_current_archives,
            prefixes=prefixes,current_tails=tails,raw_quotes=quotes,correlation=corr,recovered_tails=preserve_tails(evidence/'book',pre),
            qualification_state_adopted=False,financial_predecessor_admitted=False,full_p01_comparison_complete=False,
            production_contacted=False)
        save(out/'native-resume-financial-review.json',result)
        return result


main = review
