#!/usr/bin/env bash
# Measure ONE phase's resource envelope, and say whether the declared limits
# have headroom.
#
# ## Why this is a script and not a session
#
# `docker-compose.sentinel.yml` says it plainly at `mem_limit: 1g`:
#
#     SET EARLY AND GENEROUSLY, tightened to the measured envelope later. The
#     value is not the point yet; ENFORCEMENT is.
#
# "Later" is finding #15, and the measurement has to be an ARTEFACT rather than
# a number someone read off a terminal. A limit tightened from a remembered
# figure is a limit nobody can re-derive when the phase gets slower, and the
# failure it produces is an OOM kill in the middle of a seed — which, as the 8b
# incident showed, looks like a silent exit and gets INFERRED rather than
# measured.
#
# ## What it samples, and why each one is here
#
# ```text
# docker stats --no-stream   PEAK RSS and CPU per container. --no-stream on a
#                            timer, NOT the streaming form: streaming redraws
#                            with control codes, so a tee'd log is unreadable
#                            and unparseable, and the first frame's CPU figure
#                            is meaningless anyway
# /proc/meminfo              host MemAvailable. A container inside its limit on
#                            a host that is swapping is not a passing envelope
# pg_stat_database           temp_bytes. The corpus sort spills, and a spill is
#                            invisible to `docker stats` — it is disk, and it is
#                            the thing the staging table was built to bound
# du on the data volume      disk growth across the phase
# docker inspect             OOMKilled and RestartCount. A container that was
#                            killed and restarted reports healthy afterwards;
#                            peak RSS says nothing about it
# ```
#
# Wall time is recorded because a phase that fits in 1g by taking six hours has
# not passed either.
#
# ## Usage
#
#     scripts/sentinel-measure.sh seed  -- sentinel feed-seed --date-from 1998-01-01
#     scripts/sentinel-measure.sh daily -- sentinel feed-daily
#     scripts/sentinel-measure.sh plan  -- sentinel prepare-paper-plan \
#       --through <YYYY-MM-DD> --warmup-sessions 252 \
#       --expect-account <PAPER_ACCOUNT_ID>
#     scripts/sentinel-measure.sh ready -- sentinel check-data
#
# The phase name is free text and only labels the artefacts. Everything after
# `--` runs through `docker compose run -T --name <phase>`, so it is measured
# inside the limits it is being measured against — and NOT with `--rm`, so
# its final `.State` can be inspected before it is removed.
#
# `prepare-paper-plan` is the production catch-up entry point. It advances the
# canonical state and adopts one durable current plan under the writer and
# publication locks. It performs the required paper-broker reads but has no
# broker mutation operation; migration and submission remain separate commands.
set -euo pipefail

cd "$(dirname "$0")/.."

# THE RESOLVER decides which compose file this host can actually run. On a
# Synology with no CPU CFS quota the canonical one makes the daemon refuse
# before the container exists, so measuring anything requires the generated,
# cpus-free deployment. Never hardcode `-f docker-compose.sentinel.yml` here:
# the whole point is that the file differs by host and the artefact says so.
COMPOSE="bash $(dirname "$0")/sentinel-compose.sh --run"
ART="artifacts/envelope"
INTERVAL="${SENTINEL_SAMPLE_SECONDS:-5}"
DB_SERVICE="sentinel-postgres"

die() { printf '\n\033[31mMEASUREMENT FAILED\033[0m  %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[36m── %s\033[0m\n' "$*"; }

PHASE="${1:-}"
[ -n "${PHASE}" ] || die "usage: $0 <phase-name> -- <command...>"
shift
[ "${1:-}" = "--" ] || die "expected \`--\` before the command; got '${1:-}'"
shift
[ "$#" -gt 0 ] || die "no command given after \`--\`"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${ART}"
SAMPLES="${ART}/${PHASE}-${STAMP}.csv"
REPORT="${ART}/${PHASE}-${STAMP}.json"

