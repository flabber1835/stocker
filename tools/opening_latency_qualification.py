"""Credential-free profiling of real verifiers on an isolated retained copy.

Run in the exact candidate runtime, mounting this tool read-only outside /app.
This diagnostic never grants authority or submits an order. Full simulated
gateway qualification is a separate acceptance gate; a verifier PASS alone
must never be reported as opening execution qualification.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import cProfile
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pstats
import re
import time


class QualificationRefused(RuntimeError):
    def __init__(self, code, **metrics):
        super().__init__(code)
        self.metrics = metrics


PRIVATE_DATABASE = re.compile(r"(?:rehearsal(?:_[a-z0-9]+)?|opening_latency_[a-z0-9_]+)\Z")
SYSTEM_ID = re.compile(r"[1-9][0-9]{1,19}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
PROFILE_FUNCTIONS = frozenset({
    "verified_shadow_status", "status", "_load_closure", "verified_shadow_intent",
    "rederive_plan", "_rederive_plan", "verify_content", "_verify_content_uncached",
    "load_evidence", "material", "deepcopy", "state_hash",
})


def require_environment(environ, sentinel_file):
    # Do not load a .env, inherit provider access, or let a source overlay stand
    # in for the tested runtime. PostgreSQL/publication authentication is needed
    # to read the private copied source and is never included in the report.
    for name, value in environ.items():
        if value and (name.startswith(("ALPACA_", "OPENFIGI_", "SHARADAR_", "NDL_"))
                      or name in ("REHEARSAL_PRODUCTION_DATABASE_URL",)):
            raise QualificationRefused("PROVIDER_OR_PRODUCTION_ENVIRONMENT_PRESENT")
    if Path(sentinel_file).resolve().parent != Path("/app/sentinel"):
        raise QualificationRefused("RUNTIME_IMPORT_IS_NOT_EXACT_IMAGE")
    if REVISION.fullmatch(environ.get("SENTINEL_IMAGE_SOURCE_REVISION", "")) is None:
        raise QualificationRefused("RUNTIME_REVISION_UNAVAILABLE")


def require_target(args):
    if not args.private_rehearsal:
        raise QualificationRefused("EXPLICIT_PRIVATE_REHEARSAL_REQUIRED")
    if PRIVATE_DATABASE.fullmatch(args.expected_database) is None:
        raise QualificationRefused("PRIVATE_DATABASE_NAME_REQUIRED")
    for value in (args.expected_system_id, args.production_system_id):
        if SYSTEM_ID.fullmatch(value) is None:
            raise QualificationRefused("PHYSICAL_CLUSTER_ID_REQUIRED")
    if args.expected_system_id == args.production_system_id:
        raise QualificationRefused("PRODUCTION_CLUSTER_FORBIDDEN")
    if DIGEST.fullmatch(args.runtime_image_digest) is None:
        raise QualificationRefused("IMMUTABLE_RUNTIME_IMAGE_REQUIRED")
    if not 1 <= args.repetitions <= 10:
        raise QualificationRefused("REPETITIONS_OUT_OF_RANGE")
    if getattr(args, "minimum_bars", 1_000_000) < 1_000_000:
        raise QualificationRefused("PRODUCTION_SIZE_THRESHOLD_CANNOT_BE_LOWERED")


def require_database(conn, args, *, read_only=True):
    actual = conn.execute(
        "SELECT current_database(),system_identifier::text,"
        "current_setting('transaction_read_only') FROM pg_control_system()"
    ).fetchone()
    if actual != (args.expected_database, args.expected_system_id, "on" if read_only else "off"):
        raise QualificationRefused("PRIVATE_READ_ONLY_DATABASE_IDENTITY_MISMATCH")


def connect(args, *, read_only=True):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    require_target(args)
    # A typo must not even open the ordinary primary database for identity
    # inspection. The server independently rechecks this name and cluster ID.
    if conninfo_to_dict(args.database).get("dbname") != args.expected_database:
        raise QualificationRefused("EXPLICIT_PRIVATE_DATABASE_CONNECTION_REQUIRED")
    # Keyword options replace connection-string options, including attempts to
    # disable read-only transactions. All subsequent transactions stay read-only.
    if not read_only and (not args.mutate_private_rehearsal
                         or not args.expected_database.startswith("opening_latency_")):
        raise QualificationRefused("PRIVATE_MUTATION_NAMESPACE_AND_GRANT_REQUIRED")
    conn = psycopg.connect(args.database, connect_timeout=5,
        options=f"-c default_transaction_read_only={'on' if read_only else 'off'} -c statement_timeout=120000 "
                "-c lock_timeout=3000 -c idle_in_transaction_session_timeout=120000")
    try:
        require_database(conn, args, read_only=read_only)
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def read_only_writer(conn, lock_key):
    """Own the real writer mutex without entering a financial mutation path."""
    if not conn.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()[0]:
        raise QualificationRefused("PRIVATE_WRITER_LOCK_BUSY")
    try:
        yield
    finally:
        conn.rollback()
        try:
            if not conn.execute("SELECT pg_advisory_unlock(%s)", (lock_key,)).fetchone()[0]:
                raise QualificationRefused("PRIVATE_WRITER_LOCK_LOST")
        finally:
            conn.rollback()


class Stages:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.rows = []

    def run(self, name, function):
        started = self.clock()
        row = {"stage": name, "result": "REFUSED"}
        try:
            value = function()
            row["result"] = "PASS"
            return value
        except BaseException as exc:
            row["error_type"] = type(exc).__name__
            raise
        finally:
            row["seconds"] = round(self.clock() - started, 6)
            self.rows.append(row)
            print(json.dumps(row), flush=True)


def profile_rows(profiler):
    rows = []
    for (filename, line, function), (primitive, total, own, cumulative, _) in pstats.Stats(profiler).stats.items():
        rows.append({"file": filename, "line": line, "function": function,
                     "primitive_calls": primitive, "total_calls": total,
                     "own_seconds": round(own, 6), "cumulative_seconds": round(cumulative, 6)})
    rows.sort(key=lambda row: row["cumulative_seconds"], reverse=True)
    return {"top_cumulative": rows[:50], "selected_invocations": [
        row for row in rows if row["function"] in PROFILE_FUNCTIONS]}


@contextmanager
def reviewed_runtime(conn, args):
    """Use genuine candidate identity and an already admitted retained book."""
    from sentinel import retained_go, rolling_checkpoint, runtime_admission
    checkpoint = rolling_checkpoint.read(conn)
    if checkpoint is None:
        raise QualificationRefused("RETAINED_ORIGIN_REQUIRED")
    context = runtime_admission.current_context(
        observation_id=args.observation_id, starting_cash=args.starting_cash)
    if (context["runtime"]["runtime_image_digest"] != args.runtime_image_digest
            or context["runtime"]["git_commit"] != os.environ["SENTINEL_IMAGE_SOURCE_REVISION"]):
        raise QualificationRefused("DECLARED_RUNTIME_DIFFERS_FROM_ACTUAL_IMAGE_CONTEXT")
    if (runtime_admission.process_binding(context["runtime"])
            != runtime_admission.process_binding(checkpoint.runtime_identity)
            and runtime_admission.read(conn, context, checkpoint) is None):
        raise QualificationRefused("SUPPORTED_RETAINED_CANDIDATE_ADMISSION_REQUIRED")
    with retained_go.reviewed_process(context,
            data_publication_sha256=checkpoint.runtime_identity["validated_data_publication_sha256"],
            deadline=datetime.now(timezone.utc) + timedelta(minutes=20)):
        yield context


def admit(args, stages):
    """Append supported compatible-runtime admission only in the private copy."""
    import sentinel
    require_environment(os.environ, sentinel.__file__)
    require_target(args)
    if args.retained_source_manifest is None:
        raise QualificationRefused("RETAINED_SOURCE_MANIFEST_REQUIRED")
    from sentinel import retained_go, rolling_checkpoint, rolling_daily_checkpoint, runtime_admission
    with connect(args, read_only=False) as conn:
        before = [reader.read(conn) for reader in (rolling_checkpoint, rolling_daily_checkpoint)]
        context = runtime_admission.current_context(
            observation_id=args.observation_id, starting_cash=args.starting_cash)
        manifest = retained_go.load_manifest(args.retained_source_manifest)
        proof = stages.run("supported_retained_runtime_admission", lambda:
            runtime_admission.admit(conn, context=context, manifest=manifest))
        after = [reader.read(conn) for reader in (rolling_checkpoint, rolling_daily_checkpoint)]
        if before != after:
            raise QualificationRefused("RETAINED_BOOK_CHANGED")
        return {"authority_effect": "NONE", "admission_sha256": proof.manifest_sha256,
                "book_preserved": True, "production_admission": False,
                "runtime_identity_substituted": False, "gateway_qualified": False}


def benchmark(args, stages):
    import sentinel
    require_environment(os.environ, sentinel.__file__)
    require_target(args)
    from sentinel import binding, dual_plan_authority, dual_reconciliation
    from sentinel import shadow_runtime, structural_verification
    from sentinel.authority import load_rollout_state
    from sentinel.execution import feed_inputs, journal
    from sentinel.feed import rolling_store

    with connect(args) as conn:
        with reviewed_runtime(conn, args), read_only_writer(conn, journal.WRITER_LOCK_KEY):
            with feed_inputs.pinned(conn, commit=False) as pub:
                evidence = pub.evidence.get("rolling_snapshot", {})
                candidate = evidence.get("candidate_id")
                if not candidate:
                    raise QualificationRefused("RETAINED_ROLLING_SNAPSHOT_REQUIRED")
                manifest = rolling_store.manifest(conn, candidate)
                if manifest.bar_count < args.minimum_bars:
                    raise QualificationRefused("PRODUCTION_SIZE_INPUT_REQUIRED")
                plan = journal.latest_plan(conn) if args.mode == "dual" else None
                if args.mode == "dual" and plan is None:
                    raise QualificationRefused("RETAINED_PLAN_REQUIRED")
                bound = binding.require(conn) if plan is not None else None
                rollout = load_rollout_state(conn) if plan is not None else None
                scope = structural_verification.Scope(conn)

                def verify(reader, number):
                    with scope.guard(reader):
                        shadow = stages.run(f"{number}:verified_shadow_status", lambda:
                            shadow_runtime.verified_shadow_status(reader,
                                observation_id=args.observation_id, starting_cash=args.starting_cash))
                        if shadow is None or shadow.verification != "VERIFIED":
                            raise QualificationRefused("VERIFIED_SHADOW_REQUIRED")
                        if plan is not None:
                            intent = stages.run(f"{number}:verified_shadow_intent", lambda:
                                dual_reconciliation.verified_shadow_intent(reader,
                                    decision_session=plan.decision_session,
                                    observation_id=args.observation_id, starting_cash=args.starting_cash))
                            stages.run(f"{number}:rederive_plan", lambda:
                                dual_plan_authority.rederive_plan(reader, plan=plan,
                                    binding=bound, rollout_state=rollout, expected_shadow_result=intent))
                    return shadow

                latest = verify(conn, "owner")
                for index in range(args.repetitions):
                    with connect(args) as reader:
                        latest = verify(reader, f"guard-{index + 1}")
                writes = conn.execute(
                    "SELECT coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0)::bigint "
                    "FROM pg_stat_xact_user_tables").fetchone()[0]
                if writes != 0:
                    raise QualificationRefused("READ_ONLY_DIAGNOSTIC_RECORDED_WRITES")
                return {"database": args.expected_database, "system_id": args.expected_system_id,
                    "source_revision": os.environ["SENTINEL_IMAGE_SOURCE_REVISION"],
                    "runtime_image_digest": args.runtime_image_digest,
                    "runtime_import": sentinel.__file__, "snapshot_id": manifest.snapshot_id,
                    "bar_count": manifest.bar_count, "session": latest.session,
                    "read_only": True, "broker_calls": 0, "database_mutations": 0,
                    "gateway_qualified": False, "authority_effect": "NONE"}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database", required=True, help="explicit private PostgreSQL connection string")
    result.add_argument("--expected-database", required=True)
    result.add_argument("--expected-system-id", required=True)
    result.add_argument("--production-system-id", required=True)
    result.add_argument("--runtime-image-digest", required=True)
    result.add_argument("--private-rehearsal", action="store_true")
    result.add_argument("--mode", choices=("shadow", "dual", "admit", "gateway"), default="dual")
    result.add_argument("--mutate-private-rehearsal", action="store_true")
    result.add_argument("--retained-source-manifest", type=Path)
    result.add_argument("--scheduler-profile", type=Path)
    result.add_argument("--profile", action="store_true", help="enable cProfile; overhead affects timings")
    result.add_argument("--observation-id", default="primary")
    result.add_argument("--starting-cash", default="50000")
    result.add_argument("--minimum-bars", type=int, default=1_000_000)
    result.add_argument("--repetitions", type=int, default=3)
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    stages, profiler = Stages(), cProfile.Profile()
    report = {"schema": "sentinel.opening-verifier-profile/1", "mode": args.mode,
              "result": "REFUSED", "observed_at": datetime.now(timezone.utc).isoformat()}
    # Refuse overwriting prior evidence before starting any database operation.
    with args.output.open("x", encoding="utf-8") as stream:
        started = time.monotonic()
        try:
            if args.profile and args.mode == "gateway":
                raise QualificationRefused("GATEWAY_TIMING_MUST_NOT_USE_CPROFILE")
            if args.profile:
                profiler.enable()
            handler = admit if args.mode == "admit" else benchmark
            if args.mode == "gateway":
                from tools.opening_gateway_qualification import qualify
                handler = qualify
            report.update(handler(args, stages))
            report["result"] = "PASS"
        except Exception as exc:
            # Exception messages may contain a DSN. Retain only type and our
            # fixed refusal code; provider/account/connection bytes never print.
            report["error_type"] = type(exc).__name__
            if isinstance(exc, QualificationRefused):
                report["refusal"] = str(exc)
                report.update(exc.metrics)
            elif (type(exc).__name__ == "QualificationRefused"
                  and re.fullmatch(r"[A-Z_0-9]+", str(exc))):
                # Direct script/-m launches can load this file once as main
                # and once through the gateway's normal tools import.
                report["refusal"] = str(exc)
                report.update(getattr(exc, "metrics", {}))
        finally:
            profiler.disable()
            report.update(seconds=round(time.monotonic() - started, 6), stages=stages.rows,
                          profiling_enabled=args.profile,
                          profile=profile_rows(profiler) if args.profile else {})
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps({key: report[key] for key in ("result", "mode", "seconds")}))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
