"""Continue admitted P01 evidence with one disclosed fractional-cash estimate.

No canonical engine implementation is copied here. All financial execution is
restricted to the existing offline GitHub worker and its frozen source epoch.
"""
import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN
from fractions import Fraction
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import traceback
import zipfile

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from typing import Literal
from p01_iac_unit_contract import need, sha, digest, unique

HERE = Path(__file__).parent
REQUEST = 'p01_iac_namespace_continue_request.json'
SPEC = 'p01_iac_namespace_continue_parent.json'
INPUT = 'p01_iac_namespace_continue_input.json'
SCHEMA = 'research.p01-estimated-fraction-input/1'
STAGE = 'campaign-p01-accurate-progress'
SID = '107908173248206014'
TARGET = '179665193162456864'
EVENT = '2020-10-08'
END = '2026-07-31'
ROOT_ADMISSION = '6eb93b3367bbca557c39e3cb8a26f0e11d316b2036077d68604a6e25f4a2fa00'
OUTER = '5dc336e287d41607b338bd84c6a143a3f1701eb95b307461b8ac478c5e9cb6c3'
ORIGIN = 'da8f0ef0e04f70f1f388ee68ee1bb70d923dcb35b41f53e4d39b3e1e4b81f0ee'


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def read(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def cp_read(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()), object_pairs_hook=unique)


class EstimatedInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.p01-estimated-fraction-input/1'] = Field(alias='schema')
    earliest_affected_session: Literal['2020-10-08']
    predecessor_checkpoint_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    root_admission_sha256: Literal[ROOT_ADMISSION]
    source_security_id: Literal[SID]
    delivered_security_id: Literal[TARGET]
    exchange_ratio: Literal['11/20']
    estimated_delivered_share_basis: Literal['73.2545']
    basis: Literal['SEC_RSU_CASH_40_29_DIVIDED_BY_0_55_ESTIMATE_NOT_OBSERVED_VWAP']
    fractional_cash_rounding: Literal['HOLDER_FLOOR_TO_CENTS']
    reference_policy: Literal['EXISTING_CANONICAL_INITIAL_REFERENCE_ROUNDING_QUALIFIED_AT_EVENT']
    sources: list[str]
    _sha256: str | None = PrivateAttr(default=None)

    @property
    def sha256(self):
        return self._sha256


def settlement(episodes):
    """Exact holder settlement math, independent of the canonical engine."""
    quantities = [Fraction(str(e['current_shares'])) for e in episodes]
    need(quantities and all(q > 0 for q in quantities), 'ESTIMATE_POSITIVE_SOURCE_HOLDINGS')
    quantity = sum(quantities, Fraction())
    entitlement = quantity * Fraction(11, 20)
    whole = entitlement.numerator // entitlement.denominator
    fraction = entitlement - whole
    need(whole > 0, 'ESTIMATE_DELIVERY_REQUIRES_POSITIVE_WHOLE_SHARES')
    cents = (fraction * Fraction('73.2545') * 100).__floor__()
    cash = Fraction(cents, 100)
    # This is a settlement allocation rate, never an observed market price.
    rate = None if not fraction else float(cash / fraction)
    return dict(quantity=str(quantity), whole=whole, fraction=str(fraction),
                modeled_cash=str(cash), allocation_rate=rate,
                estimated_basis='73.2545', observed_contract_vwap=None)


def parent_check(root, spec):
    path = Path(root) / 'book/checkpoint.json.gz'
    raw = path.read_bytes(); cp = cp_read(path)
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['selected_file'], 'CONTINUE_RAW_PARENT')
    need(cp['sha256'] == spec['outer_sha256']
         and cp['sha256'] == digest({k: v for k, v in cp.items() if k != 'sha256'})
         and cp['completed'] == spec.get('completed', 697) and cp['source_cursor'] == spec.get('selected_session', '2020-10-07')
         and cp['run']['checkpoint_sha256'] == spec['inner_sha256']
         and cp['run']['state_sha256'] == spec['state_sha256']
         and cp['run']['input_sha256'] == spec['input_sha256']
         and cp['base'] == spec['base'] and cp['repairs'] == spec['repairs']
         and len(cp['repairs']) == len(spec['repairs']), 'CONTINUE_ADMITTED_PARENT_IDENTITY')
    for name, entry in cp['journals'].items():
        raw = (Path(root) / 'book' / (name + '.jsonl')).read_bytes()
        need(sha(raw[:entry['bytes']]) == entry['prefix_sha256'], 'CONTINUE_PARENT_PREFIX')
        tail = raw[entry['bytes']:]
        need(dict(bytes=len(tail), sha256=sha(tail)) == spec['tails'][name], 'CONTINUE_PRESERVED_OLD_TAIL')
    return cp


