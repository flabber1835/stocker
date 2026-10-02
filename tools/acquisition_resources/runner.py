"""Isolated Docker orchestration; retains evidence for failure as well as success."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

from tools.acquisition_resources.profiles import SPECS
from tools.acquisition_resources.measurement import pairs, qualifies

POSTGRES = "postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
GIB = 1024 ** 3


def command(*args, timeout=60, check=True):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("command failed: " + str(args[:3]) + ": " + result.stderr[-1000:])
    return result.stdout.strip()


def inspect(name):
    return json.loads(command("docker", "inspect", name))[0]


def database_memory(name):
    raw = command("docker", "exec", name, "sh", "-c",
        "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak "
        "/sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.stat")
    lines = raw.splitlines()
    current, peak, limit = map(int, lines[:3])
    values = pairs("\n".join(lines[3:]))
    return dict(current=current, peak=peak, limit=limit,
                working=max(0, current-values["inactive_file"]), anon=values["anon"],
                shmem=values["shmem"], file=values["file"],
                active_file=values["active_file"],
                inactive_file=values["inactive_file"],
                slab_unreclaimable=values["slab_unreclaimable"],
                kernel_stack=values["kernel_stack"],
                pagetables=values["pagetables"],
                events={k: values[k] for k in ("oom", "oom_kill")})


def ready(name, args, deadline):
    while time.monotonic() < deadline:
        out = subprocess.run(["docker", "exec", name, *args], capture_output=True, timeout=20)
        if out.returncode == 0:
            return
        if not inspect(name)["State"]["Running"]:
            raise RuntimeError(name + " exited before readiness")
        time.sleep(1)
    raise TimeoutError(name + " readiness deadline")


def run(args):
    prefix = "acq-resource-" + uuid.uuid4().hex[:12]
    network = prefix + "-net"
    db, provider, worker = [prefix + "-" + role for role in ("db", "provider", "worker")]
    volumes = [prefix + "-db", prefix + "-cache"]
    report = dict(schema="sentinel.local-acquisition-resources/1", profile=args.profile,
                  scope="SYNTHETIC_HTTP_REFERENCES_AND_SQL_STAGING", verdict="FAIL",
                  excluded=["candidate building", "strategy", "GO", "broker", "NAS qualification"],
                  worker_limit=args.worker_memory_mib * 1024**2, database_limit=GIB,
                  worker_cpus=args.worker_cpus,
                  resources=dict(network=network, volumes=volumes,
                                 containers=dict(worker=worker, provider=provider, database=db)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.deadline_seconds
    samples = []
    cleanup_errors = []
    created_volumes = []
    created_network = False
    try:
        report["image"] = json.loads(command("docker", "image", "inspect", args.image))[0]["Id"]
        image = report["image"]  # A concurrent tag rebuild cannot change this run.
        report["postgres_image"] = POSTGRES
        command("docker", "network", "create", "--internal", network)
        created_network = True
        for volume in volumes:
            command("docker", "volume", "create", volume)
            created_volumes.append(volume)
        command("docker", "run", "-d", "--name", db, "--network", network, "--network-alias", "database",
                "--memory", str(GIB), "--memory-swap", str(GIB), "--shm-size", "1g", "--cpus", "1.5",
                "--mount", f"type=volume,src={volumes[0]},dst=/var/lib/postgresql/data",
                "-e", "POSTGRES_PASSWORD=resource-fixture-only", POSTGRES)
        common = ["--network", network, "--entrypoint", "python", "-w", "/qualification",
                  "-e", "PYTHONPATH=/qualification:/qualification/shared:/qualification/scripts",
                  "-e", "SENTINEL_REPO_ROOT=/qualification"]
        command("docker", "run", "-d", "--name", provider, "--network-alias", "provider", *common,
                "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", image,
                "-m", "tools.acquisition_resources.fixtures", "--profile", args.profile)
        ready(db, ["pg_isready", "-h", "127.0.0.1", "-U", "postgres"], deadline)
        ready(provider, ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/metrics',timeout=5).read()"], deadline)
        print(json.dumps(dict(event="fixture_ready", profile=args.profile)), flush=True)
        limit = report["worker_limit"]
        command("docker", "run", "-d", "--name", worker, *common,
                "--memory", str(limit), "--memory-swap", str(limit), "--cpus", str(args.worker_cpus),
                "--mount", f"type=volume,src={volumes[1]},dst=/var/lib/sentinel",
                "-e", "SENTINEL_STATE_DIR=/var/lib/sentinel",
                "-e", "NDL_BASE_URL=http://provider:8080/api/v3/datatables/SHARADAR",
                "-e", "SHARADAR_ALLOW_INSECURE_BASE_URL=1", "-e", "SHARADAR_API_KEY=resource-fixture-only",
                "-e", "RESOURCE_DSN=postgresql://postgres:resource-fixture-only@database/postgres",
                image, "-u", "-m", "tools.acquisition_resources.worker", "--profile", args.profile,
                "--cycles", str(args.cycles))
        report["limits"] = {}
        for role, name, expected in (("worker", worker, limit), ("database", db, GIB)):
            config = inspect(name)["HostConfig"]
            report["limits"][role] = {k: config[k] for k in ("Memory", "MemorySwap", "NanoCpus", "ShmSize")}
            assert config["Memory"] == config["MemorySwap"] == expected
            assert config["NanoCpus"] == int((args.worker_cpus if role == "worker" else 1.5) * 10**9)
        last_progress = 0
        while inspect(worker)["State"]["Running"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("resource profile deadline exceeded")
            samples.append(database_memory(db))
            if time.monotonic() - last_progress > 30:
                progress = subprocess.run(["docker", "logs", "--tail", "5", worker],
                                          capture_output=True, text=True, timeout=30)
                log = progress.stdout + progress.stderr
                print(json.dumps(dict(event="working", profile=args.profile, tail=log[-1500:])), flush=True)
                last_progress = time.monotonic()
            time.sleep(1)
        report["worker_state"] = inspect(worker)["State"]
        db_final = database_memory(db)
        samples.append(db_final)
        measured_db = dict(cgroup=db_final, samples=len(samples),
                           working_peak_bytes=max(s["working"] for s in samples),
                           anon_peak_bytes=max(s["anon"] for s in samples))
        report["database_measurement"] = measured_db
        logs = command("docker", "logs", worker)
        results = [json.loads(line) for line in logs.splitlines() if line.startswith('{"')]
        complete = [item for item in results if item.get("event") == "result"]
        report["phases"] = [item for item in results if item.get("event") == "phase_end"]
        assert report["worker_state"]["ExitCode"] == 0, "worker did not complete"
        assert not report["worker_state"]["OOMKilled"], "worker was OOM-killed"
        assert len(complete) == 1, "missing complete measurement"
        report["worker"] = complete[0]
        assert qualifies(complete[0]["measurement"], limit), "worker lacks measured headroom"
        assert qualifies(measured_db, GIB), "database lacks measured headroom"
        report["verdict"] = "PASS_WITHIN_SYNTHETIC_PROFILE"
    except (Exception, KeyboardInterrupt) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        # Save the primary result before any fallible evidence/cleanup operation.
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        for role, name in (("worker", worker), ("provider", provider), ("database", db)):
            try:
                raw = command("docker", "inspect", name, check=False)
                if raw and raw != "[]":
                    report[role + "_final_state"] = json.loads(raw)[0]["State"]
                    try:
                        log = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=30)
                        if log.returncode:
                            raise RuntimeError("could not retain " + role + " logs")
                        args.output.with_suffix("." + role + ".log").write_text(log.stdout + log.stderr, encoding="utf-8")
                    finally:
                        command("docker", "rm", "-f", name)
            except Exception as exc:
                cleanup_errors.append(f"{name}: {type(exc).__name__}: {exc}")
        for kind, name in [("volume", v) for v in created_volumes] + ([("network", network)] if created_network else []):
            try:
                command("docker", kind, "rm", name)
            except Exception as exc:
                cleanup_errors.append(f"{name}: {type(exc).__name__}: {exc}")
        if cleanup_errors:
            report["cleanup_errors"] = cleanup_errors
            report["verdict"] = "FAIL"
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(dict(event="complete", verdict=report["verdict"], output=str(args.output))), flush=True)
    return report["verdict"] != "PASS_WITHIN_SYNTHETIC_PROFILE"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--profile", choices=SPECS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-memory-mib", type=int, default=4096)
    parser.add_argument("--worker-cpus", type=int, choices=(1, 2), default=2)
    parser.add_argument("--deadline-seconds", type=int, default=1800)
    parser.add_argument("--cycles", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if not 128 <= args.worker_memory_mib <= 4096 or not 60 <= args.deadline_seconds <= 3600:
        parser.error("resource limits must stay within the local qualification envelope")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
