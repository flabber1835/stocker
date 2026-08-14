#!/usr/bin/env python3
"""Delete `cpus:` from a compose file. Nothing else.

Textual, line-by-line, rather than yaml.load + yaml.dump. A round-trip through
PyYAML would rewrite the whole file — reordering keys, dropping every comment,
and re-quoting scalars — and this repository's compose file is more comment
than configuration, with the reasoning for each limit written beside it. A
generated deployment nobody can diff against the canonical one is not a
deployment anybody should trust.

So the output is the input with exactly the `cpus:` lines removed, and
`--verify` proves that: the two files must differ only by those lines.

## Why deleting rather than zeroing

The daemon's check is gated on `NanoCPUs > 0`, so `cpus: 0` would also start.
But it survives into `docker compose config`, and a deployment that advertises
a ceiling the kernel cannot hold is the defect being fixed, not a workaround
for it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MIN_PYTHON = (3, 7)
if sys.version_info < MIN_PYTHON:                       # pragma: no cover
    sys.stderr.write("REFUSED: needs Python 3.7+\n")
    raise SystemExit(2)

#: A service-level `cpus:` with a scalar. Deliberately narrow: it will not
#: match `cpus:` nested under `deploy.resources`, which is a different key with
#: different semantics (swarm-only, ignored by `docker compose up`), nor a
#: commented-out line.
CPUS_LINE = re.compile(r"^\s+cpus:\s*[\d.]+\s*$")

#: Preserved, and asserted preserved. This host enforces both, and they are the
#: half that actually protects the machine — 1g on PostgreSQL and the 1gb shm
#: the parallel-scan segments need.
MUST_SURVIVE = ("mem_limit:", "shm_size:")

BANNER = (
    "# ── GENERATED — DO NOT EDIT ──────────────────────────────────────────\n"
    "# scripts/sentinel_strip_cpu_limits.py, from docker-compose.sentinel.yml\n"
    "#\n"
    "# Every `cpus:` line is REMOVED because this host has no CPU CFS quota\n"
    "# (Synology DSM, kernel 3.10, cgroup v1) and the daemon refuses to create\n"
    "# a container that asks for one. mem_limit and shm_size are UNTOUCHED and\n"
    "# still enforced.\n"
    "#\n"
    "# CPU is therefore OBSERVED on this host, not BOUNDED. Finding #15 must\n"
    "# not report a CPU envelope as certified here — see\n"
    "# `scripts/sentinel_host_capabilities.py` and the resource artefact's\n"
    "# cpu_limit_enforcement field.\n"
    "#\n"
    "# Regenerated on every `scripts/sentinel-compose.sh`, so it cannot drift.\n"
    "# ─────────────────────────────────────────────────────────────────────\n"
)


def strip(text: str) -> tuple[str, list[str]]:
    """(output, the removed lines)."""
    kept, removed = [], []
    for line in text.splitlines(keepends=True):
        if CPUS_LINE.match(line.rstrip("\n")):
            removed.append(line.rstrip("\n"))
        else:
            kept.append(line)
    return "".join(kept), removed


def verify(src: str, out: str, removed: list[str]) -> list[str]:
    """Everything that is wrong with the result. Empty is a pass."""
    problems = []
    if not removed:
        problems.append("no `cpus:` line was found — either the canonical file "
                        "stopped declaring them or the pattern no longer "
                        "matches, and a silent no-op is indistinguishable")
    if re.search(r"^\s+cpus:", out, re.M):
        problems.append("a `cpus:` line survived the strip")
    for key in MUST_SURVIVE:
        if src.count(key) != out.count(key):
            problems.append(f"{key} count changed: {src.count(key)} -> "
                            f"{out.count(key)}. Only cpus may be removed")
    # The two files must differ ONLY by the removed lines. Anything else means
    # the rewrite touched configuration it was not asked to touch.
    expect = [l for l in src.splitlines() if l not in removed]
    got = [l for l in out.splitlines() if not l.startswith("#")
           or l in src.splitlines()]
    banner_lines = BANNER.count("\n")
    if got[banner_lines:] != expect and out.splitlines()[banner_lines:] != expect:
        problems.append("the output differs from the input by more than the "
                        "`cpus:` lines")
    return problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or len(argv) > 2:
        sys.stderr.write("usage: sentinel_strip_cpu_limits.py <src> [<dst>]\n")
        return 2
    src_path = Path(argv[0])
    text = src_path.read_text(encoding="utf-8")
    out, removed = strip(text)
    out = BANNER + out

    problems = verify(text, out, removed)
    if problems:
        for p in problems:
            sys.stderr.write("REFUSED: %s\n" % p)
        return 1

    if len(argv) == 2:
        dst = Path(argv[1])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(out, encoding="utf-8")
        sys.stderr.write("  stripped %d `cpus:` line(s) -> %s\n"
                         % (len(removed), dst))
        for r in removed:
            sys.stderr.write("    removed:%s\n" % r)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
