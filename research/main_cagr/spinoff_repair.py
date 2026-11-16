"""Explicit research assumptions for an exactly identified spin-off remainder."""
from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel.feed.rolling_contract import digest
from .inputs import sha256


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file: str
    url: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class SpinoffRepair(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_: Literal['research-spinoff-cash-repair/1'] = Field(alias='schema')
    policy: Literal['FRACTIONAL_CIL_AT_CHILD_OPEN_LESS_COST_V1']
    session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    source_row_id: str
    term_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    raw_child_open: Decimal = Field(gt=0)
    transaction_cost_bps: Literal[10]
    cash_in_lieu_price: Decimal = Field(gt=0)
    assumption: str = Field(min_length=1)
    source_evidence: tuple[SourceEvidence, ...] = Field(min_length=1)


def apply(schedule, path):
    if path is None:
        return schedule, None
    path = Path(path)
    repair = SpinoffRepair.model_validate_json(path.read_text())
    for evidence in repair.source_evidence:
        source = (path.parent/evidence.file).resolve()
        if (source.parent != path.parent.resolve() or not source.is_file()
                or sha256(source) != evidence.sha256 or not evidence.url.startswith('https://')):
            raise ValueError('spin-off primary evidence missing or changed')
    events = schedule.get(repair.session, ())
    matched = [event for event in events if event.source_row_id == repair.source_row_id]
    if len(matched) != 1 or digest(asdict(matched[0])) != repair.term_sha256:
        raise ValueError('spin-off original event changed')
    original = matched[0]
    if original.cash_in_lieu_price not in (None, ''):
        raise ValueError('spin-off cash price already supplied')
    if Decimal(str(original.child_price)) != repair.raw_child_open:
        raise ValueError('spin-off opening price changed')
    net = repair.raw_child_open * (1 - Decimal(repair.transaction_cost_bps)/10000)
    if net != repair.cash_in_lieu_price:
        raise ValueError('spin-off modeled net price changed')
    corrected = replace(original, cash_in_lieu_price=str(net))
    result = {day:list(items) for day, items in schedule.items()}
    result[repair.session] = [corrected if event is original else event for event in events]
    provenance = dict(sha256=sha256(path), document=repair.model_dump(mode='json', by_alias=True),
                      original_event=asdict(original), corrected_event=asdict(corrected))
    return result, provenance
