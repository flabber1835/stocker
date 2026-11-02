"""Hydrate the admitted CELG source epoch before any financial-state restore."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import gzip
import json
from pathlib import Path

from p01_epoch_parent import (HERE, OUTER, SOURCE_RECEIPT, TENTH, digest, sha,
                              need, validate_contents)


def _hosted():
    from full_system_core import hosted
    hosted()


def _source_module():
    from research.pooled_vacancy_funding import source_successor
    return source_successor


def _checkpoint(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def _source_files():
    return {p.relative_to('/variant').as_posix():sha(p.read_bytes())
            for p in Path('/variant').rglob('*') if p.is_file()}


def _adoption(saved, prior, overlay_sha256, earliest):
    from system_campaign_pxd_pause import adoption
    return adoption(saved, prior, overlay_sha256, earliest)


class EpochSourceGate:
    """Continue a committed source epoch; never manufacture another boundary."""
    def __init__(self, parent, source_map, receipt_path, checkpoint_path):
        need(parent['sha256'] == OUTER and parent['base']['sources'] == source_map['successor_financial_sources'],
             'GATE_ONLY_ADMITTED_CURRENT_EPOCH')
        self.parent = deepcopy(parent)
        self.base = deepcopy(parent['base'])
        self.receipt_path = Path(receipt_path)
        self.checkpoint_path = Path(checkpoint_path)
        self.allowed = {OUTER: deepcopy(parent)}
        self.loads = 0

    def load(self, path, current_base):
        raw = Path(path).read_bytes(); receipt = json.loads(raw)
        if receipt.get('schema') != 'research.p01-celg-own475-source-successor/1':
            return self.original_load(path, current_base)
        need(Path(path).resolve() == self.receipt_path.resolve() and sha(raw) == SOURCE_RECEIPT,
             'CONTINUATION_EXACT_ARCHIVED_SOURCE_RECEIPT')
        need({**current_base, 'source_successor_sha256': SOURCE_RECEIPT} == self.base
             and ('source_successor_sha256' not in current_base
                  or current_base['source_successor_sha256'] == SOURCE_RECEIPT),
             'CONTINUATION_IDENTICAL_CURRENT_SOURCE_POLICY_AND_INPUT_BASE')
        saved = _checkpoint(self.checkpoint_path)
        need(saved['sha256'] in self.allowed and saved == self.allowed[saved['sha256']]
             and saved['base'] == self.base
             and saved['sha256'] == digest({k:v for k,v in saved.items() if k != 'sha256'})
             and saved['run']['input_sha256'] == digest(dict(base=self.base, repairs=saved['repairs'])),
             'ONLY_EXACT_ADMITTED_OR_VERIFIED_INPUT_ZERO_CHECKPOINT')
        self.loads += 1
        # Canonical backtest appends a source event only when binding is non-None.
        return deepcopy(self.base), None

    def allow_input(self, saved, overlay_sha256, earliest):
        need(saved['source_cursor'] == self.parent['source_cursor'] and saved['completed'] == 526
             and saved['base'] == self.base and saved['repairs'][:-1] == self.parent['repairs']
             and len(saved['repairs']) == 11 and saved['repairs'][-1]['sha256'] == overlay_sha256
             and type(earliest) is str and earliest > self.parent['source_cursor'],
             'ONLY_CURRENT_EPOCH_ELEVENTH_INPUT_ZERO')
        event = _adoption(saved, self.parent, overlay_sha256, earliest)
        need(saved['run']['state'] == self.parent['run']['state']
             and saved['sha256'] == digest({k:v for k,v in saved.items() if k != 'sha256'}),
             'INPUT_ZERO_ENTIRE_SESSIONSTATE_UNCHANGED')
        self.allowed[saved['sha256']] = deepcopy(saved)
        return event

    def __enter__(self):
        _hosted(); self.module = _source_module()
        self.original_load = self.module.load_successor
        self.module.load_successor = self.load
        return self

    def __exit__(self, *args):
        self.module.load_successor = self.original_load


@dataclass(frozen=True)
class HistoricalEpoch:
    parent: dict
    source_map: dict
    quote: dict
    descriptor: dict
    objects: tuple
    source_gate: EpochSourceGate
    source_receipt_path: Path

    @property
    def source_args(self):
        return ['--source-successor', str(self.source_receipt_path)]


def _quote(quote_root, descriptor_path):
    """The original approved transport owns all quote authentication semantics."""
    from p01_celg_input_transport import load_authenticated_input
    raw = Path(descriptor_path).read_bytes()
    need(raw == (HERE/'p01_celg_bridge_quote_descriptor.json').read_bytes(), 'EXACT_APPROVED_QUOTE_DESCRIPTOR')
    descriptor = json.loads(raw)
    actual = load_authenticated_input(Path(quote_root), descriptor)
    value = actual.quote.model_dump(mode='json')
    value.update(authority='AUTHENTICATED_RETAINED_ALPACA_RAW_SIP_INPUT', observed_market_data=True,
        capture_sha256=actual.capture_sha256, manifest_sha256=actual.manifest_sha256,
        ciphertext_sha256=actual.ciphertext_sha256, input_identity_sha256=actual.input_identity_sha256)
    from stock_strategy_shared.wealth_core import merger_rights
    merger_rights.bind_market_quote(value, expected_sha256=digest(value))
    need(merger_rights.quote() == value, 'HISTORICAL_QUOTE_REGISTERED_BEFORE_LEDGER_RESTORE')
    return value, descriptor


@contextmanager
def historical_epoch(old, out, spec, *, quote_root=Path('/celg-input'),
                     quote_descriptor_path=Path('/celg-input-descriptor.json'), checkpoint_path=None):
    """Caller owns book copies and may restore only after this context yields."""
    _hosted(); old, out = Path(old), Path(out)
    parent = validate_contents(old, spec)  # Hash/JSON only, no financial decode.
    mapping = json.loads((old/'source-map.json').read_bytes())
    actual_files = _source_files()
    need(actual_files == mapping['successor_all_sources'], 'ACTUAL_CURRENT516_SOURCE_BYTES_BEFORE_RESTORE')
    quote, descriptor = _quote(quote_root, quote_descriptor_path)
    # These frozen contexts only hydrate/parse inputs. No state is restored here.
    from p01_celg_bridge_run import old_inputs, native
    from p01_celg_bridge_codec import InputCodec, OLD, SID
    from research.pooled_vacancy_funding import backtest
    raw = (old/'book/repairs'/parent['repairs'][-1]['filename']).read_bytes()
    need(sha(raw) == TENTH, 'EXACT_ARCHIVED_TENTH_INPUT')
    document = json.loads(raw)
    need(document['quote_capsule'] == descriptor and document['terms']['right_quote'] == quote
         and document['quote_input_sha256'] == digest(quote), 'ARCHIVED_CELG_CODEC_AUTHENTICATED_QUOTE_BINDING')
    receipt_path = old/'source-successor.json'
    checkpoint_path = checkpoint_path or out/'book/checkpoint.json.gz'
    with old_inputs(old, {**parent, 'repairs':parent['repairs'][:9]}, out/'contexts'), \
            InputCodec(native(OLD, SID), document) as codec:
        objects = []
        for d in parent['repairs']:
            obj = backtest.load_repair(old/'book/repairs'/d['filename'], resume_session=d['resume_session'],
                predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
            need(obj.sha256 == d['sha256'], 'ALL_TEN_ARCHIVED_CODECS_LOADED_IN_ORDER_BEFORE_RESTORE')
            objects.append(obj)
        need(len(objects) == 10 and any(objects[-1] is item for item in codec.objects),
             'EXACT_HISTORICAL_TENTH_CODEC_REGISTERED')
        with EpochSourceGate(parent, mapping, receipt_path, checkpoint_path) as gate:
            yield HistoricalEpoch(deepcopy(parent), deepcopy(mapping), deepcopy(quote), deepcopy(descriptor),
                                  tuple(objects), gate, receipt_path)
