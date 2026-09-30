"""Bounded Linux host commands, including descendants of Git/Compose clients."""
import os
import signal
import subprocess
import threading


def run(argv, *, cwd, env=None):
    values = dict(os.environ if env is None else env)
    raw = values.get("SENTINEL_GO_COMMAND_TIMEOUT_SECONDS", "10800")
    try:
        timeout = int(raw)
        if timeout < 1:
            raise ValueError
    except (TypeError, ValueError):
        return subprocess.CompletedProcess(argv, 2, "", "invalid host command timeout")
    previous = {}
    proc = None

    def interrupt(signum, frame):
        raise KeyboardInterrupt("host command interrupted")

    def stop():
        if proc is None:
            return
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)

    try:
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, interrupt)
        proc = subprocess.Popen([str(x) for x in argv], cwd=str(cwd), env=values,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop()
            out, err = proc.communicate(timeout=5)
            return subprocess.CompletedProcess(argv, 124, out, err + "\nhost command deadline exceeded")
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)
    except BaseException:
        stop()
        raise
    finally:
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                stream.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
