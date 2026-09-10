"""Deterministic, authority-checked research sources; no data load or Core run."""
import ast
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ORIGINAL_SHA = '335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d'
SIMPLIFIED_SHA = '2f3e0a6d2fbeb2704e0ea61972a4c8509a6d75462cb7ecb69b56afedb8637c2c'
REFERENCE_SHA = 'dc69494262a6e1bfd8219bfb7e97e338a0d4232436a0e579919140a88dd952d3'
CAPS = dict(ordinary_age=20, ordinary_h=3, base_fast_age=10, base_fast_h=3,
            base_dur=30, fast_age=9, fast_h=3, slow_age=19, slow_h=6)
TRACKS = ('original', 'simplified', 'original_no_ramp', 'simplified_no_ramp',
          'compact_original_no_ramp', 'compact_simplified_no_ramp')


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def replace(text, old, new, n=1):
    assert text.count(old) == n, (old, text.count(old), n)
    return text.replace(old, new)


def segment(source, name):
    return next(ast.get_source_segment(source, n) for n in ast.parse(source).body
                if getattr(n, 'name', None) == name)


def authorities():
    original = (HERE.parent/'wealth-core-v5-ex3-v6-simplification-v1/frozen_reference.txt').read_text()
    simplified = (HERE.parent/'wealth-core-v5-ex3-v6-simplification-v2/results/34480037109-1/sources/clean_cached.py').read_text()
    assert sha(original) == ORIGINAL_SHA
    assert sha(simplified) == SIMPLIFIED_SHA
    assert sha((HERE/'ablation_reference.py').read_text()) == REFERENCE_SHA
    return original, simplified


SNAPSHOT = '''
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
                valid = value is None or (type(value) in (int, float) and finite(value) and value > 0)
            elif key == '_audit':
                valid = (isinstance(value, dict) and set(value) == set(default)
                         and all(type(v) is int and v >= 0 for v in value.values()))
            else:
                valid = False
            if not valid:
                raise ValueError('invalid snapshot value: ' + key)
        obj.__dict__ = copy.deepcopy(state)
        return obj
'''


def no_ramp(native):
    native = '\n'.join(line for line in native.split('\n')
                       if 'self.ramp=False;' not in line or not line.startswith('        self.ramp='))
    # Only the initialization line above is removed; the entire decision block follows.
    native = replace(native, '        prior_parent=0. if (self.fast or self.slow) else 1.\n', '')
    start = native.index('        parent=0. if (self.fast or self.slow) else 1.\n')
    end = native.index('        self.r40hist=(self.r40hist+[r40])[-6:]\n', start)
    end += len('        self.r40hist=(self.r40hist+[r40])[-6:]\n')
    native = native[:start] + '        target=0. if (self.fast or self.slow) else 1.\n' + native[end:]
    native = native.replace('        self.ramp_h=min(self.ramp_h,10)\n', '')
    assert 'ramp' not in native and 'r40hist' not in native and 'prior_parent' not in native
    return native


def compact_native(native):
    for key, cap in CAPS.items():
        line = f'        self.{key}=min(self.{key},{cap})\n'
        if line not in native:
            native = replace(native, '        return float(target)', line+'        return float(target)')
    native = replace(native, 'dd>-.06 and not fastsig', 'dd>-.06', 2)
    return native + '\n    _schema = "ramp-free-native/1"\n    _caps = '+repr(CAPS)+'\n'+SNAPSHOT


