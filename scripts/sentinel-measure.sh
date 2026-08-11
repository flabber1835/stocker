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
#     scripts/sentinel-measure.sh plan  -- sentinel plan
#     scripts/sentinel-measure.sh ready -- sentinel check-data
#
# The phase name is free text and only labels the artefacts. Everything after
# `--` runs through `docker compose run --rm -T`, so it is measured inside the
# limits it is being measured against.
#
# NOT MEASURABLE TODAY: the catch-up orchestrator. `sentinel/core/catchup.py`
# exists and is tested, but nothing in `sentinel/__main__.py` exposes it — there
# is no `catch-up` verb, so finding #15's catch-up phase has no entry point to
# time. That is a wiring gap, not a measurement one; say so rather than
# substituting a different phase and calling it catch-up.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.sentinel.yml"
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
# -T, like the certify script. Without it compose allocates a TTY whenever
# stdin is one — which over SSH it is — and the tee'd log fills with cursor
# control codes. Same reason `docker stats` is sampled rather than streamed:
# an artefact you cannot grep is not evidence.
${COMPOSE} run --rm -T "$@" 2>&1 | tee "${ART}/${PHASE}-${STAMP}.log"
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
    "headroom_verdict": "PASS",
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
    if hard:
        entry["headroom_pct"] = round(100.0 * (hard - m) / hard, 1)
        # 20% is a floor for a MEASUREMENT, not a tuning target: this samples on
        # a timer, so a spike between two frames is invisible and a peak that
        # already sits near the wall is a peak that has probably touched it.
        if entry["headroom_pct"] < 20.0:
            report["headroom_verdict"] = "TIGHT"
    report["containers"][c] = entry

if not rows:
    report["headroom_verdict"] = "UNMEASURED"
if int(env["RC"]) != 0:
    report["headroom_verdict"] = "PHASE FAILED"
if any(o.get("oom_killed") for o in report["oom_and_restarts"]):
    report["headroom_verdict"] = "OOM KILLED"

open(env["REPORT"], "w").write(json.dumps(report, indent=2, sort_keys=True))
print(json.dumps(report, indent=2, sort_keys=True))
print(f"\n  -> {env['REPORT']}")
PY

VERDICT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["headroom_verdict"])' "${REPORT}")"
case "${VERDICT}" in
  PASS)  printf '\n\033[32mENVELOPE MEASURED\033[0m — %s, %ss\n' "${PHASE}" "${ELAPSED}" ;;
  TIGHT) printf '\n\033[33mENVELOPE TIGHT\033[0m — a peak is within 20%% of its limit. Read %s before tightening anything.\n' "${REPORT}" ;;
  *)     die "${VERDICT} — read ${REPORT} and ${ART}/${PHASE}-${STAMP}.log" ;;
esac

[ "${RC}" -eq 0 ] || die "the phase itself exited ${RC}; the envelope describes a run that did not finish"