# ── the declared limits, READ from compose ───────────────────────────────────
# Never transcribed. The whole point is to compare the measurement against what
# the deployment actually enforces, and a hardcoded copy of `1g` here would
# keep reporting headroom after someone changed the file.
# WHAT THIS HOST CAN ENFORCE, before what it was asked to enforce. A CPU
# ceiling the kernel cannot hold is not a limit with headroom — it is not a
# limit, and #15 must not report one as certified.
step "probing what this host can ENFORCE"
CAPS_JSON="$(python3 scripts/sentinel_host_capabilities.py --json)" \
  || die "the host capability probe failed; the envelope would describe limits
  that may not be in force"
echo "${CAPS_JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin);
print("  cpu_quota    :", d["capabilities"]["cpu_quota"]);
print("  memory_limit :", d["capabilities"]["memory_limit"]);
print("  kernel       :", d["host"]["kernel"], "cgroup", d["host"]["cgroup_version"])'
mkdir -p "${ART}"
echo "${CAPS_JSON}" > "${ART}/capabilities-${STAMP}.json"

step "reading the declared limits from docker-compose.sentinel.yml"
LIMITS_JSON="$(python3 - <<'PY'
import json, re, sys, yaml, pathlib
c = yaml.safe_load(pathlib.Path("docker-compose.sentinel.yml").read_text())
_SCALE = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}
def to_bytes(v):
    """`1g`, `512m`, `1gb` -> bytes. Compose's own short form, binary units."""
    if v is None: return None
    m = re.fullmatch(r"(?i)\s*([\d.]+)\s*([kmgt]?)b?\s*", str(v))
    return None if not m else int(float(m.group(1))
                                  * 1024 ** _SCALE[m.group(2).lower()])
out = {}
for name, svc in (c.get("services") or {}).items():
    out[name] = {"mem_limit": to_bytes(svc.get("mem_limit")),
                 "cpus": svc.get("cpus"),
                 "shm_size": to_bytes(svc.get("shm_size"))}
print(json.dumps(out))
PY
)" || die "could not read the declared limits — the comparison would be against nothing"
echo "${LIMITS_JSON}" | python3 -m json.tool

# ── the database has to be up BEFORE the baseline ────────────────────────────
step "bringing up ${DB_SERVICE}"
${COMPOSE} up -d "${DB_SERVICE}" >/dev/null
for _ in $(seq 1 60); do
  ${COMPOSE} exec -T "${DB_SERVICE}" pg_isready -U sentinel -h 127.0.0.1 \
    >/dev/null 2>&1 && break
  sleep 2
done
${COMPOSE} exec -T "${DB_SERVICE}" pg_isready -U sentinel -h 127.0.0.1 >/dev/null \
  || die "${DB_SERVICE} never became ready"

psql_scalar() {
  ${COMPOSE} exec -T "${DB_SERVICE}" psql -U sentinel -d sentinel -tAq \
    -v ON_ERROR_STOP=1 -c "$1" 2>/dev/null | tr -d '[:space:]'
}

TEMP_BEFORE="$(psql_scalar "SELECT COALESCE(temp_bytes,0) FROM pg_stat_database WHERE datname='sentinel'")"
DISK_BEFORE="$(${COMPOSE} exec -T "${DB_SERVICE}" du -sb /var/lib/postgresql/data 2>/dev/null | cut -f1)"
: "${TEMP_BEFORE:=0}" "${DISK_BEFORE:=0}"
echo "  temp_bytes before : ${TEMP_BEFORE}"
echo "  data volume before: ${DISK_BEFORE}"

# ── the sampler ──────────────────────────────────────────────────────────────
# A plain loop rather than `docker stats` streaming, so every row is a complete
# line with its own timestamp and the file is still valid CSV if the run is
# interrupted.
printf 'iso8601,container,mem_bytes,mem_limit_bytes,cpu_pct,host_mem_available_bytes\n' \
  > "${SAMPLES}"

