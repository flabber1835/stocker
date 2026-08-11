#!/usr/bin/env python3
"""What resource limits can THIS host actually enforce?

## Why this exists

The first real #15 run, on a Synology DS216+II:

```text
Error response from daemon: NanoCPUs can not be set, as your kernel does not
support CPU CFS scheduler or the cgroup is not mounted
```

Kernel 3.10.108, cgroup v1, Docker 24.0.2. `docker-compose.sentinel.yml`
declares `cpus:` on all three services and the daemon refuses before the
container is created, so nothing starts at all.

The daemon REFUSING is the right behaviour and the reason this is a probe
rather than a patch. A CPU ceiling that the kernel silently ignored would be
the exact failure `docs/sentinel-deployment.md` §11 names — a setting believed
to be in force, that is not. So the question to answer is not "how do I make
the error go away" but "which of the declared limits does this host enforce",
and the answer belongs in the certification record.

## What it reports

```text
cpu_quota      ENFORCED    the daemon accepts --cpus
               UNSUPPORTED no CFS quota; CPU cannot be BOUNDED here, only
                           observed. #15 must not claim a CPU envelope
memory_limit   ENFORCED / UNSUPPORTED   mem_limit
memory_swap    ENFORCED / UNSUPPORTED   swap accounting; absent on many
                                        distros and NOT fatal
```

Read from `docker info`, which is the daemon's own account of its host, rather
than inferred from the kernel version — a version string is a proxy and this
is the fact itself.

Exit code is 0 whenever the probe RAN. An unenforceable limit is a finding to
record, not an error: refusing here would strand the very host the probe exists
to characterise.
"""
from __future__ import annotations

import json
import subprocess
import sys

MIN_PYTHON = (3, 7)
if sys.version_info < MIN_PYTHON:                       # pragma: no cover
    sys.stderr.write("REFUSED: needs Python 3.7+; this is %d.%d\n"
                     % sys.version_info[:2])
    raise SystemExit(2)

ENFORCED = "ENFORCED"
UNSUPPORTED = "UNSUPPORTED"
UNKNOWN = "UNKNOWN"

#: `docker info` field -> the capability it decides. Names are the daemon's,
#: not ours, so they stay comparable to what an operator sees.
_FIELDS = {
    "cpu_quota": "CPUCfsQuota",
    "cpu_period": "CPUCfsPeriod",
    "memory_limit": "MemoryLimit",
    "memory_swap": "SwapLimit",
}


def docker_info() -> dict:
    """The daemon's own report, or {} when there is no daemon.

    `{{json .}}` rather than individual templates: one call, and a field this
    file does not yet read is still captured in the artefact.
    """
    try:
        out = subprocess.run(["docker", "info", "--format", "{{json .}}"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {}


def classify(info: dict) -> dict:
    """`docker info` -> a capability verdict per limit.

    A MISSING field is UNKNOWN, never ENFORCED. Older daemons omit some of
    these, and defaulting an absent field to "supported" would let a host claim
    an envelope it cannot hold — the same shape as the defect being fixed.
    """
    caps = {}
    for name, field in _FIELDS.items():
        if field not in info:
            caps[name] = UNKNOWN
        else:
            caps[name] = ENFORCED if info[field] else UNSUPPORTED
    # `--cpus` needs BOTH period and quota; the daemon checks them separately
    # and this host has neither. Reported as one verdict because one verdict is
    # what the compose file needs.
    if UNSUPPORTED in (caps["cpu_quota"], caps["cpu_period"]):
        caps["cpu_quota"] = UNSUPPORTED
    return caps


def probe() -> dict:
    info = docker_info()
    caps = classify(info)
    return {
        "probed": bool(info),
        "capabilities": caps,
        # ONLY a positive UNSUPPORTED strips the limits. UNKNOWN keeps them.
        #
        # The first version said `== ENFORCED`, which made an UNPROBED host —
        # no daemon, a `docker` that errors, CI — look unsupported and silently
        # drop every CPU ceiling on a machine that could hold them. That is the
        # defect this file exists to prevent, arrived at from the other side.
        # Erring the other way costs a loud daemon refusal, which is
        # recoverable and self-describing.
        "cpu_limits_usable": caps["cpu_quota"] != UNSUPPORTED,
        "host": {
            "kernel": info.get("KernelVersion"),
            "operating_system": info.get("OperatingSystem"),
            "cgroup_version": info.get("CgroupVersion"),
            "cgroup_driver": info.get("CgroupDriver"),
            "storage_driver": info.get("Driver"),
            "server_version": info.get("ServerVersion"),
            "ncpu": info.get("NCPU"),
            "mem_total": info.get("MemTotal"),
        },
        # The daemon's own warnings name unenforceable limits in prose. Kept
        # verbatim: they are the most direct evidence for the record.
        "daemon_warnings": info.get("Warnings") or [],
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable only")
    a = ap.parse_args(argv)

    rec = probe()
    if a.json:
        print(json.dumps(rec, indent=2, sort_keys=True))
        return 0

    if not rec["probed"]:
        print("no docker daemon reachable — capabilities UNKNOWN")
    print(json.dumps(rec, indent=2, sort_keys=True))
    if not rec["cpu_limits_usable"] and rec["probed"]:
        print("\n  CPU quota is not enforceable on this host. `cpus:` in a "
              "compose file\n  makes the daemon REFUSE to create the "
              "container. Use scripts/sentinel-compose.sh,\n  which strips "
              "those fields and records the fact — and note that #15 cannot\n "
              " certify a CPU envelope here. CPU can be OBSERVED, not BOUNDED.")
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
