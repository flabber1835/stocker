"""Closed common byte-proof wire validation, standard library on the host."""
import math
import re


KEYS = frozenset(('schema enabled system_identifier base_backup recoverable_from_wal '
    'recovery_marker_wal recoverable_through_wal wal_segments timeline_history wal_integrity '
    'integrity_objects_hashed integrity_full_scrub integrity_read_passes integrity_max_reuse_seconds '
    'wal_segment_bytes integrity_completed_uptime integrity_observed_uptime').split())


def validate(value):
    if not isinstance(value, dict) or set(value) != KEYS:
        raise ValueError('common integrity report fields are invalid')
    for key, pattern in (('system_identifier', r'[1-9][0-9]{0,19}'),
            ('base_backup', r'base-[0-9]{8}T[0-9]{6}Z'),
            *((key, r'[0-9A-F]{24}') for key in ('recoverable_from_wal',
                 'recovery_marker_wal', 'recoverable_through_wal'))):
        if not isinstance(value[key], str) or re.fullmatch(pattern, value[key]) is None:
            raise ValueError('common integrity identity is invalid')
    numbers = ('wal_segments', 'wal_segment_bytes', 'integrity_objects_hashed',
               'integrity_read_passes', 'integrity_max_reuse_seconds')
    if (any(type(value[k]) is not int for k in numbers)
            or type(value['integrity_full_scrub']) is not bool
            or value['enabled'] is not True or value['schema'] != 'sentinel.maintenance-integrity/1'
            or value['wal_integrity'] != 'sha256-sidecar-v1'):
        raise ValueError('common integrity types are invalid')
    size = value['wal_segment_bytes']; count = value['wal_segments']
    if (not 1024**2 <= size <= 1024**3 or size & (size-1)
            or not 1 <= count <= 1024 or size*count > 16*1024**3):
        raise ValueError('common integrity resource bounds are invalid')
    names = [value[k] for k in ('recoverable_from_wal', 'recovery_marker_wal', 'recoverable_through_wal')]
    timeline = names[0][:8]; per_log = 2**32//size
    indices = [int(n[8:16], 16)*per_log+int(n[16:], 16) for n in names]
    history = None if timeline == '00000001' else timeline+'.history'
    reads = value['integrity_objects_hashed']
    if (int(timeline, 16) < 1 or any(n[:8] != timeline or int(n[16:], 16) >= per_log for n in names)
            or not indices[0] <= indices[1] <= indices[2]
            or count != indices[2]-indices[0]+1 or value['timeline_history'] != history
            or not 0 <= reads <= 2*(count+(history is not None)) or reads % 2
            or value['integrity_read_passes'] != (2 if reads else 0)
            or value['integrity_full_scrub'] and reads != 2*(count+(history is not None))
            or value['integrity_max_reuse_seconds'] != 300):
        raise ValueError('common integrity interval or work counts are invalid')
    stamps = [value[k] for k in ('integrity_completed_uptime', 'integrity_observed_uptime')]
    if (any(type(s) not in (int, float) or not math.isfinite(s) or s < 0 for s in stamps)
            or not 0 <= stamps[1]-stamps[0] < 300):
        raise ValueError('common integrity original clock is invalid')
    return value
