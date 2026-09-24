"""Run a disjoint portion of the complete Sentinel collection in a fresh process."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sentinel_go_suites import SENTINEL_PARTITIONS, partition_for  # noqa: E402


class Partition:
    def __init__(self, name):
        if name not in SENTINEL_PARTITIONS:
            raise ValueError('unknown Sentinel certification partition')
        self.name = name

    def pytest_collection_modifyitems(self, config, items):
        selected, remainder = [], []
        for item in items:
            destination = selected if partition_for(Path(item.path).name) == self.name else remainder
            destination.append(item)
        config.hook.pytest_deselected(items=remainder)
        items[:] = selected


def main(argv=None):
    import pytest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('partition', choices=SENTINEL_PARTITIONS)
    args, pytest_args = parser.parse_known_args(argv)
    return pytest.main(['tests/sentinel', *pytest_args], plugins=[Partition(args.partition)])


if __name__ == '__main__':
    raise SystemExit(main())