def prepare(old, out, spec):
    """Continue committed bytes; retain the refused tail separately."""
    cp = parent_check(old, spec); book = out / 'book'; book.mkdir()
    for dirname in ('repairs', 'source-successors', 'predecessor-checkpoints'):
        source = old / 'book' / dirname
        if source.exists(): shutil.copytree(source, book / dirname)
    (book / 'predecessor-checkpoints').mkdir(exist_ok=True)
    for path in book.rglob('*'):
        if path.is_dir(): os.chmod(path, 0o700)
    for name in ('checkpoint.json.gz', 'identity.json'):
        shutil.copyfile(old / 'book' / name, book / name)
    shutil.copyfile(old / 'book/checkpoint.json.gz', book / 'predecessor-checkpoints' / (cp['sha256'] + '.json.gz'))
    # Preserve existing raw archived checkpoints without using them as new state.
    lineage = out / 'lineage/original-checkpoints'; lineage.mkdir(parents=True)
    for base in ('book', 'lineage'):
        for path in (old / base).rglob('*.json.gz'):
            target = lineage / path.relative_to(old)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
    tail_dir = out / 'preserved-unadmitted-tails'; tail_dir.mkdir()
    for name, entry in cp['journals'].items():
        raw = (old / 'book' / (name + '.jsonl')).read_bytes()
        (book / (name + '.jsonl')).write_bytes(raw[:entry['bytes']])
        if raw[entry['bytes']:]: (tail_dir / (name + '.jsonl')).write_bytes(raw[entry['bytes']:])
    for name in ('source-successor.json', 'source-map.json', 'source-bindings.json',
                 'hydrated-factual-catalog.json', 'hydrated-distribution-catalog.json'):
        if (old / name).exists(): shutil.copyfile(old / name, out / name)
    return cp


