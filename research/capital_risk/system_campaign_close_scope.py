"""Guarded intraday closing conversion; no owned-lot settlement or account edits.

This module is a research input boundary. The hosted codec delegates every
terminal operation to the unchanged canonical repair implementation. It never
supplies a cash-settlement model for a holding or order in the scoped names.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from system_campaign_uncertainty_input import Digest, Evidence
from system_campaign_uncertainty_math import require


SCHEMA = 'research.guarded-close-conversion-input/1'
WATCH = 'research.guarded-close-conversion-watch/1'
SCOPE = 'UNOWNED_UNORDERED_CONSIDERATION_KNOWN_BEFORE_CLOSE'
NATIVES = {'533554648046407798': '2023-11-06'}
COMPLETIONS = {'533554648046407798': '2023-11-07'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   allow_nan=False).encode()).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'CLOSE_SCOPE_DUPLICATE_JSON_KEY')
        value[key] = item
    return value


def active(session):
    require(type(session) is str and date.fromisoformat(session).isoformat() == session,
            'CLOSE_SCOPE_CANONICAL_SESSION')
    return sorted(sid for sid, first in NATIVES.items() if session >= first)


def require_absent(wealth_core, pending, names):
    require(isinstance(wealth_core, dict) and isinstance(wealth_core.get('episodes'), dict)
            and isinstance(pending, (list, tuple)), 'CLOSE_SCOPE_POSITION_SCHEMA')
    for values, label in ((wealth_core['episodes'].values(), 'OWNED'), (pending, 'ORDERED')):
        require(all(isinstance(v, dict) and type(v.get('security_id')) is str
                    and v['security_id'] not in names for v in values),
                'CLOSE_SCOPE_MUST_NOT_BE_' + label)
    for name in ('unresolved_terminals', 'terminal_pending_terms', 'terminal_pending_sessions', 'terminal_carry_audit'):
        value = wealth_core.get(name, {})
        require(isinstance(value, dict) and not set(value) & set(names),
                'CLOSE_SCOPE_NO_UNRESOLVED_OR_PENDING_TERMINAL_CLAIM')


def require_intents(intents, names):
    require(isinstance(intents, (list, tuple)) and all(isinstance(v, dict)
            and type(v.get('security_id')) is str and v['security_id'] not in names for v in intents),
            'CLOSE_SCOPE_NO_SIGNALLED_ENTRY_INTENT')


def projection(wealth_core, pending, names):
    require_absent(wealth_core, pending, names)
    return dict(wealth_core_sha256=digest(wealth_core), pending=deepcopy(list(pending)))


class GuardedInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, allow_inf_nan=False)
    schema_id: Literal['research.guarded-close-conversion-input/1'] = Field(alias='schema')
    predecessor_checkpoint_sha256: Digest
    scope: Literal['UNOWNED_UNORDERED_CONSIDERATION_KNOWN_BEFORE_CLOSE']
    require_unowned_and_unordered: Literal[True]
    require_no_entry_intents: Literal[True]
    morning_settlement_claimed: Literal[False]
    canonical_repair: dict[str, Any]
    source_evidence: list[Evidence] = Field(min_length=3, max_length=32)
    _file_sha256: str | None = PrivateAttr(default=None)
    _resume_session: str | None = PrivateAttr(default=None)
    _admitted_document_sha256: str | None = PrivateAttr(default=None)
    _canonical: Any = PrivateAttr(default=None)

    @field_validator('require_unowned_and_unordered', 'require_no_entry_intents', 'morning_settlement_claimed', mode='before')
    @classmethod
    def exact_boolean(cls, value, info):
        expected = info.field_name in ('require_unowned_and_unordered', 'require_no_entry_intents')
        require(value is expected, 'CLOSE_SCOPE_EXACT_BOOLEAN')
        return value

    @property
    def sha256(self):
        return self._file_sha256

    @property
    def earliest_affected_session(self):
        return min(t['session'] for key in ('suppress', 'add') for t in self.canonical_repair[key])


def parse(path, *, resume_session, predecessor_checkpoint_sha256, expected_repair, expected_evidence):
    raw = Path(path).read_bytes()
    require(len(raw) <= 1024 * 1024, 'CLOSE_SCOPE_INPUT_SIZE')
    value = GuardedInput.model_validate(json.loads(raw, object_pairs_hook=unique))
    active(resume_session)
    require(value.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256,
            'CLOSE_SCOPE_EXACT_OWN_PREDECESSOR')
    require(resume_session < min(NATIVES.values())
            and resume_session < value.earliest_affected_session, 'CLOSE_SCOPE_UNCONSUMED')
    require(value.canonical_repair == expected_repair
            and expected_repair['schema'] == 'terminal-repair/1'
            and expected_repair['predecessor_checkpoint_sha256'] == predecessor_checkpoint_sha256,
            'CLOSE_SCOPE_EXACT_INDEPENDENTLY_ASSEMBLED_REPAIR')
    evidence = [v.model_dump() for v in value.source_evidence]
    require(evidence == expected_evidence and len({v['reference'] for v in evidence}) == len(evidence),
            'CLOSE_SCOPE_EXACT_EVIDENCE')
    value._file_sha256 = hashlib.sha256(raw).hexdigest()
    value._resume_session = resume_session
    value._admitted_document_sha256 = digest(value.model_dump(by_alias=True))
    return value


class TransitionGuard:
    """Observe both canonical states; commit proof with the actual financial row."""
    def __init__(self, codec):
        self.codec = codec
        self.pending = None
        self.last_session = None
        self.failure = None

    def relevant(self, state, packet):
        original = self.original_relevant(state, packet)
        names = sorted(sid for sid, day in COMPLETIONS.items() if packet.day == day)
        if not names:
            return original
        require(len(self.codec.objects) == 1, 'CLOSE_SCOPE_EVENT_TYPED_INPUT_REQUIRED')
        return {**(original or dict(terminal=[], spinoff=[])),
                'research_close_scope': dict(security_ids=names, scope=SCOPE,
                    guarded_input_sha256=self.codec.objects[0].sha256)}

    def advance(self, run, published):
        names = active(published.session)
        if not names:
            return self.original_advance(run, published)
        require(self.pending is None, 'CLOSE_SCOPE_PREVIOUS_TRANSITION_NOT_COMMITTED')
        require(len(self.codec.objects) == 1, 'CLOSE_SCOPE_TYPED_INPUT_REQUIRED')
        obj = self.codec.objects[0]
        require(digest(obj.model_dump(by_alias=True)) == obj._admitted_document_sha256,
                'CLOSE_SCOPE_ADMITTED_INPUT_UNCHANGED')
        try:
            before = projection(run.state.wealth_core, run.state.pending, names)
            require_intents(run.state.last_evidence['wealth_core']['intents'], names)
            result = self.original_advance(run, published)
            after = projection(result.state.wealth_core, result.state.pending, names)
            require_intents(result.state.last_evidence['wealth_core']['intents'], names)
        except Exception:
            self.failure = dict(session=published.session, affected_security_ids=names,
                                prior_state_sha256=run.state.state_hash,
                                input_sha256=run.input_sha256,
                                after_state_sha256=None if 'result' not in locals() else result.state.state_hash,
                                financial_row_committed=False)
            raise
        self.pending = dict(schema=WATCH, session=published.session, scope=SCOPE,
                            affected_security_ids=names, guarded_input_sha256=obj.sha256,
                            input_sha256=run.input_sha256, prior_state_sha256=run.state.state_hash,
                            next_state_sha256=result.state.state_hash, before=before, after=after)
        return result

    def append(self, journal, name, record):
        if name not in ('formation', 'daily') or not active(record['session']):
            return self.original_append(journal, name, record)
        value = self.pending
        require(value is not None and value['session'] == record['session']
                and value['next_state_sha256'] == record['state_sha256']
                and value['input_sha256'] == record['input_sha256'],
                'CLOSE_SCOPE_EXACT_ACTUAL_FINANCIAL_ROW')
        require(self.last_session is None or self.last_session < record['session'],
                'CLOSE_SCOPE_STRICT_ACTUAL_AXIS')
        self.original_append(journal, 'watch', {**value, 'financial_row_sha256': digest(record)})
        result = self.original_append(journal, name, record)
        self.last_session = record['session']
        self.pending = None
        return result

    def __enter__(self):
        from research.pooled_vacancy_funding import backtest, journal, runtime
        self.runtime, self.journal, self.backtest = runtime, journal, backtest
        self.original_advance, self.original_append = runtime.advance, journal.Journal.append
        self.original_relevant = backtest.relevant
        runtime.advance = self.advance
        backtest.relevant = self.relevant
        # A function is required here: assigning a bound method breaks Journal's
        # descriptor binding when composed with the existing interval certificate.
        def append(owner, name, record):
            return self.append(owner, name, record)
        journal.Journal.append = append
        return self

    def __exit__(self, *args):
        self.runtime.advance = self.original_advance
        self.journal.Journal.append = self.original_append
        self.backtest.relevant = self.original_relevant


class InputCodec:
    """Dispatch a distinct guarded schema, preserving the ordinary parser."""
    def __init__(self, expected_repair, expected_evidence):
        self.expected_repair = deepcopy(expected_repair)
        self.evidence = deepcopy(expected_evidence)
        self.objects = []
        self.guard = TransitionGuard(self)

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes(), object_pairs_hook=unique).get('schema') != SCHEMA:
            return self.original_load(path, resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj = parse(path, resume_session=resume_session,
                    predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,
                    expected_repair=self.expected_repair, expected_evidence=self.evidence)
        from research.pooled_vacancy_funding.repair import Repair, _digest
        canonical = Repair.model_validate(obj.canonical_repair)
        canonical._file_sha256 = obj.sha256
        canonical._resume_session = resume_session
        canonical._document_sha256 = _digest(canonical.model_dump(mode='json', by_alias=True))
        obj._canonical = canonical
        # Repeated canonical loads of the same admitted descriptor are normal;
        # differing commitments within a context are not.
        require(not self.objects or self.objects[0].sha256 == obj.sha256,
                'CLOSE_SCOPE_ONLY_ONE_COMMITMENT')
        self.objects[:] = [obj]
        return obj

    def apply(self, packet, obj):
        if not isinstance(obj, GuardedInput):
            return self.original_apply(packet, obj)
        require(self.objects and obj.sha256 == self.objects[0].sha256
                and obj._canonical is not None
                and digest(obj.model_dump(by_alias=True)) == obj._admitted_document_sha256
                and obj.canonical_repair == self.expected_repair,
                'CLOSE_SCOPE_ONLY_UNCHANGED_ADMITTED_INPUT')
        return self.original_apply(packet, obj._canonical)

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest, repair
        self.backtest, self.repair = backtest, repair
        self.original_load, self.original_apply = repair.load_repair, backtest.apply_repair
        self.saved_backtest_load = backtest.load_repair
        repair.load_repair = backtest.load_repair = self.load
        backtest.apply_repair = self.apply
        try:
            self.guard.__enter__()
        except BaseException:
            repair.load_repair = self.original_load
            backtest.load_repair = self.saved_backtest_load
            backtest.apply_repair = self.original_apply
            raise
        return self

    def __exit__(self, *args):
        try:
            self.guard.__exit__(*args)
        finally:
            self.repair.load_repair = self.original_load
            self.backtest.load_repair = self.saved_backtest_load
            self.backtest.apply_repair = self.original_apply


def review_guards(financial, watch, *, guarded_input_sha256):
    """Pure stopped-evidence check using independently audited accounting rows.

    Callers supply only committed journal prefixes, already axis/accounting
    reviewed. Unsent watch or financial tails stay outside this admission.
    """
    proofs = [r for r in watch if r.get('schema') == WATCH]
    expected = [r for r in financial if active(r['session'])]
    require([r['session'] for r in proofs] == [r['session'] for r in expected],
            'CLOSE_SCOPE_EXACT_GUARD_AND_FINANCIAL_AXIS')
    by_day = {r['session']: (i, r) for i, r in enumerate(financial)}
    require(len(by_day) == len(financial), 'CLOSE_SCOPE_UNIQUE_FINANCIAL_AXIS')
    for proof, row in zip(proofs, expected):
        index, _ = by_day[row['session']]
        require(index > 0, 'CLOSE_SCOPE_PREVIOUS_ACTUAL_FINANCIAL_ROW')
        previous = financial[index - 1]
        names = active(row['session'])
        before = previous['evidence']['research_entry_audit']['closing_accounting']
        after = row['evidence']['research_entry_audit']['closing_accounting']
        intents = row['evidence']['wealth_core']['intents']
        # Intents contain only newly signalled orders and use a different schema.
        # Full pending queues include carried orders and funding/waiting fields.
        require_absent(after['wealth_core'], intents, names)
        require_intents(previous['evidence']['wealth_core']['intents'], names)
        require_intents(intents, names)
        wanted = dict(schema=WATCH, session=row['session'], scope=SCOPE,
                      affected_security_ids=names, guarded_input_sha256=guarded_input_sha256,
                      input_sha256=row['input_sha256'], prior_state_sha256=previous['state_sha256'],
                      next_state_sha256=row['state_sha256'],
                      before=projection(before['wealth_core'], before['pending'], names),
                      after=projection(after['wealth_core'], after['pending'], names),
                      financial_row_sha256=digest(row))
        require(proof == wanted, 'CLOSE_SCOPE_EVERY_ACTUAL_POSITION_STATE_AND_ROW_BOUND')
    return dict(status='COMMITTED_GUARD_EVIDENCE_REVIEWED', rows=len(proofs),
                every_before_and_after_position_and_intent_checked=True,
                every_actual_input_state_and_financial_row_bound=True,
                every_actual_position_pending_and_entry_intent_checked=True,
                no_morning_settlement_claimed=True,
                no_owned_lot_settlement_model=True, production_contacted=False)
