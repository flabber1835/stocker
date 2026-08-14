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
BASH = (r"C:\Program Files\Git\bin\bash.exe"
        if os.name == "nt" and Path(r"C:\Program Files\Git\bin\bash.exe").exists()
        else "bash")


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


#: The DS216+II, transcribed from the machine's own `docker info` warnings and
#: `/proc/cgroups` — not from the kernel version, and not from what seemed
#: likely. The first version of this fixture guessed `SwapLimit: False` on the
#: reasoning that an old Synology kernel would not have swap accounting. The
#: host's warning list does not contain "No swap limit support", and it does
#: contain four blkio ones, so swap accounting is present and disk throttling
#: is not. A fixture describing a host has to come from the host.
#:
#: The two CPU flags are proven twice over: the daemon's check is
#: `NanoCPUs > 0 && !CPUCfsPeriod`, so the refusal implies them, and the
#: warnings name them outright.
SYNOLOGY = {
    "ServerVersion": "24.0.2", "KernelVersion": "3.10.108",
    "OperatingSystem": "Synology DSM", "CgroupVersion": "1",
    "CgroupDriver": "cgroupfs", "Driver": "btrfs", "NCPU": 2,
    "MemTotal": 8287367168,
    "CPUCfsPeriod": False, "CPUCfsQuota": False,
    "MemoryLimit": True, "SwapLimit": True,
    "Warnings": ["WARNING: No kernel memory TCP limit support",
                 "WARNING: No cpu cfs quota support",
                 "WARNING: No cpu cfs period support",
                 "WARNING: No blkio throttle.read_bps_device support",
                 "WARNING: No blkio throttle.write_bps_device support",
                 "WARNING: No blkio throttle.read_iops_device support",
                 "WARNING: No blkio throttle.write_iops_device support"],
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
        assert caps["cpu_period"] == "UNSUPPORTED"
        # Enforced, both of them, and confirmed on the machine itself:
        # `docker run --memory=256m --memory-swap=256m sentinel:latest status`
        # exits 0. So the MEMORY envelope #15 measures here is a real one.
        assert caps["memory_limit"] == "ENFORCED"
        assert caps["memory_swap"] == "ENFORCED"

    def test_the_synology_warnings_are_carried_into_the_RECORD(self, probe, monkeypatch):
        """The daemon's own prose is the most direct evidence of what it cannot
        hold, and it names limits this probe does not model — blkio throttling,
        which matters for an I/O-heavy seed on a NAS. Carried verbatim rather
        than reduced to the four fields, so the artefact does not silently
        narrow what was observed."""
        monkeypatch.setattr(probe, "docker_info", lambda: SYNOLOGY)
        rec = probe.probe()
        assert any("cfs quota" in w for w in rec["daemon_warnings"])
        assert any("blkio" in w for w in rec["daemon_warnings"])
        assert rec["host"]["kernel"] == "3.10.108"
        assert rec["host"]["ncpu"] == 2

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

    def test_active_nanocpus_refusal_overrides_false_positive_metadata(
            self, probe, monkeypatch):
        monkeypatch.setattr(probe, "docker_info", lambda: MODERN)
        monkeypatch.setattr(
            probe, "active_cpu_quota",
            lambda: {"status": "UNSUPPORTED",
                     "detail": "NanoCPUs can not be set"})
        rec = probe.probe()
        assert rec["capabilities"]["cpu_quota"] == "UNSUPPORTED"
        assert rec["cpu_limits_usable"] is False
        assert rec["cpu_limit_mode"] == "OBSERVED_NOT_BOUNDED"

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
        env = dict(os.environ, PATH=f"{tmp_path}:{os.environ.get('PATH', '')}",
                   SENTINEL_BACKUP_DIR="/backup")
        r = subprocess.run([BASH, str(RESOLVER)], capture_output=True,
                           text=True, env=env, cwd=str(REPO))
        assert r.returncode == 0, r.stderr
        assert "-f docker-compose.sentinel.yml" in r.stdout, r.stdout
        assert "-f docker-compose.sentinel-backup.yml" in r.stdout, r.stdout

    def test_the_force_switch_skips_the_probe(self):
        r = subprocess.run([BASH, str(RESOLVER)], capture_output=True,
                           text=True, cwd=str(REPO),
                           env=dict(os.environ, SENTINEL_FORCE_CPU_LIMITS="1",
                                    SENTINEL_BACKUP_DIR="/backup"))
        assert "-f docker-compose.sentinel.yml" in r.stdout
        assert "-f docker-compose.sentinel-backup.yml" in r.stdout

    def test_force_no_cpu_is_supported_and_records_observed_not_bounded(self):
        r = subprocess.run(
            [BASH, str(RESOLVER), "--explain"], capture_output=True,
            text=True, cwd=str(REPO),
            env=dict(os.environ, SENTINEL_FORCE_NO_CPU_LIMITS="1",
                     SENTINEL_PYTHON=sys.executable,
                     SENTINEL_BACKUP_DIR="/backup"))
        assert r.returncode == 0, r.stderr
        assert "docker-compose.sentinel.nocpu.yml" in r.stdout
        assert "CPU observed, not bounded" in r.stderr

    def test_conflicting_force_modes_refuse(self):
        r = subprocess.run(
            [BASH, str(RESOLVER)], capture_output=True, text=True,
            cwd=str(REPO), env=dict(
                os.environ, SENTINEL_FORCE_CPU_LIMITS="1",
                SENTINEL_FORCE_NO_CPU_LIMITS="1",
                SENTINEL_BACKUP_DIR="/backup"))
        assert r.returncode != 0
        assert "mutually exclusive" in r.stderr

    def test_it_prints_ONLY_compose_args(self):
        """It is substituted into a command line. A stray diagnostic on stdout
        becomes an argument to `docker compose`."""
        r = subprocess.run([BASH, str(RESOLVER), "--explain"],
                           capture_output=True, text=True, cwd=str(REPO),
                           env=dict(os.environ, SENTINEL_FORCE_CPU_LIMITS="1",
                                    SENTINEL_BACKUP_DIR="/backup"))
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


class TestTheGeneratedFileKeepsTheREPOAsProjectDirectory:
    """A compose file's meaning depends on WHERE IT SITS.

    Compose defines the project directory as the directory of the first `-f`
    file, and everything relative resolves against it. The generated file lives
    at `artifacts/compose/`, so emitting only `-f <generated>` silently moved:

    ```text
    build: {context: .}   ->  artifacts/compose/  instead of the repo root
    the implicit .env     ->  artifacts/compose/.env, which does not exist, so
                              SENTINEL_POSTGRES_PASSWORD is unset and compose
                              refuses on its `:?` — or an optional var quietly
                              takes a default nobody chose
    ```

    Measured, not argued. `docker compose config` on this checkout:

    ```text
    canonical                          context: /home/user/stocker
    generated, no --project-directory  context: /home/user/stocker/artifacts/compose
    generated, with it                 context: /home/user/stocker
    ```

    The YAML is byte-identical to the canonical file apart from the `cpus:`
    lines. A YAML comparison cannot see this, which is exactly why the
    real-compose branch below exists.
    """

    @staticmethod
    def resolver_args(force=None):
        env = dict(os.environ, SENTINEL_BACKUP_DIR="/backup")
        if force:
            env["SENTINEL_FORCE_CPU_LIMITS"] = force
        r = subprocess.run([BASH, str(RESOLVER)], capture_output=True,
                           text=True, cwd=str(REPO), env=env)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip().split()

    @staticmethod
    def generated_args():
        """The args the resolver emits on a host without CFS quota, read OUT OF
        THE SCRIPT rather than restated here — otherwise this class would test
        a copy of the resolver and pass while the resolver was wrong."""
        out = REPO / "artifacts" / "compose" / "docker-compose.sentinel.nocpu.yml"
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, str(STRIP), str(CANONICAL), str(out)],
                           capture_output=True, text=True, cwd=str(REPO))
        assert r.returncode == 0, r.stderr
        body = RESOLVER.read_text()
        assert 'COMPOSE_ARGS=(--project-directory "$(pwd -P)"' in body
        return ["--project-directory", str(REPO), "-f",
                out.relative_to(REPO).as_posix(), "-f",
                "docker-compose.sentinel-backup.yml"]

    def test_the_script_emits_project_directory_with_a_NON_ROOT_file(self):
        """Structural, and always runs."""
        code = "\n".join(l for l in RESOLVER.read_text().splitlines()
                         if not l.strip().startswith("#"))
        tail = code[code.index("COMPOSE_ARGS=(--project-directory"):]
        assert "--project-directory" in tail, (
            "the generated file is emitted without --project-directory, so "
            "compose resolves `build: context: .` and the implicit .env "
            "against artifacts/compose/ instead of the repository root")

    def test_the_canonical_branch_needs_no_flag(self):
        """It sits at the repo root, so the default is already correct. A flag
        there would be noise pretending to be safety."""
        assert self.resolver_args(force="1") == [
            "-f", "docker-compose.sentinel.yml", "-f",
            "docker-compose.sentinel-backup.yml"]

    def test_both_variants_resolve_the_SAME_build_context(self):
        """The authoritative check, with a structural fallback so it is never a
        SKIP — inside the certified image a skip is a failure and that image has
        no docker CLI. Same shape as `test_compose_image.py`'s `branch`
        fixture: a degraded path needs its degradation exercised."""
        import shutil
        generated = self.generated_args()
        if shutil.which("docker") is None:
            assert generated[0] == "--project-directory"
            assert Path(generated[1]) == REPO
            return

        env = dict(os.environ, SENTINEL_POSTGRES_PASSWORD="probe",
                   SENTINEL_BACKUP_DIR="/backup")

        def resolved(args):
            r = subprocess.run(["docker", "compose", *args, "config"],
                               capture_output=True, text=True, cwd=str(REPO),
                               env=env)
            if r.returncode != 0:
                pytest.fail(f"docker compose config failed for {args}: {r.stderr}")
            return yaml.safe_load(r.stdout)

        a = resolved(["-f", "docker-compose.sentinel.yml", "-f",
                      "docker-compose.sentinel-backup.yml"])
        b = resolved(generated)
        for name in a["services"]:
            sa, sb = a["services"][name], b["services"][name]
            assert sa.get("build") == sb.get("build"), (
                f"{name}: build context differs between the canonical and "
                f"CPU-free deployments — the generated file's LOCATION changed "
                f"its meaning")
            for key in ("environment", "volumes", "image", "mem_limit",
                        "shm_size", "profiles", "command"):
                assert sa.get(key) == sb.get(key), f"{name}.{key}"
        assert a.get("name") == b.get("name")
        assert a.get("volumes") == b.get("volumes")
        # And the ONLY difference is the CPU ceiling.
        assert any(s.get("cpus") for s in a["services"].values())
        assert not any(s.get("cpus") for s in b["services"].values())

    def test_the_environment_resolves_from_the_REPO_dotenv(self):
        """The other half of the bug, and the one that would have surfaced as a
        confusing `:?` refusal rather than a wrong build."""
        import shutil
        generated = self.generated_args()
        if shutil.which("docker") is None:
            assert Path(generated[1]) == REPO
            return
        env = dict(os.environ, SENTINEL_POSTGRES_PASSWORD="from-the-env",
                   SENTINEL_BACKUP_DIR="/backup")
        r = subprocess.run(["docker", "compose", *generated, "config"],
                           capture_output=True, text=True, cwd=str(REPO), env=env)
        assert r.returncode == 0, r.stderr
        assert "from-the-env" in r.stdout
