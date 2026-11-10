#!/usr/bin/env python3
"""Scheduled host coordinator; standard library only, host Python >=3.8.15."""
from __future__ import annotations

import json
import math
import fcntl
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from sentinel_backup_lock import lock_is_held, _lock_path
from sentinel_backup_deadlines import BASE_COMMAND_SECONDS, INVOCATION_SECONDS
from sentinel_maintenance_process import run_bounded
from sentinel_backup_integrity_report import validate as validate_shared_integrity
from sentinel_backup_integrity_report import parse_failure, failure as failure_record
import sentinel_backup_renewal as renewal


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "docker-compose.sentinel.yml",
           "-f", "docker-compose.sentinel-backup.yml"]
IMAGE_RE = re.compile(r"(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[0-9a-f]{64})\Z")
BASE_RE = re.compile(r"base-[0-9]{8}T[0-9]{6}Z\Z")
RENEW_BYTES = 8 * 1024 * 1024 * 1024
RENEW_SECONDS = 24 * 3600
RUNTIME_CHAIN_BYTES = 16 * 1024 * 1024 * 1024
MAINTENANCE_INTERVAL_SECONDS = 300


class Refused(RuntimeError):
    def __init__(self,message,*,failure=None):
        super().__init__(message)
        self.failure = failure


def run(command, *, timeout=120, stdin=None, on_wait=None):
    options = dict(timeout=timeout,stdin=stdin,private_group=False)
    if on_wait is not None: options['on_wait'] = on_wait
    result = run_bounded(command, **options)
    if result.returncode:
        # Child output is retained by the scheduler; no environment/credentials.
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        failure = None
        try: failure = parse_failure(result.stdout+'\n'+result.stderr,returncode=result.returncode)
        except (ValueError,TypeError,KeyError): pass
        raise Refused("maintenance command failed: " + command[0],failure=failure)
    return result.stdout.strip()


def sql(query, runner=run):
    return runner(COMPOSE + ["exec", "-T", "sentinel-postgres", "psql", "-U", "sentinel",
                            "-d", "sentinel", "-v", "ON_ERROR_STOP=1", "-Atc", query])