class EstimateCodec:
    def __init__(self, parent):
        self.parent = parent; self.objects = []; self.applied = []
        self.episodes = [deepcopy(e) for e in parent['run']['state']['wealth_core']['episodes'].values()
                         if e['security_id'] == SID]
        self.value = settlement(self.episodes)

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        raw = Path(path).read_bytes(); value = json.loads(raw)
        if value.get('schema') != SCHEMA:
            return self.original_load(path, resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        need(raw == (HERE / INPUT).read_bytes() and resume_session == self.parent['source_cursor']
             and predecessor_checkpoint_sha256 == self.parent['run']['checkpoint_sha256'], 'ESTIMATE_EXACT_FUTURE_INPUT')
        result = EstimatedInput.model_validate(value); result._sha256 = sha(raw)
        need(result.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256, 'ESTIMATE_INPUT_PARENT')
        self.objects.append(result); return result

    def apply(self, packet, loaded):
        if not isinstance(loaded, EstimatedInput): return self.original_apply(packet, loaded)
        need(any(loaded is obj for obj in self.objects), 'ESTIMATE_REGISTERED_TYPED_INPUT')
        if packet.day != EVENT: return packet
        from system_campaign_discovery_context import material
        from p01_factual_batch_contract import facts, term
        action, = [a for a in facts()['records'] if a['source_security_id'] == SID]
        source, = [t for t in packet.terminal if t.security_id == SID]
        need(material(source) == term(action), 'ESTIMATE_EXACT_PREVIOUS_TERMINAL_PREIMAGE')
        changed = replace(source, cash_in_lieu_price_per_delivered_share=self.value['allocation_rate'])
        self.applied.append(dict(session=packet.day, source_term=material(source),
                                 estimated_term=material(changed), settlement=self.value))
        return replace(packet, terminal=tuple(changed if t is source else t for t in packet.terminal))

    def scope(self, prior, action):
        from p01_factual_batch_guard import require_scope, roles
        if action['source_security_id'] != SID: return require_scope(prior, action)
        value = roles(prior)
        held = [e for e in value['episodes'].values() if e['security_id'] == SID]
        need(held == self.episodes and not any(p['security_id'] == SID for p in value['pending'])
             and not any(e.get('exit_pending', False) for e in held), 'ESTIMATE_EXACT_QUALIFIED_HOLDINGS_NO_SOURCE_INTENT')
        need(settlement(held) == self.value, 'ESTIMATE_HOLDER_CASH_AND_QUANTITY_CONSERVATION')
        return value

    def expected_term(self, action):
        from p01_factual_batch_contract import term
        value = term(action)
        if action['source_security_id'] == SID:
            value['cash_in_lieu_price_per_delivered_share'] = self.value['allocation_rate']
        return value

    def __enter__(self):
        from research.pooled_vacancy_funding import backtest, repair
        self.backtest, self.repair = backtest, repair
        self.original_load, self.saved_load = repair.load_repair, backtest.load_repair
        self.original_apply = backtest.apply_repair
        repair.load_repair = backtest.load_repair = self.load; backtest.apply_repair = self.apply
        return self

    def __exit__(self, *args):
        self.repair.load_repair = self.original_load; self.backtest.load_repair = self.saved_load
        self.backtest.apply_repair = self.original_apply


class SourceGate:
    def __init__(self, parent, old, out):
        self.parent = parent; self.old = old; self.out = out; self.allowed = {parent['sha256']: parent}

    def load(self, path, current_base):
        from p01_iac_unit_parent import SOURCE_RECEIPT
        need(Path(path).resolve() == (self.old / 'source-successor.json').resolve()
             and sha(Path(path).read_bytes()) == SOURCE_RECEIPT
             and {**current_base, 'source_successor_sha256': SOURCE_RECEIPT} == self.parent['base'], 'CONTINUE_FROZEN_SOURCE_EPOCH')
        cp = cp_read(self.out / 'book/checkpoint.json.gz')
        need(cp['sha256'] in self.allowed and cp == self.allowed[cp['sha256']], 'CONTINUE_EXACT_REGISTERED_STARTUP')
        return deepcopy(self.parent['base']), None

    def allow(self, cp, overlay):
        from system_campaign_pxd_pause import adoption
        event = adoption(cp, self.parent, overlay, EVENT)
        need(cp['run']['state'] == self.parent['run']['state'] and cp['completed'] == 697
             and cp['source_cursor'] == '2020-10-07' and cp['base'] == self.parent['base']
             and cp['repairs'][:-1] == self.parent['repairs'] and len(cp['repairs']) == 13,
             'CONTINUE_INPUT_ADOPTION_HAS_NO_FINANCIAL_TRANSITION')
        self.allowed[cp['sha256']] = deepcopy(cp); return event

    def __enter__(self):
        from research.pooled_vacancy_funding import source_successor
        self.module = source_successor; self.original = source_successor.load_successor
        source_successor.load_successor = self.load; return self

    def __exit__(self, *args): self.module.load_successor = self.original


@contextmanager
def hydrate(old, out, spec, rows):
    """Authenticate and register all twelve historical codecs before restore."""
    from full_system_core import hosted
    hosted(); parent = parent_check(old, spec)
    from p01_epoch_resume import _source_files
    mapping = read(old / 'source-map.json')
    need(_source_files() == mapping['successor_all_sources'], 'CONTINUE_EXACT_FROZEN516_SOURCE')
    from p01_iac_quote_epoch import authenticated_quote
    quote, descriptor = authenticated_quote(Path('/celg-input'), Path('/celg-input-descriptor.json'))
    from p01_celg_bridge_run import old_inputs, native
    from p01_celg_bridge_codec import InputCodec as CelgCodec, OLD, SID as CELG
    from p01_factual_batch_codec import InputCodec as BatchCodec, source_terms
    from p01_iac_unit_codec import InputCodec as UnitCodec
    origin = None
    for path in old.rglob('*.json.gz'):
        if not any(s in path.parts for s in ('book', 'lineage')): continue
        value = cp_read(path)
        if isinstance(value, dict) and value.get('sha256') == ORIGIN: origin = value; break
    need(origin is not None, 'CONTINUE_RETAINED_EXACT628_CODEC_ORIGIN')
    from research.pooled_vacancy_funding import backtest
    tenth = read(old / 'book/repairs' / parent['repairs'][9]['filename'])
    need(tenth['quote_capsule'] == descriptor and tenth['terms']['right_quote'] == quote, 'CONTINUE_RETAINED_AUTHENTICATED_QUOTE')
    with old_inputs(old, {**parent, 'repairs': parent['repairs'][:9]}, out / 'contexts'), \
         CelgCodec(native(OLD, CELG), tenth), BatchCodec(source_terms()), UnitCodec(rows, origin) as unit, \
         EstimateCodec(input_origin(old, parent)) as estimate, SourceGate(parent, old, out) as gate:
        for entry in parent['repairs']:
            obj = backtest.load_repair(old / 'book/repairs' / entry['filename'], resume_session=entry['resume_session'],
                                      predecessor_checkpoint_sha256=entry['predecessor_checkpoint_sha256'])
            need(obj.sha256 == entry['sha256'], 'CONTINUE_ALL_TWELVE_ORIGINAL_CODECS_IN_ORDER')
        yield parent, unit, estimate, gate, mapping



def input_origin(old, parent):
    if parent['sha256'] == OUTER: return parent
    for path in old.rglob('*.json.gz'):
        if not any(part in path.parts for part in ('book', 'lineage')): continue
        value = cp_read(path)
        if isinstance(value, dict) and value.get('sha256') == OUTER: return value
    need(False, 'CONTINUE_RETAINED_697_ESTIMATE_INPUT_ORIGIN')


def admitted_capabilities(spec, mapping):
    value = spec['reused_action_qualification']
    need(value['source_map_identity_sha256'] == digest(mapping)
         and all(value[k] is True for k in ('target_independence_qualified', 'held_target_holding_qualified', 'ordinary_representation_qualified'))
         and value['held_source_with_target_pending_qualified'] is False
         and value['old_synthetic_components_reexecuted'] is False,
         'CONTINUE_ONLY_ROOT_ADMITTED_SAME516_ACTION_CAPABILITIES')
    return deepcopy(value)


def monthly_reproduction(evidence, parent=None):
    """Exact reporting replay only; no financial runtime is restored/advanced."""
    from decimal import getcontext
    from research.pooled_vacancy_funding.monthly import MonthlyStats
    getcontext().prec = 50
    current = cp_read(evidence / 'book/checkpoint.json.gz')
    parent = input_origin(evidence, current) if parent is None else parent
    need(parent['completed'] >= 697 and current['completed'] >= parent['completed'], 'MONTHLY_EXACT_PREVIOUS_ADMISSION')
    def rows(name):
        a = parent['journals'][name]['bytes']; b = current['journals'][name]['bytes']
        raw = (evidence / 'book' / (name + '.jsonl')).read_bytes()
        return [json.loads(line) for line in raw[a:b].splitlines()]
    daily = rows('daily'); reports = rows('monthly')
    following = None
    with (evidence / 'book/daily.jsonl').open('rb') as stream:
        stream.seek(current['journals']['daily']['bytes']); line = stream.readline()
        if line: following = json.loads(line)['session']
    if following is None:
        following = '2026-08-03' if current['source_cursor'] == END else read(evidence / 'book/result.json').get('failed_session')
    need(type(following) is str and following > current['source_cursor'], 'MONTHLY_ACTUAL_LOOKAHEAD')
    dates = [r['session'] for r in daily] + [following]
    stats = MonthlyStats.from_dict(parent['stats']); actual = []; stored = []
    for index,row in enumerate(daily):
        report = stats.advance(row['session'], {k:Decimal(v) for k,v in row['comparison_navs'].items()},
            core_target=str(row['decision']['target_core_exposure']), month_end=dates[index+1][:7] != row['session'][:7])
        if report: actual.append(report)
    for value in reports:
        value = deepcopy(value); value.pop('slot_retries'); stored.append(value)
    need(actual == stored and stats.to_dict() == current['stats'], 'ALL_NEW_MONTHLY_REPORTS_AND_FULL_SUMMARY_EXACT')
    source = Path('/variant/research/pooled_vacancy_funding/monthly.py').read_bytes()
    need(sha(source) == current['base']['sources']['research/pooled_vacancy_funding/monthly.py'], 'MONTHLY_ACTUAL_FROZEN_SOURCE')
    return dict(schema='research.p01-exact-linux-monthly-reproduction/1', passed=True,
                parent_sha256=parent['sha256'], checkpoint_sha256=current['sha256'],
                completed=current['completed'], source_cursor=current['source_cursor'],
                new_daily_records=len(daily), new_reports=len(reports),
                all_new_monthly_reports_exact=True, all_monthly_checkpoint_state_exact=True,
                financial_transitions_reexecuted=0, financial_authority=False,
                monthly_source_sha256=sha(source),
                complete_stored_reports_sha256=digest(reports),
                entire_monthly_journal_sha256=sha((evidence / 'book/monthly.jsonl').read_bytes()))


def authenticate_successor(root, key, spec):
    import system_campaign_factual_admit as crypto
    from p01_iac_stopped_review_transport import extract, fences
    from seal import sha256_file
    t = spec['transport']; origin = t['origin']; root.mkdir(mode=0o700); archive = root / 'selected.zip'
    with archive.open('xb') as stream:
        subprocess.run(['gh','api',f'repos/flabber1835/stocker/actions/artifacts/{t["artifact_id"]}/zip'],stdout=stream,check=True,timeout=180)
    need(dict(bytes=archive.stat().st_size,sha256=sha256_file(archive)) == t['zip'], 'CONTINUE_SELECTED_SUCCESSOR_ZIP')
    with zipfile.ZipFile(archive) as z:
        asset = t['asset']; header, tag = crypto.authenticate(z,asset,key); out = root / 'financial'
        extract(z,asset,key,header,tag,out,t['manifest'],origin,t['stage'])
    value = read(out / 'worker-inspect.json')
    command = ['-B','-u','/driver/p01_iac_namespace_continue.py','--mode','economic']
    fences(value,'capital-system-p01-iac-namespace-worker-'+str(origin['run_id'])+'-1',command)
    need(value['Id'] == t['worker_id'] and value['State']['Running'] is False
         and value['State']['OOMKilled'] is False and value['State']['ExitCode'] == 0,
         'CONTINUE_PREVIOUS_ACTUAL_STOPPED_FINANCIAL_WORKER')
    parent_check(out,spec)
    return out

def branch(old, out, spec, rows, *, mode='FAST', maximum=None, qualified=None):
    from full_system_core import arguments
    from research.pooled_vacancy_funding import backtest, journal, runtime
    from p01_factual_batch_pause import EpochPause
    from system_campaign_pxd_pause import PauseAfterAdoption
    from p01_iac_unit_recovery_guard import UnitGuard
    from p01_iac_unit_guard import source_contract
    from p01_iac_unit_contract import reused_qualification
    from system_campaign_factual_run import SeededObservation, correlation_seed
    from system_campaign_acceleration import Execution
    from research.pooled_input_support.bundle import axis
    parent = prepare(old, out, spec)
    wanted = [d for d in axis() if parent['source_cursor'] < d <= END]
    need(len(wanted) == 2156-parent['completed'] and wanted[0] == spec.get('next_session', EVENT) and wanted[-1] == END, 'CONTINUE_EXACT_REMAINING_SOURCE_AXIS')
    with hydrate(old, out, spec, rows) as values:
        parent, unit, estimate, gate, mapping = values
        args = arguments(out / 'book', True); args[args.index('--policy') + 1] = parent['base']['policy']
        source_args = ['--source-successor', str(old / 'source-successor.json')]
        if len(parent['repairs']) == 12:
            # Canonical startup validates the restored state without advancing it.
            with EpochPause(parent, out / 'book/checkpoint.json.gz'):
                code = backtest.main(args + source_args)
            need(code == 0 and journal.read_checkpoint(out / 'book/checkpoint.json.gz') == parent, 'CONTINUE_EXACT_ZERO_STARTUP')
            input_path = out / 'estimated-fraction-input.json'; input_path.write_bytes((HERE / INPUT).read_bytes())
            loaded = backtest.load_repair(input_path, resume_session=parent['source_cursor'],
                                          predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
            with PauseAfterAdoption(parent, out / 'book/checkpoint.json.gz', loaded.sha256, EVENT):
                code = backtest.main(args + source_args + ['--repair-overlay', str(input_path)])
            zero = journal.read_checkpoint(out / 'book/checkpoint.json.gz'); adoption = gate.allow(zero, loaded.sha256)
            need(code == 0, 'CONTINUE_CANONICAL_FUTURE_INPUT_ZERO')
        else:
            need(len(parent['repairs']) == 13 and len(estimate.objects) > 0, 'CONTINUE_REGISTERED_EXISTING_ESTIMATE')
            loaded = estimate.objects[-1]; adoption = None
        reused = reused_qualification(old, mapping) if len(parent['repairs']) == 12 else admitted_capabilities(spec, mapping)
        contract = source_contract(type('Binding', (), {'source_map': mapping})())
        guard = UnitGuard(out / 'book', unit, contract, reused=reused, processing_endpoint=END)
        guard.scope_check = estimate.scope; guard.expected_term = estimate.expected_term
        original_advance = guard.advance; components = []
        def advance(run, published):
            following = original_advance(run, published)
            if published.session in wanted[:2]:
                cp = runtime.checkpoint(following)
                restored = runtime.restore(cp, policy=following.policy, input_sha256=following.input_sha256)
                need(runtime.checkpoint(restored) == cp, 'CONTINUE_EVENT_WHOLE_CANONICAL_ROUNDTRIP')
                if qualified is not None: need(cp == qualified[len(components)], 'CONTINUE_FRESH_FINANCE_EQUALS_QUALIFIED_EVENT')
                components.append(cp)
            return following
        guard.advance = advance
        count = len(wanted) if maximum is None else maximum
        args = arguments(out / 'book', True, count); args[args.index('--policy') + 1] = parent['base']['policy']
        with guard, SeededObservation(out / 'correlation-inputs.jsonl.gz', correlation_seed(old, parent)) as observation, \
             Execution(mode, signal_closes=1) as execution:
            code = backtest.main(args + source_args)
        current = journal.read_checkpoint(out / 'book/checkpoint.json.gz')
        result = dict(schema='research.p01-accurate-progress-outcome/1', completed=current['completed'],
                      source_cursor=current['source_cursor'], new_transitions=current['completed'] - parent['completed'],
                      requested_transitions=count, complete=current['completed'] == 2156 and current['source_cursor'] == END,
                      canonical_return_code=code, parent_sha256=parent['sha256'], input_sha256=loaded.sha256,
                      input_adoption=adoption, estimated_treatment=estimate.value,
                      estimated_applications=estimate.applied, original_twelve_inputs_unchanged=current['repairs'][:12] == parent['repairs'],
                      financial_source_changed=False, qualification_state_adopted=False, production_contacted=False,
                      financial_authority=False, checkpoint_sha256=current['sha256'])
        (out / 'accurate-outcome.json').write_bytes(encoded(result))
        (out / 'acceleration-proof.json').write_bytes(encoded(execution.proof()))
        (out / 'correlation-capture-proof.json').write_bytes(encoded(observation.proof()))
        return components, result


def qualification(old, out, spec, rows):
    reference = out / 'event-reference'; fast = out / 'event-fast'; reference.mkdir(); fast.mkdir()
    ref, r = branch(old, reference, spec, rows, mode='REFERENCE', maximum=2)
    actual, f = branch(old, fast, spec, rows, maximum=2)
    need(len(ref) == len(actual) == 2 and ref == actual and r == f
         and r['new_transitions'] == 2, 'CONTINUE_TARGETED_FRACTION_REFERENCE_FAST_EXACT')
    # Only the new event qualification is performed. No old Q is replayed.
    result = dict(schema='research.p01-estimated-event-qualification/1', passed=True, parent_sha256=OUTER,
                  components=actual, estimated_treatment=r['estimated_treatment'], financial_authority=False,
                  old_qualification_reexecuted=False, qualification_state_adopted=False)
    (out / 'qualification.json.gz').write_bytes(gzip.compress(encoded(result), compresslevel=1))


def review(old, evidence, out, spec, rows):
    from research.pooled_vacancy_funding import journal, runtime, backtest
    from system_campaign_readonly import reader
    from core_window_review import reconcile, factor, near
    parent = parent_check(old, spec); current = cp_read(evidence / 'book/checkpoint.json.gz')
    with hydrate(old, out, spec, rows):
        restored = runtime.restore(current['run'], policy=current['base']['policy'], input_sha256=current['run']['input_sha256'])
        need(runtime.checkpoint(restored) == current['run'] and current['base'] == parent['base']
             and current['repairs'][:len(parent['repairs'])] == parent['repairs'] and len(current['repairs']) == 13,
             'CONTINUE_CURRENT_SOURCE_INPUT_AND_CANONICAL_ROUNDTRIP')
        stream = reader(journal.Journal, evidence / 'book', journal.STREAMS)
        try: stream.verify(current['journals'])
        finally: stream.close()
        events = current['run']['state']['ledger']['events']; prior = parent['economics']; chain = parent['chain']
        watch = (evidence / 'book/watch.jsonl').read_bytes()
        new_watch = [json.loads(v) for v in watch[parent['journals']['watch']['bytes']:current['journals']['watch']['bytes']].splitlines()]
        input_event = read(evidence / 'accurate-outcome.json')['input_adoption']
        if input_event is not None:
            need(new_watch and new_watch[0] == input_event, 'CONTINUE_ONE_ACTUAL_INPUT_CHAIN_ADOPTION')
        successors = [e for e in new_watch if e.get('schema') == 'research.pooled-action-successor/1']
        checked = 0; accountings = 0
        raw = (evidence / 'book/daily.jsonl').read_bytes()
        need(raw[:parent['journals']['daily']['bytes']] == (old / 'book/daily.jsonl').read_bytes()[:parent['journals']['daily']['bytes']], 'CONTINUE_ORIGINAL_DAILY_PREFIX_UNCHANGED')
        for line in raw[parent['journals']['daily']['bytes']:current['journals']['daily']['bytes']].splitlines():
            row = json.loads(line)
            for key, valuation in (('opening_accounting', 'parent_core_open_equity'), ('closing_accounting', 'parent_core_close_equity')):
                snapshot = row['evidence']['research_entry_audit'][key]; n = snapshot['ledger'].pop('event_count')
                need(type(n) is int and 0 <= n <= len(events), 'CONTINUE_FULL_LEDGER_PREFIX')
                snapshot['ledger']['events'] = events[:n]; reconcile(snapshot)
                near(snapshot['resolved_equity'], row['economics'][valuation], 'CONTINUE_INDEPENDENT_RAW_VALUATION'); accountings += 1
            factor(prior, row); prior = row['economics']
            while successors and successors[0]['unchanged_through'] < row['session']:
                chain = backtest.hash_value(dict(previous=chain, event=successors.pop(0)))
            chain = backtest.hash_value(dict(previous=chain, session=row['session'], state_sha256=row['state_sha256'], economics=row['economics']))
            need(chain == row['chain_sha256'], 'CONTINUE_EVERY_NEW_DAILY_CHAIN'); checked += 1
        need(checked == current['completed'] - parent['completed'] and chain == current['chain'] and prior == current['economics'], 'CONTINUE_FINAL_SUFFIX_CHAIN_AND_ECONOMICS')
        for name, entry in parent['journals'].items():
            before = (old / 'book' / (name + '.jsonl')).read_bytes(); after = (evidence / 'book' / (name + '.jsonl')).read_bytes()
            need(after[:entry['bytes']] == before[:entry['bytes']], 'CONTINUE_EVERY_ORIGINAL_COMMITTED_PREFIX')
            tail = before[entry['bytes']:]
            if tail: need((evidence / 'preserved-unadmitted-tails' / (name + '.jsonl')).read_bytes() == tail, 'CONTINUE_OLD_REFUSAL_TAIL_PRESERVED')
        result = dict(schema='research.p01-accurate-progress-review/1', passed=True, completed=current['completed'],
                      source_cursor=current['source_cursor'], new_rows=checked, raw_accounting_snapshots=accountings,
                      checkpoint_sha256=current['sha256'], estimated_treatment=read(evidence / 'accurate-outcome.json')['estimated_treatment'],
                      complete=current['completed'] == 2156 and current['source_cursor'] == END, financial_authority=False)
        result['monthly_reproduction'] = monthly_reproduction(evidence, parent)
        (out / 'accurate-review.json').write_bytes(encoded(result))


def expected_request():
    from seal import sha256_file
    old = read(HERE / 'p01_iac_stopped_review_request.json')
    names = sorted(set(old['sources']) | {'p01_iac_stopped_review_request.json', Path(__file__).name, SPEC, INPUT})
    parent = read(HERE / SPEC)
    return dict(schema='research.p01-accurate-progress-request/1', arm='P01', stage=STAGE,
                parent_sha256=parent['outer_sha256'], root_admission_sha256=parent['root_admission_sha256'], first_session=parent.get('next_session', EVENT), endpoint=END,
                original_sessions=parent.get('completed', 697), remaining_sessions=2156-parent.get('completed', 697), estimated_fractional_cash=True,
                monthly_review_only=parent.get('monthly_review_only',False),
                financial_resume_authorized=parent.get('financial_predecessor_admitted',False) and not parent.get('monthly_review_only',False),
                protocol_sha256=old['protocol_sha256'], capacity_source_sha256=old['capacity_source_sha256'],
                quote_descriptor=old['quote_descriptor'], old_qualification_reexecuted=False,
                financial_wait_seconds=9000, qualification_wait_seconds=1200, review_wait_seconds=1200,
                initial_min_disk_bytes=12*1024**3, preworker_min_disk_bytes=10*1024**3,
                preworker_min_memory_bytes=10*1024**3, production_contacted=False,
                sources={name: sha256_file(HERE / name) for name in names})


def validate_request(path):
    value = expected_request(); need(Path(path).read_bytes() == encoded(value), 'CONTINUE_EXACT_WHOLE_REQUEST_AND_DRIVER_SOURCES')
    return value


def authenticate_parent(root, key):
    """Use the existing retained cipher as this runner's admitted input."""
    import system_campaign_factual_admit as crypto
    from p01_iac_stopped_review_target import target
    from p01_iac_stopped_review_transport import extract, original_stop
    from seal import sha256_file
    selected = read(HERE / SPEC)
    if 'transport' in selected: return authenticate_successor(root, key, selected)
    spec = target(); origin = spec['original']; root.mkdir(mode=0o700); archive = root / 'original.zip'
    with archive.open('xb') as stream:
        subprocess.run(['gh', 'api', f'repos/flabber1835/stocker/actions/artifacts/{origin["artifact_id"]}/zip'], stdout=stream, check=True, timeout=180)
    need(dict(bytes=archive.stat().st_size, sha256=sha256_file(archive)) == origin['zip'], 'CONTINUE_ORIGINAL_IMMUTABLE_ZIP')
    with zipfile.ZipFile(archive) as z:
        asset = origin['assets']['encrypted_output']; header, tag = crypto.authenticate(z, asset, key)
        out = root / 'financial'
        manifest = extract(z, asset, key, header, tag, out, origin['manifests']['financial'], origin, 'campaign-p01-iac-namespace-financial')
    original_stop(read(out / 'worker-inspect.json'), 'worker', spec)
    # Root's independent review and admission authorize this actual checkpoint;
    # the original failed reviewer remains an immutable historical outcome.
    parent_check(out, read(HERE / SPEC))
    return out


def command(name, mode, source, frozen, out, old, capsule, evidence):
    from full_system_trials_job import command as base
    from p01_factual_batch_job import DESCRIPTOR
    args = base(name, source, frozen, out, 'review' if mode in ('review','monthly') else 'economic')
    i = args.index('--entrypoint')
    mounts = []
    for source_path, destination in ((old, '/old'), (capsule, '/celg-input'), (HERE / DESCRIPTOR, '/celg-input-descriptor.json'), (evidence, '/evidence')):
        mounts += ['--mount', f'type=bind,source={source_path},target={destination},readonly']
    args[i:i] = mounts
    args[args.index('-B'):] = ['-B', '-u', '/driver/' + Path(__file__).name, '--mode', mode]
    return args


def inspect(name, identity=None):
    from p01_iac_stopped_review_transport import fences
    from runtime_identity import EXECUTION_IMAGE
    value = json.loads(subprocess.run(['docker', 'inspect', name], capture_output=True, check=True, timeout=20).stdout)[0]
    mode = ('monthly' if read(HERE / SPEC).get('monthly_review_only') else 'review') if '-review-' in name else 'qualify' if '-qualify-' in name else 'economic'
    fences(value, name, ['-B', '-u', '/driver/' + Path(__file__).name, '--mode', mode])
    need(identity is None or value['Id'] == identity, 'CONTINUE_EXACT_RUNNING_CONTAINER_ID')
    need(value['Config']['Labels']['research.role'] == ('review' if mode == 'review' else 'worker'), 'CONTINUE_WORKER_ROLE')
    return value


def host(args):
    from p01_iac_namespace_job import check_context, stage_valid, validate_prepared_receipt, resources, freeze, reconstruct, authenticate_capsule
    from p01_iac_namespace_job import SECRET, stopped_run, StopUnknown
    from system_campaign_p01_accurate_export import qualify_export, finish, write_receipt as public_receipt
    from seal import sha256_file
    check_context(os.environ); need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'CONTINUE_NO_BLIND_RERUN')
    request = validate_request(args.request)
    validate_prepared_receipt(read(args.capacity), head=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'], source_sha256=request['capacity_source_sha256'])
    stage_valid(read(args.staging)); temp = Path(os.environ['RUNNER_TEMP']); args.output.parent.mkdir(parents=True, exist_ok=True)
    def write_receipt(path, value):
        public_receipt(path, value)
        print('P01_PHASE '+value['status'], flush=True)
    receipt = dict(schema='research.p01-accurate-financial-prefix-receipt/1', arm='P01', stage='campaign-p01-accurate-prefix',
                   run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], request_sha256=sha256_file(args.request),
                   protocol_sha256=request['protocol_sha256'], strict_parent_outer_sha256=read(HERE / SPEC)['outer_sha256'],
                   strict_parent_run_id=read(HERE / SPEC).get('run_id', 41487773225), status='PREPARING_CONTINUATION', production_contacted=False)
    write_receipt(args.output, receipt)
    marker = qualify_export(temp / 'p01-progress-export-probe', args.request)
    marker_path = args.output.parent / 'p01-accurate-export-qualification.json'; marker_path.write_bytes(encoded(marker))
    receipt['export_qualification_sha256'] = sha256_file(marker_path)
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True); need(len(key) == 32, 'CONTINUE_SEPARATE_KEY')
    out = temp / 'p01-progress-output'; out.mkdir(mode=0o700); known = False
    try:
        need(shutil.disk_usage(temp).free >= request['initial_min_disk_bytes'], 'CONTINUE_INITIAL_DISK')
        old = authenticate_parent(temp / 'campaign-factual-transfer-p01-progress', key)
        capsule = temp / 'p01-progress-approved-quote'; authenticate_capsule(request['quote_descriptor'], capsule, key=key)
        frozen = temp / 'capital-risk-stage-001/inputs'; original, source = reconstruct(frozen, old, temp)
        for root in (old, capsule, original, source): freeze(root)
        os.environ.pop('GH_TOKEN', None)
        if request['monthly_review_only']:
            need(request['financial_resume_authorized'] is False, 'MONTHLY_CANDIDATE_CANNOT_AUTHORIZE_FINANCE')
            for filename in (SPEC, INPUT, REQUEST): shutil.copyfile(HERE / filename, out / filename)
            name = 'capital-system-p01-iac-namespace-review-' + os.environ['GITHUB_RUN_ID'] + '-1'
            receipt['status'] = 'DATA_ONLY_MONTHLY_REVIEW_RUNNING'; write_receipt(args.output, receipt)
            resources(request,temp)
            receipt['reviewer'] = stopped_run(command(name,'monthly',source,frozen,out,old,capsule,old),name,out,
                deadline=request['review_wait_seconds'],inspector=inspect)
            known = True; stop = receipt['reviewer']
            receipt['status'] = 'MONTHLY_REVIEW_PASSED_PENDING_ROOT' if stop['exit_code'] == 0 and not stop['oom_killed'] else 'MONTHLY_REVIEW_REFUSED_PRESERVED'
            finish(receipt,out,args.output,key,args.request,known=True); key=None
            raise SystemExit(0 if receipt['status']=='MONTHLY_REVIEW_PASSED_PENDING_ROOT' else 2)
        need(request['financial_resume_authorized'] is True, 'ROOT_FINANCIAL_ADMISSION_REQUIRED_BEFORE_CONTINUATION')
        qual = temp / 'p01-progress-new-event-qualification'; qual.mkdir(mode=0o700)
        for name in (SPEC, INPUT, REQUEST): shutil.copyfile(HERE / name, out / name)
        if len(read(HERE / SPEC)['repairs']) == 12:
            name = 'capital-system-p01-iac-namespace-qualify-' + os.environ['GITHUB_RUN_ID'] + '-1'
            resources(request, temp); receipt['status'] = 'NEW_FRACTION_EVENT_QUALIFYING'; write_receipt(args.output, receipt)
            stop = stopped_run(command(name, 'qualify', source, frozen, qual, old, capsule, old), name, qual, deadline=request['qualification_wait_seconds'], inspector=inspect)
            known = True
            shutil.copytree(qual, out / 'new-event-qualification')
            need(stop['exit_code'] == 0 and not stop['oom_killed'], 'CONTINUE_NEW_EVENT_QUALIFICATION_REFUSED')
            proof = json.loads(gzip.decompress((qual / 'qualification.json.gz').read_bytes()))
            need(proof['passed'] is True and proof['parent_sha256'] == OUTER and proof['old_qualification_reexecuted'] is False, 'CONTINUE_NEW_EVENT_QUALIFICATION')
            freeze(qual); resources(request, temp)
        else:
            (qual / 'reused-qualification.json').write_bytes(encoded(dict(root_admission_sha256=read(HERE / SPEC)['root_admission_sha256'], old_qualification_reexecuted=False)))
            freeze(qual); resources(request, temp)
        name = 'capital-system-p01-iac-namespace-worker-' + os.environ['GITHUB_RUN_ID'] + '-1'
        known = False; receipt['status'] = 'FINANCIAL_RUNNING_FROM_ADMITTED_CHECKPOINT'; write_receipt(args.output, receipt)
        receipt['worker'] = stopped_run(command(name, 'economic', source, frozen, out, old, capsule, qual), name, out, deadline=request['financial_wait_seconds'], inspector=inspect)
        known = True; receipt['status'] = 'FINANCIAL_STOPPED_PENDING_REVIEW'; write_receipt(args.output, receipt)
        review_out = temp / 'p01-progress-review'; review_out.mkdir(mode=0o700); resources(request, temp)
        name = 'capital-system-p01-iac-namespace-review-' + os.environ['GITHUB_RUN_ID'] + '-1'
        receipt['reviewer'] = stopped_run(command(name, 'review', source, frozen, review_out, old, capsule, out), name, review_out, deadline=request['review_wait_seconds'], inspector=inspect)
        shutil.copytree(review_out, out / 'stopped-review')
        outcome = read(out / 'accurate-outcome.json'); stop = receipt['reviewer']
        receipt['status'] = ('FINANCIAL_COMPLETE_HOSTED_REVIEWED_PENDING_CLIENT' if outcome['complete'] else 'PARTIAL_PREFIX_HOSTED_REVIEWED') if stop['exit_code'] == 0 and not stop['oom_killed'] else 'FINANCIAL_REVIEW_REFUSED_PRESERVED'
    except StopUnknown:
        known = False; receipt['status'] = 'STOP_UNKNOWN_NO_MUTABLE_EXPORT'
    except Exception as error:
        import re
        code = str(error)
        print('P01_FAILURE '+(code if re.fullmatch('REFUSED_[A-Z0-9_]+', code) else type(error).__name__), flush=True)
        receipt['status'] = 'CONTINUATION_REFUSED_PRESERVED'
        (out / 'driver-failure.txt').write_text(traceback.format_exc())
    finish(receipt, out, args.output, key, args.request, known=known); key = None
    raise SystemExit(0 if receipt['status'] == 'FINANCIAL_COMPLETE_HOSTED_REVIEWED_PENDING_CLIENT' else 2)


