"""Controller-only research transformations of the SHA-pinned economic oracle."""
import ast
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_SHA = '335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d'
VARIANTS = ('baseline', 'selective_peers', 'bounded_counters', 'map65_to55',
            'ramp10', 'ramp20', 'no_peers', 'no_cross_surface', 'no_spy_rebound', 'combined')
CAPS = {'ordinary_age': 20, 'ordinary_h': 3, 'base_fast_age': 10,
        'base_fast_h': 3, 'base_dur': 30, 'fast_age': 9, 'fast_h': 3,
        'slow_age': 19, 'slow_h': 6, 'ramp_h': 10}


def oracle():
    source = (HERE / 'frozen_reference.txt').read_text()
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA:
        raise RuntimeError('economic oracle source hash mismatch')
    return source


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'expected exactly one source seam: {old!r}')
    return text.replace(old, new, 1)


def scope(source, name, transform):
    node = next(n for n in ast.parse(source).body if getattr(n, 'name', None) == name)
    lines = source.splitlines(keepends=True)
    old = ''.join(lines[node.lineno-1:node.end_lineno])
    return ''.join(lines[:node.lineno-1]) + transform(old) + ''.join(lines[node.end_lineno:])


def assert_scope(original, candidate, allowed):
    def projection(source):
        tree = ast.parse(source)
        return [ast.dump(n, include_attributes=False) for n in tree.body
                if getattr(n, 'name', None) not in allowed]
    if projection(original) != projection(candidate):
        raise RuntimeError('transformation escaped controller-only AST scope')


def build(variant):
    if variant not in VARIANTS:
        raise ValueError(variant)
    original = source = oracle()
    allowed = set()
    if variant == 'selective_peers':
        allowed.add('dynamic_peer_breadth')
        def selective(body):
            body = replace_once(body,
                '    residuals=[_prior_residuals(int(z[0]),gday,close_ring,spy,shadow_dates) for z in held]',
                '    individuals=[(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03) for z in held]\n'
                '    unresolved=any(not individual and not bool(z[6]) for z,individual in zip(held,individuals))\n'
                '    residuals=[_prior_residuals(int(z[0]),gday,close_ring,spy,shadow_dates) for z in held] if unresolved else [{} for z in held]')
            return replace_once(body, '    for i,z in enumerate(held):\n',
                '    for i,z in enumerate(held):\n'
                '        if individuals[i] or greens[i]:\n'
                '            ng+=int(greens[i]); na+=int(individuals[i]); continue\n')
        source = scope(source, 'dynamic_peer_breadth', selective)
    if variant in ('no_peers', 'combined'):
        allowed.add('dynamic_peer_breadth')
        source = scope(source, 'dynamic_peer_breadth', lambda _: '''def dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates):
    if not held: return 0.,0.
    PEER_STATS['breadth_sessions']+=1; PEER_STATS['holding_observations']+=len(held)
    green=sum(int(bool(z[6])) for z in held)
    damaged=sum(int((finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03)) for z in held)
    return green/len(held),damaged/len(held)
''')
    if variant == 'bounded_counters':
        allowed.update(('Native', 'CandidateA'))
        clamp = ''.join(f'        self.{k}=min(self.{k},{v})\n' for k,v in CAPS.items())
        source = scope(source, 'Native', lambda s: replace_once(s,
            '        return float(target), bool(fastsig), bool(slowsig)',
            clamp + '        return float(target), bool(fastsig), bool(slowsig)'))
        source = scope(source, 'CandidateA', lambda s: replace_once(s,
            '        self.prev_native=native; self.prev_desired=desired',
            '        self.full_streak=min(self.full_streak,LDRC_REC)\n'
            '        self.recent_positive_streak=min(self.recent_positive_streak,LDRC_REC)\n'
            '        self.prev_native=native; self.prev_desired=desired'))
    if variant in ('ramp10', 'ramp20', 'combined'):
        allowed.add('Native')
        def ramp(body):
            body = replace_once(body, 'if self.ramp_idx>=2:', 'if self.ramp_idx>=1:')
            if variant in ('ramp20', 'combined'):
                body = replace_once(body, '            need=10', '            need=20')
            return body
        source = scope(source, 'Native', ramp)
    if variant == 'map65_to55':
        allowed.add('CandidateA')
        source = scope(source, 'CandidateA', lambda s: replace_once(s,
            "        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'",
            "        return (.55 if desired==.65 else float(desired)), '|'.join(reasons) if reasons else 'NORMAL'"))
    if variant in ('no_cross_surface', 'combined'):
        allowed.add('CandidateA')
        source = scope(source, 'CandidateA', lambda s: replace_once(s,
            '            concordant=(\n', '            concordant=False and (\n'))
    if variant in ('no_spy_rebound', 'combined'):
        allowed.add('CandidateA')
        source = scope(source, 'CandidateA', lambda s: replace_once(s,
            '        vre=finite(spy20) and spy20>LDRC_V', '        vre=False'))
    assert_scope(original, source, allowed)
    compile(source, f'{variant}.py', 'exec')
    return source
