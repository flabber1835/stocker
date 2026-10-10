"""Finite host/worker budgets for the existing recovery owners."""
import argparse

INVOCATION_SECONDS = 3600
BASE_COMMAND_SECONDS = 900
CHAIN_STATUS_SECONDS = 600
RESTORE_COMMAND_SECONDS = 2100
RESTORE_WORKER_SECONDS = RESTORE_COMMAND_SECONDS + 60


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('budget', choices=('restore-worker',))
    parser.parse_args()
    print(RESTORE_WORKER_SECONDS)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
