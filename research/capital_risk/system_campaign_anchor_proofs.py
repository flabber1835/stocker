"""Immutable per-use proofs for the exact retained diagnostic anchor gate."""
import ast
from copy import deepcopy
import hashlib
import os
from pathlib import Path

from full_system_benchmark import need
from system_campaign_discovery_context import TAINT, digest, encoded
import system_campaign_parallel_discovery_run as original

ORIGINAL_SHA256 = 'ea61a782ee1dce3e70a19a09112841458094498b3950456ce88494ac98af4d20'
PROOF_STATUS = 'ACTUAL_CANONICAL_DIAGNOSTIC_ANCHOR_USE_QUALIFIED'


def sync_directory(path):
    if os.name == 'nt': return
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try: os.fsync(fd)
    finally: os.close(fd)


def original_method(name):
    raw = Path(original.__file__).read_bytes()
    need(hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA256,
         'ANCHOR_PROOFS_EXACT_ORIGINAL_QUALIFICATION_SOURCE')
    owner, = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef)
              and n.name == 'AnchorQualification']
    fn, = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name]
    return deepcopy(fn)


def after_tree():
    fn = original_method('after')
    sites = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == 'save']
    need(len(sites) == 1 and ast.unparse(sites[0].args[0]) ==
         "self.out / 'actual-anchor-qualification.json'",
         'ANCHOR_PROOFS_ONE_EXCLUSIVE_CUMULATIVE_SAVE_SITE')
    old = sites[0]
    old.func = ast.parse('self.writer.write', mode='eval').body
    old.args = [ast.parse('self.pending', mode='eval').body]
    old.keywords = []
    # The old history is unnecessary: each immutable proof is written once.
    appends = [n for n in ast.walk(fn) if isinstance(n, ast.Expr)
               and isinstance(n.value, ast.Call)
               and ast.unparse(n.value.func) == 'self.proofs.append']
    need(len(appends) == 1, 'ANCHOR_PROOFS_ONE_OLD_CUMULATIVE_MEMORY_APPEND')
    fn.body.remove(appends[0])
    return ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))


class VersionedAnchorProofWriter:
    def __init__(self, output, anchors, *, seed_proofs=(), predecessor=None):
        self.output, self.anchors = Path(output), anchors
        self.directory = self.output / 'anchor-qualifications'
        self.directory.mkdir()
        self.sequence = 0
        self.seed_proofs = tuple(deepcopy(seed_proofs))
        self.predecessor = deepcopy(predecessor)
        self.chain = digest(dict(authority=TAINT, stream='anchor-qualifications/index.jsonl',
                                 predecessor=self.predecessor, seed_proofs=self.seed_proofs))
        self.hash = hashlib.sha256()
        self.bytes = 0
        self.index = self.directory / 'index.jsonl'
        with self.index.open('xb') as stream:
            stream.flush(); os.fsync(stream.fileno())
        sync_directory(self.directory); sync_directory(self.output)

    def write(self, proof):
        need(proof['status'] == PROOF_STATUS and proof['financial_authority'] is False
             and proof['historical_auxiliary_only'] and proof['current_bars_unchanged']
             and proof['window_dates'] == 300 and proof['security_ids']
             and proof['prior_state_sha256'] != proof['next_state_sha256'],
             'ANCHOR_PROOFS_ONLY_ACTUAL_QUALIFIED_CANONICAL_USE')
        records = {sid: self.anchors.records[sid].model_dump() for sid in proof['security_ids']}
        need(all(row['security_id'] == sid and row['session'] < proof['session']
                 for sid, row in records.items()), 'ANCHOR_PROOFS_EXACT_HISTORICAL_RECORDS')
        body = dict(schema='research.diagnostic-anchor-use-proof/1', authority=TAINT,
                    financial_authority=False, production_contacted=False,
                    sequence=self.sequence, previous_chain_sha256=self.chain,
                    source_sha256=self.anchors.source_sha256,
                    input_sha256=self.anchors.input_sha256,
                    source_records=records, source_records_sha256=digest(records),
                    qualification=deepcopy(proof))
        chain = digest(body)
        raw = encoded(dict(record=body, chain_sha256=chain)) + b'\n'
        name = f'{self.sequence:08d}-{chain}.json'
        with (self.directory / name).open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        # A durable index must never point to an undurable new file name.
        sync_directory(self.directory)
        reference = encoded(dict(sequence=self.sequence, file=name, bytes=len(raw),
                                 sha256=hashlib.sha256(raw).hexdigest(), chain_sha256=chain)) + b'\n'
        with self.index.open('ab') as stream:
            stream.write(reference); stream.flush(); os.fsync(stream.fileno())
        self.hash.update(reference); self.bytes += len(reference)
        self.chain = chain; self.sequence += 1
        return chain

    def commitment(self):
        return dict(rows=self.sequence, bytes=self.bytes, prefix_sha256=self.hash.hexdigest(),
                    chain_sha256=self.chain, predecessor=self.predecessor,
                    seed_proofs_sha256=digest(self.seed_proofs))


