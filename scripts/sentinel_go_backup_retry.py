"""Resume a fenced acquisition only after host backup renewal succeeds."""
import json
import subprocess
from uuid import UUID

from sentinel_go_deadline import command_timeout

FAILURE = "SENTINEL_GO_PREPARATION_FAILURE="
PROGRESS = "SENTINEL_FEED_PROGRESS="
RESUME_ENV = "SENTINEL_GO_RESUME_JOB_ID"
MAX_RENEWALS = 2


def failure_payload(completed):
    lines = [line[len(FAILURE):] for stream in
             (completed.stdout or "", completed.stderr or "")
             for line in stream.splitlines() if line.startswith(FAILURE)]
    if len(lines) != 1:
        return None
    try:
        value = json.loads(lines[0])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def resumable_job(completed):
    value = failure_payload(completed)
    if (completed.returncode != 1 or value is None
            or value.get("phase") != "DAILY_CATCHUP"
            or value.get("error_type") != "BackupHorizonExceeded"
            or value.get("reason_code") != "BACKUP_RUNTIME_HORIZON_EXCEEDED"
            or value.get("schema_migration_attempted") is not True
            or value.get("bounded_sharadar_daily_attempted") is not True):
        return None
    job = value.get("resume_job_id")
    try:
        return job if isinstance(job, str) and str(UUID(job)) == job else None
    except ValueError:
        return None


class RenewalRunner:
    def __init__(self, runner, *, preparation_code, renew, refuse, cwd):
        self.runner = runner
        self.preparation_code = preparation_code
        self.renew = renew
        self.refuse = refuse
        self.cwd = cwd
        self.attempts = [False, False]

    @property
    def last_preparation_output(self):
        return self.runner.last_preparation_output

    @last_preparation_output.setter
    def last_preparation_output(self, value):
        self.runner.last_preparation_output = value

    def _finish(self, completed, prior):
        # Previous failures were handled; retain their progress, not stale
        # terminal markers which would make the final child result ambiguous.
        result = subprocess.CompletedProcess(completed.args, completed.returncode,
            completed.stdout or "", "\n".join(prior) + "\n" + (completed.stderr or ""))
        if hasattr(self.runner, "last_preparation_output"):
            self.runner.last_preparation_output = result.stdout + "\n" + result.stderr
        return result

    def _refused(self, command, reason, prior):
        self.refuse(reason)
        value = dict(phase="BACKUP_RENEWAL", error_type="BackupRefreshRefused",
                     reason_code=reason, schema_migration_attempted=self.attempts[0],
                     bounded_sharadar_daily_attempted=self.attempts[1])
        return self._finish(subprocess.CompletedProcess(command, 1, "",
            FAILURE + json.dumps(value, sort_keys=True)), prior)

    def run(self, argv, *, env=None, cwd=None):
        cwd = self.cwd if cwd is None else cwd
        command = list(argv)
        if (command[:2] != ["docker", "compose"] or not command
                or command[-1] != self.preparation_code or "--entrypoint" not in command):
            return self.runner.run(command, env=env, cwd=cwd)
        run_env = dict(env or {})
        run_env.pop(RESUME_ENV, None)
        prior = []
        job = None
        for attempt in range(MAX_RENEWALS + 1):
            if command_timeout(1) <= 0:
                return self._refused(command, "BACKUP_RENEWAL_DEADLINE_EXHAUSTED", prior)
            invocation = list(command)
            if job is not None:
                run_env[RESUME_ENV] = job
                index = invocation.index("--entrypoint")
                invocation[index:index] = ["--env", RESUME_ENV]
            completed = self.runner.run(invocation, env=run_env, cwd=cwd)
            payload = failure_payload(completed) or {}
            for i, key in enumerate(("schema_migration_attempted", "bounded_sharadar_daily_attempted")):
                self.attempts[i] |= payload.get(key) is True
            job = resumable_job(completed)
            if job is None:
                return self._finish(completed, prior)
            prior.extend(line for stream in (completed.stdout or "", completed.stderr or "")
                         for line in stream.splitlines() if line.startswith(PROGRESS))
            if attempt == MAX_RENEWALS:
                return self._refused(command, "BACKUP_RENEWAL_LIMIT_EXHAUSTED", prior)
            print("[GO] acquisition paused at backup horizon; renewing backup before resume", flush=True)
            reason = self.renew()
            if reason:
                return self._refused(command, reason, prior)
        raise AssertionError("bounded renewal loop fell through")
