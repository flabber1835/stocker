"""A separately typed PXD scope using unchanged, isolated guard function bodies."""
import hashlib
from pathlib import Path
from types import FunctionType
from typing import Literal

from pydantic import Field
import system_campaign_close_scope as original


SCHEMA = 'research.unowned-preopen-stock-conversion-input/1'
WATCH = 'research.unowned-preopen-stock-conversion-watch/1'
SCOPE = 'UNOWNED_UNORDERED_PREOPEN_STOCK_CONVERSION'
NATIVES = {'276044719892003870': '2024-05-02'}
COMPLETIONS = {'276044719892003870': '2024-05-03'}
SOURCE_SHA256 = '76c7229d84405053a8212111dedffe435da7a103a68974c4e2cf70655c0e7af8'


def require_source():
    original.require(hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest()
                     == SOURCE_SHA256, 'PXD_SCOPE_EXACT_UNCHANGED_SEVENTH_INPUT_IMPLEMENTATION')


def isolated(fn, **bindings):
    require_source()
    original.require(fn.__closure__ is None, 'PXD_SCOPE_NO_HIDDEN_CLOSURE')
    result = FunctionType(fn.__code__, dict(fn.__globals__, **bindings),
                          fn.__name__, fn.__defaults__)
    result.__kwdefaults__ = fn.__kwdefaults__
    return result


class GuardedInput(original.GuardedInput):
    schema_id: Literal['research.unowned-preopen-stock-conversion-input/1'] = Field(alias='schema')
    scope: Literal['UNOWNED_UNORDERED_PREOPEN_STOCK_CONVERSION']


active = isolated(original.active, NATIVES=NATIVES)
parse = isolated(original.parse, NATIVES=NATIVES, active=active, GuardedInput=GuardedInput)
require_absent = original.require_absent
require_intents = original.require_intents
projection = original.projection


class TransitionGuard(original.TransitionGuard):
    relevant = isolated(original.TransitionGuard.relevant, COMPLETIONS=COMPLETIONS, SCOPE=SCOPE)
    advance = isolated(original.TransitionGuard.advance, active=active, WATCH=WATCH, SCOPE=SCOPE)
    append = isolated(original.TransitionGuard.append, active=active)


class InputCodec(original.InputCodec):
    def __init__(self, expected_repair, expected_evidence):
        require_source()
        super().__init__(expected_repair, expected_evidence)
        self.guard = TransitionGuard(self)

    load = isolated(original.InputCodec.load, SCHEMA=SCHEMA, parse=parse, GuardedInput=GuardedInput)
    apply = isolated(original.InputCodec.apply, GuardedInput=GuardedInput)


review_guards = isolated(original.review_guards, active=active, WATCH=WATCH, SCOPE=SCOPE)