def compact_candidate(candidate, rebound):
    candidate = replace(candidate,
        '        self.prev_native=1.; self.prev_desired=1.; self.episodes=0\n        self.concordance_releases=0',
        "        self.previous_native_was_full=True\n        self._audit={'episodes':0, 'concordance_releases':0}")
    candidate = replace(candidate, '        full_healthy=',
        "        if native not in (0., 1.):\n            raise ValueError('ramp-free controller requires binary Native')\n        full_healthy=")
    candidate = replace(candidate, 'self.prev_native>=1-1e-12', 'self.previous_native_was_full')
    candidate = replace(candidate, 'desired=self.prev_desired', 'desired=0.')
    candidate = replace(candidate, 'self.prev_native=native; self.prev_desired=desired',
                        'self.previous_native_was_full=(native==1.)')
    candidate = replace(candidate, 'self.episodes+=1', "self._audit['episodes']+=1")
    candidate = replace(candidate, 'self.concordance_releases+=1', "self._audit['concordance_releases']+=1")
    for key in ('full_streak', 'recent_positive_streak'):
        line = f'        self.{key}=min(self.{key},LDRC_REC)\n'
        if line not in candidate:
            candidate = replace(candidate, '        return float(desired)', line+'        return float(desired)')
    if not rebound:
        candidate = replace(candidate, 'if not self.latched and not cleared:', 'if not self.latched:')
    candidate += '''
    @property
    def episodes(self):
        return self._audit['episodes']

    @property
    def concordance_releases(self):
        return self._audit['concordance_releases']
'''
    candidate += '\n    _schema = '+repr('ramp-free-ex3-rebound-'+str(rebound).lower()+'/1')
    candidate += '\n    _caps = {"full_streak":8, "recent_positive_streak":8}\n'+SNAPSHOT
    return candidate


def fast_peer(peer):
    marker = '    unresolved=any('
    peer = replace(peer, marker,
        "    if not any(bool(z[7]) for z in held):\n"
        "        return sum(int(bool(z[6])) for z in held)/len(held), sum(int(x) for x in individuals)/len(held)\n"+marker)
    peer = replace(peer, 'stress=sum(int(reds[j]) for j in neighbors)/len(neighbors)',
                        'stressed=2*sum(int(reds[j]) for j in neighbors)>=len(neighbors)')
    return replace(peer, 'stress>=.50', 'stressed')


def build_sources():
    original, simplified = authorities()
    result = {'original': original, 'simplified': simplified}
    for name, source, rebound in [('original', original, True), ('simplified', simplified, False)]:
        raw_n, raw_c = segment(source, 'Native'), segment(source, 'CandidateA')
        minimal = replace(source, raw_n, no_ramp(raw_n))
        result[name+'_no_ramp'] = minimal
        compact = replace(minimal, segment(minimal, 'Native'), compact_native(no_ramp(raw_n)))
        compact = replace(compact, raw_c, compact_candidate(raw_c, rebound))
        compact = replace(compact, segment(compact, 'dynamic_peer_breadth'),
                          fast_peer(segment(simplified, 'dynamic_peer_breadth')))
        result['compact_'+name+'_no_ramp'] = compact
    # All AST nodes outside named controller/peer definitions are preserved per parent.
    for name, source in result.items():
        compile(source, name, 'exec')
        parent = simplified if 'simplified' in name else original
        a, b = source, parent
        for definition in ('Native', 'CandidateA', 'dynamic_peer_breadth'):
            a = a.replace(segment(a, definition), definition+' = None')
            b = b.replace(segment(b, definition), definition+' = None')
        assert ast.dump(ast.parse(a)) == ast.dump(ast.parse(b)), name
    return {name: result[name] for name in TRACKS}


NAMES = {'finite', 'Native', 'CandidateA', '_peer_corr', '_prior_residuals', 'dynamic_peer_breadth'}
CONSTANTS = {'ORD_DD', 'FAST', 'SLOW', 'LDRC_DD', 'LDRC_R20', 'LDRC_CEIL', 'LDRC_REC',
             'LDRC_V', 'PEER_LOOKBACK', 'PEER_MIN_OBS', 'PEER_COUNT', 'PEER_CORR_FLOOR', 'PEER_STATS'}


def pure(source):
    nodes = []
    for node in ast.parse(source).body:
        if getattr(node, 'name', None) in NAMES:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets):
            nodes.append(node)
    env = {'np': np}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pure>', 'exec'), env)
    return env


def write_sources():
    sources = build_sources()
    out = HERE/'sources'
    out.mkdir(exist_ok=True)
    manifest = {}
    for name, source in sources.items():
        (out/(name+'.py')).write_text(source)
        env = pure(source)
        manifest[name] = {'sha256':sha(source), 'native_fields': sorted(vars(env['Native']())),
                          'ex3_fields':sorted(vars(env['CandidateA']()))}
    (HERE/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    return manifest


if __name__ == '__main__':
    print(json.dumps(write_sources(), indent=2))
