"""An observation cannot outlive the callback that owns it."""
import multiprocessing
import sys
import time

import pytest

from sentinel import supervisor_io


def slow_observation():time.sleep(5);return 'late result'


@pytest.mark.skipif(sys.platform!='linux', reason='fork required')
def test_owner_cancellation_reaps_the_dependency_observer():
    before={process.pid for process in multiprocessing.active_children()}
    started=time.monotonic()
    with pytest.raises(TimeoutError,match='cancelled by owner'):
        supervisor_io.run(slow_observation,timeout=4,cancelled=lambda:time.monotonic()-started>.1)
    assert time.monotonic()-started<2
    assert {process.pid for process in multiprocessing.active_children()}==before