# One frame: every sentinel container's memory and CPU, plus the host's
# MemAvailable, as CSV rows sharing a timestamp. Environment rather than argv
# for the two shell-side values, so a stray character in a container name
# cannot become part of the Python.
sample_once() {
  local now avail
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  avail="$(awk '/^MemAvailable:/ {print $2 * 1024}' /proc/meminfo 2>/dev/null || echo 0)"
  docker stats --no-stream --format '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}' 2>/dev/null \
    | SAMPLE_NOW="${now}" SAMPLE_AVAIL="${avail}" python3 -c '
import os, re, sys
now, avail = os.environ["SAMPLE_NOW"], os.environ["SAMPLE_AVAIL"]
def b(tok):
    m = re.fullmatch(r"([\d.]+)\s*([KMGT]?i?B)", tok.strip())
    if not m: return ""
    u = {"B":1,"KiB":1024,"MiB":1024**2,"GiB":1024**3,"TiB":1024**4,
         "KB":1000,"MB":1000**2,"GB":1000**3,"TB":1000**4}
    return str(int(float(m.group(1)) * u.get(m.group(2), 1)))
for line in sys.stdin:
    parts = line.rstrip("\n").split("|")
    if len(parts) != 3: continue
    name, mem, cpu = parts
    if not name.startswith("sentinel"): continue
    used, lim = (mem.split("/") + [""])[:2]
    print(",".join([now, name, b(used), b(lim), cpu.rstrip("%").strip(), avail]))
' >> "${SAMPLES}"
}

sampler_loop() { while :; do sample_once; sleep "${INTERVAL}"; done; }

step "sampling every ${INTERVAL}s -> ${SAMPLES}"
sampler_loop &
SAMPLER=$!
# The sampler must die with this script however it ends, including a failed
# phase. An orphaned loop writing into artifacts/ across the next run would
# blend two phases' peaks into one envelope.
trap 'kill "${SAMPLER}" 2>/dev/null || true' EXIT INT TERM

# ── the phase ────────────────────────────────────────────────────────────────
step "running: $*"
START_EPOCH="$(date +%s)"
set +e
# NOT --rm, and that is the fix for a real weakness in the evidence.
#
# The phase used to run with `--rm`, so the container was GONE by the time the
# OOM scan looked — and the scan then swept surviving `sentinel*` containers,
# which are the database and the panel, not the workload. A non-zero exit still
# prevented a false PASS, but "the OOM killer specifically" was lost, and the
# comments claimed otherwise.
#
# So: a NAMED container, kept until its final `.State` has been inspected, then
# removed here. `--name` also removes the guesswork about which container was
# the phase.
#
# -T, like the certify script. Without it compose allocates a TTY whenever
# stdin is one — which over SSH it is — and the tee'd log fills with cursor
# control codes. Same reason `docker stats` is sampled rather than streamed:
# an artefact you cannot grep is not evidence.
PHASE_CONTAINER="sentinel-measure-${PHASE}-${STAMP}"
${COMPOSE} run -T --name "${PHASE_CONTAINER}" "$@" 2>&1 \
  | tee "${ART}/${PHASE}-${STAMP}.log"
RC="${PIPESTATUS[0]}"
set -e
ELAPSED=$(( $(date +%s) - START_EPOCH ))

sample_once                       # one last frame, at the peak of the phase
kill "${SAMPLER}" 2>/dev/null || true
trap - EXIT INT TERM

# ── after ────────────────────────────────────────────────────────────────────
TEMP_AFTER="$(psql_scalar "SELECT COALESCE(temp_bytes,0) FROM pg_stat_database WHERE datname='sentinel'")"
DISK_AFTER="$(${COMPOSE} exec -T "${DB_SERVICE}" du -sb /var/lib/postgresql/data 2>/dev/null | cut -f1)"
: "${TEMP_AFTER:=0}" "${DISK_AFTER:=0}"

