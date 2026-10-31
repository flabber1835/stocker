"""Pure bounded wire format shared by independent financial observers."""
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import pickle

from sentinel.panel import model

MAX_BYTES = 32 * 1024


def pack(rows, errors, *, observed_at):
    value = {'rows': [asdict(row) for row in rows], 'errors': errors,
             'observed_at': observed_at}
    for raw, row in zip(value['rows'], rows):
        raw['shadow_book'] = row.shadow_book.model_dump(mode='json') if row.shadow_book else None
    if (len(json.dumps(value, default=str, allow_nan=False).encode()) > MAX_BYTES
            or len(pickle.dumps(value)) > MAX_BYTES):
        raise ValueError('financial observer result exceeds bound')
    return value


def validate_envelope(value, expected_keys):
    if (not isinstance(value, dict)
            or set(value) != {'rows', 'errors', 'observed_at'}
            or not isinstance(value['rows'], list)
            or len(value['rows']) != len(expected_keys)
            or any(not isinstance(row, dict) for row in value['rows'])
            or {row.get('key') for row in value['rows']} != expected_keys
            or not isinstance(value['errors'], list)
            or len(value['errors']) > 4
            or any(not isinstance(error, str) or len(error) > 1000
                   for error in value['errors'])):
        raise ValueError('observer shape is incomplete')
    for row in value['rows']:
        if (any(not isinstance(row.get(field), str)
                for field in ('key', 'label', 'value', 'status', 'detail'))
                or row['status'] not in {model.OK, model.PENDING, model.WARN,
                                         model.FAIL, model.UNKNOWN}
                or any(len(row[field]) > 1000 for field in ('label', 'value', 'detail'))):
            raise ValueError('observer row is malformed')
    return value


def row_from_observation(value):
    """Materialize nested dataclass evidence before public projection."""
    row = dict(value)
    if row.get('shadow_book') is not None:
        if row.get('key') != 'book':
            raise ValueError('holdings are only permitted on the canonical book')
        row['shadow_book'] = model.ShadowBook.model_validate(row['shadow_book'])
    if type(row.get('required_current', False)) is not bool:
        raise ValueError('observer current flag is malformed')
    if row.get('paper_alignment') not in {None, 'SCHEDULED', 'SCHEDULED_WITH_HISTORY', 'PRIOR_CYCLE_FAILED'} or (
            row.get('paper_alignment') is not None
            and (row.get('key') != 'paper_reconciliation'
                 or row.get('status') != (model.OK if row['paper_alignment']=='SCHEDULED' else model.WARN)
                 or row.get('valid_until') is None
                 or (row['paper_alignment']=='SCHEDULED_WITH_HISTORY'
                     and (row.get('required_current') is not True or row.get('recovery') is not None
                          or not isinstance(row.get('valid_until'), datetime)
                          or row['valid_until'].utcoffset() != timedelta(0)))
                 or (row['paper_alignment']=='PRIOR_CYCLE_FAILED'
                     and (row.get('required_current',False) or row.get('recovery') is not None)))):
        raise ValueError('observer alignment fact is malformed')
    for field in ('as_of', 'valid_until'):
        boundary = row.get(field)
        if boundary is not None and (not isinstance(boundary, datetime)
                                     or boundary.utcoffset() is None):
            raise ValueError('observer clock is malformed')
    recovery = row.get('recovery')
    if recovery is not None:
        if not isinstance(recovery, dict):
            raise ValueError('observer recovery is malformed')
        recovery = model.RecoveryEvidence(**recovery)
        if (not isinstance(recovery.phase, str) or len(recovery.phase) > 1000
                or type(recovery.automatic) is not bool
                or type(recovery.operator_required) is not bool
                or any(bound is not None and type(bound) is not int
                       for bound in (recovery.attempt, recovery.maximum_attempts))
                or any(clock is not None and (not isinstance(clock, datetime)
                                              or clock.utcoffset() is None)
                       for clock in (recovery.next_attempt_at, recovery.deadline))):
            raise ValueError('observer recovery fields are malformed')
        row['recovery'] = recovery
    return model.Row(**row)
