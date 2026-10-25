"""One exact retained source edge for backed owner PAPER, never authority."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from sentinel import structural_refactor_source_basis as structural
from sentinel.rolling_checkpoint import RollingColdStartRefused as Refused


ORIGIN_REVISION = '90a960547b58bb245c998ae3f70d0baed1fe95d0'
ORIGIN_SOURCE_SHA256 = 'c2950194bf6ea20bbac66d5bcf356c118e8518d4e9c9d3dda17b08ff10080003'
BASELINE_REVISION = '0067e90b9f3a0e3e0b8c859fe4a90212e750ef16'
BASELINE_SOURCE_SHA256 = '56890ee50268961357faf2f6a8c2dc66ca76eb74c7440c832ba3a7bd06a09e15'
PROFILE_SHA256 = '9927c102f3836036c313126d1e189ad83a09bf7aeaa117efb0aa4918ad983081'
PROFILE = Path(__file__).with_name('backed-paper-source-transition.json')
_SCHEMA = 'sentinel.owner-paper-retained-source-transition/1'
_SEAMS = frozenset({'core/decision.py', 'rolling_checkpoint.py', 'rolling_daily_checkpoint.py'})
_DIGEST = re.compile(r'[0-9a-f]{64}')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate source profile key')
        result[key] = value
    return result


def _source_map(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError('source map must be a mapping')
    result = dict(value)
    for name, digest in result.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError('source map keys and hashes must be strings')
        path = Path(name)
        if (path.is_absolute() or path.drive or '..' in path.parts
                or path.as_posix() != name or '\\' in name or '__pycache__' in path.parts
                or not name.endswith('.py') or _DIGEST.fullmatch(digest) is None):
            raise ValueError('source map contains a noncanonical entry')
    return result


def _closure(files: Mapping[str, str]) -> str:
    result = hashlib.sha256()
    for name, digest in sorted(_source_map(files).items()):
        result.update(name.encode() + b'\0' + digest.encode() + b'\n')
    return result.hexdigest()


def _profile() -> dict:
    try:
        raw = PROFILE.read_bytes()
        if _sha(raw) != PROFILE_SHA256:
            raise ValueError('source profile digest changed')
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite profile')))
        if (not isinstance(value, dict) or set(value) != {
                'schema', 'authority_effect', 'origin_revision', 'origin_source_sha256',
                'origin_files', 'baseline_revision', 'baseline_source_sha256', 'baseline_files'}
                or value['schema'] != _SCHEMA or value['authority_effect'] != 'NONE'
                or value['origin_revision'] != ORIGIN_REVISION
                or value['origin_source_sha256'] != ORIGIN_SOURCE_SHA256
                or value['baseline_revision'] != BASELINE_REVISION
                or value['baseline_source_sha256'] != BASELINE_SOURCE_SHA256
                or len(value['origin_files']) != 338 or len(value['baseline_files']) != 364
                or _closure(value['origin_files']) != ORIGIN_SOURCE_SHA256
                or _closure(value['baseline_files']) != BASELINE_SOURCE_SHA256
                or set(value['origin_files']) - set(value['baseline_files'])):
            raise ValueError('source profile shape or complete maps changed')
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise Refused('OWNER_PAPER_SOURCE_PROFILE_CHANGED') from exc


def _dump(node) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _definition(tree, name):
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(found) != 1:
        raise ValueError('decision definition is not unique')
    return found[0]


def _reverse_decision(old_bytes: bytes, current_bytes: bytes) -> bool:
    old = ast.parse(old_bytes)
    current = ast.parse(current_bytes)
    assignments = [node for node in current.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == '_DATA_SEMANTICS_MODULES'
                           for target in node.targets)]
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Tuple):
        return False
    inventory = assignments[0].value.elts
    entries = [index for index, node in enumerate(inventory)
               if isinstance(node, ast.Constant) and node.value == 'sentinel.execution.held_targets']
    if len(entries) != 1:
        return False
    del inventory[entries[0]]

    build = _definition(current, 'build_execution_plan')
    indices = [index for index, argument in enumerate(build.args.kwonlyargs)
               if argument.arg == 'retained_targets']
    expected = ast.parse('def f(*, retained_targets: Mapping[str, Decimal] | None = None): pass').body[0]
    if (len(indices) != 1 or indices[0] != len(build.args.kwonlyargs) - 1
            or _dump(build.args.kwonlyargs[indices[0]]) != _dump(expected.args.kwonlyargs[0])
            or _dump(build.args.kw_defaults[indices[0]]) != _dump(expected.args.kw_defaults[0])):
        return False
    del build.args.kwonlyargs[indices[0]]
    del build.args.kw_defaults[indices[0]]

    adjacent = ast.parse('''sized = _cap_unpriced_increases(
    sized, target, observation, shadow_equity=shadow_equity, nav=nav,
    exposure=exposure, defensive_weight=defensive_weight,
    defensive_security=defensive_security)
from sentinel.execution import held_targets
sized = held_targets.apply(sized, targets=retained_targets,
    canonical_target=target, marks=current_marks)
basket = desired_basket(sized)
''').body
    windows = [index for index in range(len(build.body) - len(adjacent) + 1)
               if [_dump(node) for node in build.body[index:index + len(adjacent)]]
               == [_dump(node) for node in adjacent]]
    if len(windows) != 1:
        return False
    del build.body[windows[0] + 1:windows[0] + 3]

    recipe = _definition(current, 'data_semantics_source_identity')
    original_recipe = _definition(old, 'data_semantics_source_identity')
    offset = int(bool(recipe.body) and isinstance(recipe.body[0], ast.Expr)
                 and isinstance(recipe.body[0].value, ast.Constant)
                 and isinstance(recipe.body[0].value.value, str))
    original_offset = int(bool(original_recipe.body) and isinstance(original_recipe.body[0], ast.Expr)
                          and isinstance(original_recipe.body[0].value, ast.Constant)
                          and isinstance(original_recipe.body[0].value.value, str))
    delegated = ast.parse('''from sentinel.economic_manifest import identity
return identity(schema=DATA_SEMANTICS_IDENTITY_SCHEMA)
''').body
    original = ast.parse('''from sentinel.semantic_source_basis import economic_sources
return economic_sources(_DATA_SEMANTICS_MODULES, schema=DATA_SEMANTICS_IDENTITY_SCHEMA)
''').body
    if ([_dump(node) for node in recipe.body[offset:]] != [_dump(node) for node in delegated]
            or [_dump(node) for node in original_recipe.body[original_offset:]]
                != [_dump(node) for node in original]):
        return False
    recipe.body[offset:] = original
    return _dump(current) == _dump(old)


@dataclass(frozen=True)
class ScopeProof:
    """Detached source facts only; mode and durable account remain fresh guards."""
    origin_files: Mapping[str, str]
    baseline_files: Mapping[str, str]
    current_files: Mapping[str, str]
    current_source_sha256: str

    def require_mode(self) -> None:
        from sentinel import local_paper
        try:
            if not local_paper.enabled() or local_paper.backup_policy() != local_paper.BACKUP_POLICY:
                raise ValueError('backed owner PAPER mode is required')
        except (RuntimeError, ValueError) as exc:
            raise Refused('OWNER_PAPER_SOURCE_MODE_REQUIRED') from exc

    def matches_manifest(self, revision: str, files: Mapping[str, str]) -> bool:
        return revision == ORIGIN_REVISION and isinstance(files, Mapping) and dict(files) == self.origin_files

    def source_allowed(self, name: str, previous: str, comparison: str) -> bool:
        return (name not in _SEAMS and name in self.origin_files
                and self.origin_files[name] == previous and self.baseline_files.get(name) == comparison)

    def decision_compatible(self, old_bytes: bytes, current_bytes: bytes) -> bool:
        if (not isinstance(old_bytes, bytes) or not isinstance(current_bytes, bytes)
                or _sha(old_bytes) != self.origin_files['core/decision.py']
                or _sha(current_bytes) != self.current_files['core/decision.py']):
            return False
        try:
            return _reverse_decision(old_bytes, current_bytes)
        except (SyntaxError, ValueError, TypeError):
            return False


def scope_for(*, revision: str, source_sha256: str,
              actual: Mapping[str, str]) -> ScopeProof | None:
    """Recognize the exact source pair independently of current operating mode."""
    if revision != ORIGIN_REVISION or source_sha256 != ORIGIN_SOURCE_SHA256:
        return None
    value = _profile()
    try:
        files = _source_map(actual)
        sealed = structural._profile()
        if sealed is None:
            raise ValueError('current structural seal is absent')
        expected = dict(sealed['candidate_files'])
        expected['structural_refactor_source_basis.py'] = _sha(Path(structural.__file__).read_bytes())
        if (expected.get(Path(__file__).name) != _sha(Path(__file__).read_bytes())
                or files != expected or sealed['base_revision'] != BASELINE_REVISION
                or sealed['baseline_source_sha256'] != BASELINE_SOURCE_SHA256
                or sealed['baseline_files'] != value['baseline_files']):
            raise ValueError('current complete source or comparison baseline is not sealed')
    except (OSError, ValueError, TypeError) as exc:
        raise Refused('OWNER_PAPER_CURRENT_SOURCE_UNSEALED') from exc
    return ScopeProof(MappingProxyType(dict(value['origin_files'])),
                      MappingProxyType(dict(value['baseline_files'])),
                      MappingProxyType(files), _closure(files))