def worker(mode):
    from full_system_core import hosted
    hosted(); validate_request(HERE / REQUEST)
    spec = read(HERE / SPEC); old = Path('/old'); out = Path('/out')
    need((mode == 'monthly') == spec.get('monthly_review_only', False), 'EXACT_REQUESTED_REPORTING_OR_FINANCIAL_ROLE')
    if mode == 'economic':
        need(spec.get('financial_predecessor_admitted') is True, 'ROOT_ADMISSION_REQUIRED_BEFORE_WORKER_FINANCE')
    if mode == 'monthly':
        need(spec.get('monthly_review_only') is True and spec.get('financial_predecessor_admitted') is False,
             'ONLY_EXPLICIT_DATA_MONTHLY_CANDIDATE')
        result = monthly_reproduction(old)
        (out / 'monthly-runtime-reproduction.json').write_bytes(encoded(result))
        return
    from p01_iac_unit_codec import source_rows
    rows, _ = source_rows(through=END)
    if mode == 'qualify': qualification(old, out, spec, rows)
    elif mode == 'economic':
        components = None
        if len(spec['repairs']) == 12:
            proof = json.loads(gzip.decompress(Path('/evidence/qualification.json.gz').read_bytes()))
            need(proof['passed'] is True and proof['parent_sha256'] == OUTER, 'CONTINUE_PROOF_BEFORE_FINANCE')
            components = proof['components']
        else:
            need(read(Path('/evidence/reused-qualification.json'))['root_admission_sha256'] == spec['root_admission_sha256'], 'CONTINUE_ADMITTED_QUALIFICATION_REUSE')
        branch(old, out, spec, rows, qualified=components)
    else: review(old, Path('/evidence'), out, spec, rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--mode', choices=('qualify', 'economic', 'review', 'monthly', 'probe'), required=True)
    p.add_argument('--request', type=Path); p.add_argument('--capacity', type=Path)
    args = p.parse_args()
    if args.mode == 'probe':
        validate_request(args.request)
        from ephemeral_runner_capacity import validate_prepared_receipt
        validate_prepared_receipt(read(args.capacity), head=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'], source_sha256=expected_request()['capacity_source_sha256'])
        print('P01 continuation source and capacity checks passed.')
    else: worker(args.mode)
