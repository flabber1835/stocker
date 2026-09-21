"""Independent numeric witnesses prevent reporting cache pressure as a clean pass."""
import pytest

from audit.economic_399.postgres_pressure.report import samples, summarize


def sample(at, *, maximum=5, oom=0):
    return f'''BEGIN {at}
phase publish
memory.current
1000000000
memory.peak
1073800000
memory.events
max {maximum}
oom {oom}
oom_kill 0
oom_group_kill 0
memory.stat
anon 50000000
file 900000000
shmem 150000000
kernel 10000000
memory.pressure
some avg10=0.00 avg60=0.00 avg300=0.00 total={at*10000}
full avg10=0.00 avg60=0.00 avg300=0.00 total={at*5000}
cpu.stat
usage_usec 100
END
'''


def test_shared_memory_is_not_subtracted_as_reclaimable_file_cache():
    rows = samples(sample(10)+sample(12, maximum=8))
    assert rows[0]['file_cache_bytes'] == 750000000
    assert rows[0]['non_file_cache_estimate_bytes'] == 210000000
    result = summarize(rows)
    assert result['total_memory_headroom'] == 'TIGHT'
    assert result['events_delta']['max'] == 3
    assert result['sampled_non_file_cache_peak_bytes'] == 210000000
    assert result['some_stall_seconds'] == .02
    assert result['some_stall_percent'] == 1
    assert result['full_stall_percent'] == .5


@pytest.mark.parametrize('text', [
    '', sample(10).replace('END\n', ''), sample(10, oom=1),
    sample(10)+sample(12, maximum=0),
    sample(10).replace('shmem 150000000\n', ''),
    sample(10).replace('file 900000000', 'file 100000000'),
    sample(10)+sample(10),
])
def test_missing_oom_reset_or_inconsistent_evidence_refuses(text):
    with pytest.raises(AssertionError):
        samples(text)
