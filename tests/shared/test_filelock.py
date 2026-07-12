"""file_lock — the cross-container flock guarding proposals.json (audit F1)."""
import os
import subprocess
import sys

from stock_strategy_shared.filelock import file_lock


def test_lock_creates_parent_dirs_and_releases(tmp_path):
    lock = str(tmp_path / "deep" / "nested" / "x.lock")
    with file_lock(lock):
        assert os.path.exists(lock)
    with file_lock(lock):   # re-acquirable after release
        pass


def test_lock_is_exclusive_across_processes(tmp_path):
    """While held here, a separate interpreter must FAIL a non-blocking probe;
    after release it must succeed — proving real kernel-level flock semantics
    (what makes it work across containers sharing the bind-mounted dir)."""
    lock = str(tmp_path / "p.lock")
    probe = (
        "import fcntl, sys\n"
        "f = open(sys.argv[1], 'a')\n"
        "try:\n"
        "    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "    print('ACQUIRED')\n"
        "except BlockingIOError:\n"
        "    print('BLOCKED')\n"
    )
    with file_lock(lock):
        out = subprocess.run([sys.executable, "-c", probe, lock],
                             capture_output=True, text=True, timeout=30)
        assert out.stdout.strip() == "BLOCKED"
    out = subprocess.run([sys.executable, "-c", probe, lock],
                         capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "ACQUIRED"
