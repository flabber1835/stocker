"""Pure compact champion transitions, preserved from the certified source.

Source SHA256: 3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663
See docs/production-compact-champion.md for authority and state contracts.
"""
import numpy as np

ORD_DD = -0.155
FAST = {'dd': -0.1, 'dam': 0.88, 'green': 0.2, 'r5': -0.05, 'r10': -0.08, 'ddam5': 0.3, 'volacc': 0.04, 'spy20': -0.01, 'r10confirm': -0.1}
SLOW = {'dur': 30, 'ret': -0.02, 'r40': -0.03, 'dam': 0.75, 'green': 0.25}
LDRC_DD = -0.1
LDRC_R20 = -0.085
LDRC_CEIL = 0.55
LDRC_REC = 8
LDRC_V = 0.11

def finite(x):
    return x is not None and np.isfinite(x)

class Native:

    def __init__(self):
        self.ordinary = False
        self.binary_armed = True
        self.ordinary_age = 0
        self.ordinary_h = 0
        self.base_fast = False
        self.base_fast_armed = True
        self.base_fast_age = 0
        self.base_fast_h = 0
        self.base_anchor = None
        self.base_dur = 0
        self.fast = False
        self.fast_armed = True
        self.fast_age = 0
        self.fast_h = 0
        self.slow = False
        self.slow_age = 0
        self.slow_h = 0

    def step(self, ob):
        dd, r5, r10, r20, r40, dam, green, ddam5, spy20, volacc, stops, nav = ob
        healthy = finite(r20) and finite(dam) and finite(green) and (r20 > 0) and (dam <= 0.63) and (green >= 0.2)
        short = finite(r5) and r5 <= FAST['r5'] or (finite(r10) and r10 <= FAST['r10'])
        conf = finite(spy20) and spy20 <= FAST['spy20'] or (finite(r10) and r10 <= FAST['r10confirm'])
        fastsig = all([finite(dd), finite(dam), finite(green), finite(ddam5), finite(volacc)]) and dd <= FAST['dd'] and (dam >= FAST['dam']) and (green <= FAST['green']) and short and (ddam5 >= FAST['ddam5']) and (volacc >= FAST['volacc']) and conf
        prior_base = self.ordinary or self.base_fast
        if finite(dd) and dd > ORD_DD:
            self.binary_armed = True
        if finite(dd) and dd <= ORD_DD and self.binary_armed and (not self.ordinary):
            self.ordinary = True
            self.binary_armed = False
            self.ordinary_age = 0
            self.ordinary_h = 0
        elif self.ordinary:
            self.ordinary_age += 1
            bh = finite(r20) and r20 > 0 and (stops is not None) and (stops <= 2)
            self.ordinary_h = self.ordinary_h + 1 if bh else 0
            if self.ordinary_age >= 20 and self.ordinary_h >= 3:
                self.ordinary = False
                self.ordinary_h = 0
        if finite(dd) and dd > -0.06:
            self.base_fast_armed = True
        if fastsig and self.base_fast_armed and (not self.base_fast) and (not self.ordinary):
            self.base_fast = True
            self.base_fast_armed = False
            self.base_fast_age = 0
            self.base_fast_h = 0
        elif self.base_fast:
            self.base_fast_age += 1
            self.base_fast_h = self.base_fast_h + 1 if healthy else 0
            if self.base_fast_age >= 10 and self.base_fast_h >= 3:
                self.base_fast = False
                self.base_fast_h = 0
        base = self.ordinary or self.base_fast
        if base:
            if not prior_base:
                self.base_anchor = nav
                self.base_dur = 1
            else:
                self.base_dur += 1
        else:
            self.base_anchor = None
            self.base_dur = 0
        since = nav / self.base_anchor - 1 if base and self.base_anchor and finite(nav) else None
        slowsig = base and finite(since) and finite(r40) and finite(dam) and finite(green) and (self.base_dur >= SLOW['dur']) and (since <= SLOW['ret']) and (r40 <= SLOW['r40']) and (dam >= SLOW['dam']) and (green <= SLOW['green'])
        if finite(dd) and dd > -0.06:
            self.fast_armed = True
        if fastsig and self.fast_armed and (not self.fast):
            self.fast = True
            self.fast_armed = False
            self.fast_age = 0
            self.fast_h = 0
        elif self.fast:
            self.fast_age += 1
            self.fast_h = self.fast_h + 1 if healthy else 0
            if self.fast_age + 1 >= 10 and self.fast_h >= 3:
                self.fast = False
                self.fast_h = 0
        if self.slow:
            self.slow_age += 1
            self.slow_h = self.slow_h + 1 if healthy else 0
            if self.slow_age + 1 >= 20 and self.slow_h >= 6:
                self.slow = False
                self.slow_h = 0
        elif slowsig:
            self.slow = True
            self.slow_age = 0
            self.slow_h = 0
        target = 0.0 if self.fast or self.slow else 1.0
        self.ordinary_age = min(self.ordinary_age, 20)
        self.ordinary_h = min(self.ordinary_h, 3)
        self.base_fast_age = min(self.base_fast_age, 10)
        self.base_fast_h = min(self.base_fast_h, 3)
        self.base_dur = min(self.base_dur, 30)
        self.fast_age = min(self.fast_age, 9)
        self.fast_h = min(self.fast_h, 3)
        self.slow_age = min(self.slow_age, 19)
        self.slow_h = min(self.slow_h, 6)
        return (float(target), bool(fastsig), bool(slowsig))
    _schema = 'ramp-free-native/1'
    _caps = {'ordinary_age': 20, 'ordinary_h': 3, 'base_fast_age': 10, 'base_fast_h': 3, 'base_dur': 30, 'fast_age': 9, 'fast_h': 3, 'slow_age': 19, 'slow_h': 6}

    def snapshot(self):
        import copy
        return {'schema': self._schema, 'state': copy.deepcopy(self.__dict__)}

    @classmethod
    def from_snapshot(cls, payload):
        import copy
        if not isinstance(payload, dict) or set(payload) != {'schema', 'state'} or payload['schema'] != cls._schema:
            raise ValueError('incompatible snapshot schema')
        obj = cls()
        state = payload['state']
        if not isinstance(state, dict) or set(state) != set(obj.__dict__):
            raise ValueError('snapshot fields differ')
        for key, default in obj.__dict__.items():
            value = state[key]
            if type(default) is bool:
                valid = type(value) is bool
            elif type(default) is int:
                valid = type(value) is int and 0 <= value <= cls._caps[key]
            elif key == 'base_anchor':
                valid = value is None or (type(value) in (int, float) and finite(value) and (value > 0))
            elif key == '_audit':
                valid = isinstance(value, dict) and set(value) == set(default) and all((type(v) is int and v >= 0 for v in value.values()))
            else:
                valid = False
            if not valid:
                raise ValueError('invalid snapshot value: ' + key)
        obj.__dict__ = copy.deepcopy(state)
        return obj