# THE PHASE CONTAINER ITSELF, inspected BEFORE it is removed. This is the only
# reading that can attribute an OOM to the measured workload: the sweep below
# sees surviving `sentinel*` containers, which are the database and the panel.
PHASE_STATE="$(docker inspect -f '{"name":"{{.Name}}","oom_killed":{{.State.OOMKilled}},"restarts":{{.RestartCount}},"exit_code":{{.State.ExitCode}}}' "${PHASE_CONTAINER}" 2>/dev/null || echo '{}')"
docker rm -f "${PHASE_CONTAINER}" >/dev/null 2>&1 || true

# OOM and restarts are read from the DAEMON, not inferred from the log. A
# container killed at its limit and restarted by the policy leaves a healthy
# container and a truncated log, which is exactly how an OOM gets recorded as
# "the process exited".
OOM_JSON="$(docker ps -a --filter 'name=sentinel' --format '{{.Names}}' \
  | while read -r n; do
      docker inspect -f '{"name":"{{.Name}}","oom_killed":{{.State.OOMKilled}},"restarts":{{.RestartCount}},"exit_code":{{.State.ExitCode}}}' "$n" 2>/dev/null
    done | python3 -c 'import json,sys; print(json.dumps([json.loads(l) for l in sys.stdin if l.strip()]))')"

step "the envelope"
PHASE="${PHASE}" STAMP="${STAMP}" RC="${RC}" ELAPSED="${ELAPSED}" \
TEMP_BEFORE="${TEMP_BEFORE}" TEMP_AFTER="${TEMP_AFTER}" \
DISK_BEFORE="${DISK_BEFORE}" DISK_AFTER="${DISK_AFTER}" \
LIMITS_JSON="${LIMITS_JSON}" OOM_JSON="${OOM_JSON}" \
CAPS_JSON="${CAPS_JSON}" PHASE_STATE="${PHASE_STATE}" \
CMD="$*" SAMPLES="${SAMPLES}" REPORT="${REPORT}" \
python3 <<'PY'
import csv, json, os, sys
from collections import defaultdict

env = os.environ
rows = list(csv.DictReader(open(env["SAMPLES"])))
peak_mem, peak_cpu, lim, min_avail = (defaultdict(int), defaultdict(float),
                                      {}, None)
for r in rows:
    c = r["container"]
    if r["mem_bytes"]:
        peak_mem[c] = max(peak_mem[c], int(r["mem_bytes"]))
    if r["mem_limit_bytes"]:
        lim[c] = int(r["mem_limit_bytes"])
    if r["cpu_pct"]:
        try: peak_cpu[c] = max(peak_cpu[c], float(r["cpu_pct"]))
        except ValueError: pass
    if r["host_mem_available_bytes"]:
        v = int(r["host_mem_available_bytes"])
        min_avail = v if min_avail is None else min(min_avail, v)

declared = json.loads(env["LIMITS_JSON"])
caps = json.loads(env.get("CAPS_JSON") or "{}").get("capabilities", {})
# CPU is OBSERVED here, not necessarily BOUNDED. On a host with no CFS quota
# the compose `cpus:` never reaches the kernel — the resolver strips it so the
# container can start at all — so reporting headroom against it would be
# reporting headroom against a number nothing enforces. Peak CPU is still
# recorded; what changes is the CLAIM attached to it.
cpu_enforced = caps.get("cpu_quota") == "ENFORCED"
mem_enforced = caps.get("memory_limit") == "ENFORCED"
def declared_for(container):
    # compose names containers `<project>-<service>-<n>`; match the longest
    # service name that appears, so `sentinel-postgres` wins over `sentinel`.
    best = None
    for svc in declared:
        if svc in container and (best is None or len(svc) > len(best)):
            best = svc
    return declared.get(best, {}), best