class AnchorQualification(original.AnchorQualification):
    """Drop-in gate; the frozen original checks execute for every novel use."""
    def __init__(self, out, anchors, *, seed_proofs=(), predecessor=None):
        original_method('prepare')  # Verify the inherited financial guard body.
        super().__init__(out, anchors)
        self.writer = VersionedAnchorProofWriter(out, anchors, seed_proofs=seed_proofs,
                                                predecessor=predecessor)
        for proof in self.writer.seed_proofs:
            need(proof['status'] == PROOF_STATUS and proof['financial_authority'] is False
                 and proof['source_sha256'] == anchors.source_sha256
                 and proof['input_sha256'] == anchors.input_sha256
                 and proof['source_records'] and proof['source_records_sha256'] == digest(proof['source_records']),
                 'ANCHOR_PROOFS_SEED_ONLY_AUTHENTICATED_QUALIFIED_SOURCE_RECORDS')
            for sid, row in proof['source_records'].items():
                need(sid == row['security_id'] and row['session'] < proof['session'],
                     'ANCHOR_PROOFS_SEED_EXACT_RECORD_BEFORE_ACTUAL_USE')
                self.seen.add((sid, row['session']))

    def after(self, prior, next_run):
        scope = dict(vars(original))
        exec(compile(after_tree(), '<exact-anchor-gate-immutable-proof-save-only>', 'exec'), scope)
        return scope['after'](self, prior, next_run)

    def commitment(self):
        return self.writer.commitment()


VersionedAnchorQualification = AnchorQualification


def verify_proofs(root, commitment, *, seed_proofs=(), predecessor=None, allow_tail=False):
    """Pure reader: authenticate every disjoint proof and the linear index."""
    root = Path(root) / 'anchor-qualifications'
    full = (root / 'index.jsonl').read_bytes()
    need(len(full) >= commitment['bytes'] and (allow_tail or len(full) == commitment['bytes']),
         'ANCHOR_PROOFS_INDEX_PREFIX_AND_EXPLICIT_TAIL_POLICY')
    raw = full[:commitment['bytes']]
    need(len(raw) == commitment['bytes'] and hashlib.sha256(raw).hexdigest() == commitment['prefix_sha256']
         and (not raw or raw.endswith(b'\n')) and commitment['seed_proofs_sha256'] == digest(tuple(seed_proofs))
         and commitment['predecessor'] == predecessor, 'ANCHOR_PROOFS_EXACT_INDEX_AND_SEED_BINDINGS')
    import json
    chain = digest(dict(authority=TAINT, stream='anchor-qualifications/index.jsonl',
                        predecessor=predecessor, seed_proofs=tuple(seed_proofs)))
    references = [json.loads(line) for line in raw.splitlines()]
    need(len(references) == commitment['rows'], 'ANCHOR_PROOFS_INDEX_ROW_COUNT')
    values = []
    for sequence, ref in enumerate(references):
        need(ref['sequence'] == sequence and ref['file'] == f"{sequence:08d}-{ref['chain_sha256']}.json",
             'ANCHOR_PROOFS_EXACT_SEQUENCE_AND_SAFE_NAME')
        data = (root / ref['file']).read_bytes()
        need(len(data) == ref['bytes'] and hashlib.sha256(data).hexdigest() == ref['sha256'],
             'ANCHOR_PROOFS_IMMUTABLE_PROOF_BYTES')
        value = json.loads(data); body = value['record']; proof = body['qualification']
        need(body['sequence'] == sequence and body['previous_chain_sha256'] == chain
             and digest(body) == value['chain_sha256'] == ref['chain_sha256']
             and body['source_records_sha256'] == digest(body['source_records'])
             and body['authority'] == TAINT and body['financial_authority'] is False
             and proof['status'] == PROOF_STATUS and proof['financial_authority'] is False,
             'ANCHOR_PROOFS_FULL_CHAIN_AND_QUALIFICATION_BINDINGS')
        chain = value['chain_sha256']; values.append(value)
    need(chain == commitment['chain_sha256'], 'ANCHOR_PROOFS_FINAL_CHAIN')
    return values


def proof_prefix_evidence(root, commitment, *, seed_proofs=(), predecessor=None):
    """Verify committed prefix and describe every unsent index/proof byte."""
    values = verify_proofs(root, commitment, seed_proofs=seed_proofs,
                           predecessor=predecessor, allow_tail=True)
    directory = Path(root) / 'anchor-qualifications'
    raw = (directory / 'index.jsonl').read_bytes(); tail = raw[commitment['bytes']:]
    committed = {f"{v['record']['sequence']:08d}-{v['chain_sha256']}.json" for v in values}
    uncommitted = {}
    for path in directory.glob('*.json'):
        if path.name in committed: continue
        data = path.read_bytes()
        uncommitted[path.name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return dict(committed_proofs=values,
                full_index=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
                uncommitted_index=dict(bytes=len(tail), sha256=hashlib.sha256(tail).hexdigest()),
                uncommitted_proof_files=uncommitted)
