"""Explicit guarded-close receipt eligibility; unchanged crypto and full spec."""
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_normal_reference as original

SOURCE_SHA = '9166a676235bcd3b41e0aadf221297b8945e0454787a13c0df659b4e7b3d6abc'
RECEIPT = 'research.system-p02-close-suffix-receipt/1'


def function(name, **bindings):
    need(sha(Path(original.__file__).read_bytes()) == SOURCE_SHA,
         'CLOSE_REFERENCE_EXACT_ADOPTED_NORMAL_REFERENCE_SOURCE')
    fn = getattr(original, name)
    need(fn.__closure__ is None, 'CLOSE_REFERENCE_ORIGINAL_BODY_WITHOUT_CLOSURE')
    value = FunctionType(fn.__code__, dict(fn.__globals__, **bindings), fn.__name__, fn.__defaults__)
    value.__kwdefaults__ = fn.__kwdefaults__
    return value


def reference(spec):
    return function('reference', RECEIPTS=original.RECEIPTS | {RECEIPT})(spec)


def preserve(old, out, spec):
    return function('preserve', reference=reference)(old, out, spec)


def admit(spec, root, key, *, max_zip_bytes=original.LIMIT):
    return function('admit', reference=reference)(spec, root, key, max_zip_bytes=max_zip_bytes)