report = {
    "phase": env["PHASE"], "stamp": env["STAMP"], "command": env["CMD"],
    "exit_code": int(env["RC"]), "elapsed_seconds": int(env["ELAPSED"]),
    "samples": len(rows), "samples_file": env["SAMPLES"],
    "host_min_mem_available_bytes": min_avail,
    "postgres_temp_bytes_delta": int(env["TEMP_AFTER"]) - int(env["TEMP_BEFORE"]),
    "data_volume_growth_bytes": int(env["DISK_AFTER"]) - int(env["DISK_BEFORE"]),
    "containers": {}, "oom_and_restarts": json.loads(env["OOM_JSON"]),
    # THE MEASURED WORKLOAD's own final state, kept separate from the sweep of
    # surviving containers. Attribution is the point: the sweep can only say
    # "something was OOM-killed", and the database being killed during a seed
    # is a different finding from the seed being killed.
    "phase_container": json.loads(env.get("PHASE_STATE") or "{}"),
    "host_capabilities": caps,
    # The two verdicts are SEPARATE because the two limits are separate facts.
    # A Synology enforces memory and cannot enforce CPU, and one summary word
    # for both would either overclaim or discard a real measurement.
    # FOUR AXES, SEPARATELY, because the evidence for each is different in
    # kind and one word for all of them grows broader than what was measured.
    #
    #   container memory   bounded by mem_limit; a real PASS/TIGHT
    #   host memory        OBSERVED. MemAvailable collapsing means the host was
    #                      starving even if every container sat inside its own
    #                      ceiling — which is a different failure and not one
    #                      a per-container headroom figure can see
    #   CPU                bounded only where CFS quota exists
    #   disk I/O           never bounded here: this host reports no blkio
    #                      throttle support at all
    #   runtime            measured. A phase that fits in 1g by taking nine
    #                      hours has not passed either, and no memory number
    #                      says so
    "memory_verdict": "PASS",
    "cpu_limit_enforcement": "ENFORCED" if cpu_enforced else (
        caps.get("cpu_quota") or "UNKNOWN"),
    "cpu_verdict": "PASS" if cpu_enforced else "UNSUPPORTED — CPU was measured "
                                               "but NOT bounded on this host",
    "headroom_verdict": "PASS",
    "host_memory_verdict": "OBSERVED",
    "io_limit_enforcement": "UNSUPPORTED" if any(
        "blkio" in w for w in json.loads(env.get("CAPS_JSON") or "{}"
                                         ).get("daemon_warnings", [])
    ) else "UNKNOWN",
    "runtime_verdict": "MEASURED",
}

for c, m in sorted(peak_mem.items()):
    d, svc = declared_for(c)
    hard = lim.get(c) or d.get("mem_limit")
    entry = {"peak_mem_bytes": m, "peak_mem_mib": round(m / 1024**2, 1),
             "peak_cpu_pct": round(peak_cpu.get(c, 0.0), 1),
             "declared_service": svc,
             "declared_mem_limit_bytes": d.get("mem_limit"),
             "declared_cpus": d.get("cpus"),
             "enforced_mem_limit_bytes": hard}
    entry["cpu_bounded"] = cpu_enforced
    if hard and mem_enforced:
        entry["headroom_pct"] = round(100.0 * (hard - m) / hard, 1)
        # 20% is a floor for a MEASUREMENT, not a tuning target: this samples on
        # a timer, so a spike between two frames is invisible and a peak that
        # already sits near the wall is a peak that has probably touched it.
        if entry["headroom_pct"] < 20.0:
            report["memory_verdict"] = "TIGHT"
            report["headroom_verdict"] = "TIGHT"
    elif hard:
        # A declared limit the host does not enforce. Recorded, never scored.
        entry["headroom_pct"] = None
        entry["note"] = ("memory limit declared but the host reports "
                         f"memory_limit={caps.get('memory_limit')}")
        report["memory_verdict"] = "UNENFORCED"
        report["headroom_verdict"] = "UNENFORCED"
    report["containers"][c] = entry