def runtime_image(runner=run):
    pointer = ROOT / "artifacts/sentinel/deployment/validated-runtime.env"
    value = os.environ.get("SENTINEL_RUNTIME_IMAGE_REF", "")
    if pointer.exists():
        raw = pointer.read_text(encoding="ascii")
        prefix = "SENTINEL_RUNTIME_IMAGE_REF="
        if not raw.startswith(prefix) or len(raw.splitlines()) != 1:
            raise Refused("invalid validated runtime selector")
        value = raw[len(prefix):].strip()
    if not IMAGE_RE.fullmatch(value):
        raise Refused("maintenance requires an immutable runtime image")
    head = runner(["git", "rev-parse", "HEAD"])
    if runner(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise Refused("maintenance requires a clean reviewed checkout")
    revision = runner(["docker", "image", "inspect", "--format",
                       '{{index .Config.Labels "org.opencontainers.image.revision"}}', value])
    if not re.fullmatch(r"[0-9a-f]{40}", head) or revision != head:
        raise Refused("runtime image does not match the maintenance checkout")
    return value


def observe_primary(runner=run):
    value = json.loads(sql("""SELECT json_build_object(
        'system_id',system_identifier::text,
        'now',floor(extract(epoch FROM clock_timestamp()))::bigint,
        'lsn',pg_current_wal_lsn()::text,
        'timeline',substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8),
        'segment_size',pg_size_bytes(current_setting('wal_segment_size')),
        'publication_at',(SELECT observed_at FROM sentinel_backup_evidence
            WHERE kind='RUNTIME_CHAIN' AND evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex')
            ORDER BY observed_at DESC,seq DESC LIMIT 1))
        FROM pg_control_system()""", runner))
    if (not re.fullmatch(r"[1-9][0-9]{0,19}", str(value.get("system_id", "")))
            or not re.fullmatch(r"[0-9A-F]{8}", str(value.get("timeline", "")))
            or not re.fullmatch(r"[0-9A-F]+/[0-9A-F]{1,8}", str(value.get("lsn", "")))
            or type(value.get("now")) is not int
            or type(value.get("segment_size")) is not int):
        raise Refused("invalid primary observation")
    size = value["segment_size"]
    if not 1024 * 1024 <= size <= 1024**3 or size & (size - 1):
        raise Refused("invalid primary WAL geometry")
    return value


def renewal_due(selected, observation):
    age = observation["now"] - selected["timestamp"]
    if age < 0:
        raise Refused("backup is future-dated")
    current_timeline = int(observation["timeline"], 16)
    ranges = selected["ranges"]
    if any(item["timeline"] > current_timeline for item in ranges):
        raise Refused("primary timeline regressed")
    if any(item["timeline"] < current_timeline for item in ranges):
        return True
    high, low = observation["lsn"].split("/")
    current = int(high, 16) * 2**32 + int(low, 16)
    end = max(item["end"] for item in ranges)
    if current < end:
        raise Refused("primary WAL regressed")
    size = observation["segment_size"]
    footprint = (current // size - (end - 1) // size + 1) * size
    now = datetime.fromtimestamp(observation['now'], timezone.utc)
    prior = datetime.fromtimestamp(selected['timestamp'], timezone.utc)
    daily = 9 <= now.hour < 12 and now.date() > prior.date() and age >= 12*3600
    return daily or age >= RENEW_SECONDS or footprint >= RENEW_BYTES


def renew_base(root, image, runner=run, *, on_wait=None):
    """Produce and select one exact successor; callers retain their lock/budget."""
    options = dict(timeout=BASE_COMMAND_SECONDS)
    if on_wait is not None: options['on_wait'] = on_wait
    output = runner(['bash', 'scripts/sentinel-base-backup.sh'], **options)
    paths = [line[len('verified_base_backup:'):].strip() for line in output.splitlines()
             if line.startswith('verified_base_backup:')]
    if len(paths) != 1:
        raise Refused('producer did not return one exact successor')
    observation = observe_primary(runner)
    selected = worker('observe', image, root, observation, runner)
    if not BASE_RE.fullmatch(selected['name']) or paths[0] != root + '/base/' + selected['name']:
        raise Refused('producer successor differs from selected generation')
    if renewal_due(selected, observation):
        raise Refused('successor already exhausts maintenance headroom')
    return selected, observation


def heavy_work_allowed(observation):
    now = datetime.fromtimestamp(observation['now'], timezone.utc)
    minutes = now.hour*60 + now.minute
    return not 12*60+30 <= minutes < 21*60


def worker(action, image, root, observation, runner=run, request=None, *, on_wait=None):
    mount_mode = ':ro' if action == 'observe-current' else ''
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
               "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
               "--security-opt", "no-new-privileges",
               "--memory", "256m", "--pids-limit", "64",
               "-v", root + "/base:/backup/base"+mount_mode, "-v", root + "/wal:/backup/wal"+mount_mode,
               "--entrypoint", "python", image, "-m", "sentinel.backup_retention", action,
               "--system-id", observation["system_id"]]
    options = dict(timeout=600,stdin=json.dumps(request) if request is not None else None)
    if on_wait is not None: options['on_wait'] = on_wait
    if action != 'observe-current': return json.loads(runner(command,**options))
    name = 'sentinel-maintenance-observe-'+uuid.uuid4().hex
    command[2:2] = ['--name',name]
    primary,reader_started = None,time.monotonic()
    try:
        return json.loads(runner(command,**options))
    except Exception as exc:
        primary = exc
        raise
    finally:
        removed = False
        try:
            runner(['docker','rm','-f',name],timeout=5); removed = True
        except Exception:
            try:
                removed = not runner(['docker','ps','-a','--filter','name=^/'+name+'$',
                    '--format','{{.ID}}'],timeout=5).strip()
            except Exception: pass
        if not removed:
            cause = ('Refused' if isinstance(primary,Refused) else 'ValueError' if isinstance(primary,ValueError)
                else 'OSError' if isinstance(primary,OSError) else 'UNCLASSIFIED' if primary else 'PROTOCOL')
            detail = failure_record(origin='HOST',code='TRANSPORT_FAILURE',stage='HOST_POSTGRES' if primary else 'HOST_CLEANUP',
                cause_type=cause,elapsed_seconds=time.monotonic()-reader_started,
                proof_lock='NOT_ACQUIRED',worker_container='FAILED')
            raise Refused('read-only metadata worker cleanup failed',failure=detail) from primary


def _selected_full_restore_receipt(selected, observation, runner=run):
    name, digest = selected["name"], selected["metadata_sha256"]
    if not BASE_RE.fullmatch(name) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise Refused("invalid selected identity")
    # Fields interpolated below are already restricted to machine identities.
    raw = sql("SELECT proof::text FROM sentinel_backup_evidence "
              "WHERE kind='RESTORE_DRILL' AND proof->>'base_backup'='" + name + "' "
              "AND proof->>'metadata_sha256'='" + digest + "' "
              "AND evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex') "
              "ORDER BY observed_at DESC,seq DESC LIMIT 1", runner)
    if not raw:
        return None
    result = json.loads(raw)
    expected = {"base_backup": name, "metadata_sha256": digest,
                "system_identifier": observation["system_id"],
                "physical_only": False, "marker": selected["marker"],
                "target_lsn": selected["target_lsn"]}
    if not isinstance(result, dict) or any(type(result.get(k)) is not type(v) or result.get(k) != v
                                          for k, v in expected.items()):
        return None
    prior_image = result.get("runtime_image")
    if not isinstance(prior_image, str) or not IMAGE_RE.fullmatch(prior_image):
        return None
    return result


def verified_base_receipt(selected, observation, runner=run):
    """Authenticate producer identity independently of a later archive scan."""
    name=selected['name']
    if not BASE_RE.fullmatch(name):
        raise Refused('invalid selected identity')
    raw=sql("SELECT json_build_object('proof',proof,'authentic',"
        "evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex')) "
        "FROM sentinel_backup_evidence WHERE kind='BASE_BACKUP' "
        "AND proof->>'base_backup'='"+name+"' ORDER BY observed_at DESC,seq DESC LIMIT 1",runner)
    if not raw:
        return None
    record=json.loads(raw)
    expected=dict(schema='sentinel.verified-base/1',physical_verified=True,
        metadata_sha256=selected['metadata_sha256'],base_backup=name,
        marker=selected['marker'],marker_lsn=selected['target_lsn'],
        system_identifier=observation['system_id'])
    proof=record.get('proof') if isinstance(record,dict) else None
    if not isinstance(proof,dict) or record.get('authentic') is not True:
        raise Refused('verified base producer evidence is unauthenticated')
    if proof.get('schema')!='sentinel.verified-base/1':
        return None  # Older bases retain their genuine exact-base restore receipt.
    if any(type(proof.get(k)) is not type(v) or proof.get(k)!=v for k,v in expected.items()):
        raise Refused('verified base producer evidence identity mismatch')
    return proof


def verified_base_chain_receipt(selected, observation, chain, runner=run):
    """Use actual verified producer evidence, never manufacture a restore drill."""
    if verified_base_receipt(selected, observation, runner) is None:
        return None
    return _base_chain_receipt(selected, observation, chain)


def _base_chain_receipt(selected, observation, chain):
    """Compose an already authenticated producer with the verified chain."""
    name = selected['name']
    if (chain.get('base_backup')!=name or chain.get('system_identifier')!=observation['system_id']
            or chain.get('wal_integrity')!='sha256-sidecar-v1' or chain.get('enabled') is not True):
        raise Refused('verified base chain identity mismatch')
    return dict(schema='sentinel.verified-base-chain/1',base_backup=name,
        metadata_sha256=selected['metadata_sha256'],marker=selected['marker'],
        target_lsn=selected['target_lsn'],system_identifier=observation['system_id'],
        physical_verified=True,wal_integrity='sha256-sidecar-v1')


def runtime_chain_proof(output, selected, observation, root):
    """Validate one exact successful private-media status observation."""
    if not isinstance(output, str) or len(output) > 65536:
        raise Refused("invalid runtime chain report")
    chain_re = re.compile(
        r"wal_chain_ready:true start_index=([0-9]+) end=([0-9A-F]{24}) "
        r"segments=([0-9]+) marker=([0-9A-F]{24}) "
        r"history=(none|[0-9A-F]{8}\.history)\Z")
    ready_re = re.compile(
        r"backup_ready:true base=(.+) age_hours=[0-9]+ "
        r"wal_age_hours=[0-9]+ system_id=([1-9][0-9]{0,19})\Z")
    chains = [chain_re.fullmatch(line) for line in output.splitlines()
              if line.startswith("wal_chain_ready:")]
    ready = [ready_re.fullmatch(line) for line in output.splitlines()
             if line.startswith("backup_ready:")]
    if (len(chains) != 1 or chains[0] is None
            or len(ready) != 1 or ready[0] is None):
        raise Refused("runtime chain report is malformed or ambiguous")
    start_text, end, count_text, marker, history = chains[0].groups()
    path, system_id = ready[0].groups()
    name = selected["name"]
    if (not BASE_RE.fullmatch(name) or path != root + "/base/" + name
            or system_id != observation["system_id"]):
        raise Refused("runtime chain report differs from selected backup")
    size = observation["segment_size"]
    per_log = 2**32 // size
    start, count = int(start_text), int(count_text)
    timeline, log, segment = (int(end[i:i+8], 16) for i in (0, 8, 16))
    last = log * per_log + segment
    marker_timeline, marker_log, marker_segment = (
        int(marker[i:i+8], 16) for i in (0, 8, 16))
    marker_index = marker_log * per_log + marker_segment
    high, low = selected["target_lsn"].split("/")
    # pg_walfile_name assigns an exact segment boundary to its preceding WAL.
    marker_lsn = int(high, 16)*2**32 + int(low, 16)
    marker_lsn_index = (marker_lsn-1) // size
    ranges = selected["ranges"]
    expected_start = max(item["end"] for item in ranges) // size
    expected_history = "none" if timeline == 1 else "%08X.history" % timeline
    if (timeline < 1 or "%08X" % timeline != observation["timeline"]
            or any(item["timeline"] != timeline for item in ranges)
            or start != expected_start or segment >= per_log
            or marker_segment >= per_log or marker_timeline != timeline
            or marker_index != marker_lsn_index or not start <= marker_index <= last
            or count != last-start+1 or not 1 <= count <= 1024
            or count*size > RUNTIME_CHAIN_BYTES or history != expected_history):
        raise Refused("runtime chain interval contradicts selected metadata")
    first_log, first_segment = divmod(start, per_log)
    proof = dict(enabled=True, system_identifier=system_id, base_backup=name,
        recoverable_from_wal="%08X%08X%08X" % (timeline, first_log, first_segment),
        recovery_marker_wal=marker, recoverable_through_wal=end,
        wal_segments=count, timeline_history=None if history == "none" else history,
        wal_integrity="sha256-sidecar-v1", integrity_full_scrub=True,
        integrity_objects_hashed=count + (history != "none"), integrity_read_passes=1)
    shared = [line[len('shared_integrity_proof:'):] for line in output.splitlines()
              if line.startswith('shared_integrity_proof:')]
    if shared:
        try:
            if len(shared) != 1:
                raise ValueError('ambiguous common integrity reports')
            actual = validate_shared_integrity(json.loads(shared[0]))
            fields = ('enabled', 'system_identifier', 'base_backup', 'recoverable_from_wal',
                'recovery_marker_wal', 'recoverable_through_wal', 'wal_segments',
                'timeline_history', 'wal_integrity')
            if (any(type(actual[k]) is not type(proof[k]) or actual[k] != proof[k] for k in fields)
                    or actual['wal_segment_bytes'] != size):
                raise ValueError('common integrity differs from observed chain')
        except (ValueError, TypeError, KeyError):
            raise Refused('common runtime chain proof is malformed or contradictory') from None
        proof = actual
    return proof


def publish_runtime_chain(output, selected, observation, root, runner=run, *, schedule=None):
    """Publish only the exact successful private-media status observation."""
    proof = runtime_chain_proof(output, selected, observation, root)
    # The existing host producers publish operational evidence through psql.
    # Every variable field above is a validated machine identity; no operator
    # text or credentials enter SQL. The database supplies the observation time.
    payload = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    # An outer SELECT avoids psql's INSERT command tag in the JSON protocol.
    query = ("WITH evidence AS (SELECT '" + payload + "'::jsonb AS proof), recorded AS ("
        "INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof) "
        "SELECT 'RUNTIME_CHAIN',encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof "
        "FROM evidence RETURNING proof,observed_at) SELECT json_build_object('proof',proof,"
        "'observed_at',observed_at)::text FROM recorded")
    observed = json.loads(sql(query, runner))
    if (not isinstance(observed,dict) or set(observed) != {'proof','observed_at'}
            or observed['proof'] != proof):
        raise Refused("runtime chain evidence was not persisted exactly")
    renewal.timestamp(observed['observed_at'])
    if schedule is not None: schedule.accept(observed['observed_at'])
    return proof


def reap_restore_resources(now, runner=run):
    """Remove only expired, labeled and unreferenced disposable resources."""
    removed = 0
    for kind in ("volume", "network"):
        names = runner(["docker", kind, "ls", "--filter", "label=sentinel.restore-drill=v1",
                        "--format", "{{.Name}}"]).splitlines()
        if len(names) > 256:
            raise Refused("restore resource inventory exceeds recovery bound")
        for name in names:
            if not re.fullmatch(r"sentinel-restore-drill-[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9a-f]{32}", name):
                raise Refused("unexpected labeled restore resource identity")
            raw = runner(["docker", kind, "inspect", "--format", "{{json .}}", name])
            record = json.loads(raw)
            if record.get("Name") != name or record.get("Labels", {}).get("sentinel.restore-drill") != "v1":
                raise Refused("restore resource identity changed")
            stamp_text = record["CreatedAt" if kind == "volume" else "Created"]
            # Docker emits nanoseconds; host Python 3.8 accepts microseconds.
            stamp_text = re.sub(r"\.(\d{1,9})(?=Z|[+-][0-9]{2}:[0-9]{2}$)",
                                lambda match: "." + match[1][:6].ljust(6, "0"), stamp_text)
            stamp = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise Refused("restore resource has no clock offset")
            age = now - stamp.astimezone(timezone.utc).timestamp()
            if age < 0:
                raise Refused("restore resource is future-dated")
            if age < 7200:
                continue
            if kind == "volume":
                if runner(["docker", "ps", "-a", "--filter", "volume=" + name, "--format", "{{.ID}}"]):
                    continue
            elif record.get("Containers") != {}:
                continue
            # Docker's removal is the final atomic in-use check; never force it.
            runner(["docker", kind, "rm", name])
            removed += 1
    return removed


def publish_progress(progress, runner=run):
    """Presentation evidence only; never lends authority to a recovery gate."""
    payload = json.dumps(progress, sort_keys=True, separators=(',', ':'))
    # Machine identities are validated before interpolation; JSON strings can
    # still contain apostrophes (e.g. an image tag), so escape the SQL literal.
    payload = payload.replace("'", "''")
    query = ("WITH evidence AS (SELECT '" + payload + "'::jsonb AS proof), recorded AS ("
        "INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof) "
        "SELECT 'MAINTENANCE_PROGRESS',encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof "
        "FROM evidence RETURNING proof) SELECT proof::text FROM recorded")
    if json.loads(sql(query, runner)) != progress:
        raise Refused('maintenance progress was not persisted exactly')


def _progress(progress, runner, **changes):
    # Keep the last committed identity for failure reporting if this write fails.
    successor = dict(progress, **changes)
    publish_progress(successor, runner)
    progress.clear()
    progress.update(successor)


class FreshnessReader:
    minimum_seconds = 40
    def __init__(self,schedule):
        self.schedule = schedule

    def next_at(self): return self.schedule.next_at()

    def __call__(self,remaining):
        limits = [remaining,600]
        with self.schedule.lock:
            if self.schedule.deadline is not None and self.schedule.deadline > self.schedule.clock():
                limits.append(self.schedule.deadline-self.schedule.clock())
        budget = math.floor(min(limits)-20)
        if budget < 15:
            value = renewal.result(outcome='BLOCKED',phase='PREFLIGHT',code='DEADLINE_EXCEEDED',
                publication_at=self.schedule.publication())
        else:
            try:
                child = run_bounded([sys.executable,'-B','scripts/sentinel_backup_maintenance.py',
                    '--freshness-only','--timeout-seconds',str(budget)],timeout=budget+5,private_group=False)
                value = renewal.parse(child.stdout,refresh=True)
                expected = 0 if value['outcome']=='SUCCESS' else 75 if value['outcome']=='RETRYABLE' else 4
                if child.returncode != expected: raise ValueError('freshness child result mismatch')
            except Exception:
                value = renewal.result(outcome='BLOCKED',phase='VERIFY_CHAIN',code='INVALID_RESULT',
                    publication_at=self.schedule.publication(),cause_type='UNKNOWN')
        self.schedule.consume(value)
        renewal.emit(value,refresh=True)


def tick(root, runner=run, *, freshness=False, budget=None):
    progress = {}
    started = time.monotonic()
    state = dict(phase='PREFLIGHT',schedule=renewal.Schedule())
    if budget is not None:
        deadline = started+budget
        underlying = runner
        def bounded(command,**options):
            command = list(command)
            cleanup = command[:2] in (['docker','rm'],['docker','ps'])
            remaining = deadline-time.monotonic()-(0 if cleanup else 10)
            if remaining <= 0: raise Refused('freshness read budget exhausted')
            options['timeout'] = min(options.get('timeout',120),remaining)
            if command[:2] == ['bash','scripts/sentinel-backup-status.sh']:
                position = command.index('--backup') if '--backup' in command else len(command)
                command[position:position] = ['--timeout-seconds',str(max(1,math.floor(remaining)))]
            if 'observe-current' in command and 'sentinel.backup_retention' in command:
                command += ['--timeout-seconds',str(max(1,min(540,math.floor(remaining-1))))]
            return underlying(command,**options)
        runner = bounded
    try:
        value = (_fresh_tick(root,runner,state) if freshness else _tick(root, runner, progress, started,state))
        renewal.emit(renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',
            publication_at=state['schedule'].publication(),elapsed_seconds=time.monotonic()-started),refresh=freshness)
        return value
    except Exception as exc:
        if progress:
            progress['phase'] = 'FAILED'
            try:
                publish_progress(progress, runner)
            except Exception as exc:
                print('maintenance failure progress unreadable: ' + type(exc).__name__, file=sys.stderr)
        failure = exc.failure if isinstance(exc,Refused) else None
        renewal.emit(renewal.result(outcome='RETRYABLE' if failure and failure['retryable'] else 'BLOCKED',
            phase=state['phase'],code=failure['code'] if failure else 'COORDINATOR_REFUSED'
                if isinstance(exc,Refused) else 'UNCLASSIFIED',
            cause_type=type(exc).__name__ if type(exc).__name__ in {'Refused','OSError','ValueError','KeyError','TypeError'}
                else 'UNKNOWN',publication_at=state['schedule'].publication(),
            elapsed_seconds=time.monotonic()-started,failure=failure),refresh=freshness)
        raise


