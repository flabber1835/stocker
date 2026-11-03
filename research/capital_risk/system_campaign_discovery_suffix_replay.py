"""One exact hosted suffix; reuse source-bound canonical discovery AST."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_discovery_context import TAINT, digest, encoded
import system_campaign_discovery_context as context_source
import system_campaign_discovery_replay as original
import system_campaign_p01_discovery_suffix_replay as proven
from system_campaign_parallel_discovery_run import Anchors as OriginalAnchors
from system_campaign_anchor_proofs import AnchorQualification, PROOF_STATUS
from system_campaign_discovery_suffix_parent import (validate_contents, verify_prefix, verify_chain, exact_source)


def write_new(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


class ContinuedContext(context_source.DiscoveryContext):
    def __init__(self, output, *, source_sha256, previous, saved, bindings=None):
        super().__init__(output, source_sha256=source_sha256, bindings=bindings)
        full = (Path(previous) / 'discovery-events.jsonl').read_bytes()
        rows = verify_chain(full, saved['events'])
        raw = full[:saved['events']['bytes']]
        write_new(self.output / 'discovery-events.jsonl', raw)
        self.event_hash.update(raw); self.sequence = saved['events']['rows']
        self.chain = saved['events']['chain_sha256']; self.transitions = saved['discovery_transitions']
        self.tainted = any(row['context'].get('bypass') is True for row in rows)

    def __enter__(self):
        raw = exact_source(context_source)
        owner, = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'DiscoveryContext']
        fn, = [deepcopy(n) for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == '__enter__']
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) ==
                 "(self.output / 'discovery-events.jsonl').open"]
        need(len(calls) == 1 and ast.literal_eval(calls[0].args[0]) == 'xb', 'SUFFIX_ONE_EVENT_APPEND_MODE_SITE')
        calls[0].args = [ast.Constant('ab')]
        scope = dict(vars(context_source))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<same-context-committed-prefix-append>', 'exec'), scope)
        return scope['__enter__'](self)


class Anchors(OriginalAnchors):
    def __init__(self, *args, previous, saved, **kwargs):
        super().__init__(*args, **kwargs); self.previous = Path(previous); self.saved = saved

    def __enter__(self):
        super().__enter__()
        full = (self.previous / 'retained-anchor-events.jsonl').read_bytes()
        rows = verify_chain(full, self.saved['retained_source_anchors'], anchor=True)
        raw = full[:self.saved['retained_source_anchors']['bytes']]
        self.stream.write(raw); self.stream.flush(); os.fsync(self.stream.fileno())
        self.hash.update(raw); self.sequence = self.saved['retained_source_anchors']['rows']
        self.chain = self.saved['retained_source_anchors']['chain_sha256']
        for row in rows:
            source = row['source_anchor']
            self.records[row['security_id']] = __import__('system_campaign_p01_discovery_anchors').SourceAnchor(**source)
        return self


def qualified_anchor_seeds(previous, saved, source_sha256):
    path = Path(previous) / 'actual-anchor-qualification.json'
    if not path.exists(): return []
    rows = verify_chain((Path(previous) / 'retained-anchor-events.jsonl').read_bytes(),
                        saved['retained_source_anchors'], anchor=True)
    daily = [json.loads(line) for line in verify_prefix((Path(previous) / 'diagnostic-book/daily.jsonl').read_bytes(),
                                                     saved['journals']['daily']).splitlines()]
    states = {row['session']: row['state_sha256'] for row in daily}
    result = []
    for proof in json.loads(path.read_bytes())['actual_uses']:
        if proof['session'] > saved['source_cursor']: continue
        records = {}
        for sid in proof['security_ids']:
            matches = [row for row in rows if row['session'] == proof['session'] and row['security_id'] == sid
                       and row['prior_state_sha256'] == proof['prior_state_sha256']]
            need(matches, 'SUFFIX_QUALIFIED_SEED_REQUIRES_ACTUAL_COMMITTED_SOURCE_ANCHOR_USE')
            record = matches[0]
            need(all(row['source_anchor'] == record['source_anchor'] for row in matches)
                 and record['source_sha256'] == source_sha256
                 and record['input_sha256'] == saved['runtime_checkpoint']['input_sha256'],
                 'SUFFIX_SEED_ANCHOR_SOURCE_INPUT_AND_RECORD_UNAMBIGUOUS')
            records[sid] = record['source_anchor']
        need(proof['status'] == PROOF_STATUS and proof['financial_authority'] is False
             and states.get(proof['session']) == proof['next_state_sha256'],
             'SUFFIX_SEED_ONLY_ACTUAL_COMMITTED_CANONICAL_NEXT_STATE')
        result.append(dict(proof, source_sha256=source_sha256,
            input_sha256=saved['runtime_checkpoint']['input_sha256'], source_records=records,
            source_records_sha256=digest(records)))
    return result


def seed_book(book, previous, saved):
    book = Path(book); previous = Path(previous); book.mkdir()
    lineage = book.parent / 'lineage/diagnostic-predecessor'; lineage.mkdir(parents=True)
    # Retain every original checkpoint/proof/complete stream once, without
    # recursively copying older lineage or cumulative archives.
    for src in previous.rglob('*'):
        relative = src.relative_to(previous)
        if not src.is_file() or relative.parts[0] == 'lineage': continue
        target = lineage / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    for name, commitment in saved['journals'].items():
        raw = (previous / 'diagnostic-book' / (name + '.jsonl')).read_bytes()
        verify_prefix(raw, commitment, last=True)
        write_new(book / (name + '.jsonl'), raw)
    (book / 'retained-checkpoints').mkdir()


@contextmanager
def recovered_stream(book, saved):
    from research.pooled_vacancy_funding import journal
    with journal.Journal(book, resume=True) as stream:
        stream.verify(saved['journals'])
        tails = stream.recover(saved['journals'])
        need(stream.commitment() == saved['journals'], 'SUFFIX_ACTUAL_JOURNAL_RECOVER_EXACT_COMMITTED_PREFIX')
        expected_tails = {}
        for name, commitment in saved['journals'].items():
            raw = (Path(book) / (name + '.jsonl')).read_bytes()
            need(raw == verify_prefix(raw, commitment, last=True), 'SUFFIX_RECOVERY_REMOVES_UNSENT_BYTES_BEFORE_APPEND')
            original = (Path(book).parent / 'lineage/diagnostic-predecessor/diagnostic-book' / (name + '.jsonl')).read_bytes()
            tail = original[commitment['bytes']:]
            if tail: expected_tails[name] = tail
        archived = {}
        for path in tails:
            path = Path(path)
            match = re.fullmatch(r'interrupted-(formation|daily|monthly|watch)-[0-9a-f]{32}\.jsonl', path.name)
            need(path.resolve().parent == Path(book).resolve() and match is not None,
                 'SUFFIX_ACTUAL_RECOVER_TAIL_PATH_IN_NEW_DISJOINT_BOOK')
            name = match.group(1); data = path.read_bytes()
            need(name not in archived and name in expected_tails and data == expected_tails[name],
                 'SUFFIX_ACTUAL_RECOVER_EVERY_ARCHIVED_TAIL_EQUALS_ORIGINAL_UNSENT_BYTES')
            archived[name] = dict(filename=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        need(set(archived) == set(expected_tails), 'SUFFIX_ACTUAL_RECOVER_ALL_EXPECTED_TAILS_DURABLY_ARCHIVED')
        save(Path(book).parent / 'actual-journal-recovery.json', dict(actual_canonical_journal_recover=True,
            original_full_streams_preserved_in_lineage=True, recovered_tails=archived,
            committed_journals=saved['journals'], financial_authority=False, production_contacted=False))
        yield stream


class FirstTransition:
    def __init__(self, output, saved, spec, anchor_gate):
        self.output, self.saved, self.spec, self.anchor_gate = Path(output), saved, spec, anchor_gate
        self.prepared = False; self.passed = False

    def prepare(self, buffer, run):
        if not self.prepared:
            need(buffer.current.day == self.spec['next_session']
                 and run.state.state_hash == self.spec['state_sha256']
                 and run.input_sha256 == self.spec['input_sha256']
                 and digest(run.state.to_dict()) == self.spec['state_sha256'],
                 'SUFFIX_FIRST_ACTUAL_NEXT_SESSION_PRIOR_STATE_INPUT_ADJACENCY')
            self.before = deepcopy(run.state.to_dict()); self.prepared = True
        return self.anchor_gate.prepare(buffer, run)

    def after(self, prior, next_run):
        self.anchor_gate.after(prior, next_run)
        if self.passed: return
        need(self.prepared and prior.state.to_dict() == self.before
             and next_run.state.last_processed_session == self.spec['next_session'],
             'SUFFIX_FIRST_CANONICAL_ACTUAL_PRIOR_UNCHANGED_NEXT_STATE_ADJACENCY')
        save(self.output / 'actual-first-suffix-transition.json', dict(
            schema='research.exact-diagnostic-first-suffix-transition/1', authority=TAINT,
            prior_state_sha256=prior.state.state_hash, next_state_sha256=next_run.state.state_hash,
            prior_runtime_checkpoint_sha256=self.spec['runtime_checkpoint_sha256'],
            input_sha256=self.spec['input_sha256'], session=self.spec['next_session'],
            actual_canonical_transition=True, financial_authority=False, production_contacted=False))
        self.passed = True


def suffix_tree(raw):
    tree = proven.suffix_tree(raw)
    cp, = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'checkpoint']
    changes = [n for n in ast.walk(cp) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'value.update'
               and any(k.arg == 'retained_source_anchors' for k in n.keywords)]
    need(len(changes) == 1, 'SUFFIX_ONE_ADDITIONAL_VERSIONED_ANCHOR_COMMITMENT_SITE')
    changes[0].keywords.append(ast.keyword(arg='retained_anchor_qualifications',
        value=ast.parse('anchor_gate.commitment()', mode='eval').body))
    return ast.fix_missing_locations(tree)


def replay(root, parent, output, *, selected_file, strict_admission_sha256, previous, spec,
           anchors, context_class=None, anchor_gate=None):
    hosted(); saved = validate_contents(previous, spec)
    old_daily = verify_prefix((Path(previous) / 'diagnostic-book/daily.jsonl').read_bytes(), saved['journals']['daily'])
    old_days = [json.loads(line)['session'] for line in old_daily.splitlines()]
    need(len(old_days) == spec['transitions'] and old_days[-1] == spec['selected_session'], 'SUFFIX_EXACT_OLD_COMMITTED_DAILY_AXIS')
    from research.pooled_input_support import bundle
    axis = bundle.axis(); full_wanted = axis[axis.index(parent['source_cursor'])+1:axis.index(spec['target_end'])+1]
    need(full_wanted[:len(old_days)] == old_days and len(full_wanted) == spec['cumulative_expected_sessions']
         and full_wanted[len(old_days)] == spec['next_session'], 'SUFFIX_FULL_FROZEN_ORDERED_AXIS_NO_RESTART_OR_SKIP')
    reference = dict(schema='research.exact-diagnostic-suffix-reference/1', authority=TAINT,
        financial_authority=False, arm=spec['arm'], run_id=spec['run_id'], head=spec['head'], artifact_id=spec['artifact_id'],
        checkpoint_sha256=spec['diagnostic_checkpoint_sha256'], runtime_checkpoint_sha256=spec['runtime_checkpoint_sha256'],
        transitions=spec['transitions'], source_cursor=spec['selected_session'], specification_sha256=digest(spec))
    seed = qualified_anchor_seeds(previous, saved, anchors.source_sha256)
    anchor_gate = anchor_gate or AnchorQualification(output, anchors, seed_proofs=seed, predecessor=reference)
    first = FirstTransition(output, saved, spec, anchor_gate)
    scope = dict(vars(original), saved=saved, anchors=anchors)
    exec(compile(proven.iterator_tree(proven.exact_raw(original)), '<same-source-exact-diagnostic-runtime-cursor>', 'exec'), scope)
    scope.update(previous=Path(previous), old_days=old_days, full_wanted=full_wanted,
        seed_book=seed_book, recovered_stream=recovered_stream,
        ContinuedContext=ContinuedContext if context_class is None else context_class(ContinuedContext),
        first=first, anchor_gate=anchor_gate, diagnostic_reference=reference, shutil=shutil)
    save(Path(output) / 'diagnostic-predecessor-admission.json', dict(reference=reference,
        old_full_streams_and_unsent_tails_preserved=True, committed_only_event_and_anchor_seed=True,
        reused_original_three_case_gate=True, financial_authority=False, production_contacted=False))
    exec(compile(suffix_tree(proven.exact_raw(original)), '<exact-common-diagnostic-suffix>', 'exec'), scope)
    return scope['replay'](root, parent, output, selected_file=selected_file,
                           strict_admission_sha256=strict_admission_sha256)
