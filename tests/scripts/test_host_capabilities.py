"""The host cannot enforce every limit the compose file declares.

## The run that produced this

First real #15 attempt, on a Synology DS216+II:

```text
Error response from daemon: NanoCPUs can not be set, as your kernel does not
support CPU CFS scheduler or the cgroup is not mounted
```

Docker 24.0.2, kernel 3.10.108, cgroup v1, btrfs, Celeron N3060. Nothing
started — the daemon refuses before creating the container, so `up`, `run` and
every measurement were blocked.

The daemon refusing is CORRECT, and it is why this is a capability probe rather
than a patch that deletes resource controls. A CPU ceiling the kernel silently
ignored would be `docs/sentinel-deployment.md` §11's own named defect: a
setting believed to be in force, that is not. So the question is not "how do I
stop the error" but "which limits does this host enforce", and the answer is
part of the certification record.

## What is asserted here

```text
classify()      a canned `docker info` -> the right verdict, including the
                REAL Synology one. A missing field is UNKNOWN, never ENFORCED
strip           the generated deployment has NO `cpus:` and keeps every
                mem_limit and shm_size, byte for byte
resolver        fails toward the CANONICAL file when it cannot probe
harness         reports CPU as UNSUPPORTED, not PASS, and still records the
                measured peak
```
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
PROBE = REPO / "scripts" / "sentinel_host_capabilities.py"
STRIP = REPO / "scripts" / "sentinel_strip_cpu_limits.py"
RESOLVER = REPO / "scripts" / "sentinel-compose.sh"
CANONICAL = REPO / "docker-compose.sentinel.yml"
MEASURE = REPO / "scripts" / "sentinel-measure.sh"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def probe():
    return _load(PROBE)


@pytest.fixture(scope="module")
def stripper():
    return _load(STRIP)


#: The DS216+II, from its own `docker info` and the error it produced. The two
#: CPU flags are FACTS: the daemon's check is `NanoCPUs > 0 && !CPUCfsPeriod`,
#: so the refusal proves them false.
SYNOLOGY = {
    "ServerVersion": "24.0.2", "KernelVersion": "3.10.108",
    "OperatingSystem": "Synology DSM", "CgroupVersion": "1",
    "CgroupDriver": "cgroupfs", "Driver": "btrfs", "NCPU": 2,
    "MemTotal": 8287367168,
    "CPUCfsPeriod": False, "CPUCfsQuota": False,
    "MemoryLimit": True, "SwapLimit": False,
    "Warnings": ["WARNING: No cpu cfs quota support",
                 "WARNING: No cpu cfs period support",
                 "WARNING: No swap limit support"],
}

MODERN = {
    "ServerVersion": "27.3.1", "KernelVersion": "6.8.0-45-generic",
    "OperatingSystem": "Ubuntu 24.04", "CgroupVersion": "2",
    "CgroupDriver": "systemd", "Driver": "overlay2", "NCPU": 16,
    "MemTotal": 67108864000,
    "CPUCfsPeriod": True, "CPUCfsQuota": True,
    "MemoryLimit": True, "SwapLimit": True, "Warnings": [],
}


class TestTheCapabilityVerdict:
    def test_the_SYNOLOGY_result_is_reproduced(self, probe):
        """The regression test for the run that found this. If a future change
        made this host look capable, the compose file would be handed back its
        `cpus:` and the NAS would stop starting containers again."""
        caps = probe.classify(SYNOLOGY)
        assert caps["cpu_quota"] == "UNSUPPORTED"
        assert caps["memory_limit"] == "ENFORCED"
        assert caps["memory_swap"] == "UNSUPPORTED"

    def test_a_capable_host_is_still_capable(self, probe):
        """The fix must not disable CPU limits everywhere. That would be
        deleting a resource control, which is the thing not to do."""
        caps = probe.classify(MODERN)
        assert caps["cpu_quota"] == "ENFORCED"
        assert caps["memory_limit"] == "ENFORCED"

    def test_quota_WITHOUT_period_is_still_unsupported(self, probe):
        """`--cpus` needs both. The daemon checks them separately, and reading
        only `CPUCfsQuota` would call a half-capable host capable."""
        half = dict(SYNOLOGY, CPUCfsQuota=True, CPUCfsPeriod=False)
        assert probe.classify(half)["cpu_quota"] == "UNSUPPORTED"

    def test_a_MISSING_field_is_UNKNOWN_never_enforced(self, probe):
        """Older daemons omit some of these. Defaulting an absent field to
        "supported" would let a host claim an envelope it cannot hold — the
        same shape as the defect being fixed."""
        caps = probe.classify({"ServerVersion": "1.12"})
        assert set(caps.values()) == {"UNKNOWN"}
        assert "ENFORCED" not in caps.values()

    def test_no_daemon_is_not_a_crash(self, probe, monkeypatch):
        """It runs on hosts, in CI, and before anything is up."""
        monkeypatch.setattr(probe, "docker_info", lambda: {})
        rec = probe.probe()
        assert rec["probed"] is False
        assert rec["capabilities"]["cpu_quota"] == "UNKNOWN"

    def test_it_runs_and_emits_JSON(self):
        """End to end, whatever this machine happens to be."""
        r = subprocess.run([sys.executable, str(PROBE), "--json"],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        rec = json.loads(r.stdout)
        assert set(rec["capabilities"]) == {"cpu_quota", "cpu_period",
                                            "memory_limit", "memory_swap"}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """The NAS deployment, produced by the committed script from the real
    canonical file — not a fixture copy, so a service added later with a CPU
    limit is covered without anyone remembering to extend anything."""
    out = tmp_path_factory.mktemp("nocpu") / "docker-compose.nocpu.yml"
    r = subprocess.run([sys.executable, str(STRIP), str(CANONICAL), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


class TestTheGeneratedDeploymentHasNoCpus:
    """`docker compose config` for the NAS deployment must contain no `cpus:`
    while retaining every mem_limit and shm_size.

    Checked against the real canonical file, so a service added later with a
    CPU limit is covered without anyone remembering to extend a fixture.
    """

    def test_the_canonical_file_still_declares_cpus(self):
        """Guard the guard. If it stopped, every assertion below would pass for
        a stripper that does nothing."""
        assert "cpus:" in CANONICAL.read_text()

    def test_NO_cpus_survives(self, generated):
        import re
        body = generated.read_text()
        code = [l for l in body.splitlines() if not l.strip().startswith("#")]
        assert not [l for l in code if re.match(r"^\s+cpus:", l)], code

    def test_every_mem_limit_and_shm_size_SURVIVES(self, generated):
        a = yaml.safe_load(CANONICAL.read_text())["services"]
        b = yaml.safe_load(generated.read_text())["services"]
        assert set(a) == set(b)
        for name in a:
            assert a[name].get("mem_limit") == b[name].get("mem_limit"), name
            assert a[name].get("shm_size") == b[name].get("shm_size"), name

    def test_at_least_one_of_each_is_actually_THERE(self, generated):
        """So the assertion above cannot pass by both sides being empty."""
        b = yaml.safe_load(generated.read_text())["services"]
        assert sum(1 for s in b.values() if s.get("mem_limit")) >= 3
        assert any(s.get("shm_size") for s in b.values())

    def test_NOTHING_ELSE_changes(self, generated):
        """The generated file must be diffable against the canonical one. A
        yaml round-trip would reorder keys and drop every comment — and this
        compose file is mostly comments explaining why each limit exists."""
        a = yaml.safe_load(CANONICAL.read_text())
        b = yaml.safe_load(generated.read_text())
        assert a.get("name") == b.get("name")
        assert a.get("volumes") == b.get("volumes")
        for name, svc in a["services"].items():
            assert {k: v for k, v in svc.items() if k != "cpus"} == b["services"][name]

    def test_the_comments_survive(self, generated):
        """The reasoning beside each limit is why anybody can review this."""
        body = generated.read_text()
        assert "SET EARLY AND GENEROUSLY" in body
        assert "could not resize shared memory segment" in body

    def test_it_REFUSES_a_silent_no_op(self, tmp_path, stripper):
        """A file with no `cpus:` means the pattern stopped matching or the
        canonical file changed. Producing an identical copy and reporting
        success would hide both."""
        src = tmp_path / "c.yml"
        src.write_text("services:\n  a:\n    mem_limit: 1g\n")
        r = subprocess.run([sys.executable, str(STRIP), str(src),
                            str(tmp_path / "out.yml")],
                           capture_output=True, text=True)
        assert r.returncode == 1
        assert "no `cpus:` line was found" in r.stderr
        assert not (tmp_path / "out.yml").exists()

    def test_it_leaves_deploy_resources_alone(self, tmp_path, stripper):
        """`deploy.resources.limits.cpus` is a different key with different
        semantics — swarm-only, ignored by `docker compose up` — and is not
        what the daemon refused on."""
        body = ("services:\n  a:\n    cpus: 2.0\n    deploy:\n"
                "      resources:\n        limits:\n          cpus: '3'\n")
        out, removed = stripper.strip(body)
        assert removed == ["    cpus: 2.0"]
        assert "cpus: '3'" in out


class TestTheResolver:
    def test_it_fails_toward_the_CANONICAL_file(self, tmp_path):
        """An unprobed host keeps its declared ceilings. Guessing UNSUPPORTED
        would silently drop every CPU limit on a host that can hold them; the
        other way round the failure is a loud daemon refusal.

        A STUB docker that exits non-zero, rather than an empty PATH — the
        first version emptied PATH and removed `bash` along with it, so the
        test failed for a reason unrelated to what it checks."""
        stub = tmp_path / "docker"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
        env = dict(os.environ, PATH=f"{tmp_path}:{os.environ.get('PATH', '')}")
        r = subprocess.run(["bash", str(RESOLVER)], capture_output=True,
                           text=True, env=env, cwd=str(REPO))
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "-f docker-compose.sentinel.yml", r.stdout

    def test_the_force_switch_skips_the_probe(self):
        r = subprocess.run(["bash", str(RESOLVER)], capture_output=True,
                           text=True, cwd=str(REPO),
                           env=dict(os.environ, SENTINEL_FORCE_CPU_LIMITS="1"))
        assert r.stdout.strip() == "-f docker-compose.sentinel.yml"

    def test_it_prints_ONLY_compose_args(self):
        """It is substituted into a command line. A stray diagnostic on stdout
        becomes an argument to `docker compose`."""
        r = subprocess.run(["bash", str(RESOLVER), "--explain"],
                           capture_output=True, text=True, cwd=str(REPO),
                           env=dict(os.environ, SENTINEL_FORCE_CPU_LIMITS="1"))
        assert r.stdout.strip().startswith("-f ")
        assert "\n" not in r.stdout.strip()

    @pytest.mark.parametrize("entry", ["Makefile", "scripts/sentinel-certify.sh",
                                       "scripts/sentinel-measure.sh"])
    def test_every_entry_point_uses_it(self, entry):
        """A hardcoded `-f docker-compose.sentinel.yml` anywhere reintroduces
        the failure for that command alone, which is worse than having it
        everywhere — it works until the one path you did not change."""
        body = (REPO / entry).read_text()
        assert "sentinel-compose.sh" in body, f"{entry} bypasses the resolver"
        code = [l for l in body.splitlines()
                if not l.strip().startswith("#") and "compose" in l.lower()]
        hard = [l for l in code
                if "-f docker-compose.sentinel.yml" in l
                and "sentinel-compose.sh" not in l]
        assert not hard, hard


class TestTheHarnessDoesNotClaimACpuEnvelope:
    """#15 must not report a CPU envelope where the kernel cannot enforce one.

    CPU is still MEASURED — peak percent per container is real and useful, and
    on two 1.6GHz Celeron cores it is the number that will explain the seed's
    wall time. What it is not is BOUNDED, and the artefact has to say which.
    """

    def body(self) -> str:
        return MEASURE.read_text()

    def test_the_verdicts_are_SEPARATE(self):
        """One summary word for both limits would either overclaim CPU or
        discard a real memory measurement."""
        body = self.body()
        for field in ("cpu_limit_enforcement", "cpu_verdict", "memory_verdict"):
            assert field in body, field

    def test_UNSUPPORTED_is_never_PASS(self):
        body = self.body()
        assert 'cpu_verdict": "PASS" if cpu_enforced' in body
        assert "UNSUPPORTED" in body

    def test_the_peak_is_still_RECORDED_when_unbounded(self):
        """Refusing to report a number that was measured would be the opposite
        error: the CPU figure is exactly what explains a nine-hour seed."""
        assert "peak_cpu_pct" in self.body()
        assert "cpu_bounded" in self.body()

    def test_an_UNENFORCED_memory_limit_is_not_a_pass_either(self):
        assert "UNENFORCED" in self.body()

    def test_it_probes_BEFORE_it_measures(self):
        """A measurement taken against limits nobody applied is not an
        envelope, and discovering that afterwards wastes the run."""
        body = self.body()
        assert body.index("sentinel_host_capabilities.py") < \
            body.index("running: $*")

    def test_the_capability_record_is_SAVED(self):
        """Resource certification is only meaningful for the environment
        actually measured, and 'which limits were in force' is part of it."""
        assert "capabilities-${STAMP}.json" in self.body()

    def test_UNKNOWN_keeps_the_limits_and_only_UNSUPPORTED_strips(self, probe):
        """The inversion this test caught.

        `cpu_limits_usable` first read `== ENFORCED`, so an UNPROBED host — no
        daemon, a `docker` that errors, CI — looked unsupported and would have
        silently dropped every CPU ceiling on a machine that could hold them.
        That is this file's own defect arrived at from the other side. Erring
        the other way costs a loud, self-describing daemon refusal.
        """
        import types

        def usable(info):
            saved, probe.docker_info = probe.docker_info, lambda: info
            try:
                return probe.probe()["cpu_limits_usable"]
            finally:
                probe.docker_info = saved

        assert usable(MODERN) is True             # ENFORCED   -> canonical
        assert usable(SYNOLOGY) is False          # UNSUPPORTED -> strip
        assert usable({}) is True                 # UNKNOWN     -> canonical
        assert usable({"ServerVersion": "1.12"}) is True