def _chain(root,image,selected,observation,runner,state,*,shared_mode):
    state['phase'] = 'VERIFY_CHAIN'
    path = root+'/base/'+selected['name']
    command = ['bash','scripts/sentinel-backup-status.sh']
    if shared_mode: command.append('--shared-integrity')
    status = runner(command+['--backup',path],timeout=600)
    if shared_mode and not any(line.startswith('shared_integrity_proof:') for line in status.splitlines()):
        raise Refused('selected common integrity returned no common proof')
    observation = observe_primary(runner)
    chain = runtime_chain_proof(status,selected,observation,root)
    receipt = verified_base_chain_receipt(selected,observation,chain,runner)
    if receipt is None:
        receipt = _selected_full_restore_receipt(selected,observation,runner)
        if receipt is None: raise Refused('selected base has neither verified producer nor genuine restore evidence')
    state['phase'] = 'PUBLISH_CHAIN'
    publish_runtime_chain(status,selected,observation,root,runner,schedule=state['schedule'])
    return chain,receipt,observation


def _fresh_tick(root,runner,state):
    if os.environ.get('SENTINEL_BACKUP_SHARED_INTEGRITY') != 'REQUIRED_V1':
        raise Refused('freshness requires selected shared integrity')
    image = runtime_image(runner)
    state['phase'] = 'OBSERVE'
    observation = observe_primary(runner)
    if observation.get('publication_at') is not None: state['schedule'].accept(observation['publication_at'])
    selected = worker('observe-current',image,root,observation,runner)
    _chain(root,image,selected,observation,runner,state,shared_mode=True)
    return dict(runtime_chain_current=True,base=selected['name'])


