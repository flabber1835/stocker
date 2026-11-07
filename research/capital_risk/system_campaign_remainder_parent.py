"""Financial continuation uses the strict own41 parent, never discovery state."""
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
import system_campaign_discovery_parent as original
import system_campaign_content_reference as storage

SPEC = original.SPEC
SPEC_SHA = original.SPEC_SHA
PATH = 'lineage/remainder-strict-financial-parent-reference.json'
scope = original.scope
reference = original.reference


def admit(spec, root, key, *, max_zip_bytes=512 * 1024 ** 2):
    need(max_zip_bytes == 512 * 1024 ** 2, 'REMAINDER_UNCHANGED_STRICT_PARENT_TRANSFER_BOUND')
    return original.admit(spec, root, key)


def preserve(old, out, spec):
    scope(spec)
    fn = storage.preserve
    checked = FunctionType(fn.__code__, dict(fn.__globals__, reference=reference, PATH=PATH),
                           fn.__name__, fn.__defaults__)
    return checked(Path(old), Path(out), spec)