class CandidateA:
    """Current LD-RC plus one early cross-surface recovery route."""

    def __init__(self):
        self.episode = False
        self.latched = False
        self.full_streak = 0
        self.recent_positive_streak = 0
        self.previous_native_was_full = True
        self._audit = {'episodes': 0, 'concordance_releases': 0}

    def step(self, native, effective_native, wcdd, recent_r20, recent_r40, spy20, wc_r20):
        if native not in (0.0, 1.0):
            raise ValueError('ramp-free controller requires binary Native')
        full_healthy = finite(recent_r20) and finite(recent_r40) and (recent_r20 > 0) and (recent_r40 > -0.04)
        self.full_streak = self.full_streak + 1 if full_healthy else 0
        reasons = []
        if self.previous_native_was_full and native < 1 - 1e-12:
            if not self.episode:
                self._audit['episodes'] += 1
            self.episode = True
            self.recent_positive_streak = 0
            reasons.append('RECOVERY_EPISODE_START')
        if self.episode:
            if native > 0 and finite(recent_r20) and (recent_r20 > 0):
                self.recent_positive_streak += 1
            else:
                self.recent_positive_streak = 0
        else:
            self.recent_positive_streak = 0
        cleared = self.latched and self.full_streak >= LDRC_REC
        if cleared:
            self.latched = False
            reasons.append('DIVERGENCE_CLEAR')
        desired = native
        if self.episode and native >= 1 - 1e-12:
            concordant = self.recent_positive_streak >= LDRC_REC and finite(wc_r20) and (wc_r20 > 0) and finite(recent_r20) and (recent_r20 >= wc_r20) and finite(spy20) and (spy20 >= wc_r20)
            if self.full_streak >= LDRC_REC or concordant:
                self.episode = False
                desired = 1.0
                if concordant and self.full_streak < LDRC_REC:
                    self._audit['concordance_releases'] += 1
                    reasons.append('FULL_RISK_CERTIFIED_CROSS_SURFACE')
                else:
                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
                self.recent_positive_streak = 0
            else:
                desired = 0.0
                reasons.append('FULL_RISK_HELD')
        avail = finite(wcdd) and finite(recent_r20) and finite(spy20) and (effective_native is not None) and finite(effective_native)
        if not self.latched:
            divergence = native >= 1 - 1e-12 and effective_native is not None and finite(effective_native) and (effective_native >= 1 - 1e-12) and avail and (wcdd <= LDRC_DD) and (recent_r20 <= LDRC_R20) and (spy20 >= 0.0)
            if divergence:
                self.latched = True
                reasons.append('LD_ENTER_DIVERGENCE')
        if self.latched:
            desired = min(desired, LDRC_CEIL)
        desired = min(native, desired)
        self.full_streak = min(self.full_streak, LDRC_REC)
        self.recent_positive_streak = min(self.recent_positive_streak, LDRC_REC)
        self.previous_native_was_full = native == 1.0
        return (float(desired), '|'.join(reasons) if reasons else 'NORMAL')

    @property
    def episodes(self):
        return self._audit['episodes']

    @property
    def concordance_releases(self):
        return self._audit['concordance_releases']
    _schema = 'ramp-free-ex3-rebound-false/1'
    _caps = {'full_streak': 8, 'recent_positive_streak': 8}

    def snapshot(self):
        import copy
        return {'schema': self._schema, 'state': copy.deepcopy(self.__dict__)}

    @classmethod
    def from_snapshot(cls, payload):
        import copy
        if not isinstance(payload, dict) or set(payload) != {'schema', 'state'} or payload['schema'] != cls._schema:
            raise ValueError('incompatible snapshot schema')
        obj = cls()
        state = payload['state']
        if not isinstance(state, dict) or set(state) != set(obj.__dict__):
            raise ValueError('snapshot fields differ')
        for key, default in obj.__dict__.items():
            value = state[key]
            if type(default) is bool:
                valid = type(value) is bool
            elif type(default) is int:
                valid = type(value) is int and 0 <= value <= cls._caps[key]
            elif key == 'base_anchor':
                valid = value is None or (type(value) in (int, float) and finite(value) and (value > 0))
            elif key == '_audit':
                valid = isinstance(value, dict) and set(value) == set(default) and all((type(v) is int and v >= 0 for v in value.values()))
            else:
                valid = False
            if not valid:
                raise ValueError('invalid snapshot value: ' + key)
        obj.__dict__ = copy.deepcopy(state)
        return obj
