"""Synthetic export marker; no market, strategy, broker or database imports."""
import os
from pathlib import Path
import time

MARKER=b'EXPECTED_BOUNDED_TIMEOUT_EXPORT_V1\n'


def main():
    with Path('/out/timeout-marker.bin').open('xb') as stream:
        stream.write(MARKER);stream.flush();os.fsync(stream.fileno())
    print('SYNTHETIC_TIMEOUT_MARKER_COMMITTED',flush=True)
    time.sleep(60)


if __name__=='__main__':main()