def _tick(root, runner, progress, started,state):
    shared_mode = os.environ.get('SENTINEL_BACKUP_SHARED_INTEGRITY', '')
    if shared_mode not in ('', 'REQUIRED_V1'):
        raise Refused('unsupported maintenance shared integrity policy')
    image = runtime_image(runner)
    state['phase'] = 'OBSERVE'
    observation = observe_primary(runner)
    if observation.get('publication_at') is not None: state['schedule'].accept(observation['publication_at'])
    on_wait = FreshnessReader(state['schedule']) if shared_mode else None
    deferred = not heavy_work_allowed(observation)
    if not deferred:
        reap_restore_resources(observation["now"], runner)
    selected = worker("observe", image, root, observation, runner)
    renewed = renewal_due(selected, observation)
    if renewed and not deferred:
        state['phase'] = 'BASE_BACKUP'
        first_second = observation['now'] - math.ceil(time.monotonic()-started)
        _progress(progress, runner, schema='sentinel.backup-maintenance-progress/1',
            attempt=uuid.uuid4().hex, started_at=first_second,
            deadline=first_second + INVOCATION_SECONDS,
            system_identifier=observation['system_id'], image=image,
            predecessor_base=selected['name'], base_backup=selected['name'],phase='BASE_BACKUP')
        selected, observation = renew_base(root, image, runner,on_wait=on_wait)
        _progress(progress, runner, base_backup=selected['name'], phase='VERIFY_CHAIN')
    chain,receipt,observation = _chain(root,image,selected,observation,runner,state,shared_mode=bool(shared_mode))
    state['phase'] = 'CHECKPOINT'
    from sentinel_backup_capacity import checkpoint
    continuity_ready = checkpoint(chain, runner)
    if deferred:
        result = {'maintenance_deferred': True, 'reason': 'market and daily preparation window',
                  'base': selected['name'], 'renewal_due': renewed, 'runtime_chain_current': True}
        if continuity_ready is not None:
            result['continuity_ready'] = continuity_ready
        print(json.dumps(result, sort_keys=True))
        return result
    state['phase'] = 'RETENTION'
    result = worker("retain", image, root, observation, runner, {
        "receipt": receipt, "image": receipt.get('runtime_image',image), "now": observation["now"],
        "segment_size": observation["segment_size"],
    },on_wait=on_wait)
    if progress:
        _progress(progress, runner, phase='COMPLETE')
    print(json.dumps({"maintenance_ready": True, "observed_at": observation["now"], "renewed": renewed,
                      "base": selected["name"], **result,
                      **({'continuity_ready': continuity_ready} if continuity_ready is not None else {})}, sort_keys=True))
    return result


