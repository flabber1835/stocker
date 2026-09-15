"""Exact ownership and cleanup of GO's disposable Docker subprocesses."""
import signal
import subprocess
import threading
import uuid
from contextlib import contextmanager


def _remove_owned(name):
    result = subprocess.run(["docker", "rm", "-f", name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=20, text=True)
    if result.returncode == 0:
        return
    check = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=20, text=True)
    if check.returncode != 0 or check.stdout.strip():
        raise RuntimeError("GO could not verify cleanup of its owned Docker container")


@contextmanager
def owned_command(command):
    values = list(command)
    name = None
    if values[:2] == ["docker", "run"] or (
            values[:2] == ["docker", "compose"] and "run" in values):
        index = values.index("run") + 1
        if "--name" in values[index:]:
            raise ValueError("GO disposable command may not supply a container name")
        name = "sentinel-go-owned-" + uuid.uuid4().hex
        values[index:index] = ["--name", name]
    owner = {"command": values, "process": None}
    previous = {}
    def interrupt(signum, frame):
        raise KeyboardInterrupt("GO interrupted")
    if name and threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, interrupt)
    try:
        yield owner
    finally:
        try:
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            try:
                proc = owner["process"]
                if proc is not None:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                    proc.wait(timeout=5)
            finally:
                if name:
                    _remove_owned(name)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
