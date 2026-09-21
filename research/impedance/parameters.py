"""Research-only numeric sensitivity of the unchanged compact transition code."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from sentinel.controller import champion_frozen

PRESETS = {
    'current': {},
    'fast_sensitive': {'FAST': {'ddam5': .15}},
    'slow_earlier': {'SLOW': {'dur': 15}},
    'recovery_faster': {'LDRC_REC': 4},
    'combined': {'FAST': {'ddam5': .15}, 'SLOW': {'dur': 15}, 'LDRC_REC': 4},
}
FIELDS = ('shadow_drawdown', 'shadow_r5', 'shadow_r10', 'shadow_r20',
          'shadow_r40', 'damaged_breadth', 'green_breadth',
          'damaged_breadth_delta5', 'spy_r20', 'spy_vol_ratio', 'stops20', 'shadow_nav')


class ProbeController:
    def __init__(self, name):
        self.name = name
        source = Path(champion_frozen.__file__).read_text(encoding='utf-8')
        self.source_sha256 = hashlib.sha256(source.encode()).hexdigest()
        namespace = {'__name__': 'isolated_sentinel_parameter_probe'}
        exec(compile(source, '<unchanged-champion-source>', 'exec'), namespace)
        for key, value in PRESETS[name].items():
            if isinstance(value, dict):
                namespace[key].update(value)
            else:
                namespace[key] = value
        self.identity = 'research-only:' + hashlib.sha256(json.dumps(
            {'source': self.source_sha256, 'parameters': PRESETS[name]},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.Native, self.Candidate = namespace['Native'], namespace['CandidateA']
        self.native, self.candidate = self.Native(), self.Candidate()
        self.effective = self.previous = self.target = 1.

    def step(self, row):
        ob, leader = row['observation'], row['leadership']
        native, fast, slow = self.native.step(tuple(ob[k] for k in FIELDS))
        target, reason = self.candidate.step(native, self.effective,
            ob['shadow_drawdown'], leader['recent_r20'], leader['recent_r40'],
            ob['spy_r20'], ob['shadow_r20'])
        self.effective, self.previous, self.target = self.previous, native, target
        return dict(native=native, target=target, fast=fast, slow=slow, reason=reason)

    def snapshot(self):
        return dict(identity=self.identity, native=self.native.snapshot(),
                    candidate=self.candidate.snapshot(), effective=self.effective,
                    previous=self.previous, target=self.target)

    def restore(self, snapshot):
        if snapshot['identity'] != self.identity:
            raise ValueError('research parameter identity mismatch')
        self.native = self.Native.from_snapshot(snapshot['native'])
        self.candidate = self.Candidate.from_snapshot(snapshot['candidate'])
        self.effective, self.previous, self.target = (
            snapshot[k] for k in ('effective', 'previous', 'target'))


def assert_baseline(row, result, probe):
    assert result['target'] == row['core_multiplier'], 'production target parity'
    assert result['native'] == row['native_multiplier'], 'production native parity'
    assert result['reason'] == row['recovery_reason'], 'production recovery parity'
    assert probe.native.snapshot() == row['native_evidence']['native_snapshot'], 'production state parity'


def production_constants():
    return deepcopy({k: getattr(champion_frozen, k)
                     for k in ('ORD_DD', 'FAST', 'SLOW', 'LDRC_REC')})