def _latest_publication():
    try:
        value = sql("SELECT observed_at::text FROM sentinel_backup_evidence WHERE kind='RUNTIME_CHAIN' "
            "AND evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex') "
            "ORDER BY observed_at DESC,seq DESC LIMIT 1")
        return value or None
    except Exception: return None


def supervise():
    path = _lock_path(os.environ)
    if path is None:
        raise Refused("supervisor requires a canonical target")
    path = path.with_suffix(".maintenance-loop")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a+") as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("SENTINEL_BACKUP_MAINTENANCE=SUPERVISOR_ALREADY_RUNNING", flush=True)
            return 0
        schedule = renewal.Schedule(_latest_publication())
        while True:
            result = subprocess.run(["bash", "scripts/sentinel-backup-maintenance.sh"],
                cwd=str(ROOT),check=False,pass_fds=(handle.fileno(),),capture_output=True,text=True)
            output, errors = getattr(result,'stdout',''),getattr(result,'stderr','')
            if output: print(output,end='',flush=True)
            if errors: print(errors,end='',file=sys.stderr,flush=True)
            try:
                value = renewal.parse(output)
                expected = 0 if value['outcome']=='SUCCESS' else 75 if value['outcome']=='RETRYABLE' else 4
                if result.returncode != expected: raise ValueError('pass result exit mismatch')
            except (ValueError,TypeError,KeyError):
                standby = (result.returncode == 0 and output.splitlines().count(
                    'SENTINEL_BACKUP_MAINTENANCE=STANDBY_TARGET_OWNED') == 1
                    and not any(line.startswith((renewal.PASS_PREFIX,'shared_integrity_failure:'))
                        for line in (output+'\n'+errors).splitlines()))
                value = renewal.result(outcome='STANDBY' if standby else 'BLOCKED',phase='PREFLIGHT',
                    code='TARGET_BUSY' if standby else 'INVALID_RESULT',publication_at=schedule.publication())
                renewal.emit(value)
            schedule.consume(value)
            if result.returncode:
                print("SENTINEL_BACKUP_MAINTENANCE=FAILED_RETRY_PENDING", file=sys.stderr, flush=True)
            time.sleep(schedule.delay())


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--loop"]:
        return supervise()
    freshness, budget = False,None
    if args and args[0] == '--freshness-only':
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--freshness-only',action='store_true')
        parser.add_argument('--timeout-seconds',type=int,required=True)
        parsed = parser.parse_args(args)
        if not 15 <= parsed.timeout_seconds <= 600: parser.error('freshness budget must be15..600 seconds')
        freshness,budget = True,parsed.timeout_seconds
    elif args:
        print("usage: sentinel-backup-maintenance.sh [--loop]", file=sys.stderr)
        return 2
    if not lock_is_held():
        print("REFUSED: maintenance requires the target ownership lock", file=sys.stderr)
        return 4
    root = os.environ["SENTINEL_BASE_BACKUP_LOCK_ROOT"]
    try:
        tick(root,freshness=freshness,budget=budget)
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("REFUSED: backup maintenance: " + str(exc), file=sys.stderr, flush=True)
        return 75 if isinstance(exc,Refused) and exc.failure and exc.failure['retryable'] else 4


if __name__ == "__main__":
    raise SystemExit(main())