# HOST PRESSURE, scored on its own axis rather than folded into the memory
# verdict. 10% of total is a reporting threshold, not a limit: it says "look at
# this", because nothing here can bound host memory and a PASS that quietly
# covered it would be claiming more than was measured.
_total = json.loads(env.get("CAPS_JSON") or "{}").get("host", {}).get("mem_total")
if min_avail is not None and _total:
    report["host_mem_total_bytes"] = _total
    report["host_min_mem_available_pct"] = round(100.0 * min_avail / _total, 1)
    if min_avail < 0.10 * _total:
        report["host_memory_verdict"] = (
            f"PRESSURE — MemAvailable fell to "
            f"{report['host_min_mem_available_pct']}% of total while every "
            f"container stayed inside its own ceiling")

if not rows:
    report["memory_verdict"] = report["headroom_verdict"] = "UNMEASURED"
if int(env["RC"]) != 0:
    report["memory_verdict"] = report["headroom_verdict"] = "PHASE FAILED"
if report["phase_container"].get("oom_killed"):
    report["memory_verdict"] = report["headroom_verdict"] = \
        "OOM KILLED (the measured phase)"
elif any(o.get("oom_killed") for o in report["oom_and_restarts"]):
    report["memory_verdict"] = report["headroom_verdict"] = \
        "OOM KILLED (another container)"

open(env["REPORT"], "w").write(json.dumps(report, indent=2, sort_keys=True))
print(json.dumps(report, indent=2, sort_keys=True))
print(f"\n  -> {env['REPORT']}")
PY

read -r VERDICT CPU_ENF <<<"$(python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
print(r["headroom_verdict"].split()[0], r["cpu_limit_enforcement"])' "${REPORT}")"

# CPU FIRST, and always — including on a PASS. The memory envelope being sound
# says nothing about the CPU one, and a reader who sees only "ENVELOPE
# MEASURED" would reasonably assume both were bounded.
# EVERY axis is printed, whatever the memory verdict says. A reader who sees
# only "MEMORY ENVELOPE MEASURED" would reasonably assume the rest were bounded
# too, and on this hardware three of them are not.
python3 - "${REPORT}" <<'PYX'
import json, sys
r = json.load(open(sys.argv[1]))
print("\n  ── what this run actually proves ──")
print(f"    container memory : {r['memory_verdict']}")
print(f"    host memory      : {r['host_memory_verdict']}"
      + (f"  (min {r['host_min_mem_available_pct']}% available)"
         if "host_min_mem_available_pct" in r else ""))
print(f"    CPU              : {r['cpu_limit_enforcement']} "
      f"(peak recorded, not bounded)"
      if r["cpu_limit_enforcement"] != "ENFORCED"
      else f"    CPU              : {r['cpu_verdict']}")
print(f"    disk I/O         : {r['io_limit_enforcement']}")
print(f"    runtime          : {r['elapsed_seconds']}s")
PYX

if [ "${CPU_ENF}" != "ENFORCED" ]; then
  printf '\n\033[33mCPU LIMITS %s\033[0m — peak CPUpercent in %s was OBSERVED, not\n' \
    "${CPU_ENF}" "${REPORT}"
  printf '  BOUNDED. This host has no CFS quota, so `cpus:` never reached the kernel and\n'
  printf '  #15 cannot certify a CPU envelope here. The MEMORY envelope below is real.\n'
fi

case "${VERDICT}" in
  PASS)  printf '\n\033[32mMEMORY ENVELOPE MEASURED\033[0m — %s, %ss\n' "${PHASE}" "${ELAPSED}" ;;
  TIGHT) printf '\n\033[33mMEMORY ENVELOPE TIGHT\033[0m — a peak is within 20%% of its limit. Read %s before tightening anything.\n' "${REPORT}" ;;
  UNENFORCED)
         die "the host does not enforce mem_limit either, so this measurement
  describes NO envelope at all. Read ${ART}/capabilities-${STAMP}.json — a
  number measured under limits nothing applies is not a limit with headroom." ;;
  *)     die "${VERDICT} — read ${REPORT} and ${ART}/${PHASE}-${STAMP}.log" ;;
esac

[ "${RC}" -eq 0 ] || die "the phase itself exited ${RC}; the envelope describes a run that did not finish"
