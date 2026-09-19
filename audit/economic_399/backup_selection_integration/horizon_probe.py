"""Check actual runtime WAL geometry; this is not physical restore acceptance."""
import json

from sentinel import backup_runtime_authority as authority


def main():
    # Literal endpoints independently encode inclusive intervals starting at 1.
    # PostgreSQL's 16 MiB segments fit 256 positions in each 4 GiB log ID.
    segment_size = 16 * 1024 * 1024
    first = '000000010000000000000001'
    cases = (
        (64, '000000010000000000000040', True),
        (65, '000000010000000000000041', False),
        (288, '000000010000000100000020', False),
    )
    assert authority.RUNTIME_MAX_VERIFIED_BYTES == 1024 ** 3
    results = []
    for count, end, accepted in cases:
        oracle_bytes = count * segment_size
        assert (oracle_bytes <= 1024 ** 3) is accepted
        try:
            names = authority._expected_wals(first, end, segment_size=segment_size)
        except authority.BackupRuntimeRefused as exc:
            assert not accepted
            assert 'integrity bytes' in str(exc)
            result = {'segments': count, 'bytes': oracle_bytes,
                      'interval_admitted': False, 'reason': str(exc)}
        else:
            assert accepted and len(names) == count
            assert names[0] == first and names[-1] == end
            result = {'segments': count, 'bytes': oracle_bytes,
                      'interval_admitted': True}
        results.append(result)
    print(json.dumps({
        'scope': 'ARITHMETIC_INTERVAL_ADMISSION_ONLY',
        'segment_size': segment_size,
        'timeline': 1,
        'cases': results,
        'five_minute_switches_per_24_hours': 24 * 60 // 5,
        'minutes_for_64_five_minute_switches': 64 * 5,
        'timing_is_a_scenario_not_a_deployed_measurement': True,
        'physical_restore_qualified': False,
    }, indent=2))


if __name__ == '__main__':
    main()
