"""Fail-closed cgroup-v2 and Linux process measurements for local experiments."""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time


def process_peak():
    import resource  # Worker-only: the native controller also runs on Windows.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def pairs(text):
    return {key: int(value) for key, value in (line.split() for line in text.splitlines())}


def cgroup(root=Path("/sys/fs/cgroup")):
    current = int((root / "memory.current").read_text())
    stats = pairs((root / "memory.stat").read_text())
    return dict(current=current, peak=int((root / "memory.peak").read_text()),
                limit=int((root / "memory.max").read_text()),
                working=max(0, current - stats["inactive_file"]), anon=stats["anon"],
                events=pairs((root / "memory.events").read_text()))


def disk(root):
    result = dict(cache_bytes=0, cache_files=0, partial_bytes=0, other_bytes=0)
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except FileNotFoundError:  # An atomic cache rename can race the sampler.
            continue
        if path.suffix == ".zip":
            result["cache_bytes"] += size
            result["cache_files"] += 1
        elif path.name.startswith(".partial-"):
            result["partial_bytes"] += size
        else:
            result["other_bytes"] += size
    return result


class Measurement:
    def __init__(self, cache):
        self.cache = cache
        self.stop = threading.Event()
        self.samples = 0
        self.phases = {}
        self.disk_peaks = dict(cache_bytes=0, partial_bytes=0, other_bytes=0)
        self.phase_name = "startup"
        self.error = None
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        try:
            while not self.stop.is_set():
                self._record(dict(phase=self.phase_name,
                                  storage=disk(self.cache), **cgroup()))
                self.stop.wait(0.1)
        except Exception as exc:
            self.error = type(exc).__name__

    def _record(self, sample):
        self.samples += 1
        phase = self.phases.setdefault(sample['phase'], dict(working_peak_bytes=0, anon_peak_bytes=0))
        phase['working_peak_bytes'] = max(phase['working_peak_bytes'], sample['working'])
        phase['anon_peak_bytes'] = max(phase['anon_peak_bytes'], sample['anon'])
        for key in self.disk_peaks:
            self.disk_peaks[key] = max(self.disk_peaks[key], sample['storage'][key])

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join(timeout=5)

    @contextmanager
    def phase(self, name):
        self.phase_name = name
        start = time.monotonic()
        print(json.dumps(dict(event="phase_start", phase=name)), flush=True)
        try:
            yield
        finally:
            print(json.dumps(dict(event="phase_end", phase=name,
                seconds=round(time.monotonic()-start, 3),
                process_peak_bytes=process_peak(),
                cgroup=cgroup(), disk=disk(self.cache))), flush=True)

    def result(self):
        if self.error or self.thread.is_alive() or not self.samples:
            raise RuntimeError("resource sampler incomplete: " + str(self.error))
        return dict(phases=self.phases, cgroup=cgroup(), samples=self.samples,
                    working_peak_bytes=max(s["working_peak_bytes"] for s in self.phases.values()),
                    sampled_disk_peaks=self.disk_peaks,
                    process_peak_bytes=process_peak())


def qualifies(measured, limit):
    return (measured["cgroup"]["limit"] == limit
            and measured["samples"] > 0
            and measured["cgroup"]["events"]["oom"] == 0
            and measured["cgroup"]["events"]["oom_kill"] == 0
            and 0 < measured["working_peak_bytes"] < limit * 0.8)
