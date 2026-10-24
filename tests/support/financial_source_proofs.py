"""Mechanical inverses for two exact structural financial extractions.

Constants were independently read from Git0067e90b. Only the small moved factor
is reconstructed; the original early predecessor guard remains unchanged.
Whole modules reconstruct to their original catalog byte hashes.
"""
import ast
import hashlib
from tests.support.publisher_source_proofs import baseline_catalog


def _replace(source, before, after, count=1):
    if source.count(before) != count:
        raise ValueError('financial source extraction scope changed')
    return source.replace(before, after)


def reconstruct_units(raw):
    value = raw.decode()
    value = _replace(value, 'from typing import Mapping, Optional, Sequence\n',
                     'from typing import Mapping, Optional\n')
    value = _replace(value, REVIEWED_FACTOR_SPAN, '')
    value = _replace(value, '"record_projection", "share_action_factor"]', '"record_projection"]')
    return value.encode()


def reconstruct_held(raw):
    value = raw.decode()
    value = _replace(value, 'from fractions import Fraction\n',
                     'from fractions import Fraction\nfrom types import SimpleNamespace\n')
    value = _replace(value,
        'from sentinel.execution.target_reprojection import TargetProjectionRefused, share_action_factor',
        'from sentinel.execution.target_reprojection import TargetProjectionRefused')
    value = _replace(value, '    from sentinel.core.decision import DEFENSIVE_SECURITY_ID\n',
        '    from sentinel.core.decision import DEFENSIVE_SECURITY_ID\n'
        '    from sentinel.execution.protected_limits import _factor\n')
    value = _replace(value,
        '            factor /= share_action_factor(security_id=sid,\n'
        '                multiplier=projection.action_multipliers.get(sid, Decimal(1)),\n'
        '                evidence=projection.action_evidence)',
        '            factor /= _factor(projection, sid)')
    value = _replace(value,
        '            factor *= share_action_factor(security_id=sid, multiplier=multiplier,\n'
        '                                          evidence=events)',
        '            factor *= _factor(SimpleNamespace(\n'
        '                action_multipliers={sid: multiplier}, action_evidence=events), sid)')
    return value.encode()


def prove_full_reconstruction(name, raw):
    inverse = {'execution/held_targets.py': reconstruct_held,
               'execution/target_reprojection.py': reconstruct_units}[name]
    assert hashlib.sha256(inverse(raw)).hexdigest() == baseline_catalog()['files'][name]


def prove_factor_body():
    assert hashlib.sha256(BASE_FACTOR.encode()).hexdigest() == BASE_FACTOR_SHA256
    old = ast.parse(BASE_FACTOR).body[0]
    new = ast.parse(REVIEWED_FACTOR_SPAN).body[0]
    # The public function receives the old extracted inputs explicitly. Its
    # positivity predicate is the unchanged _positive contract expanded inline.
    assert isinstance(new.body[1], ast.If)
    assert ast.dump(new.body[1].test) == ast.dump(ast.parse(
        'not isinstance(multiplier, Decimal) or not multiplier.is_finite() or multiplier <= 0').body[0].value)
    body = new.body[2:]
    class OriginalNames(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'security_id':
                return ast.copy_location(ast.Name(id='sid', ctx=node.ctx), node)
            if node.id == 'evidence':
                return ast.copy_location(ast.Attribute(value=ast.Name(id='projection', ctx=ast.Load()),
                                                       attr='action_evidence', ctx=node.ctx), node)
            if node.id in {'_evidence_factor', '_fractions_close', '_RATIO_REPRESENTATION_TOLERANCE'}:
                return ast.copy_location(ast.Attribute(value=ast.Name(id='units', ctx=ast.Load()),
                                                       attr=node.id, ctx=node.ctx), node)
            return node
    restored = OriginalNames().visit(ast.Module(body=body, type_ignores=[]))
    assert ast.dump(restored) == ast.dump(ast.Module(body=old.body[3:], type_ignores=[]))

BASE_FACTOR = 'def _factor(projection, sid):\n    from sentinel.execution import target_reprojection as units\n    multiplier = projection.action_multipliers.get(sid, Decimal(1))\n    _positive(multiplier, "effective share multiplier")\n    events = [item for item in projection.action_evidence if item.get("security_id") == sid]\n    if not events:\n        if multiplier != 1:\n            raise TargetProjectionRefused("non-unit effective shares require durable action evidence")\n        return Fraction(multiplier)\n    published, exact = Fraction(1), Fraction(1)\n    for item in events:\n        if not item.get("source_row_id"):\n            raise TargetProjectionRefused("effective share evidence lacks source identity")\n        approximate, rational = units._evidence_factor(item)\n        published *= approximate\n        exact *= rational\n    if not units._fractions_close(Fraction(multiplier), published, units._RATIO_REPRESENTATION_TOLERANCE):\n        raise TargetProjectionRefused("effective share evidence differs from projection")\n    return exact\n'
BASE_FACTOR_SHA256 = 'd696f4cdcaecda2149f9d0bd01e9aeab453b683795edbfbba5091841bf2440b9'
REVIEWED_FACTOR_SPAN = 'def share_action_factor(*, security_id: str, multiplier: Decimal,\n                        evidence: Sequence[Mapping[str, object]]) -> Fraction:\n    """Recover exact evidenced units without rounding intended account shares."""\n    if not isinstance(multiplier, Decimal) or not multiplier.is_finite() or multiplier <= 0:\n        raise TargetProjectionRefused("effective share multiplier must be positive finite Decimal")\n    events = [item for item in evidence if item.get("security_id") == security_id]\n    if not events:\n        if multiplier != 1:\n            raise TargetProjectionRefused("non-unit effective shares require durable action evidence")\n        return Fraction(multiplier)\n    published, exact = Fraction(1), Fraction(1)\n    for item in events:\n        if not item.get("source_row_id"):\n            raise TargetProjectionRefused("effective share evidence lacks source identity")\n        approximate, rational = _evidence_factor(item)\n        published *= approximate\n        exact *= rational\n    if not _fractions_close(Fraction(multiplier), published, _RATIO_REPRESENTATION_TOLERANCE):\n        raise TargetProjectionRefused("effective share evidence differs from projection")\n    return exact\n\n\n'
